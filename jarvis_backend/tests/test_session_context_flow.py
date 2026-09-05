"""Short-term conversational context: bounded history, isolation, verified-only state."""

from modules.session_context import (
    MAX_PROMPT_CHARS,
    MAX_TURNS,
    SessionContext,
    SessionContextStore,
)

PROJECT = "/home/wiz/Desktop/Project Folder/maybe jarvis"


def test_multi_turn_project_and_file_context():
    ctx = SessionContext("s1")
    ctx.record_exchange("Open my JARVIS project.")
    ctx.remember_path(PROJECT)
    ctx.selected_project = PROJECT
    ctx.record_exchange("Read the README.", "Opened the README at the project root.")
    assert ctx.last_user_input == "Read the README."
    # Follow-up can resolve against recently referenced paths.
    assert ctx.resolve_path("maybe jarvis") == PROJECT
    prompt = ctx.to_prompt()
    assert f"Selected project: {PROJECT}" in prompt
    assert "Recent turns:" in prompt
    assert "Open my JARVIS project." in prompt
    assert "Read the README." in prompt


def test_sessions_are_isolated_from_each_other():
    store = SessionContextStore()
    a = store.get("session-a")
    b = store.get("session-b")
    a.record_exchange("open the secret lab folder")
    a.remember_path("/home/wiz/secret-lab")
    assert b.last_user_input is None
    assert b.resolve_path("secret-lab") is None
    assert b.to_prompt() == ""


def test_drop_clears_context_for_new_session_start():
    store = SessionContextStore()
    ctx = store.get("s1")
    ctx.record_exchange("hello there")
    store.drop("s1")
    fresh = store.get("s1")
    assert fresh is not ctx
    assert fresh.last_user_input is None
    assert len(fresh.turns) == 0
    assert fresh.older_summary == ""


def test_reset_keeps_identity_but_clears_state():
    ctx = SessionContext("keep-me")
    ctx.record_exchange("some exchange", "some reply")
    ctx.remember_path("/tmp/x")
    ctx.reset()
    assert ctx.session_id == "keep-me"
    assert ctx.last_user_input is None
    assert ctx.last_reply is None
    assert len(ctx.recent_paths) == 0
    assert len(ctx.turns) == 0


def test_history_is_bounded_and_older_turns_summarized():
    ctx = SessionContext("s1")
    for i in range(MAX_TURNS + 6):
        ctx.record_exchange(f"question number {i}", f"answer number {i}")
    assert len(ctx.turns) == MAX_TURNS
    assert ctx.older_summary, "overflowing turns must be folded into a summary"
    assert "question number 0" in ctx.older_summary
    # Recent turns stay verbatim; only the tail is kept.
    recent_texts = [t["text"] for t in ctx.turns]
    assert f"question number {MAX_TURNS + 5}" in recent_texts
    assert "question number 1" not in recent_texts
    prompt = ctx.to_prompt()
    assert len(prompt) <= MAX_PROMPT_CHARS
    assert "Earlier in this conversation" in prompt


def test_llm_claims_never_become_structured_context():
    ctx = SessionContext("s1")
    # A reply that *claims* an action sets no verified context fields.
    ctx.record_exchange("open vs code", "I have launched VS Code for you.")
    assert ctx.last_launched_app is None
    # Only a verified tool result does.
    ctx.record_tool_result(
        "launch_application",
        {"app": "vs code"},
        {"success": True, "data": {"launched": "vs code", "verified": True}},
    )
    assert ctx.last_launched_app == "vs code"
    summary = ctx.context_summary()
    assert summary["last_launched_app"] == "vs code"


def test_failed_tool_results_do_not_set_context():
    ctx = SessionContext("s1")
    ctx.record_tool_result(
        "launch_application",
        {"app": "firefox"},
        {"success": False, "error": "not installed"},
    )
    assert ctx.last_launched_app is None


def test_clarification_tracking():
    ctx = SessionContext("s1")
    ctx.set_pending_clarification("Which folder did you mean?")
    assert ctx.context_summary()["pending_clarification"] == "Which folder did you mean?"
    ctx.set_pending_clarification(None)
    assert ctx.context_summary()["pending_clarification"] is None
