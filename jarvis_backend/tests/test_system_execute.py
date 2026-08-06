"""Tests for the /api/system/execute route — command allowlist enforcement."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Create a TestClient with a known session token."""
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN", "test-secret-token")
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/test_session_token")
    import main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_system_info_endpoint(client):
    resp = client.get("/api/system/info")
    assert resp.status_code == 200


def test_execute_without_token_is_unauthorized(client):
    resp = client.post(
        "/api/system/execute",
        json={"command": "echo hello"},
    )
    assert resp.status_code == 401


def test_execute_with_valid_token_allows_safe_command(monkeypatch):
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN", "test-secret-token")
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/test_session_token")
    import main as main_mod

    importlib.reload(main_mod)
    client = TestClient(main_mod.app)

    resp = client.post(
        "/api/system/execute",
        json={"command": "echo hello"},
        headers={"X-Jarvis-Token": "test-secret-token"},
    )
    assert resp.status_code == 200
    assert "hello" in resp.json()["output"]


def test_execute_rejects_non_allowlisted_command(monkeypatch):
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN", "test-secret-token")
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/test_session_token")
    import main as main_mod

    importlib.reload(main_mod)
    client = TestClient(main_mod.app)

    resp = client.post(
        "/api/system/execute",
        json={"command": "rm -rf /"},
        headers={"X-Jarvis-Token": "test-secret-token"},
    )
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert "not allowed" in resp.json()["output"].lower()
