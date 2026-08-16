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
        return {
            "state": self._state,
            "mode": self._mode,
            "recording": self._recording,
            "device": self._device,
            "error": self._error,
            "mic": self.mic.diagnostics(),
            "vad": self.vad.diagnostics(),
        }

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
        if mode == "hands_free":
            self.vad.start()
        self._utterance_pcm.clear()
        self._set_state(STATE_LISTENING, mode)
        logger.info("voice: listening mode=%s", mode)
        return True

    def stop_listening(self) -> bytes:
        """Explicit stop (PTT release / tap again).  Returns captured PCM16."""
        if not self._recording:
            return b""
        self._recording = False
        self._report_levels = False
        pcm = bytes(self._utterance_pcm)
        self._utterance_pcm.clear()
        self._set_state(STATE_IDLE, "stopped")
        return pcm

    def cancel(self) -> None:
        """Discard the current utterance and return to IDLE."""
        self._recording = False
        self._report_levels = False
        self._utterance_pcm.clear()
        self.vad.reset()
        if self._state not in (STATE_ERROR,):
            self._set_state(STATE_IDLE, "cancelled")

    # ------------------------------------------------------------ VAD callbacks
    def _on_speech_start(self) -> None:
        if self._mode == "hands_free" and not self._recording:
            self._recording = True
            self._report_levels = True
            self._utterance_pcm.clear()
            self._set_state(STATE_LISTENING, "wake speech")

    def _on_speech_end(self) -> None:
        if self._mode == "hands_free" and self._recording:
            self._recording = False
            self._report_levels = False
            pcm = bytes(self._utterance_pcm)
            self._utterance_pcm.clear()
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
            chunk: AudioChunk | None = self.mic.read_chunk(timeout=0.5)
            if chunk is None:
                continue
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
        self._set_state(STATE_READY, "mic test")
        return True
