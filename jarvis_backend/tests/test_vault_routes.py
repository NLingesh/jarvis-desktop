"""Tests for the /api/vault HTTP endpoints."""

import asyncio
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import main as main_app
import routes.state as state
import routes.vault as vault_routes
from modules.vault.manager import VaultManager


@pytest.fixture
def client(tmp_path):
    manager = VaultManager(str(tmp_path / "vault"))
    asyncio.run(manager.initialize())
    state.vault = manager
    vault_routes.vault = manager
    main_app.vault = manager
    with TestClient(main_app.app) as c:
        yield c


def p(path: str) -> str:
    return quote(path, safe="/")


def test_create_and_get_note(client):
    resp = client.post(
        "/api/vault/notes",
        json={"title": "Roadmap", "content": "launch plan", "tags": ["plan"]},
    )
    assert resp.status_code == 200
    note = resp.json()["note"]
    assert note["title"] == "Roadmap"
    assert note["tags"] == ["plan"]
    assert note["id"]

    got = client.get(f"/api/vault/note/{p(note['path'])}")
    assert got.status_code == 200
    assert got.json()["note"]["body"] == "launch plan"


def test_list_notes_and_filters(client):
    client.post("/api/vault/notes", json={"title": "Alpha", "content": "x", "tags": ["work"]})
    client.post("/api/vault/notes", json={"title": "Beta", "content": "y", "folder": "Knowledge"})
    resp = client.get("/api/vault/notes")
    assert {n["title"] for n in resp.json()["notes"]} == {"Alpha", "Beta"}
    resp = client.get("/api/vault/notes", params={"folder": "Knowledge"})
    assert [n["title"] for n in resp.json()["notes"]] == ["Beta"]
    resp = client.get("/api/vault/notes", params={"tag": "work"})
    assert [n["title"] for n in resp.json()["notes"]] == ["Alpha"]


def test_update_note(client):
    note = client.post("/api/vault/notes", json={"title": "T", "content": "old"}).json()["note"]
    resp = client.put(
        f"/api/vault/note/{p(note['path'])}", json={"content": "new", "favorite": True}
    )
    assert resp.status_code == 200
    updated = resp.json()["note"]
    assert updated["body"] == "new"
    assert updated["favorite"] is True


def test_delete_note_then_404(client):
    note = client.post("/api/vault/notes", json={"title": "Temp", "content": "x"}).json()["note"]
    resp = client.delete(f"/api/vault/note/{p(note['path'])}")
    assert resp.status_code == 200
    assert client.get(f"/api/vault/note/{p(note['path'])}").status_code == 404


def test_duplicate_create_409(client):
    client.post("/api/vault/notes", json={"title": "Same", "content": "a"})
    resp = client.post("/api/vault/notes", json={"title": "Same", "content": "b"})
    assert resp.status_code == 409


def test_missing_note_404(client):
    assert client.get("/api/vault/note/Missing.md").status_code == 404


def test_rename_updates_links(client):
    client.post("/api/vault/notes", json={"title": "Source", "content": "See [[Target]]"})
    target = client.post("/api/vault/notes", json={"title": "Target", "content": "x"}).json()[
        "note"
    ]
    resp = client.post(
        "/api/vault/note/rename", json={"path": target["path"], "title": "Target Two"}
    )
    assert resp.status_code == 200
    source = client.get("/api/vault/note/Source.md").json()["note"]
    assert "[[Target Two]]" in source["body"]

    backlinks = client.get(f"/api/vault/backlinks/{p('Target Two.md')}").json()["backlinks"]
    assert [b["path"] for b in backlinks] == ["Source.md"]


def test_search_returns_results(client):
    client.post(
        "/api/vault/notes",
        json={"title": "Kickoff", "content": "deadline tomorrow", "tags": ["work"]},
    )
    client.post("/api/vault/notes", json={"title": "Groceries", "content": "apples"})
    resp = client.get("/api/vault/search", params={"q": "deadline"})
    assert [r["title"] for r in resp.json()["results"]] == ["Kickoff"]
    resp = client.get("/api/vault/search", params={"tag": "work"})
    assert [r["title"] for r in resp.json()["results"]] == ["Kickoff"]
    resp = client.get("/api/vault/search", params={})
    assert resp.status_code == 400


def test_folders_and_tags_and_meta(client):
    client.post(
        "/api/vault/notes", json={"title": "A", "content": "x", "folder": "Projects/Portal"}
    )
    resp = client.post("/api/vault/folders", json={"folder": "Ideas/New"})
    assert resp.status_code == 200
    folders = client.get("/api/vault/folders").json()["folders"]
    assert "Projects/Portal" in folders
    assert "Ideas/New" in folders

    tags = client.get("/api/vault/tags").json()["tags"]
    assert tags == []

    meta = client.get("/api/vault/meta").json()["meta"]
    assert meta["total"] == 1
    assert "templates" in meta


def test_reindex_endpoint(client):
    client.post("/api/vault/notes", json={"title": "Reindex me", "content": "hello world"})
    resp = client.post("/api/vault/index")
    assert resp.status_code == 200
    assert resp.json()["status"] == "reindexed"


def test_path_traversal_blocked(client):
    resp = client.post(
        "/api/vault/notes", json={"title": "Evil", "content": "x", "folder": "../../etc"}
    )
    assert resp.status_code == 400
