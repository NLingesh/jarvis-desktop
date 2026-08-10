"""TTS provider abstractions.

Defines the :class:`TTSProvider` interface that every provider implements,
plus the error used for permanent configuration failures (e.g. ElevenLabs 404).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


class TTSConfigError(Exception):
    """Raised for permanent configuration errors that should not be retried.

    For example, an ElevenLabs 404 (unknown voice) means the request will
    never succeed — callers should log it as a config error and move on.
    """


class TTSProvider(ABC):
    """Interface implemented by all TTS backends."""

    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """Return True when this provider can produce audio right now."""

    @abstractmethod
    def diagnostics(self) -> dict:
        """Structured status used by /api/voice/diagnostics and health."""

    @abstractmethod
    async def generate(self, text: str, voice_id: str | None = None) -> bytes:
        """Synthesize ``text`` and return raw audio bytes (WAV/MP3)."""

    def stream(self, text: str, voice_id: str | None = None) -> AsyncGenerator[bytes, None]:
        """Synthesize ``text`` and yield raw audio bytes incrementally."""
        raise NotImplementedError(f"{self.name} does not support streaming")
