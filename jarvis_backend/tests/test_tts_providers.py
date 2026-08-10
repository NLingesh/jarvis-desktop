"""Tests for the TTS provider architecture (Kokoro primary / ElevenLabs fallback)."""

import asyncio

import pytest

from managers.tts.base import TTSConfigError
from managers.tts.elevenlabs_provider import ElevenLabsProvider
from managers.tts.kokoro_provider import KokoroProvider
from managers.tts_manager import TTSManager


def run(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, status_code, content=b"", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError

            raise HTTPStatusError(str(self.status_code), request=None, response=self)


def test_kokoro_provider_diagnostics():
    provider = KokoroProvider()
    diag = provider.diagnostics()
    assert diag["provider"] == "kokoro"
    assert diag["sample_rate"] == 24000


def test_elevenlabs_not_configured_raises_config_error():
    provider = ElevenLabsProvider(api_key=None, voice_id=None)
    assert provider.available() is False
    with pytest.raises(TTSConfigError):
        run(provider.generate("hello"))


def test_elevenlabs_404_is_config_error_not_retried(monkeypatch):
    provider = ElevenLabsProvider(api_key="key", voice_id="voice-abc")

    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(404, text="voice not found")

    monkeypatch.setattr(
        "managers.tts.elevenlabs_provider.httpx.AsyncClient", _FakeAsyncClient(fake_post)
    )
    with pytest.raises(TTSConfigError) as exc_info:
        run(provider.generate("hello"))
    assert "404" in str(exc_info.value)


def test_elevenlabs_success(monkeypatch):
    provider = ElevenLabsProvider(api_key="key", voice_id="voice-abc")

    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, content=b"MP3DATA")

    monkeypatch.setattr(
        "managers.tts.elevenlabs_provider.httpx.AsyncClient", _FakeAsyncClient(fake_post)
    )
    audio = run(provider.generate("hello"))
    assert audio == b"MP3DATA"


def test_tts_manager_diagnostics_shape():
    manager = TTSManager()
    diag = manager.diagnostics()
    for key in ("provider", "kokoro_available", "elevenlabs_configured", "ready"):
        assert key in diag
    assert diag["provider"] in ("kokoro", "elevenlabs")


def test_tts_manager_primary_respects_env(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    assert TTSManager().primary == "elevenlabs"


def test_tts_manager_unknown_primary_defaults_to_kokoro(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "bogus")
    assert TTSManager().primary == "kokoro"


class _FakeAsyncClient:
    """Fake httpx.AsyncClient replacement.

    ``async with AsyncClient() as client`` then ``await client.post(...)``.
    """

    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __call__(self, *args, **kwargs):
        return self

    async def post(self, url, headers=None, json=None):
        return await self._handler(self, url, headers=headers, json=json)
