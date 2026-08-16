"""Native microphone capture layer using sounddevice/PortAudio.

Replaces the browser ``getUserMedia`` path with direct local capture on the
backend (the backend and the microphone live on the same machine).  Provides:

* explicit input-device selection (by index or name substring)
* real-time input level (RMS / peak) for meters and mic tests
* device-disconnect detection and automatic reconnection for
  PipeWire/PulseAudio device changes
* 16 kHz mono PCM16 output chunks
* structured logging that never silently swallows failures
"""

import contextlib
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger("jarvis.audio")

try:
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except Exception:  # pragma: no cover - depends on host install
    sd = None
    SOUNDDEVICE_AVAILABLE = False


@dataclass
class AudioChunk:
    pcm16: bytes
    timestamp: float
    rms: float
    peak: float


class DeviceError(RuntimeError):
    """Raised when no usable input device is available."""


def list_input_devices() -> list[dict]:
    """Return structured input-device info from PortAudio.

    Fields: ``id`` (PortAudio index), ``name``, ``max_input_channels``,
    ``default_samplerate``, ``hostapi``, ``is_default``.
    """
    if not SOUNDDEVICE_AVAILABLE:
        logger.error("sounddevice not installed — cannot enumerate microphones")
        return []
    try:
        devices = sd.query_devices()
    except Exception as e:
        logger.error("Failed to query audio devices: %s", e)
        return []
    default_index = None
    with contextlib.suppress(Exception):
        default_index = sd.default.device[0]
    out = []
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) <= 0:
            continue
        try:
            hostapi = sd.query_hostapis()[d["hostapi"]]["name"]
        except Exception:
            hostapi = "unknown"
        out.append(
            {
                "id": i,
                "name": d.get("name", ""),
                "max_input_channels": d.get("max_input_channels", 0),
                "default_samplerate": d.get("default_samplerate", 0),
                "hostapi": hostapi,
                "is_default": i == default_index,
            }
        )
    return out


def source_mute_state(device_id: int | None = None) -> bool | None:
    """Return the mute state of the input source for ``device_id``.

    * ``True``  — the source is muted.
    * ``False`` — the source is unmuted.
    * ``None``  — state could not be determined (no pactl/amixer, no match).

    Never raises: every backend call is guarded so capture is unaffected by a
    missing/misbehaving audio server CLI.
    """
    if not SOUNDDEVICE_AVAILABLE:
        return None
    name = ""
    if device_id is not None:
        with contextlib.suppress(Exception):
            name = str(sd.query_devices(device_id)["name"])
    base = name.lower()
    if base.startswith("pulse") or base.startswith("pipewire") or base.startswith("default"):
        # The virtual Pulse/PipeWire device captures the default *source*,
        # whose mute state lives in the audio server.
        if shutil.which("pactl"):
            try:
                out = subprocess.run(
                    ["pactl", "get-source-mute", "@DEFAULT_SOURCE@"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                text = out.stdout.strip().lower()
                if "yes" in text:
                    return True
                if "no" in text:
                    return False
            except Exception as e:  # pragma: no cover - host-dependent
                logger.debug("audio: pactl mute check failed: %s", e)
        return None
    # Raw hw device: check the ALSA capture mixer switch for that card.
    match = re.search(r"hw:(\d+)", base)
    if match and shutil.which("amixer"):
        try:
            out = subprocess.run(
                ["amixer", "-c", match.group(1), "sget", "Capture"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "[off]" in out.stdout:
                return True
            if "[on]" in out.stdout:
                return False
        except Exception as e:  # pragma: no cover - host-dependent
            logger.debug("audio: amixer mute check failed: %s", e)
    return None


def resolve_device(device: int | str | None) -> int | None:
    """Resolve an explicit device selector to a PortAudio index.

    * ``int`` → used directly if it is an input device.
    * ``str`` → matched against device names (substring, case-insensitive).
    * ``None`` → the PortAudio default input device.

    Returns ``None`` when nothing usable is found (caller reports the error).
    """
    if not SOUNDDEVICE_AVAILABLE:
        return None
    devices = list_input_devices()
    if not devices:
        return None
    if device is None:
        # Prefer the ALSA "pulse"/"pipewire" plugin devices when present:
        # they route capture through the audio server to the default *source*
        # (the real microphone).  The raw ALSA "default" device can resolve to
        # the sink *monitor* loopback on PipeWire systems, which would record
        # system output instead of the user's voice.
        for d in devices:
            if d["name"].lower().startswith("pulse"):
                return d["id"]
        for d in devices:
            if d["name"].lower().startswith("pipewire"):
                return d["id"]
        try:
            idx = sd.default.device[0]
        except Exception:
            return devices[0]["id"]
        if any(d["id"] == idx for d in devices):
            return idx
        return devices[0]["id"]
    if isinstance(device, int):
        if any(d["id"] == device for d in devices):
            return device
        logger.warning("Requested device %s not found, using default", device)
        return resolve_device(None)
    name = str(device).strip().lower()
    for d in devices:
        if name in d["name"].lower():
            return d["id"]
    logger.warning("No device matching %r, using default", device)
    return resolve_device(None)


class NativeMic:
    """Reliable sounddevice capture with level + reconnect handling.

    The stream is opened lazily on :meth:`start` and re-opened automatically
    if the device disappears (unplug, PipeWire restart, suspend).  PCM16 mono
    @ 16 kHz chunks land in an internal queue consumed via :meth:`read_chunk`.
    """

    SAMPLE_RATE = 16000
    BLOCK_MS = 30
    CHANNELS = 1

    def __init__(
        self,
        device: int | str | None = None,
        sample_rate: int = SAMPLE_RATE,
        block_ms: int = BLOCK_MS,
    ):
        self.device = device
        self.sample_rate = sample_rate
        self.block_ms = block_ms
        self.block_size = int(sample_rate * block_ms / 1000)

        # ONE stable queue for the lifetime of this NativeMic.  It is never
        # replaced on reopen; stream generations (``_generation``) keep stale
        # callbacks from writing into it, so the consumer can never be stranded
        # on an obsolete queue by a stream restart.
        self._stream = None
        self._queue: queue.Queue[AudioChunk | None] = queue.Queue(maxsize=1200)
        self._generation = 0
        self._last_callback_at = 0.0
        self._running = False
        self._active_device: int | None = None
        self._active_device_name = ""
        self._stream_error: str | None = None
        self._last_status: object = None
        self._capture_rate = sample_rate

        self._rms = 0.0
        self._peak = 0.0
        self._level_lock = threading.Lock()
        self._state_lock = threading.Lock()
        # Serializes open/close/reopen/stop so the watch thread and the WS
        # thread can never interleave stream mutations destructively.
        self._lifecycle_lock = threading.Lock()
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()

    # A callback stream is healthy as long as callbacks keep arriving.  If no
    # callback has been delivered within this window the stream is considered
    # stalled and is reopened (callback-liveness, not ``read_available``).
    STALL_TIMEOUT_SECONDS = 5.0

    # -- Diagnostics / introspection ----------------------------------------
    def diagnostics(self) -> dict:
        return {
            "available": SOUNDDEVICE_AVAILABLE,
            "running": self._running,
            "generation": self._generation,
            "sample_rate": self.sample_rate,
            "capture_rate": self._capture_rate,
            "block_ms": self.block_ms,
            "active_device": self._active_device,
            "active_device_name": self._active_device_name,
            "stream_error": self._stream_error,
            "queued_chunks": self._queue.qsize(),
            "last_callback_age": (
                time.monotonic() - self._last_callback_at if self._last_callback_at else None
            ),
        }

    def device_info(self) -> dict:
        return {
            "id": self._active_device,
            "name": self._active_device_name,
            "sample_rate": self.sample_rate,
            "capture_rate": self._capture_rate,
            "block_ms": self.block_ms,
        }

    def level(self) -> dict:
        with self._level_lock:
            return {"rms": round(self._rms, 4), "peak": round(self._peak, 4)}

    # -- Stream lifecycle ----------------------------------------------------
    def _native_samplerate(self, device_id: int) -> int | None:
        """Return the device's preferred capture rate, or None if unknown."""
        try:
            info = sd.query_devices(device_id)
            rate = int(info.get("default_samplerate", 0))
            return rate or None
        except Exception:
            return None

    def _resample16k(self, mono: np.ndarray, src_rate: int) -> np.ndarray:
        """Resample a mono float32 buffer to 16 kHz with linear interpolation."""
        if src_rate == self.SAMPLE_RATE or len(mono) == 0:
            return mono
        n_out = int(len(mono) * self.SAMPLE_RATE / src_rate)
        if n_out <= 0:
            return mono
        src_idx = np.linspace(0, len(mono) - 1, n_out)
        return np.interp(src_idx, np.arange(len(mono)), mono).astype(np.float32)

    def _make_callback(self, generation: int):
        """Return a callback bound to ``generation``.

        When a stream is reopened the generation advances; a stale callback
        still being invoked by the just-closed stream observes the mismatch and
        drops the chunk, so old audio can never leak into a new session.
        """

        def _cb(indata: np.ndarray, frames: int, time_info, status) -> None:
            if generation != self._generation:
                return
            self._audio_callback(indata, frames, time_info, status)

        return _cb

    def _open_stream(self, device_id: int) -> bool:
        """Open the InputStream; returns False and logs on failure.

        Uses one stable ``self._queue`` (never replaced) plus a stream
        generation so a reopen cannot strand the consumer on an obsolete queue
        and stale callbacks cannot write into a new session.  Serialized
        against ``stop``/close via ``_lifecycle_lock``.
        """
        with self._lifecycle_lock:
            if not self._running:
                logger.debug("audio: refusing open on device=%d (not running)", device_id)
                return False
            # If a previous stream is still open (reopen path), tear it down
            # first so we never leak a second native audio stream.
            if self._stream is not None:
                self._close_stream_locked()
            # Some devices (raw hw:1,0 @ 48k, hw:1,2 @ 44.1k) reject 16 kHz mono.
            # Fall back to the device's native rate and resample in the callback.
            capture_rate = self.sample_rate
            generation = self._generation + 1
            try:
                stream = sd.InputStream(
                    samplerate=capture_rate,
                    blocksize=self.block_size,
                    channels=self.CHANNELS,
                    dtype="float32",
                    device=device_id,
                    callback=self._make_callback(generation),
                )
                stream.start()
            except Exception as native_error:
                native_rate = self._native_samplerate(device_id)
                if native_rate and native_rate != capture_rate:
                    logger.info(
                        "audio: 16k open failed (%s); retrying at native rate %d on device=%d",
                        str(native_error)[:80],
                        native_rate,
                        device_id,
                    )
                    block = max(int(native_rate * self.block_ms / 1000), 1)
                    try:
                        stream = sd.InputStream(
                            samplerate=native_rate,
                            blocksize=block,
                            channels=self.CHANNELS,
                            dtype="float32",
                            device=device_id,
                            callback=self._make_callback(generation),
                        )
                        stream.start()
                        capture_rate = native_rate
                    except Exception as e:
                        logger.error("audio: failed to open stream on device=%d: %s", device_id, e)
                        with self._state_lock:
                            self._stream_error = str(e)
                            self._stream = None
                            self._active_device = None
                        return False
                else:
                    logger.error(
                        "audio: failed to open stream on device=%d: %s", device_id, native_error
                    )
                    with self._state_lock:
                        self._stream_error = str(native_error)
                        self._stream = None
                        self._active_device = None
                    return False
            self._generation = generation
            self._stream = stream
            self._capture_rate = capture_rate
            self._last_callback_at = time.monotonic()
            with self._state_lock:
                self._active_device = device_id
                self._active_device_name = self._device_name(device_id)
                self._stream_error = None
            logger.info(
                "audio: stream opened device=%d name=%r sr=%d block=%dms generation=%d",
                device_id,
                self._active_device_name,
                capture_rate,
                self.block_ms,
                generation,
            )
            return True

    def start(self) -> bool:
        """Open the capture stream and begin the device-watch thread."""
        if self._running:
            return self._stream is not None
        if not SOUNDDEVICE_AVAILABLE:
            logger.error("audio: cannot start — sounddevice/PortAudio unavailable")
            self._stream_error = "sounddevice not available"
            return False

        device_id = resolve_device(self.device)
        if device_id is None:
            logger.error("audio: cannot start — no usable input device found")
            self._stream_error = "no input device available"
            return False

        self._running = True
        self._watch_stop.clear()
        ok = self._open_stream(device_id)
        self._watch_thread = threading.Thread(
            target=self._device_watch_loop, name="audio-watch", daemon=True
        )
        self._watch_thread.start()
        return ok

    def stop(self) -> None:
        self._running = False
        self._watch_stop.set()
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=1.0)
        self._watch_thread = None
        with self._lifecycle_lock:
            self._close_stream_locked()
            with self._state_lock:
                self._active_device = None
                self._active_device_name = ""
        # Signal any blocked reader that capture has ended.  The queue is the
        # stable per-mic queue, so this always reaches the current consumer.
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        logger.info("audio: capture stopped")

    def _close_stream_locked(self) -> None:
        """Tear down the current stream; caller must hold ``_lifecycle_lock``.

        Advances the generation first so any callback still in flight from the
        stream being closed observes a mismatch and drops its chunk instead of
        writing it into the queue of a subsequent session.
        """
        self._generation += 1
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                logger.debug("audio: stream close error: %s", e)

    def _close_stream(self) -> None:
        with self._lifecycle_lock:
            self._close_stream_locked()

    def _device_name(self, device_id: int) -> str:
        try:
            return str(sd.query_devices(device_id)["name"])
        except Exception:
            return ""

    # -- Device watch / reconnect --------------------------------------------
    def _device_watch_loop(self) -> None:
        """Monitor for device loss and reconnect with backoff."""
        poll_interval = 1.0
        last_poll = time.monotonic()
        while self._running and not self._watch_stop.is_set():
            time.sleep(poll_interval)
            if not self._running:
                return
            now = time.monotonic()
            if now - last_poll < poll_interval:
                continue
            last_poll = now

            stream_alive = self._stream is not None
            if not stream_alive and self._running:
                # Stream died (device unplugged / PipeWire restarted).  Try to
                # reopen; never silently fail — log every attempt.
                logger.error(
                    "audio: capture stream lost (device=%r error=%r) — reconnecting",
                    self.device,
                    self._stream_error,
                )
                self._reconnect_loop()
                continue

            device_id = resolve_device(self.device)
            if device_id is not None and device_id != self._active_device:
                logger.info(
                    "audio: input device changed %r -> %d (%s) — reopening",
                    self._active_device,
                    device_id,
                    self._device_name(device_id),
                )
                self._close_stream()
                self._open_stream(device_id)
            elif self._stream is not None and self._stream_stalled(now):
                # The callback stream is alive but has not delivered a callback
                # for a while — treat it as stalled and reopen.  We deliberately
                # do NOT use ``read_available`` (meaningless on callback streams,
                # PaErrorCode -9977) or ``self._queue.qsize()`` (the consumer
                # drains it as fast as callbacks arrive).
                logger.warning(
                    "audio: stream stall detected (no callback for %.1fs) — reopening",
                    now - self._last_callback_at,
                )
                self._close_stream()
                self._open_stream(resolve_device(self.device))

    def _stream_stalled(self, now: float | None = None) -> bool:
        """True when an open callback stream has delivered nothing for too long."""
        if self._stream is None or self._last_callback_at <= 0:
            return False
        return (now or time.monotonic()) - self._last_callback_at > self.STALL_TIMEOUT_SECONDS

    def _reconnect_loop(self) -> None:
        """Attempt to reopen the stream with linear backoff, up to ~10s."""
        for attempt in range(1, 11):
            if not self._running or self._watch_stop.is_set():
                return
            device_id = resolve_device(self.device)
            if device_id is None:
                logger.error("audio: reconnect attempt %d — no input device present", attempt)
            else:
                if self._open_stream(device_id):
                    logger.info("audio: reconnected on attempt %d (device=%d)", attempt, device_id)
                    return
            time.sleep(min(attempt, 5))

    # -- Audio callback / level ----------------------------------------------
    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        self._last_callback_at = time.monotonic()
        if status:
            self._last_status = status
            if "error" in str(status).lower() or "overflow" in str(status).lower():
                logger.warning("audio: callback status: %s", status)
        mono = indata[:, 0]
        if self._capture_rate != self.SAMPLE_RATE:
            mono = self._resample16k(mono, self._capture_rate)
        if len(mono) > 0:
            with self._level_lock:
                self._rms = float(np.sqrt(np.mean(mono**2)))
                self._peak = float(np.max(np.abs(mono)))
        pcm16 = (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        chunk = AudioChunk(
            pcm16=pcm16,
            timestamp=time.monotonic(),
            rms=self._rms,
            peak=self._peak,
        )
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            logger.warning("audio: queue full, dropping chunk (level %r)", self._rms)

    # -- Consumption ----------------------------------------------------------
    def read_chunk(self, timeout: float = 1.0) -> AudioChunk | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> bytes:
        """Return all currently-buffered PCM16 bytes (for tests / mic checks)."""
        parts: list[bytes] = []
        while True:
            chunk = self.read_chunk(timeout=0.01)
            if chunk is None:
                break
            parts.append(chunk.pcm16)
        return b"".join(parts)

    @property
    def running(self) -> bool:
        return self._running

    def close(self) -> None:
        self.stop()
