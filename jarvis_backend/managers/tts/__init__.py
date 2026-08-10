"""TTS providers — Kokoro primary, ElevenLabs optional fallback."""

from managers.tts.base import TTSConfigError, TTSProvider
from managers.tts.elevenlabs_provider import ElevenLabsProvider
from managers.tts.kokoro_provider import KokoroProvider

__all__ = [
    "TTSConfigError",
    "TTSProvider",
    "KokoroProvider",
    "ElevenLabsProvider",
]
