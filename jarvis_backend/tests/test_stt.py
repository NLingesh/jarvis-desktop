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
