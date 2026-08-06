"""Tests for TextToSpeechModule — encoding, voice list, and fallback behavior."""

import asyncio
import base64

import edge_tts

from modules.tts import TextToSpeechModule


def run(coro):
    return asyncio.run(coro)


def make_tts(monkeypatch):
    module = TextToSpeechModule()
    monkeypatch.setattr(module, "use_elevenlabs", False)
    return module


def test_to_base64_roundtrip():
    tts = TextToSpeechModule()
    encoded = tts._to_base64(b"\x00\x01\x02")
    assert base64.b64decode(encoded) == b"\x00\x01\x02"


def test_get_supported_voices():
    voices = TextToSpeechModule.get_supported_voices()
    assert len(voices) == 4
    assert all("id" in v and "name" in v for v in voices)


def test_find_tts_engine_none(monkeypatch):
    monkeypatch.setattr("modules.tts.shutil.which", lambda name: None)
    tts = TextToSpeechModule()
    assert tts._find_tts_engine() is None


def test_find_tts_engine_detects(monkeypatch):
    monkeypatch.setattr(
        "modules.tts.shutil.which",
        lambda name: "/usr/bin/" + name if name == "espeak-ng" else None,
    )
    tts = TextToSpeechModule()
    assert tts._find_tts_engine() == "espeak-ng"


def test_generate_speech_uses_edge_tts(monkeypatch):
    tts = make_tts(monkeypatch)

    async def fake_edge(text):
        return b"RIFFaudio"

    monkeypatch.setattr(tts, "_edge_tts", fake_edge)
    result = run(tts.generate_speech("hello"))
    assert base64.b64decode(result) == b"RIFFaudio"


def test_generate_speech_elevenlabs_first(monkeypatch):
    tts = TextToSpeechModule()
    monkeypatch.setattr(tts, "use_elevenlabs", True)

    async def fake_eleven(text, voice_id=None):
        return b"eleven-bytes"

    monkeypatch.setattr(tts, "_elevenlabs_tts", fake_eleven)
    result = run(tts.generate_speech("hi"))
    assert base64.b64decode(result) == b"eleven-bytes"


def test_generate_speech_falls_back_when_elevenlabs_fails(monkeypatch):
    tts = TextToSpeechModule()
    monkeypatch.setattr(tts, "use_elevenlabs", True)

    async def broken(text, voice_id=None):
        raise RuntimeError("network down")

    async def fake_edge(text):
        return b"edge-bytes"

    monkeypatch.setattr(tts, "_elevenlabs_tts", broken)
    monkeypatch.setattr(tts, "_edge_tts", fake_edge)
    result = run(tts.generate_speech("hi"))
    assert base64.b64decode(result) == b"edge-bytes"


def test_generate_speech_empty_when_all_fail(monkeypatch):
    tts = make_tts(monkeypatch)

    async def broken_edge(text):
        raise RuntimeError("no edge")

    async def empty_system(text):
        return ""

    monkeypatch.setattr(tts, "_edge_tts", broken_edge)
    monkeypatch.setattr(tts, "_system_tts", empty_system)
    assert run(tts.generate_speech("hi")) == ""


class _FakeCommunicate:
    def __init__(self, text, voice):
        pass

    async def stream(self):
        yield {"type": "audio", "data": b"aaa"}
        yield {"type": "audio", "data": b"bbb"}
        yield {"type": "metadata"}


def test_stream_speech_yields_edge_chunks(monkeypatch):
    tts = make_tts(monkeypatch)
    monkeypatch.setattr(edge_tts, "Communicate", _FakeCommunicate)

    async def scenario():
        chunks = []
        async for chunk in tts.stream_speech("hello"):
            chunks.append(chunk)
        return chunks

    chunks = run(scenario())
    assert base64.b64decode(chunks[0]) == b"aaa"
    assert base64.b64decode(chunks[1]) == b"bbb"


def test_stream_speech_falls_back_to_generate(monkeypatch):
    tts = make_tts(monkeypatch)

    def broken_communicate(text, voice):
        raise RuntimeError("edge unavailable")

    monkeypatch.setattr(edge_tts, "Communicate", broken_communicate)

    async def fake_generate(text, voice_id=None):
        return "fallback-b64"

    monkeypatch.setattr(tts, "generate_speech", fake_generate)

    async def scenario():
        return [chunk async for chunk in tts.stream_speech("hello")]

    assert run(scenario()) == ["fallback-b64"]
