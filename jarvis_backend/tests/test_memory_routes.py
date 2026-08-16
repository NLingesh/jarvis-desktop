"""Regression tests for /api/memory route fixes.

Covers two pre-existing bugs found during the end-to-end verification run:

1. ``GET /api/memory/{session_id}`` was declared before the static routes
   (``/projects``, ``/tasks``, ``/knowledge``, ...), so FastAPI matched the
   dynamic route first and ``GET /api/memory/projects`` returned a session's
   conversation instead of the project list.
2. ``POST /api/memory/knowledge`` passed ``type=`` to
   ``MemoryManager.create_knowledge``, which expects ``k_type=``, raising an
   unhandled ``TypeError`` (500).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import main as main_app
import routes.memory as memory_routes
import routes.state as state
from managers.memory_manager import MemoryManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = MemoryManager(db_path=str(tmp_path / "test_memory.db"))

    monkeypatch.setattr(state, "memory_manager", manager)
    monkeypatch.setattr(main_app, "memory_manager", manager)
    monkeypatch.setattr(memory_routes, "memory_manager", manager)
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


def test_projects_list_not_shadowed_by_session_id(client):
    resp = client.post(
        "/api/memory/projects",
        json={"name": "shadow-check", "description": "x"},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200
    resp = client.get("/api/memory/projects", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "projects" in data
    assert any(p.get("name") == "shadow-check" for p in data["projects"])


def test_tasks_list_not_shadowed_by_session_id(client):
    resp = client.post(
        "/api/memory/tasks",
        json={"title": "shadow-task", "status": "todo"},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200
    resp = client.get("/api/memory/tasks", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert any(t.get("title") == "shadow-task" for t in data["tasks"])


def test_knowledge_create_and_delete(client):
    resp = client.post(
        "/api/memory/knowledge",
        json={"content": "a harmless fact", "type": "note"},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200
    item = resp.json()
    assert item.get("content") == "a harmless fact"
    assert item.get("type") == "note"

    resp = client.get("/api/memory/knowledge", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    assert "knowledge" in resp.json()

    resp = client.request(
        "DELETE",
        f"/api/memory/knowledge/{item['id']}",
        json={"confirm": True},
        headers={"Host": "127.0.0.1"},
    )
    assert resp.status_code == 200


def test_conversation_by_session_id_still_works(client):
    session_id = asyncio.run(state.memory_manager.create_session())
    resp = client.get(f"/api/memory/{session_id}", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.json() == {"conversation": []}
