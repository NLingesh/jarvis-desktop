"""ElevenLabs TTS provider — optional fallback.

Requires an API key plus a valid voice ID. A 404 response (unknown voice or
no access to it) is treated as a permanent configuration error
(:class:`~managers.tts.base.TTSConfigError`) and is never retried.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator

import httpx

from managers.tts.base import TTSConfigError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
DEFAULT_TIMEOUT = 30.0
STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=15.0)


class ElevenLabsProvider:
    """Cloud ElevenLabs text-to-speech provider (optional fallback)."""

    name = "elevenlabs"

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID")
        self.model_id = model_id or DEFAULT_MODEL
        self.timeout = timeout or DEFAULT_TIMEOUT

    def available(self) -> bool:
        return bool(self.api_key and self.voice_id)

    def diagnostics(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available(),
            "configured": bool(self.api_key),
            "voice_id": self.voice_id,
            "model_id": self.model_id,
        }

    def _url(self, voice_id: str) -> str:
        return f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    def _headers(self) -> dict:
        return {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _payload(self, text: str) -> dict:
        return {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {"stability": 0.75, "similarity_boost": 0.75},
        }

    async def generate(self, text: str, voice_id: str | None = None) -> bytes:
        voice = voice_id or self.voice_id
        if not self.available() or not voice:
            raise TTSConfigError("ElevenLabs not configured (missing API key or voice)")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._url(voice), headers=self._headers(), json=self._payload(text)
            )
            if response.status_code == 404:
                raise TTSConfigError(
                    f"ElevenLabs voice {voice!r} not found (404). "
                    "Check ELEVENLABS_VOICE_ID — the voice may have been deleted "
                    "or your key may lack access."
                )
            response.raise_for_status()
            return response.content

    async def stream(self, text: str, voice_id: str | None = None) -> AsyncGenerator[bytes, None]:
        voice = voice_id or self.voice_id
        if not self.available() or not voice:
            raise TTSConfigError("ElevenLabs not configured (missing API key or voice)")
        async with (
            httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client,
            client.stream(
                "POST", self._url(voice), headers=self._headers(), json=self._payload(text)
            ) as response,
        ):
            if response.status_code == 404:
                raise TTSConfigError(
                    f"ElevenLabs voice {voice!r} not found (404). "
                    "Check ELEVENLABS_VOICE_ID — the voice may have been deleted "
                    "or your key may lack access."
                )
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
