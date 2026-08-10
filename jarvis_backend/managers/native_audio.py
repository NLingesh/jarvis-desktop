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

        self._stream = None
        self._queue: queue.Queue[AudioChunk | None] = queue.Queue(maxsize=1200)
        self._running = False
        self._active_device: int | None = None
        self._active_device_name = ""
        self._stream_error: str | None = None
        self._last_status: object = None

        self._rms = 0.0
        self._peak = 0.0
        self._level_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()

    # -- Diagnostics / introspection ----------------------------------------
    def diagnostics(self) -> dict:
        return {
            "available": SOUNDDEVICE_AVAILABLE,
            "running": self._running,
            "sample_rate": self.sample_rate,
            "block_ms": self.block_ms,
            "active_device": self._active_device,
            "active_device_name": self._active_device_name,
            "stream_error": self._stream_error,
            "queued_chunks": self._queue.qsize(),
        }

    def device_info(self) -> dict:
        return {
            "id": self._active_device,
            "name": self._active_device_name,
            "sample_rate": self.sample_rate,
            "block_ms": self.block_ms,
        }

    def level(self) -> dict:
        with self._level_lock:
            return {"rms": round(self._rms, 4), "peak": round(self._peak, 4)}

    # -- Stream lifecycle ----------------------------------------------------
    def _open_stream(self, device_id: int) -> bool:
        """Open the InputStream; returns False and logs on failure."""
        try:
            self._queue = queue.Queue(maxsize=1200)
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=self.CHANNELS,
                dtype="float32",
                device=device_id,
                callback=self._audio_callback,
            )
            stream.start()
            self._stream = stream
            with self._state_lock:
                self._active_device = device_id
                self._active_device_name = self._device_name(device_id)
                self._stream_error = None
            logger.info(
                "audio: stream opened device=%d name=%r sr=%d block=%dms",
                device_id,
                self._active_device_name,
                self.sample_rate,
                self.block_ms,
            )
            return True
        except Exception as e:
            logger.error("audio: failed to open stream on device=%d: %s", device_id, e)
            with self._state_lock:
                self._stream_error = str(e)
                self._stream = None
                self._active_device = None
            return False

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
        self._close_stream()
        with self._state_lock:
            self._active_device = None
            self._active_device_name = ""
        # Signal any blocked reader that capture has ended.
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        logger.info("audio: capture stopped")

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                logger.debug("audio: stream close error: %s", e)

    def _device_name(self, device_id: int) -> str:
        try:
            return str(sd.query_devices(device_id)["name"])
        except Exception:
            return ""

    # -- Device watch / reconnect --------------------------------------------
    def _device_watch_loop(self) -> None:
        """Monitor for device loss and reconnect with backoff."""
        poll_interval = 1.0
        last_ok = time.monotonic()
        while self._running and not self._watch_stop.is_set():
            time.sleep(poll_interval)

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
                last_ok = time.monotonic()
            elif self._stream is not None and time.monotonic() - last_ok > 60:
                # Periodic sanity poll: a non-fatal PortAudio error can leave the
                # stream half-open; re-check it is still reading.
                last_ok = time.monotonic()
                if self._queue.qsize() == 0 and self._stream is not None:
                    try:
                        if self._stream.active and self._stream.read_available < 0:
                            raise OSError("stream stalled")
                    except Exception as e:
                        logger.warning("audio: stream stall detected (%s) — reopening", e)
                        self._close_stream()
                        self._open_stream(resolve_device(self.device))

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
        if status:
            self._last_status = status
            if "error" in str(status).lower() or "overflow" in str(status).lower():
                logger.warning("audio: callback status: %s", status)
        mono = indata[:, 0]
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
