"""Audio capture, resampling, silence detection, and PCM16 encoding.

This manager abstracts microphone input so the rest of the voice pipeline
does not need to know about PyAudio, sounddevice, or platform-specific
audio APIs. On Linux it prefers PulseAudio/PipeWire via sounddevice.
"""

import collections
import logging
import queue
import threading
import time
from collections.abc import Callable

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except Exception:
    SOUNDDEVICE_AVAILABLE = False

try:
    import webrtcvad

    VAD_AVAILABLE = True
except Exception:
    VAD_AVAILABLE = False


class AudioChunk:
    """Container for a single audio chunk with metadata."""

    __slots__ = ("pcm", "timestamp", "duration_ms")

    def __init__(self, pcm: bytes, timestamp: float, duration_ms: float):
        self.pcm = pcm
        self.timestamp = timestamp
        self.duration_ms = duration_ms


class AudioManager:
    """Microphone capture with configurable sample rate, VAD, and endpointing.

    The manager runs a background capture thread that pushes PCM16 chunks
    into a queue. Consumers call ``read_chunk()`` or register a callback.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        channels: int = 1,
        vad_aggressiveness: int = 2,
    ):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.channels = channels
        self.vad_aggressiveness = vad_aggressiveness

        self._queue: queue.Queue[AudioChunk | None] = queue.Queue(maxsize=1000)
        self._stream: sd.InputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._vad: webrtcvad.Vad | None = None
        self._speech_frames: collections.deque = collections.deque(maxlen=100)
        self._silence_start: float | None = None
        self._last_speech_end: float | None = None
        self._on_speech_end: Callable[[bytes], None] | None = None
        self._lock = threading.Lock()

        if VAD_AVAILABLE:
            try:
                self._vad = webrtcvad.Vad(vad_aggressiveness)
            except Exception:
                logger.warning("Failed to initialize webrtcvad")

    def diagnostics(self) -> dict:
        return {
            "sounddevice_available": SOUNDDEVICE_AVAILABLE,
            "vad_available": VAD_AVAILABLE,
            "sample_rate": self.sample_rate,
            "frame_ms": self.frame_ms,
            "channels": self.channels,
            "running": self._running,
        }

    def list_devices(self) -> list[dict]:
        if not SOUNDDEVICE_AVAILABLE:
            return []
        try:
            devices = sd.query_devices()
            return [
                {
                    "id": i,
                    "name": d.get("name", ""),
                    "max_input_channels": d.get("max_input_channels", 0),
                    "default_samplerate": d.get("default_samplerate", 0),
                }
                for i, d in enumerate(devices)
                if d.get("max_input_channels", 0) > 0
            ]
        except Exception:
            return []

    def _audio_callback(self, indata: np.ndarray, frames: int, info: dict, status) -> None:
        if status:
            logger.debug("Audio callback status: %s", status)

        pcm16 = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        timestamp = time.monotonic()
        duration_ms = (frames / self.sample_rate) * 1000

        chunk = AudioChunk(pcm16, timestamp, duration_ms)
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            logger.warning("Audio queue full, dropping chunk")

    def _capture_loop(self) -> None:
        if not SOUNDDEVICE_AVAILABLE:
            logger.error("sounddevice not available, cannot capture audio")
            return

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=int(self.sample_rate * self.frame_ms / 1000),
                channels=self.channels,
                dtype="float32",
                callback=self._audio_callback,
            ):
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            logger.error("Audio capture loop failed: %s", e)

    def start(self) -> bool:
        if self._running:
            return True

        if not SOUNDDEVICE_AVAILABLE:
            logger.error("Cannot start audio: sounddevice not installed")
            return False

        self._running = True
        self._queue = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Audio manager started (%d Hz, %d ms frames)", self.sample_rate, self.frame_ms)
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            self._queue = queue.Queue(maxsize=1000)
        logger.info("Audio manager stopped")

    def read_chunk(self, timeout: float = 1.0) -> AudioChunk | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def read_all(self) -> list[bytes]:
        chunks = []
        while True:
            chunk = self.read_chunk(timeout=0.01)
            if chunk is None:
                break
            chunks.append(chunk.pcm)
        return chunks

    @property
    def running(self) -> bool:
        return self._running

    def close(self) -> None:
        self.stop()
