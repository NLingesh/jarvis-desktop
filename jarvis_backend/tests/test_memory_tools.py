"""Memory service: save/search/update/forget, retention, secrets, context tool."""

import asyncio

import pytest

import routes.state as state
from modules.session_context import SessionContextStore
from modules.vault.manager import VaultManager
from tools.memory_tools import (
    ClearAllMemoriesTool,
    ForgetMemoryTool,
    GetCurrentContextTool,
    RecallMemoryTool,
    RememberMemoryTool,
    UpdateMemoryTool,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def vault_manager(tmp_path):
    manager = VaultManager(str(tmp_path / "vault"))
    run(manager.initialize())
    return manager


@pytest.fixture
def mem(vault_manager, monkeypatch):
    monkeypatch.setattr(state, "vault", vault_manager)
    return vault_manager


def _body(manager):
    note = run(state.get_profile_note())
    return (note or {}).get("body") or ""


# --- save / list / search ----------------------------------------------------


def test_save_and_list(mem):
    res = run(RememberMemoryTool().execute({"fact": "I prefer a male voice"}))
    assert res.success and res.data["action"] == "remembered"
    assert "I prefer a male voice" in _body(mem)
    listed = run(RecallMemoryTool().execute({}))
    assert listed.data["count"] == 1


def test_search_filters_results(mem):
    run(RememberMemoryTool().execute({"fact": "I prefer a male voice"}))
    run(RememberMemoryTool().execute({"fact": "main project is JARVIS"}, {"category": "project"}))
    hits = run(RecallMemoryTool().execute({"query": "voice"}))
    assert hits.data["count"] == 1
    assert "male voice" in hits.data["facts"][0]


def test_update_replaces_matching_item_only(mem):
    run(RememberMemoryTool().execute({"fact": "I prefer a male voice"}))
    run(RememberMemoryTool().execute({"fact": "favorite color is teal"}))
    res = run(
        UpdateMemoryTool().execute({"query": "male voice", "new_fact": "I prefer a female voice"})
    )
    assert res.success and res.data["updated"] == 1
    body = _body(mem)
    assert "- [preference] I prefer a female voice" in body
    assert "- [preference] I prefer a male voice" not in body
    assert "teal" in body


def test_forget_removes_only_matches(mem):
    run(RememberMemoryTool().execute({"fact": "I prefer a male voice"}))
    run(RememberMemoryTool().execute({"fact": "favorite color is teal"}))
    res = run(ForgetMemoryTool().execute({"query": "teal"}))
    assert res.data["removed"] == 1
    body = _body(mem)
    assert "teal" not in body and "male voice" in body


def test_forget_nothing_matched_is_honest(mem):
    run(RememberMemoryTool().execute({"fact": "I prefer a male voice"}))
    res = run(ForgetMemoryTool().execute({"query": "nonexistent thing"}))
    assert res.success and res.data["removed"] == 0


# --- security ----------------------------------------------------------------


@pytest.mark.parametrize(
    "fact",
    [
        "my password is hunter2",
        "api key sk-abc123def456ghi",
        "remember my credentials",
        "token ghp_16CharactersXXXXXXXXXXX",
    ],
)
def test_secrets_never_persist(mem, fact):
    res = run(RememberMemoryTool().execute({"fact": fact}))
    assert not res.success
    assert fact.lower() not in _body(mem).lower()
    assert "credential" in res.error or "password" in res.error or "tokens" in res.error


def test_injection_characters_are_sanitized(mem):
    res = run(RememberMemoryTool().execute({"fact": "likes cats\n- [general] injected"}))
    assert res.success
    body = _body(mem)
    assert "injected] " not in body.splitlines()[-1] or "likes cats" in body
    # The stored line count for facts stays 1.
    assert run(RecallMemoryTool().execute({})).data["count"] == 1


# --- retention ----------------------------------------------------------------


def test_retention_caps_items_dropping_oldest(mem, monkeypatch):
    import tools.memory_tools as mt

    monkeypatch.setattr(mt, "MAX_MEMORIES", 3)
    for i in range(5):
        res = run(RememberMemoryTool().execute({"fact": f"numbered fact {i}"}))
        assert res.success
    facts = run(RecallMemoryTool().execute({}))
    assert facts.data["count"] == 3
    body = _body(mem)
    assert "numbered fact 0" not in body
    assert "numbered fact 4" in body


# --- clear-all ----------------------------------------------------------------


def test_clear_all_resets_memory(mem):
    run(RememberMemoryTool().execute({"fact": "I prefer a male voice"}))
    res = run(ClearAllMemoriesTool().execute({}))
    assert res.success and res.data["cleared"]
    assert run(RecallMemoryTool().execute({})).data["count"] == 0


# --- get_current_context --------------------------------------------------------


def test_get_current_context_reports_verified_state_only(monkeypatch):
    store = SessionContextStore()
    monkeypatch.setattr(state, "session_context_store", store)
    ctx = store.get("ctx-test")
    ctx.record_tool_result(
        "launch_application",
        {"app": "vs code"},
        {"success": True, "data": {"launched": "vs code", "verified": True}},
    )
    ctx.remember_path("/home/wiz/Downloads")
    res = run(GetCurrentContextTool().execute({}, context={"session_id": "ctx-test"}))
    assert res.success
    assert res.data["last_launched_app"] == "vs code"
    assert "/home/wiz/Downloads" in res.data["recent_paths"]


def test_get_current_context_empty_session(monkeypatch):
    monkeypatch.setattr(state, "session_context_store", SessionContextStore())
    res = run(GetCurrentContextTool().execute({}, context={"session_id": "fresh"}))
    assert res.success
    assert res.data["last_launched_app"] is None


# --- legacy content preservation ----------------------------------------------


def test_freeform_note_content_survives_memory_writes(mem):
    """Non-fact lines in the profile note must never be dropped by writes."""
    run(state.ensure_profile_note())
    run(
        state.vault.update_note(
            state.resolve_profile_note_path(),
            content="## About\nFree-form paragraph about the user.\n- [preference] old fact",
        )
    )
    run(RememberMemoryTool().execute({"fact": "new fact"}))
    body = _body(mem)
    assert "Free-form paragraph about the user." in body
    assert "old fact" in body
    assert "new fact" in body
