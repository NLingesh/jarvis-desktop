import os
import base64
import io
import json
import wave
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

try:
    from vosk import Model, KaldiRecognizer
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

    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = model_dir or os.getenv("VOSK_MODEL_DIR") or self.DEFAULT_MODEL_DIR
        self._model = None
        self._recognizer = None
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_api_url = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/audio/transcriptions")

    @property
    def available(self) -> bool:
        return VOSK_AVAILABLE and os.path.isdir(self.model_dir)

    def _ensure_loaded(self):
        if self._model is not None:
            return True
        if not self.available:
            return False
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
                raise ValueError(f"Could not parse WAV audio: {e}")

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
            raise RuntimeError(f"Cloud speech recognition failed: {e}")

    def transcribe_base64(self, audio_base64: str) -> str:
        """Transcribe audio given as a base64 WAV payload."""
        raw = base64.b64decode(audio_base64)
        return self.transcribe_wav(raw)

    @property
    def has_cloud_fallback(self) -> bool:
        return bool(self.openai_api_key)

