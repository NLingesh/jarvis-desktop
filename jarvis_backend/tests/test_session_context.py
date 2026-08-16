"""Tests for the bounded session context store."""

from modules.session_context import SessionContext, SessionContextStore


def test_tool_results_are_bounded():
    ctx = SessionContext("s1")
    for i in range(50):
        ctx.record_tool_result("read_file", {"path": f"/tmp/{i}"}, {"data": {"content": f"x{i}"}})
    assert len(ctx.tool_results) == 6
    assert ctx.tool_results[-1]["args"]["path"] == "/tmp/49"


def test_recent_paths_are_bounded_and_resolvable():
    ctx = SessionContext("s1")
    ctx.record_tool_result("open_folder", {"path": "/home/user/Projects/Alpha"}, {"success": True})
    ctx.record_tool_result("open_folder", {"path": "/home/user/Projects/Beta"}, {"success": True})
    assert len(ctx.recent_paths) == 2
    resolved = ctx.resolve_path("Beta")
    assert resolved == "/home/user/Projects/Beta"


def test_resolve_path_by_partial_match():
    ctx = SessionContext("s1")
    ctx.remember_path("/home/user/Downloads/report.pdf")
    assert ctx.resolve_path("report.pdf") == "/home/user/Downloads/report.pdf"
    assert ctx.resolve_path("report") == "/home/user/Downloads/report.pdf"
    assert ctx.resolve_path("nope") is None


def test_to_prompt_is_bounded():
    ctx = SessionContext("s1")
    ctx.active_task = "organize downloads"
    for i in range(50):
        ctx.record_tool_result("read_file", {"path": f"/tmp/{i}"}, {"data": {"content": "y" * 2000}})
    prompt = ctx.to_prompt()
    assert len(prompt) <= 2500
    assert "Active task: organize downloads" in prompt


def test_store_returns_stable_context_per_session():
    store = SessionContextStore()
    a = store.get("s1")
    assert store.get("s1") is a
    assert store.get("s2") is not a


def test_store_drops_session():
    store = SessionContextStore()
    store.get("s1")
    store.drop("s1")
    new = store.get("s1")
    assert new.pending_tool is None and list(new.tool_results) == []