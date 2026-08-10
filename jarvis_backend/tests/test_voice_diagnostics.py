"""Tests for the /api/voice/diagnostics health endpoint."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN", "test-secret-token")
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/test_session_token")
    import main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_voice_diagnostics_shape(client):
    resp = client.get("/api/voice/diagnostics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"]["status"] == "ok"
    assert isinstance(body["ws_connections"], int)
    for section in ("stt", "tts", "llm"):
        assert section in body
    # stt diagnostics expose structured readiness fields.
    assert isinstance(body["stt"]["ready"], bool)
    assert isinstance(body["stt"]["model_installed"], bool)
    assert isinstance(body["stt"]["cloud_fallback"], bool)
    # tts diagnostics expose provider availability.
    assert isinstance(body["tts"]["elevenlabs_configured"], bool)
    assert isinstance(body["tts"]["edge_tts_available"], bool)
    assert isinstance(body["tts"]["ready"], bool)


def test_health_reports_stt_and_connections(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "stt" in body
    assert "ws_connections" in body
