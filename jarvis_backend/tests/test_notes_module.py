"""Tests for NotesModule — file-backed notes CRUD and search."""

import asyncio

from modules.notes_module import NotesModule


def run(coro):
    return asyncio.run(coro)


def make_module(tmp_path):
    return NotesModule(notes_dir=str(tmp_path / "notes"))


def test_create_and_get_note(tmp_path):
    module = make_module(tmp_path)
    note = run(module.create_note("Shopping", "Buy milk", tags=["errand"]))
    assert note["title"] == "Shopping"
    assert note["content"] == "Buy milk"
    assert note["tags"] == ["errand"]

    fetched = run(module.get_note(note["id"]))
    assert fetched == note


def test_create_note_without_tags(tmp_path):
    module = make_module(tmp_path)
    note = run(module.create_note("No tags", "plain"))
    assert note["tags"] == []


def test_get_notes_orders_newest_first(tmp_path):
    module = make_module(tmp_path)
    first = run(module.create_note("First", "a"))
    run(module.create_note("Second", "b"))
    notes = run(module.get_notes())
    assert [n["id"] for n in notes] == [
        notes[0]["id"],
        first["id"],
    ]
    assert notes[0]["title"] == "Second"


def test_get_notes_missing_notebook_returns_empty(tmp_path):
    module = make_module(tmp_path)
    assert run(module.get_notes("missing")) == []


def test_get_missing_note_returns_none(tmp_path):
    module = make_module(tmp_path)
    assert run(module.get_note("does-not-exist")) is None


def test_update_note(tmp_path):
    module = make_module(tmp_path)
    note = run(module.create_note("Title", "body"))
    ok = run(module.update_note(note["id"], title="New Title", content="new body"))
    assert ok is True
    updated = run(module.get_note(note["id"]))
    assert updated["title"] == "New Title"
    assert updated["content"] == "new body"


def test_update_missing_note_returns_false(tmp_path):
    module = make_module(tmp_path)
    assert run(module.update_note("nope", title="x")) is False


def test_delete_note(tmp_path):
    module = make_module(tmp_path)
    note = run(module.create_note("Delete me", "body"))
    assert run(module.delete_note(note["id"])) is True
    assert run(module.get_note(note["id"])) is None
    assert run(module.delete_note(note["id"])) is False


def test_search_notes(tmp_path):
    module = make_module(tmp_path)
    run(module.create_note("Project kickoff", "Discuss the deadline", tags=["work"]))
    run(module.create_note("Groceries", "Apples and bread"))

    by_content = run(module.search_notes("deadline"))
    assert len(by_content) == 1
    assert by_content[0]["title"] == "Project kickoff"

    by_tag = run(module.search_notes("work"))
    assert len(by_tag) == 1

    by_title = run(module.search_notes("groceries"))
    assert len(by_title) == 1

    assert run(module.search_notes("zebra")) == []


def test_notebook_isolation(tmp_path):
    module = make_module(tmp_path)
    run(module.create_note("Personal", "private", notebook="personal"))
    run(module.create_note("Work", "public", notebook="work"))
    assert len(run(module.get_notes("personal"))) == 1
    assert len(run(module.get_notes("work"))) == 1
    assert len(run(module.get_notes("default"))) == 0
