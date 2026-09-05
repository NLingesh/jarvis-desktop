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
        min_silence_ms: int = 800,
        fast_silence_ms: int = 120,
        reopen_grace_ms: int = 400,
        speech_pad_ms: int = 100,
        max_utterance_ms: int = 20000,
        on_speech_start: Callable[[], None] | None = None,
        on_speech_end: Callable[[], None] | None = None,
        on_level: Callable[[float], None] | None = None,
    ):
        self.threshold = threshold
        self.min_silence_ms = min_silence_ms
        self.fast_silence_ms = fast_silence_ms
        self.reopen_grace_ms = reopen_grace_ms
        self.speech_pad_ms = speech_pad_ms
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
        self._end_at: float | None = None
        self._pending_end = False
        self._last_end_reason: str | None = None
        self._speech_start_ts: float | None = None
        self._speech_end_ts: float | None = None
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
                # Fast end so pauses are noticed promptly; true endpointing is
                # driven by ``min_silence_ms`` grace below so short pauses
                # between words (e.g. "Hey" ... "JARVIS") stay one utterance.
                min_silence_duration_ms=self.fast_silence_ms,
                speech_pad_ms=self.speech_pad_ms,
            )
            self._buffer = np.zeros(0, dtype=np.float32)
            self._speech = False
            self._utterance_start = 0.0
            self._started_at = None
            self._end_at = None
            self._pending_end = False
            self._last_end_reason = None
            self._speech_start_ts = None
            self._speech_end_ts = None
            logger.info(
                "vad: Silero initialized (threshold=%s, min_silence=%dms, grace=%dms, max=%dms)",
                self.threshold,
                self.min_silence_ms,
                self.reopen_grace_ms,
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
            self._end_at = None
            self._pending_end = False
            self._last_end_reason = None
            self._speech_start_ts = None
            self._speech_end_ts = None
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
            self._check_endpoint()

    def _process_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        try:
            import torch

            event = self._vad(torch.from_numpy(frame).unsqueeze(0))
        except Exception as e:
            logger.warning("vad: frame processing error: %s", e)
            return

        if event is not None and "start" in event:
            if self._pending_end and self._end_at is not None:
                # Speech resumed within the grace window: merge back into the
                # same utterance instead of closing the previous one.
                pause_ms = (now - self._end_at) * 1000
                if pause_ms < self.reopen_grace_ms:
                    self._pending_end = False
                    self._end_at = None
                    self._speech = True
                    logger.info("vad: utterance reopened after %.0fms pause", pause_ms)
                    return
            if not self._speech:
                self._speech = True
                self._started_at = now
                self._speech_start_ts = now
                logger.info("vad: speech started at %.2fs", event["start"])
                if self._on_speech_start:
                    with contextlib.suppress(Exception):
                        self._on_speech_start()
        elif event is not None and "end" in event and self._speech:
            # A fast end was detected, but true endpointing waits for the full
            # ``min_silence_ms`` grace so short pauses do not cut the utterance.
            self._speech = False
            self._end_at = now
            self._pending_end = True
            self._speech_end_ts = now
            logger.info(
                "vad: speech paused at %.2fs (endpoint grace %dms)",
                event["end"],
                self.min_silence_ms,
            )

    def poll(self) -> None:
        """Advance endpointing checks even when no new audio has arrived.

        Called from the capture consumer so a trailing-silence utterance still
        ends when the mic delivers silence slower than the grace window, or
        when capture stalls entirely.
        """
        with self._lock:
            self._check_endpoint()

    def _check_endpoint(self) -> None:
        """Drive true endpointing from real silence elapsed, not fast VAD ends."""
        now = time.monotonic()
        if (
            self._pending_end
            and self._end_at is not None
            and (now - self._end_at) * 1000 >= self.min_silence_ms
        ):
            self._pending_end = False
            self._end_at = None
            self._last_end_reason = "endpoint"
            logger.info("vad: speech ended (grace elapsed)")
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
            self._pending_end = False
            self._end_at = None
            self._last_end_reason = "max_utterance"
            if self._on_speech_end:
                with contextlib.suppress(Exception):
                    self._on_speech_end()

    # -- State ----------------------------------------------------------------
    @property
    def speaking(self) -> bool:
        return self._speech

    @property
    def utterance_open(self) -> bool:
        """True while audio is still being accumulated for the current utterance."""
        return self._speech or self._pending_end

    def diagnostics(self) -> dict:
        return {
            "silero_available": SILERO_AVAILABLE,
            "threshold": self.threshold,
            "min_silence_ms": self.min_silence_ms,
            "reopen_grace_ms": self.reopen_grace_ms,
            "max_utterance_ms": self.max_utterance_ms,
            "speaking": self._speech,
            "pending_end": self._pending_end,
            "last_end_reason": self._last_end_reason,
            "speech_start_ts": self._speech_start_ts,
            "speech_end_ts": self._speech_end_ts,
            "buffered_samples": len(self._buffer),
        }
