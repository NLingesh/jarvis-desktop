"""Tests for the /ws/voice streaming protocol (audio_start/chunk/end, ping/pong)."""

import base64
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Create a TestClient with a known session token and no working STT."""
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN", "test-secret-token")
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/test_session_token")

    import main as main_mod

    importlib.reload(main_mod)

    # Force the Vosk path to be unavailable and remove the cloud fallback so
    # transcription deterministically fails without hitting a real API/LLM.
    stt = state_mod.stt
    monkeypatch.setattr(stt, "openai_api_key", None)
    monkeypatch.setattr(stt, "_ensure_loaded", lambda: False)
    return TestClient(main_mod.app)


def test_ws_rejects_missing_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/voice") as ws:
        ws.receive_json()


def test_ws_ping_gets_pong(client):
    with client.websocket_connect("/ws/voice?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
    assert data == {"type": "pong"}


def test_ws_audio_chunk_without_start_is_rejected(client):
    with client.websocket_connect("/ws/voice?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json({"type": "audio_chunk", "data": base64.b64encode(b"\x00" * 1600).decode()})
        data = ws.receive_json()
    assert data["type"] == "error"
    assert "audio_start must precede" in data["message"]


def test_ws_streaming_flow_reports_error_when_stt_unavailable(client):
    with client.websocket_connect("/ws/voice?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json(
            {
                "type": "audio_start",
                "format": "pcm16",
                "sample_rate": 16000,
                "channels": 1,
            }
        )
        assert ws.receive_json()["type"] == "status"

        for _ in range(3):
            ws.send_json({"type": "audio_chunk", "data": base64.b64encode(b"\x00" * 1600).decode()})

        ws.send_json({"type": "audio_end"})
        data = ws.receive_json()
    assert data["type"] == "error"
    assert "Speech-to-text is unavailable" in data["message"]


def _drain_server(ws):
    """The server sends a ``server`` build-welcome message on connect; consume it."""
    msg = ws.receive_json()
    assert msg.get("type") == "server"
    assert msg.get("build")
