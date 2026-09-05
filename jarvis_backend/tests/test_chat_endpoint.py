"""Regression tests for the orchestrator-backed typed chat endpoint.

Covers the divergence where typed chat used to call the bare-LLM
``/api/llm/generate`` path (no tool dispatch, so "open my Downloads folder"
was answered with a generic refusal) while the WebSocket voice path dispatched
real tools.  ``/api/chat`` must run the same orchestrator pipeline and surface
verified tool results.
"""

import asyncio

import pytest
from fastapi import HTTPException

from modules.orchestrator import Orchestrator
from routes import chat as chat_mod
from routes import state as state_mod
from tools import file_tools

run = asyncio.run

_TOKEN_KEY = "jarvis_chat_session"


class _FakeLLM:
    provider = "mistral"
    api_key = "test"
    api_url = "http://127.0.0.1:9"
    model = "x"


class _FakeRequest:
    headers: dict = {}

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _patch_chat(monkeypatch, decisions):
    """Stateful ``_openai_chat`` returning each decision JSON in order."""
    queue = list(decisions)

    async def fake_chat(self, messages):
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)


def _install_chat_orchestrator(monkeypatch):
    """Swap the route's orchestrator for one on the real tool registry + a fake LLM."""
    orch = Orchestrator(_FakeLLM(), state_mod.tool_registry, state_mod.capability_policy)
    monkeypatch.setattr(chat_mod, "orchestrator", orch)
    return orch


def _call(body, session_id=None):
    payload = dict(body)
    if session_id:
        payload["session_id"] = session_id
    return run(chat_mod.api_chat(_FakeRequest(payload)))


def test_chat_dispatches_open_folder_tool(monkeypatch):
    """Typed 'open my Downloads folder' runs the real open_folder tool."""
    calls = []

    def fake_desktop_open(target, timeout=5.0, **kwargs):
        calls.append(str(target))
        return None

    monkeypatch.setattr(file_tools, "desktop_open", fake_desktop_open)
    _patch_chat(
        monkeypatch,
        [
            '{"tool": "open_folder", "arguments": {"path": "Downloads"}}',
            '{"reply": "I have opened your Downloads folder."}',
        ],
    )
    _install_chat_orchestrator(monkeypatch)

    result = _call({"message": "open my Downloads folder"})

    assert result["text"]
    assert "Downloads" in result["text"]
    assert len(calls) == 1
    assert calls[0].endswith("Downloads")
    tools = result.get("tool_results", [])
    assert len(tools) == 1
    assert tools[0]["tool"] == "open_folder"
    assert tools[0]["result"]["success"] is True


def test_chat_no_duplicate_process_on_repeat_tool(monkeypatch):
    """Repeated identical tool decisions open the folder only once."""
    calls = []

    def fake_desktop_open(target, timeout=5.0, **kwargs):
        calls.append(str(target))
        return None

    monkeypatch.setattr(file_tools, "desktop_open", fake_desktop_open)
    _patch_chat(
        monkeypatch,
        [
            '{"tool": "open_folder", "arguments": {"path": "Downloads"}}',
            '{"tool": "open_folder", "arguments": {"path": "Downloads"}}',
        ],
    )
    _install_chat_orchestrator(monkeypatch)

    _call({"message": "open my Downloads folder"})
    assert len(calls) == 1


def test_chat_creates_and_returns_session(monkeypatch):
    _patch_chat(monkeypatch, ['{"reply": "Hello!"}'])
    _install_chat_orchestrator(monkeypatch)
    result = _call({"message": "hi"})
    assert result["session_id"]
    assert isinstance(result["session_id"], str)


def test_chat_confirmation_flow(monkeypatch):
    """Destructive tools need approval via the chat path, then run on 'yes'."""
    _patch_chat(
        monkeypatch,
        ['{"tool": "delete_file", "arguments": {"path": "/tmp/opencode/no-such-chat-file"}}'],
    )
    _install_chat_orchestrator(monkeypatch)

    first = _call({"message": "delete that file"})
    assert first["needs_confirmation"] is True
    assert first["tool"] == "delete_file"
    sid = first["session_id"]
    assert sid

    _patch_chat(monkeypatch, ['{"reply": "Deleted it."}'])
    second = _call({"message": "yes"}, session_id=sid)
    assert second.get("confirmed") is True
    assert second["text"]
    assert not second.get("needs_confirmation", False)


def test_chat_cancel_confirmation(monkeypatch):
    _patch_chat(
        monkeypatch,
        ['{"tool": "delete_file", "arguments": {"path": "/tmp/opencode/no-such-chat-file"}}'],
    )
    _install_chat_orchestrator(monkeypatch)

    first = _call({"message": "delete that file"})
    sid = first["session_id"]
    second = _call({"message": "no"}, session_id=sid)
    assert second.get("confirmed") is False
    assert "cancel" in second["text"].lower()


def test_chat_error_decision_mapped(monkeypatch):
    async def boom(self, messages):
        raise RuntimeError("provider down")

    monkeypatch.setattr(Orchestrator, "_openai_chat", boom)
    _install_chat_orchestrator(monkeypatch)
    result = _call({"message": "what is the weather"})
    assert result.get("error") is True
    assert "not responding" in result["text"].lower()


def test_chat_requires_message():
    with pytest.raises(HTTPException) as exc:
        _call({})
    assert exc.value.status_code == 400


def test_chat_rejects_false_tool_success_claim(monkeypatch):
    """A fake 'opened' reply without a real tool run must not be reported as success."""
    calls = []

    def fake_desktop_open(target, timeout=5.0, **kwargs):
        calls.append(str(target))
        return None

    monkeypatch.setattr(file_tools, "desktop_open", fake_desktop_open)
    _patch_chat(
        monkeypatch,
        [
            # Model wrongly claims the open already happened without calling a tool.
            '{"reply": "I have opened your Downloads folder."}',
        ],
    )
    _install_chat_orchestrator(monkeypatch)

    result = _call({"message": "please open my downloads"})
    assert len(calls) == 0
    assert len(result.get("tool_results", [])) == 0


def test_chat_persists_session_key(monkeypatch):
    """Follow-up messages reuse the same context when the session id is sent back."""
    _patch_chat(monkeypatch, ['{"reply": "First answer."}'])
    _install_chat_orchestrator(monkeypatch)

    first = _call({"message": "hello"})
    assert first["session_id"]
    second = _call({"message": "hello again"}, session_id=first["session_id"])
    assert second["session_id"] == first["session_id"]


def test_control_app_window_honest_failure_without_renderers():
    """No connected renderer -> the tool reports a failure, never a fake success."""
    from tools.app_tools import ControlAppWindowTool

    result = run(ControlAppWindowTool().execute({"action": "show_main"}))
    assert result.success is False
    assert "could not" in result.error.lower()
    assert result.data["verified"] is False


def test_control_app_window_verified_only_with_ack(monkeypatch):
    import modules.window_control as wc
    from tools.app_tools import ControlAppWindowTool

    async def fake_broadcast(payload):
        return 1

    async def fake_wait(request_id, timeout=3.0):
        return True

    monkeypatch.setattr(wc, "broadcast", fake_broadcast)
    monkeypatch.setattr(wc, "wait_for_ack", fake_wait)
    result = run(ControlAppWindowTool().execute({"action": "show_main"}))
    assert result.success is True
    assert result.data["verified"] is True


def test_control_app_window_unknown_action_rejected():
    from tools.app_tools import ControlAppWindowTool

    result = run(ControlAppWindowTool().execute({"action": "minimize_to_tray"}))
    assert result.success is False
