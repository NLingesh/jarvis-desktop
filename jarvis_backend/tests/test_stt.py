"""Tests for the SpeechToTextModule — WAV parsing, model availability, cloud fallback."""

import base64
import io
import wave
from unittest.mock import MagicMock, patch

import pytest

from modules.stt import SpeechToTextModule


def make_test_wav(seconds=0.1, sample_rate=16000):
    """Generate a valid mono 16 kHz WAV in memory and return its bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        n = int(sample_rate * seconds)
        wf.writeframes(b"\x00" * (n * 2))
    return buf.getvalue()


def test_available_without_model_dir_is_false():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    assert stt.available is False


def test_transcribe_base64_decode_error():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    with pytest.raises((ValueError, Exception)):
        stt.transcribe_base64("!!!not-base64!!!")


def test_has_cloud_fallback_flag():
    stt = SpeechToTextModule()
    assert stt.has_cloud_fallback is False


def test_cloud_fallback_without_api_key_raises():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    stt.openai_api_key = None
    wav = make_test_wav()
    with pytest.raises(RuntimeError, match="Speech-to-text is unavailable"):
        stt.transcribe_wav(wav)


def test_transcribe_base64_valid_wav_calls_transcribe_wav():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    stt.openai_api_key = "test-key"
    wav = make_test_wav()
    b64 = base64.b64encode(wav).decode()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "hello world"
    mock_resp.raise_for_status = MagicMock()

    with patch("modules.stt.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        result = stt.transcribe_base64(b64)
    assert result == "hello world"


def test_stream_finish_returns_text():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    stt.openai_api_key = None

    rec = MagicMock()
    rec.FinalResult.return_value = '{"text": "hello world"}'

    with (
        patch.object(stt, "_ensure_loaded", return_value=True),
        patch("modules.stt.KaldiRecognizer", return_value=rec),
    ):
        stream = stt.stream(16000)
        stream.feed(b"\x00" * 1600)
        stream.feed(b"\x00" * 1600)
        result = stream.finish()
    assert result == "hello world"


def test_stream_empty_result_falls_back_to_cloud():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    stt.openai_api_key = "test-key"

    rec = MagicMock()
    rec.FinalResult.return_value = '{"text": ""}'

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "fallback transcript"
    mock_resp.raise_for_status = MagicMock()

    with (
        patch.object(stt, "_ensure_loaded", return_value=True),
        patch("modules.stt.KaldiRecognizer", return_value=rec),
        patch("modules.stt.httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        stream = stt.stream(16000)
        stream.feed(b"\x00" * 1600)
        result = stream.finish()
    assert result == "fallback transcript"


def test_stream_emits_partials():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    stt.openai_api_key = None

    rec = MagicMock()
    rec.FinalResult.return_value = '{"text": "hello world"}'
    rec.PartialResult.side_effect = [
        '{"partial": "hello"}',
        '{"partial": "hello"}',
        '{"partial": "hello world"}',
    ]

    partials: list[str] = []

    with (
        patch.object(stt, "_ensure_loaded", return_value=True),
        patch("modules.stt.KaldiRecognizer", return_value=rec),
    ):
        stream = stt.stream(16000, on_partial=partials.append)
        stream.feed(b"\x00" * 1600)
        stream.feed(b"\x00" * 1600)
        stream.feed(b"\x00" * 1600)
        result = stream.finish()

    assert result == "hello world"
    assert partials == ["hello", "hello world"]


def test_stream_without_vosk_or_cloud_raises():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")
    stt.openai_api_key = None

    with patch.object(stt, "_ensure_loaded", return_value=False):
        stream = stt.stream(16000)
        stream.feed(b"\x00" * 1600)
        with pytest.raises(RuntimeError, match="Speech-to-text is unavailable"):
            stream.finish()


def test_stream_abandon_does_not_raise():
    stt = SpeechToTextModule(model_dir="/nonexistent/path")

    rec = MagicMock()
    rec.FinalResult.return_value = '{"text": "hi"}'

    with (
        patch.object(stt, "_ensure_loaded", return_value=True),
        patch("modules.stt.KaldiRecognizer", return_value=rec),
    ):
        stream = stt.stream(16000)
        stream.feed(b"\x00" * 1600)
        stream.abandon()
        stream.abandon()  # idempotent
    assert True
