"""Regression tests for ``_stream_sentence_audio`` segment framing.

Every ``audio_segment`` must contain exactly one complete, decodable audio
file so the renderer never has to decode concatenated RIFF/WAV blobs:

* whole-file chunks (e.g. Kokoro WAV) → one segment each;
* fragments of a single streamed file (e.g. edge-tts MP3) → one joined segment.
"""

import asyncio
import base64
import io
import wave

import pytest

import routes.state as state_mod
from routes.state import _stream_sentence_audio


class _FakeSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def _wav_b64(frames: int = 1600, sample_rate: int = 24000) -> str:
    """Build a minimal valid 16-bit mono WAV and return it as base64."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * frames)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def monkeypatch_stream(monkeypatch):
    def _set(chunks: list[str]) -> None:
        async def fake_stream(text, voice_id=None):
            for chunk in chunks:
                yield chunk

        monkeypatch.setattr(state_mod.tts, "stream_speech", fake_stream)

    return _set


def run(coro):
    return asyncio.run(coro)


def _collect(socket, sentence: str) -> list[dict]:
    run(_stream_sentence_audio(socket, sentence, "test-uid"))
    return socket.sent


def test_multiple_whole_wav_chunks_become_separate_segments(monkeypatch_stream):
    socket = _FakeSocket()
    monkeypatch_stream([_wav_b64(), _wav_b64()])
    sent = _collect(socket, "Hello world.")

    # start, chunk, end, start, chunk, end
    assert len(sent) == 6
    assert [m["type"] for m in sent] == [
        "audio_segment_start",
        "audio_chunk",
        "audio_segment_end",
        "audio_segment_start",
        "audio_chunk",
        "audio_segment_end",
    ]
    # each segment carries exactly one complete WAV file, never a join.
    for m in sent:
        if m["type"] == "audio_chunk":
            assert base64.b64decode(m["chunk"]).startswith(b"RIFF")


def test_fragments_are_joined_into_one_segment(monkeypatch_stream):
    socket = _FakeSocket()
    fragments = ["ZWRnZS0x", "ZWRnZS0y", "ZWRnZS0z"]  # edge-1/edge-2/edge-3
    monkeypatch_stream(fragments)
    sent = _collect(socket, "Testing")

    assert [m["type"] for m in sent] == [
        "audio_segment_start",
        "audio_chunk",
        "audio_segment_end",
    ]
    joined = sent[1]["chunk"]
    assert base64.b64decode(joined) == b"edge-1edge-2edge-3"


def test_mixed_wav_then_fragments_stay_in_separate_segments(monkeypatch_stream):
    socket = _FakeSocket()
    monkeypatch_stream([_wav_b64(), "ZWRnZS0x", "ZWRnZS0y"])
    sent = _collect(socket, "Mixed output.")

    types = [m["type"] for m in sent]
    assert types == [
        "audio_segment_start",
        "audio_chunk",
        "audio_segment_end",
        "audio_segment_start",
        "audio_chunk",
        "audio_segment_end",
    ]
    assert base64.b64decode(sent[1]["chunk"]).startswith(b"RIFF")
    assert base64.b64decode(sent[4]["chunk"]) == b"edge-1edge-2"


def test_no_audio_sends_error_and_empty_segment(monkeypatch_stream):
    socket = _FakeSocket()
    monkeypatch_stream([])
    sent = _collect(socket, "Silence please.")

    assert any(m["type"] == "error" for m in sent)
    assert sent[-1] == {"type": "audio_segment_end"}