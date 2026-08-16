"""Regression tests for TTSManager fallback serialization (Kokoro unavailable).

Covers the Kokoro-unavailable fallback path and every sentence-level response
path used by the WebSocket voice pipeline. All server-to-client chunks must be
valid JSON-serializable base64 strings (no raw bytes).
"""

import asyncio
import base64
import json

import pytest

from managers.tts_manager import TTSManager


def run(coro):
    return asyncio.run(coro)


class _FakeEdgeCommunicate:
    """Mimics edge_tts.Communicate with multiple audio chunks + metadata."""

    def __init__(self, text, voice):
        self._chunks = [b"edge-audio-1", b"edge-audio-2", b"edge-audio-3"]

    async def stream(self):
        for chunk in self._chunks:
            yield {"type": "audio", "data": chunk}
        yield {"type": "metadata", "data": {"key": "value"}}


class _EmptyEdgeCommunicate:
    def __init__(self, text, voice):
        pass

    async def stream(self):
        return
        yield  # pragma: no cover


def _manager_without_providers(monkeypatch):
    """TTSManager where Kokoro + ElevenLabs are unavailable (true fallback path)."""
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _FakeEdgeCommunicate)
    manager = TTSManager()
    monkeypatch.setattr(manager.kokoro, "available", lambda: False)
    monkeypatch.setattr(manager.elevenlabs, "available", lambda: False)
    return manager


def _collect(manager, text):
    async def go():
        return [c async for c in manager.stream_speech(text)]

    return run(go())


def test_fallback_chunks_are_json_serializable_strings(monkeypatch):
    manager = _manager_without_providers(monkeypatch)
    chunks = _collect(manager, "Hello world. Second sentence here!")
    assert len(chunks) >= 3
    for chunk in chunks:
        assert isinstance(chunk, str), f"expected str, got {type(chunk)}"
        assert chunk, "chunk must not be empty"
        json.dumps({"type": "audio_chunk", "chunk": chunk})
        assert base64.b64decode(chunk), "chunk must be valid base64 audio"


def test_fallback_chunks_decode_to_original_bytes(monkeypatch):
    manager = _manager_without_providers(monkeypatch)
    chunks = _collect(manager, "Testing")
    decoded = b"".join(base64.b64decode(c) for c in chunks)
    assert decoded == b"edge-audio-1edge-audio-2edge-audio-3"


def test_sentence_level_stream_all_sentences_yield_serializable(monkeypatch):
    """Every sentence in a multi-sentence reply must produce JSON-safe chunks."""
    manager = _manager_without_providers(monkeypatch)
    text = "First sentence. Second sentence! Third sentence?"
    chunks = _collect(manager, text)
    assert chunks, "expected audio chunks for the reply"
    for chunk in chunks:
        json.dumps({"type": "audio_chunk", "chunk": chunk})


def test_no_audio_when_edge_empty_falls_to_system(monkeypatch):
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _EmptyEdgeCommunicate)
    manager = TTSManager()
    monkeypatch.setattr(manager.kokoro, "available", lambda: False)
    monkeypatch.setattr(manager.elevenlabs, "available", lambda: False)

    async def fake_system(text):
        return "c3lzdGVtLWF1ZGlv"  # base64("system-audio")

    monkeypatch.setattr(manager, "_system_tts", fake_system)
    chunks = _collect(manager, "Hello")
    assert chunks == ["c3lzdGVtLWF1ZGlv"]


def test_ws_send_json_accepts_all_chunk_types(monkeypatch):
    """Simulate the exact send path used by _stream_sentence_audio."""
    manager = _manager_without_providers(monkeypatch)
    chunks = _collect(manager, "Hello there")
    sent = []
    for chunk in chunks:
        msg = json.dumps({"type": "audio_chunk", "chunk": chunk})
        sent.append(json.loads(msg)["chunk"])
    assert sent == chunks


def test_generate_speech_fallback_returns_base64(monkeypatch):
    """Non-streaming generate path must also be JSON-safe under the fallback."""
    manager = _manager_without_providers(monkeypatch)
    result = run(manager.generate_speech("Hello"))
    assert isinstance(result, str)
    assert result
    json.dumps({"type": "audio_chunk", "chunk": result})