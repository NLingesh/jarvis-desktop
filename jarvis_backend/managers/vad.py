"""Silero voice-activity detection with utterance endpointing.

Consumes PCM16 chunks (16 kHz mono) from the capture layer, buffers them into
the 512-sample windows Silero expects, and reports speech start/end via a
callback so the pipeline knows when an utterance begins and when to stop.
"""

import contextlib
import logging
import threading
import time
from collections.abc import Callable

import numpy as np

logger = logging.getLogger("jarvis.vad")

try:
    import torch
    from silero_vad import VADIterator, load_silero_vad

    SILERO_AVAILABLE = True
except Exception:
    torch = None
    SILERO_AVAILABLE = False

# Silero consumes fixed 512-sample windows at 16 kHz.
SILERO_FRAME = 512


class VoiceActivityDetector:
    """Silero VAD wrapper that produces speech start / end events.

    The detector maintains an internal sample buffer so arbitrarily-sized PCM16
    chunks from the mic layer are accepted.  When speech starts it fires
    ``on_speech_start``; once ``min_silence_ms`` of speech-free audio elapses it
    fires ``on_speech_end`` and stops the current utterance.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_ms: int = 500,
        max_utterance_ms: int = 20000,
        on_speech_start: Callable[[], None] | None = None,
        on_speech_end: Callable[[], None] | None = None,
        on_level: Callable[[float], None] | None = None,
    ):
        self.threshold = threshold
        self.min_silence_ms = min_silence_ms
        self.max_utterance_ms = max_utterance_ms
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end
        self._on_level = on_level

        self._vad = None
        self._buffer = np.zeros(0, dtype=np.float32)
        self._sample_rate = 16000
        self._speech = False
        self._utterance_start = 0.0
        self._last_speech_sample = 0
        self._started_at: float | None = None
        self._lock = threading.Lock()

    # -- Lifecycle ------------------------------------------------------------
    def start(self) -> bool:
        if not SILERO_AVAILABLE:
            logger.error("vad: Silero not available — cannot start voice activity detection")
            return False
        try:
            model = load_silero_vad()
            model.eval()
            self._vad = VADIterator(
                model,
                threshold=self.threshold,
                sampling_rate=self._sample_rate,
                min_silence_duration_ms=self.min_silence_ms,
                speech_pad_ms=30,
            )
            self._buffer = np.zeros(0, dtype=np.float32)
            self._speech = False
            self._utterance_start = 0.0
            self._started_at = None
            logger.info(
                "vad: Silero initialized (threshold=%s, min_silence=%dms, max=%dms)",
                self.threshold,
                self.min_silence_ms,
                self.max_utterance_ms,
            )
            return True
        except Exception as e:
            logger.error("vad: failed to initialize Silero: %s", e)
            return False

    def reset(self) -> None:
        """Drop buffered audio and any partial utterance."""
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)
            self._speech = False
            self._started_at = None
            if self._vad is not None:
                self._vad.reset_states()

    # -- Feeding ---------------------------------------------------------------
    def feed(self, pcm16: bytes) -> None:
        """Feed PCM16 16 kHz mono bytes into the detector."""
        if self._vad is None:
            return
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        with self._lock:
            self._buffer = np.concatenate([self._buffer, samples])

            while len(self._buffer) >= SILERO_FRAME:
                frame = self._buffer[:SILERO_FRAME]
                self._buffer = self._buffer[SILERO_FRAME:]
                if self._on_level is not None:
                    with contextlib.suppress(Exception):
                        self._on_level(float(np.sqrt(np.mean(frame**2))))
                self._process_frame(frame)

    def _process_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        try:
            import torch

            event = self._vad(torch.from_numpy(frame).unsqueeze(0))
        except Exception as e:
            logger.warning("vad: frame processing error: %s", e)
            return

        if event is not None and "start" in event and not self._speech:
            self._speech = True
            self._started_at = now
            logger.info("vad: speech started at %.2fs", event["start"])
            if self._on_speech_start:
                with contextlib.suppress(Exception):
                    self._on_speech_start()
        elif event is not None and "end" in event and self._speech:
            self._speech = False
            logger.info("vad: speech ended at %.2fs", event["end"])
            if self._on_speech_end:
                with contextlib.suppress(Exception):
                    self._on_speech_end()

        # Hard safety cap: never let one utterance run forever.
        if (
            self._speech
            and self._started_at is not None
            and (now - self._started_at) * 1000 > self.max_utterance_ms
        ):
            logger.warning(
                "vad: max utterance length reached (%dms), forcing end",
                self.max_utterance_ms,
            )
            self._speech = False
            if self._on_speech_end:
                with contextlib.suppress(Exception):
                    self._on_speech_end()

    # -- State ----------------------------------------------------------------
    @property
    def speaking(self) -> bool:
        return self._speech

    def diagnostics(self) -> dict:
        return {
            "silero_available": SILERO_AVAILABLE,
            "threshold": self.threshold,
            "min_silence_ms": self.min_silence_ms,
            "max_utterance_ms": self.max_utterance_ms,
            "speaking": self._speech,
            "buffered_samples": len(self._buffer),
        }
