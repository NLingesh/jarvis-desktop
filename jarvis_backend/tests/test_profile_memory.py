"""Tests for profile-note memory persistence and legacy case migration.

Regression coverage for the bug where ``PROFILE_NOTE_PATH`` (``People/me.md``)
did not match the note actually created by ``create_note(title="Me")``
(``People/Me.md``) on case-sensitive filesystems, silently breaking save/read.
"""

import asyncio
import os

import pytest

import routes.state as state
from modules.vault.manager import VaultManager
from tools.memory_tools import ForgetMemoryTool, RecallMemoryTool, RememberMemoryTool


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def vault_manager(tmp_path):
    manager = VaultManager(str(tmp_path / "vault"))
    run(manager.initialize())
    return manager


@pytest.fixture
def state_with_vault(vault_manager, monkeypatch):
    monkeypatch.setattr(state, "vault", vault_manager)
    return vault_manager


def _notes_under(manager, folder):
    return [f for f in manager.store.list_files() if f.startswith(folder + "/")]


# --- core save / read / update / delete ------------------------------------

def test_ensure_creates_canonical_path(state_with_vault):
    run(state.ensure_profile_note())
    assert "People/Me.md" in _notes_under(state_with_vault, "People")
    note = run(state.get_profile_note())
    assert note is not None
    assert note["title"] == "Me"


def test_remember_roundtrip(state_with_vault):
    res = run(RememberMemoryTool().execute({"fact": "favorite color is teal"}))
    assert res.success
    recalled = run(RecallMemoryTool().execute({"query": "teal"}))
    assert recalled.success
    assert any("teal" in f for f in recalled.data["facts"])


def test_remember_deduplicates(state_with_vault):
    run(RememberMemoryTool().execute({"fact": "favorite color is teal"}))
    res = run(RememberMemoryTool().execute({"fact": "favorite color is teal"}))
    assert res.data["action"] == "already_remembered"


def test_update_persists_body(state_with_vault):
    run(state.ensure_profile_note())
    run(state.vault.update_note("People/Me.md", content="## About\n- updated fact"))
    note = run(state.get_profile_note())
    assert "updated fact" in note["body"]


def test_forget_removes_memory(state_with_vault):
    run(RememberMemoryTool().execute({"fact": "favorite color is teal"}))
    res = run(ForgetMemoryTool().execute({"query": "teal"}))
    assert res.success
    assert res.data["removed"] >= 1
    recalled = run(RecallMemoryTool().execute({"query": "teal"}))
    assert recalled.data["count"] == 0


def test_reset_profile_note(state_with_vault):
    run(state.ensure_profile_note())
    run(state.vault.update_note("People/Me.md", content="## About\n- secret fact"))
    ok = run(state.reset_profile_note())
    assert ok
    note = run(state.get_profile_note())
    assert "secret fact" not in note["body"]
    assert "Add things to remember" in note["body"]


def test_restart_persistence(state_with_vault, tmp_path):
    """Data must survive a fresh VaultManager over the same vault directory."""
    run(state.ensure_profile_note())
    run(state.vault.update_note("People/Me.md", content="## About\n- persistent fact"))

    manager2 = VaultManager(str(tmp_path / "vault"))
    run(manager2.initialize())
    old_vault = state.vault
    state.vault = manager2
    try:
        note = run(state.get_profile_note())
        assert note is not None
        assert "persistent fact" in note["body"]
    finally:
        state.vault = old_vault


# --- legacy case migration --------------------------------------------------

def test_legacy_lowercase_path_is_readable(state_with_vault, tmp_path):
    """A pre-existing ``People/me.md`` must still be read/written (migration)."""
    run(state.vault.create_note(
        title="me", folder="People", note_type="person",
        tags=["profile"], content="## About\n- legacy fact",
    ))
    # resolve must pick the existing lowercase file, not fail on the canonical
    resolved = state.resolve_profile_note_path()
    assert resolved == "People/me.md"
    note = run(state.get_profile_note())
    assert note is not None
    assert "legacy fact" in note["body"]

    res = run(RememberMemoryTool().execute({"fact": "added after migration"}))
    assert res.success
    note = run(state.get_profile_note())
    assert "added after migration" in note["body"]
    # still writing to the legacy path (no canonical file created)
    assert os.path.exists(os.path.join(str(tmp_path / "vault"), "People", "me.md"))


def test_missing_profile_returns_none(state_with_vault):
    assert run(state.get_profile_note()) is None
    assert run(state.ensure_profile_note()) is not None


def test_remember_missing_fact_rejected(state_with_vault):
    res = run(RememberMemoryTool().execute({"fact": ""}))
    assert not res.success
    assert "Missing fact" in res.error