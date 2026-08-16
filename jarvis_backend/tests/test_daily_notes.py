"""Tests for the /api/memory/vault/daily-notes endpoints.

Regression coverage for the fix where ``get_daily_notes`` called the missing
``search_notes`` method (renamed to ``scan_notes``), producing an unhandled 500.
Covers empty notes, matching notes, no matches, malformed dates, and missing
vault data — all with typed client-safe errors.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import main as main_app
import routes.state as state
import routes.vault as vault_routes
from modules.vault.manager import VaultManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = VaultManager(str(tmp_path / "vault"))
    asyncio.run(manager.initialize())
    monkeypatch.setattr(state, "vault", manager)
    monkeypatch.setattr(main_app, "vault", manager)
    monkeypatch.setattr(vault_routes, "vault", manager)
    _reset_rate_limit(main_app.app)
    with TestClient(main_app.app) as c:
        yield c


def _iter_rate_limiters(app):
    stack = getattr(app, "middleware_stack", None)
    seen = set()
    while stack is not None and id(stack) not in seen:
        seen.add(id(stack))
        if isinstance(stack, main_app.RateLimitMiddleware):
            yield stack
        stack = getattr(stack, "app", None)


def _reset_rate_limit(app):
    """Clear the shared RateLimitMiddleware budget so tests do not 429 each other."""
    for mw in _iter_rate_limiters(app):
        mw._requests.clear()


def test_daily_notes_empty(client):
    resp = client.get("/api/memory/vault/daily-notes", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.json() == {"daily_notes": []}


def test_daily_notes_lists_created(client):
    resp = client.post(
        "/api/memory/vault/daily-notes",
        json={"date": "2026-08-15"},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "2026-08-15"

    got = client.get("/api/memory/vault/daily-notes", headers={"Host": "127.0.0.1"})
    assert got.status_code == 200
    notes = got.json()["daily_notes"]
    assert any(n["title"] == "2026-08-15" for n in notes)


def test_daily_notes_multiple_sorted_newest_first(client):
    for date in ("2026-08-10", "2026-08-11", "2026-08-12"):
        resp = client.post(
            "/api/memory/vault/daily-notes",
            json={"date": date},
            headers={"Host": "127.0.0.1"},
        )
        assert resp.status_code == 200
    got = client.get("/api/memory/vault/daily-notes", headers={"Host": "127.0.0.1"})
    titles = [n["title"] for n in got.json()["daily_notes"]]
    assert titles[0] == "2026-08-12"
    assert titles[1] == "2026-08-11"
    assert titles[2] == "2026-08-10"


def test_daily_notes_no_matches_when_only_other_notes(client):
    resp = client.post(
        "/api/vault/notes",
        json={"title": "Roadmap", "content": "plan", "tags": []},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200
    got = client.get("/api/memory/vault/daily-notes", headers={"Host": "127.0.0.1"})
    assert got.json() == {"daily_notes": []}


def test_create_daily_note_default_date(client):
    resp = client.post(
        "/api/memory/vault/daily-notes",
        json={},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200
    import datetime as dt

    assert resp.json()["title"] == dt.date.today().isoformat()


def test_create_daily_note_malformed_date_rejected(client):
    resp = client.post(
        "/api/memory/vault/daily-notes",
        json={"date": "not-a-date"},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]


def test_create_daily_note_path_traversal_rejected(client):
    resp = client.post(
        "/api/memory/vault/daily-notes",
        json={"date": "2026-01-01/../../evil"},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 400


def test_daily_notes_handles_missing_vault_data(client, monkeypatch):
    class _BrokenVault:
        async def get_daily_notes(self, limit=30):
            raise RuntimeError("index corrupt")

    monkeypatch.setattr(state, "vault", _BrokenVault())
    resp = client.get("/api/memory/vault/daily-notes", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 500
    assert "Failed to list daily notes" in resp.json()["detail"]


def test_daily_notes_typed_error_not_html(client, monkeypatch):
    """A vault failure must yield a JSON error, never an HTML 500 page."""
    class _BrokenVault:
        async def get_daily_notes(self, limit=30):
            raise RuntimeError("boom")

    monkeypatch.setattr(state, "vault", _BrokenVault())
    resp = client.get("/api/memory/vault/daily-notes", headers={"Host": "127.0.0.1"})
    assert resp.headers["content-type"].startswith("application/json")
    assert "detail" in resp.json()