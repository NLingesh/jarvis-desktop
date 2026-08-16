"""Kokoro TTS provider — fully local, the primary engine.

Uses ``kokoro.KPipeline`` (v0.9.x API). The model is downloaded once into the
Hugging Face cache on first use and then runs offline. Output is 24 kHz mono
WAV; audio is streamed sentence-by-sentence.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
import wave
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)

try:
    import kokoro
    import torch

    KOKORO_AVAILABLE = True
except Exception:  # pragma: no cover - depends on install
    torch = None  # type: ignore[assignment]
    kokoro = None  # type: ignore[assignment]
    KOKORO_AVAILABLE = False

DEFAULT_VOICE = os.getenv("KOKORO_VOICE", "am_adam")
DEFAULT_LANG = os.getenv("KOKORO_LANG", "a")
SAMPLE_RATE = 24000


class KokoroProvider:
    """Local Kokoro text-to-speech provider (primary)."""

    name = "kokoro"

    def __init__(
        self,
        voice: str | None = None,
        lang_code: str | None = None,
        model_path: str | None = None,
    ) -> None:
        self.voice = voice or DEFAULT_VOICE
        self.lang_code = lang_code or DEFAULT_LANG
        self.model_path = model_path or os.getenv("KOKORO_MODEL_PATH")
        self._pipeline: Any | None = None
        self._loaded = False
        self._load_lock = threading.Lock()

    def _ensure_pipeline(self) -> Any:
        if self._loaded and self._pipeline is not None:
            return self._pipeline
        if not KOKORO_AVAILABLE:
            raise RuntimeError("kokoro package is not installed")
        with self._load_lock:
            if self._loaded and self._pipeline is not None:
                return self._pipeline
            kwargs: dict[str, Any] = {"lang_code": self.lang_code}
            if self.model_path:
                kwargs["repo_id"] = self.model_path
            self._pipeline = kokoro.KPipeline(**kwargs)
            self._loaded = True
            logger.info("Kokoro TTS loaded (lang=%s, voice=%s)", self.lang_code, self.voice)
            return self._pipeline

    def available(self) -> bool:
        return KOKORO_AVAILABLE

    def diagnostics(self) -> dict:
        return {
            "provider": self.name,
            "available": KOKORO_AVAILABLE,
            "loaded": self._loaded,
            "lang": self.lang_code,
            "voice": self.voice,
            "sample_rate": SAMPLE_RATE,
        }

    def _synthesize(self, text: str, voice_id: str | None) -> list[bytes]:
        """Run Kokoro in a worker thread; return one WAV per sentence."""
        pipe = self._ensure_pipeline()
        voice = voice_id or self.voice
        chunks: list[bytes] = []
        for result in pipe(text, voice=voice):
            audio = getattr(result, "audio", None)
            if audio is None:
                continue
            chunks.append(self._tensor_to_wav(audio, SAMPLE_RATE))
        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for voice {voice!r}")
        return chunks

    @staticmethod
    def _tensor_to_wav(audio: Any, sr: int) -> bytes:
        """Convert a float32 torch tensor in [-1, 1] to 16-bit mono WAV."""
        samples = audio.detach().cpu().numpy()
        samples = (samples * 32767.0).clip(-32768, 32767).astype("<i2")
        with io.BytesIO() as buf:
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(samples.tobytes())
            return buf.getvalue()

    async def generate(self, text: str, voice_id: str | None = None) -> bytes:
        chunks = await asyncio.to_thread(self._synthesize, text, voice_id)
        return b"".join(chunks)

    async def stream(self, text: str, voice_id: str | None = None) -> AsyncGenerator[bytes, None]:
        chunks = await asyncio.to_thread(self._synthesize, text, voice_id)
        for chunk in chunks:
            yield chunk
