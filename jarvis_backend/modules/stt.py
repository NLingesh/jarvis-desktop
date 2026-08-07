import base64
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
    from vosk import KaldiRecognizer, Model

    VOSK_AVAILABLE = True
except Exception:
    VOSK_AVAILABLE = False


class SpeechToTextModule:
    """Speech-to-text with offline Vosk and cloud fallback.

    The model is loaded lazily on first use so the backend starts fast even
    when no model has been downloaded yet. If Vosk is unavailable, a cloud
    fallback (OpenAI Whisper-compatible API) is attempted when configured.
    """

    DEFAULT_MODEL_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models",
        "vosk-model-small-en-us-0.15",
    )

    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir or os.getenv("VOSK_MODEL_DIR") or self.DEFAULT_MODEL_DIR
        self._model = None
        self._recognizer = None
        self._load_lock = threading.Lock()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_api_url = os.getenv(
            "OPENAI_API_URL", "https://api.openai.com/v1/audio/transcriptions"
        )

    @property
    def available(self) -> bool:
        return VOSK_AVAILABLE and os.path.isdir(self.model_dir)

    def _ensure_loaded(self):
        if self._model is not None:
            return True
        if not self.available:
            return False
        with self._load_lock:
            if self._model is not None:
                return True
            try:
                self._model = Model(self.model_dir)
                return True
            except Exception as e:
                logger.error(f"Failed to load Vosk model from {self.model_dir}: {e}")
                return False

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        """Transcribe PCM16 mono 16kHz WAV audio bytes."""
        if self._ensure_loaded():
            try:
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    rate = wf.getframerate()
                    channels = wf.getnchannels()
                    if channels != 1:
                        raise ValueError(f"Expected mono audio, got {channels} channels")
                    data = wf.readframes(wf.getnframes())
            except (wave.Error, ValueError, EOFError) as e:
                raise ValueError(f"Could not parse WAV audio: {e}") from e

            try:
                recognizer = KaldiRecognizer(self._model, rate)
                recognizer.AcceptWaveform(data)
                result = json.loads(recognizer.FinalResult())
                text = (result.get("text") or "").strip()
                if text:
                    return text
            except Exception as vosk_err:
                logger.warning(f"Vosk transcription failed, falling back to cloud: {vosk_err}")

        return self._transcribe_cloud(wav_bytes)

    def _transcribe_cloud(self, wav_bytes: bytes) -> str:
        """Fallback to cloud STT (OpenAI Whisper-compatible API)."""
        if not self.openai_api_key:
            raise RuntimeError(
                "Speech-to-text is unavailable. Install vosk + download a model, "
                "or set OPENAI_API_KEY for cloud fallback."
            )
        try:
            with httpx.Client(timeout=30.0) as client:
                files = {"file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")}
                data = {"model": "whisper-1", "response_format": "text"}
                headers = {"Authorization": f"Bearer {self.openai_api_key}"}
                response = client.post(self.openai_api_url, headers=headers, files=files, data=data)
                response.raise_for_status()
                text = response.text.strip()
                if text and not text.startswith("{"):
                    return text
                return ""
        except Exception as e:
            logger.error(f"Cloud STT failed: {e}")
            raise RuntimeError(f"Cloud speech recognition failed: {e}") from e

    def transcribe_base64(self, audio_base64: str) -> str:
        """Transcribe audio given as a base64 WAV payload."""
        raw = base64.b64decode(audio_base64)
        return self.transcribe_wav(raw)

    @property
    def has_cloud_fallback(self) -> bool:
        return bool(self.openai_api_key)

    def preload(self) -> bool:
        """Load the Vosk model in the background so the first utterance is fast."""
        return self._ensure_loaded()

    def stream(
        self, sample_rate: int = 16000, on_partial: "Callable[[str], None] | None" = None
    ) -> "_StreamingRecognizer":
        """Create a streaming recognizer for an in-progress utterance.

        ``on_partial`` is invoked from the worker thread with the live partial
        hypothesis whenever it changes (may be called many times per utterance).
        """
        return _StreamingRecognizer(self, sample_rate, on_partial)


def _pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM16 mono samples into a WAV container."""
    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()


class _StreamingRecognizer:
    """Incremental Vosk transcription fed by PCM16 chunks.

    PCM chunks are pushed to a worker thread as they arrive over the WebSocket;
    ``AcceptWaveform`` is called per chunk so the recognizer is always up to
    date. ``finish()`` returns the final transcription. When Vosk is unavailable
    or returns no text, the cloud fallback is used with the accumulated WAV.
    """

    def __init__(
        self,
        stt_module: "SpeechToTextModule",
        sample_rate: int,
        on_partial: "Callable[[str], None] | None" = None,
    ):
        self._stt = stt_module
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

    def _run(self):
        try:
            vosk_used = False
            if self._stt._ensure_loaded():
                vosk_used = True
                recognizer = KaldiRecognizer(self._stt._model, self._sample_rate)
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
                            logger.warning("PartialResult unavailable, ignoring", exc_info=True)
                result = json.loads(recognizer.FinalResult())
                text = (result.get("text") or "").strip()
                if text:
                    self._result = text
                    self._done.set()
                    return
            else:
                while True:
                    chunk = self._queue.get()
                    if chunk is None:
                        break
                    self._pcm_all.extend(chunk)

            wav = _pcm16_to_wav(bytes(self._pcm_all), self._sample_rate)
            if vosk_used and not self._stt.has_cloud_fallback:
                # Vosk heard nothing and there is no cloud fallback to try.
                self._result = ""
            else:
                self._result = self._stt._transcribe_cloud(wav)
        except Exception as e:
            self._error = e
        finally:
            self._done.set()

    def feed(self, pcm: bytes) -> None:
        """Push a PCM16 chunk to the recognizer worker (non-blocking)."""
        self._queue.put(pcm)

    def abandon(self) -> None:
        """Discard an unfinished utterance without waiting for the result."""
        self._queue.put(None)

    def finish(self, timeout: float = 15.0) -> str:
        """Finalize the utterance and return the transcription."""
        self._queue.put(None)
        if not self._done.wait(timeout):
            raise RuntimeError("Speech recognition timed out")
        if self._error is not None:
            raise self._error
        return self._result
