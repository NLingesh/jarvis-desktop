"""Speech-to-text manager with Faster Whisper primary, Vosk/cloud fallback.

Provides both streaming (real-time partials) and batch (full-utterance)
transcription. The manager selects the best available backend at runtime.
"""

import asyncio
import base64
import contextlib
import io
import json
import logging
import os
import queue
import threading
import wave
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel

    FASTER_WHISPER_AVAILABLE = True
except Exception:
    FASTER_WHISPER_AVAILABLE = False

try:
    from vosk import KaldiRecognizer, Model

    VOSK_AVAILABLE = True
except Exception:
    VOSK_AVAILABLE = False


class STTManager:
    """Unified speech-to-text with multiple backends.

    Backend priority:
    1. Faster Whisper (local, high quality)
    2. Vosk (local, lightweight fallback)
    3. Cloud OpenAI Whisper API (if configured)
    """

    DEFAULT_VOSK_MODEL_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models",
        "vosk-model-small-en-us-0.15",
    )

    def __init__(
        self,
        faster_whisper_model: str = "small",
        faster_whisper_device: str = "cpu",
        vosk_model_dir: str | None = None,
        openai_api_key: str | None = None,
        openai_api_url: str = "https://api.openai.com/v1/audio/transcriptions",
    ):
        self.faster_whisper_model = faster_whisper_model
        self.faster_whisper_device = faster_whisper_device
        self.vosk_model_dir = (
            vosk_model_dir or os.getenv("VOSK_MODEL_DIR") or self.DEFAULT_VOSK_MODEL_DIR
        )
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.openai_api_url = openai_api_url

        self._faster_whisper_model: WhisperModel | None = None
        self._faster_whisper_loaded = False
        self._vosk_model = None
        self._vosk_loaded = False
        self._load_lock = threading.Lock()

    def diagnostics(self) -> dict:
        return {
            "faster_whisper_available": FASTER_WHISPER_AVAILABLE,
            "faster_whisper_model": self.faster_whisper_model,
            "faster_whisper_device": self.faster_whisper_device,
            "faster_whisper_loaded": self._faster_whisper_loaded,
            "vosk_available": VOSK_AVAILABLE,
            "vosk_model_dir": self.vosk_model_dir,
            "vosk_model_installed": os.path.isdir(self.vosk_model_dir),
            "vosk_loaded": self._vosk_loaded,
            "cloud_fallback": bool(self.openai_api_key),
            "ready": self.available,
        }

    @property
    def available(self) -> bool:
        return (
            (FASTER_WHISPER_AVAILABLE and self._faster_whisper_loaded)
            or (VOSK_AVAILABLE and self._vosk_loaded)
            or bool(self.openai_api_key)
        )

    def _ensure_faster_whisper(self) -> bool:
        if self._faster_whisper_loaded:
            return True
        if not FASTER_WHISPER_AVAILABLE:
            return False
        with self._load_lock:
            if self._faster_whisper_loaded:
                return True
            try:
                self._faster_whisper_model = WhisperModel(
                    self.faster_whisper_model,
                    device=self.faster_whisper_device,
                    compute_type="int8" if self.faster_whisper_device == "cpu" else "float16",
                )
                self._faster_whisper_loaded = True
                logger.info(
                    "Faster Whisper model loaded: %s (%s)",
                    self.faster_whisper_model,
                    self.faster_whisper_device,
                )
                return True
            except Exception as e:
                logger.error("Failed to load Faster Whisper model: %s", e)
                return False

    def _ensure_vosk(self) -> bool:
        if self._vosk_loaded:
            return True
        if not VOSK_AVAILABLE:
            return False
        if not os.path.isdir(self.vosk_model_dir):
            return False
        with self._load_lock:
            if self._vosk_loaded:
                return True
            try:
                self._vosk_model = Model(self.vosk_model_dir)
                self._vosk_loaded = True
                logger.info("Vosk model loaded from %s", self.vosk_model_dir)
                return True
            except Exception as e:
                logger.error("Failed to load Vosk model: %s", e)
                return False

    def _preload_async(self) -> None:
        asyncio.run(self._preload_async_impl())

    async def _preload_async_impl(self) -> None:
        await asyncio.to_thread(self._ensure_faster_whisper)

    def preload(self) -> bool:
        """Load the primary model in a background thread."""
        return self._ensure_faster_whisper()

    def transcribe_pcm16(self, pcm: bytes, sample_rate: int = 16000) -> str:
        """Transcribe raw PCM16 mono audio bytes."""
        if self._ensure_faster_whisper():
            return self._transcribe_faster_whisper(pcm, sample_rate)
        if self._ensure_vosk():
            return self._transcribe_vosk(pcm, sample_rate)
        if self.openai_api_key:
            return self._transcribe_cloud(pcm)
        return ""

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        """Transcribe WAV container bytes."""
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                rate = wf.getframerate()
                channels = wf.getnchannels()
                if channels != 1:
                    raise ValueError(f"Expected mono audio, got {channels} channels")
                data = wf.readframes(wf.getnframes())
            return self.transcribe_pcm16(data, rate)
        except Exception as e:
            logger.error("WAV parse failed: %s", e)
            return ""

    def _transcribe_faster_whisper(self, pcm: bytes, sample_rate: int) -> str:
        try:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm)
                tmp_path = tmp.name

            segments, info = self._faster_whisper_model.transcribe(
                tmp_path,
                language="en",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            os.unlink(tmp_path)
            text = " ".join(segment.text for segment in segments).strip()
            return text
        except Exception as e:
            logger.warning("Faster Whisper transcription failed: %s", e)
            return ""

    def _transcribe_vosk(self, pcm: bytes, sample_rate: int) -> str:
        try:
            recognizer = KaldiRecognizer(self._vosk_model, sample_rate)
            recognizer.AcceptWaveform(pcm)
            result = json.loads(recognizer.FinalResult())
            return (result.get("text") or "").strip()
        except Exception as e:
            logger.warning("Vosk transcription failed: %s", e)
            return ""

    def _transcribe_cloud(self, pcm: bytes) -> str:
        if not self.openai_api_key:
            return ""
        try:
            wav = self._pcm16_to_wav(pcm)
            with httpx.Client(timeout=30.0) as client:
                files = {"file": ("audio.wav", io.BytesIO(wav), "audio/wav")}
                data = {"model": "whisper-1", "response_format": "text"}
                headers = {"Authorization": f"Bearer {self.openai_api_key}"}
                response = client.post(self.openai_api_url, headers=headers, files=files, data=data)
                response.raise_for_status()
                text = response.text.strip()
                return text if text and not text.startswith("{") else ""
        except Exception as e:
            logger.error("Cloud STT failed: %s", e)
            return ""

    @staticmethod
    def _pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        with io.BytesIO() as buf:
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm)
            return buf.getvalue()

    def transcribe_base64(self, audio_base64: str) -> str:
        raw = base64.b64decode(audio_base64)
        return self.transcribe_wav(raw)

    def stream(
        self, sample_rate: int = 16000, on_partial: Callable[[str], None] | None = None
    ) -> "_StreamingRecognizer":
        return _StreamingRecognizer(self, sample_rate, on_partial)

    def wake_word(
        self,
        on_detected: Callable[[str], None],
        phrase: str = "computer",
        sample_rate: int = 16000,
    ) -> "_WakeWordDetector":
        return _WakeWordDetector(self, on_detected, phrase, sample_rate)


class _StreamingRecognizer:
    """Incremental transcription fed by PCM16 chunks."""

    def __init__(
        self,
        stt_manager: STTManager,
        sample_rate: int,
        on_partial: Callable[[str], None] | None = None,
    ):
        self._stt = stt_manager
        self._sample_rate = sample_rate
        self._on_partial = on_partial
        self._last_partial = ""
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._done = threading.Event()
        self._result = ""
        self._error: Exception | None = None
        self._pcm_all = bytearray()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            if self._stt._ensure_faster_whisper():
                self._run_faster_whisper()
            elif self._stt._ensure_vosk():
                self._run_vosk()
            else:
                self._result = ""
        except Exception as e:
            self._error = e
        finally:
            self._done.set()

    def _run_faster_whisper(self) -> None:
        if self._stt._vosk_loaded:
            recognizer = KaldiRecognizer(self._stt._vosk_model, self._sample_rate)
            while True:
                chunk = self._queue.get()
                if chunk is None:
                    break
                self._pcm_all.extend(chunk)
                recognizer.AcceptWaveform(chunk)
                if self._on_partial is not None:
                    try:
                        partial = json.loads(recognizer.PartialResult())
                        text = (partial.get("partial") or "").strip()
                        if text and text != self._last_partial:
                            self._last_partial = text
                            self._on_partial(text)
                    except Exception:
                        pass
            result = json.loads(recognizer.FinalResult())
            text = (result.get("text") or "").strip()
            if text:
                self._result = text
                return

        wav = STTManager._pcm16_to_wav(bytes(self._pcm_all), self._sample_rate)
        self._result = self._stt._transcribe_cloud(wav) if self._stt.openai_api_key else ""

    def _run_vosk(self) -> None:
        if not self._stt._vosk_loaded:
            self._result = ""
            return
        recognizer = KaldiRecognizer(self._stt._vosk_model, self._sample_rate)
        while True:
            chunk = self._queue.get()
            if chunk is None:
                break
            self._pcm_all.extend(chunk)
            recognizer.AcceptWaveform(chunk)
            if self._on_partial is not None:
                try:
                    partial = json.loads(recognizer.PartialResult())
                    text = (partial.get("partial") or "").strip()
                    if text and text != self._last_partial:
                        self._last_partial = text
                        self._on_partial(text)
                except Exception:
                    pass
        result = json.loads(recognizer.FinalResult())
        self._result = (result.get("text") or "").strip()

    def feed(self, pcm: bytes) -> None:
        self._queue.put(pcm)

    def abandon(self) -> None:
        self._queue.put(None)

    def finish(self, timeout: float = 15.0) -> str:
        self._queue.put(None)
        if not self._done.wait(timeout):
            raise RuntimeError("Speech recognition timed out")
        if self._error is not None:
            raise self._error
        return self._result


class _WakeWordDetector:
    """Continuous keyphrase spotter using Vosk grammar constraint."""

    def __init__(
        self,
        stt_manager: STTManager,
        on_detected: Callable[[str], None],
        phrase: str = "computer",
        sample_rate: int = 16000,
    ):
        self._stt = stt_manager
        self._on_detected = on_detected
        self._phrase = phrase
        self._sample_rate = sample_rate
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        recognizer = None
        if self._stt._ensure_vosk():
            grammar = json.dumps([self._phrase, "[unk]"])
            recognizer = KaldiRecognizer(self._stt._vosk_model, self._sample_rate, grammar)
        while True:
            chunk = self._queue.get()
            if chunk is None:
                break
            if recognizer is None:
                continue
            try:
                recognizer.AcceptWaveform(chunk)
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
            except Exception:
                continue
            words = [w for w in partial.split() if w != "[unk]"]
            if self._phrase in words:
                recognizer.Reset()
                with self._stt._load_lock:
                    pass
                with contextlib.suppress(Exception):
                    self._on_detected(self._phrase)

    def feed(self, pcm: bytes) -> None:
        self._queue.put(pcm)

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=2.0)
