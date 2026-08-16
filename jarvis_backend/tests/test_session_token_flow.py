"""Dev-only /api/session-token flow and packaged-mode session token enforcement.

The session token endpoint exists so the local dev frontend can learn the WS
token.  It must fail closed in packaged mode, for non-loopback servers/clients,
and for unknown origins.  In packaged mode every API call must present the
exact X-Jarvis-Token.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

import main as main_mod
import routes.state as state_mod

TOKEN = "pkg-secret-token"
HOST = "127.0.0.1:8000"


def _fresh_app():
    importlib.reload(main_mod)
    return main_mod.app


def _dev_client():
    return TestClient(_fresh_app())


def _packaged_client(monkeypatch):
    monkeypatch.setattr(state_mod, "SESSION_TOKEN", TOKEN)
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/jarvis_pkg_test/session.token")
    return TestClient(_fresh_app())


# --- dev context: token served to loopback -----------------------------------

def test_dev_loopback_gets_token():
    with _dev_client() as c:
        r = c.get("/api/session-token", headers={"Host": HOST})
    assert r.status_code == 200
    assert r.json()["token"]


def test_dev_non_loopback_client_host_denied():
    with _dev_client() as c:
        r = c.get("/api/session-token", headers={"Host": "10.0.0.5:8000"})
    assert r.status_code == 403


def test_dev_wrong_origin_denied():
    with _dev_client() as c:
        r = c.get(
            "/api/session-token",
            headers={"Host": HOST, "Origin": "http://evil.example"},
        )
    assert r.status_code == 403


def test_dev_known_origin_allowed():
    with _dev_client() as c:
        r = c.get(
            "/api/session-token",
            headers={"Host": HOST, "Origin": "http://localhost:5173"},
        )
    assert r.status_code == 200


def test_dev_non_loopback_server_host_denied(monkeypatch):
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    with _dev_client() as c:
        r = c.get("/api/session-token", headers={"Host": HOST})
    assert r.status_code == 403


# --- packaged mode: endpoint disabled, token required everywhere -------------

def test_packaged_session_token_endpoint_denied(monkeypatch):
    with _packaged_client(monkeypatch) as c:
        r = c.get("/api/session-token", headers={"Host": HOST})
    assert r.status_code == 403


def test_packaged_missing_token_rejected(monkeypatch):
    with _packaged_client(monkeypatch) as c:
        r = c.post("/api/system/execute", json={"command": "echo hello"})
    assert r.status_code == 401


def test_packaged_invalid_token_rejected(monkeypatch):
    with _packaged_client(monkeypatch) as c:
        r = c.post(
            "/api/system/execute",
            json={"command": "echo hello"},
            headers={"X-Jarvis-Token": "wrong-token"},
        )
    assert r.status_code == 401


def test_packaged_valid_token_accepted(monkeypatch):
    with _packaged_client(monkeypatch) as c:
        r = c.post(
            "/api/system/execute",
            json={"command": "echo hello"},
            headers={"X-Jarvis-Token": TOKEN},
        )
    assert r.status_code == 200