"""Native voice session — orchestrates the backend-owned microphone.

Wires :class:`NativeMic` → :class:`VoiceActivityDetector` into an utterance
lifecycle controlled over the WebSocket.  Supports three interaction modes:

* ``ptt``        — record while a key is held (frontend sends start/stop)
* ``tap``        — start on first command, stop on a second command
* ``hands_free`` — VAD starts the utterance automatically and endpointing
                   stops it when the user finishes speaking

Every state change is emitted through ``on_state`` so the UI never gets stuck:
any failure returns to ``IDLE`` with an ``error`` description.
"""

import contextlib
import logging
import threading
import time
from collections.abc import Callable

from managers.native_audio import AudioChunk, NativeMic, list_input_devices, resolve_device
from managers.vad import VoiceActivityDetector

logger = logging.getLogger("jarvis.voice")

# Pipeline states reported to the UI.
STATE_IDLE = "IDLE"
STATE_CONNECTING = "CONNECTING"
STATE_READY = "READY"
STATE_LISTENING = "LISTENING"
STATE_PROCESSING = "PROCESSING"
STATE_SPEAKING = "SPEAKING"
STATE_ERROR = "ERROR"

VALID_MODES = {"ptt", "tap", "hands_free"}

# Keep ~300 ms of pre-roll so the first syllable ("Hey") is never clipped when
# the VAD opens the utterance; 16 kHz * 2 bytes * 300 ms.
PRE_ROLL_BYTES = int(16000 * 2 * 0.300)


class NativeVoiceSession:
    """One backend-owned microphone session per /ws/voice/native connection."""

    def __init__(
        self,
        device: int | str | None = None,
        on_state: Callable[[str, str], None] | None = None,
        on_level: Callable[[dict], None] | None = None,
        on_utterance: Callable[[bytes], None] | None = None,
    ):
        self.mic = NativeMic(device=device)
        self.vad = VoiceActivityDetector(
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end,
        )
        self._on_state = on_state
        self._on_level = on_level
        self._on_utterance = on_utterance

        self._mode: str | None = None
        self._recording = False
        self._report_levels = False
        self._utterance_pcm = bytearray()
        self._pre_roll = bytearray()
        self._last_utterance_meta: dict | None = None
        self._consumer_thread: threading.Thread | None = None
        self._consumer_stop = threading.Event()
        self._state = STATE_IDLE
        self._error: str | None = None
        self._device: int | str | None = device

    # ------------------------------------------------------------------ state
    def _set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        logger.info("voice: state=%s detail=%r", state, detail)
        if self._on_state:
            with contextlib.suppress(Exception):
                self._on_state(state, detail)

    @property
    def state(self) -> str:
        return self._state

    def diagnostics(self) -> dict:
        diag = {
            "state": self._state,
            "mode": self._mode,
            "recording": self._recording,
            "device": self._device,
            "error": self._error,
            "mic": self.mic.diagnostics(),
            "vad": self.vad.diagnostics(),
            "pre_roll_bytes": len(self._pre_roll),
            "last_utterance": self._last_utterance_meta,
        }
        return diag

    def last_utterance_meta(self) -> dict | None:
        """Safe metadata from the most recently finalized utterance (no audio)."""
        return dict(self._last_utterance_meta) if self._last_utterance_meta else None

    def _start_consumer(self) -> None:
        """Start the consumer thread unless one is already running.

        Guards against duplicate consumer threads when the session is reused
        (e.g. ``connect`` after a mic test, or a reconnect after the stream was
        reopened underneath us).
        """
        if self._consumer_thread and self._consumer_thread.is_alive():
            return
        self._consumer_stop.clear()
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop, name="voice-consumer", daemon=True
        )
        self._consumer_thread.start()

    # --------------------------------------------------------------- lifecycle
    def _wait_for_frames(self, timeout_s: float = 3.0) -> bool:
        """Wait until the capture callback has delivered at least one frame.

        ``READY`` is only reported once frames are actually arriving so the UI
        never shows a truthful "mic ready" state for a stream that is silent.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            diag = self.mic.diagnostics()
            if diag.get("last_callback_age") is not None:
                return True
            time.sleep(0.05)
        return False

    def connect(self) -> bool:
        """Open the microphone stream and enter READY."""
        if self._state in (STATE_LISTENING, STATE_PROCESSING):
            return True
        if (
            self._state == STATE_READY
            and self._consumer_thread
            and self._consumer_thread.is_alive()
        ):
            return True
        self._set_state(STATE_CONNECTING, "opening microphone")
        ok = self.mic.start()
        if not ok:
            self._error = self.mic.diagnostics().get("stream_error") or "failed to open mic"
            self._set_state(STATE_ERROR, self._error)
            logger.error("voice: connect failed: %s", self._error)
            return False
        self._start_consumer()
        if not self._wait_for_frames():
            self._error = self.mic.diagnostics().get("stream_error") or (
                "microphone opened but no capture frames arrived"
            )
            self._set_state(STATE_ERROR, self._error)
            logger.error("voice: connect opened but no frames: %s", self._error)
            return False
        self._set_state(STATE_READY, self.mic.device_info().get("name") or "")
        return True

    def set_device(self, device: int | str | None) -> dict:
        """Switch the input device (reopens the stream)."""
        self._device = device
        self.mic.device = device
        if self.mic.running:
            self.mic.stop()
        return {"devices": list_input_devices(), "active": resolve_device(device)}

    def disconnect(self) -> None:
        self._recording = False
        self._report_levels = False
        self._consumer_stop.set()
        self.mic.stop()
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=2.0)
        self._consumer_thread = None
        if self._state not in (STATE_ERROR,):
            self._set_state(STATE_IDLE, "disconnected")

    # ------------------------------------------------------------ listening
    def start_listening(self, mode: str) -> bool:
        if mode not in VALID_MODES:
            self._set_state(STATE_ERROR, f"unknown mode {mode!r}")
            return False
        if self._state == STATE_LISTENING:
            return True
        if self._state != STATE_READY and not self.connect():
            return False
        self._mode = mode
        self._recording = True
        self._report_levels = True
        self.vad.reset()
        self._pre_roll.clear()
        if mode == "hands_free":
            self.vad.start()
        self._utterance_pcm.clear()
        self._last_utterance_meta = None
        self._set_state(STATE_LISTENING, mode)
        logger.info("voice: listening mode=%s", mode)
        return True

    def _drain_queued(self) -> bytes:
        """Flush any PCM the mic has already queued so the final audio chunk is
        never dropped before transcription (the tail of the utterance)."""
        try:
            return self.mic.drain()
        except Exception:
            return b""

    def _record_utterance_meta(self, pcm: bytes, reason: str) -> None:
        """Capture safe, audio-free diagnostics for the finalized utterance."""
        vad_diag = self.vad.diagnostics()
        started = vad_diag.get("speech_start_ts")
        ended = vad_diag.get("speech_end_ts")
        meta = {
            "finalization_reason": reason,
            "capture_bytes": len(pcm),
            "capture_samples": len(pcm) // 2,
            "capture_duration_ms": round(len(pcm) / 32.0, 1),
            "chunks": max(1, round(len(pcm) / 960.0)),
            "pre_roll_bytes": len(self._pre_roll),
            "vad_speech_start_ts": started,
            "vad_speech_end_ts": ended,
            "vad_last_end_reason": vad_diag.get("last_end_reason"),
            "stt_partial": False,
            "stt_final": False,
        }
        if started is not None and ended is not None:
            meta["vad_utterance_ms"] = round((ended - started) * 1000, 1)
        self._last_utterance_meta = meta
        logger.info(
            "voice: utterance finalized reason=%s duration=%sms bytes=%d chunks=%d "
            "vad_start=%s vad_end=%s",
            reason,
            meta["capture_duration_ms"],
            meta["capture_bytes"],
            meta["chunks"],
            started,
            ended,
        )

    def stop_listening(self) -> bytes:
        """Explicit stop (PTT release / tap again).  Returns captured PCM16."""
        if not self._recording:
            return b""
        self._recording = False
        self._report_levels = False
        pcm = bytes(self._utterance_pcm) + self._drain_queued()
        self._utterance_pcm.clear()
        self._pre_roll.clear()
        self._record_utterance_meta(pcm, "ptt_release")
        self._set_state(STATE_IDLE, "stopped")
        return pcm

    def cancel(self) -> None:
        """Discard the current utterance and return to IDLE."""
        self._recording = False
        self._report_levels = False
        self._utterance_pcm.clear()
        self._pre_roll.clear()
        self.vad.reset()
        if self._state not in (STATE_ERROR,):
            self._set_state(STATE_IDLE, "cancelled")

    # ------------------------------------------------------------ VAD callbacks
    def _on_speech_start(self) -> None:
        if self._mode == "hands_free" and not self._recording:
            self._recording = True
            self._report_levels = True
            self._utterance_pcm.clear()
            # Pre-roll: seed the utterance with the last ~300 ms so the first
            # syllable ("Hey") is captured, not clipped.
            self._utterance_pcm.extend(self._pre_roll)
            self._set_state(STATE_LISTENING, "wake speech")

    def _on_speech_end(self) -> None:
        if self._mode == "hands_free" and self._recording:
            self._recording = False
            self._report_levels = False
            # Flush any queued mic chunks so the trailing audio is included.
            pcm = bytes(self._utterance_pcm) + self._drain_queued()
            self._utterance_pcm.clear()
            self._pre_roll.clear()
            reason = self.vad.diagnostics().get("last_end_reason") or "endpoint"
            self._record_utterance_meta(pcm, reason)
            self._set_state(STATE_PROCESSING, "endpointing")
            if self._on_utterance:
                try:
                    self._on_utterance(pcm)
                except Exception as e:
                    logger.error("voice: utterance callback failed: %s", e)

    # ------------------------------------------------------------- consumer
    def _consumer_loop(self) -> None:
        """Drain mic chunks; accumulate when recording, feed VAD always."""
        while not self._consumer_stop.is_set():
            chunk: AudioChunk | None = self.mic.read_chunk(timeout=0.1)
            if chunk is None:
                # Keep endpointing checks alive during silence / stalled capture.
                if self._mode == "hands_free":
                    self.vad.poll()
                continue
            # Rolling pre-roll buffer (capped) so a hands-free start never loses
            # the beginning of the utterance.
            self._pre_roll.extend(chunk.pcm16)
            if len(self._pre_roll) > PRE_ROLL_BYTES:
                del self._pre_roll[: len(self._pre_roll) - PRE_ROLL_BYTES]
            if self._on_level and self._report_levels:
                with contextlib.suppress(Exception):
                    self._on_level({"rms": chunk.rms, "peak": chunk.peak})
            if self._recording:
                self._utterance_pcm.extend(chunk.pcm16)
            if self._mode == "hands_free":
                self.vad.feed(chunk.pcm16)

    # ------------------------------------------------------------ mic test
    def mic_test(self, duration_ms: int = 0) -> bool:
        """Open the mic for a level-only session (Settings mic test).

        ``duration_ms`` of 0 means run until :meth:`disconnect` is called.
        """
        if self.mic.running:
            self._report_levels = True
            return True
        if not self.mic.start():
            self._error = self.mic.diagnostics().get("stream_error") or "mic test failed"
            self._set_state(STATE_ERROR, self._error)
            return False
        self._report_levels = True
        self._start_consumer()
        if not self._wait_for_frames():
            self._error = self.mic.diagnostics().get("stream_error") or (
                "microphone opened but no capture frames arrived"
            )
            self._set_state(STATE_ERROR, self._error)
            return False
        self._set_state(STATE_READY, "mic test")
        return True
