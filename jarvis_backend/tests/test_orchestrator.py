"""Tests for the typed conversational orchestrator."""

import asyncio

import pytest

from modules.capability import CapabilityPolicy
from modules.orchestrator import Orchestrator, strip_markdown_for_speech
from modules.session_context import SessionContext
from tools import BaseTool

run = asyncio.run


class _Result:
    def __init__(self, success=True, data=None, error=None, requires_confirmation=False):
        self.success = success
        self.data = data
        self.error = error
        self.requires_confirmation = requires_confirmation

    def to_dict(self):
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "requires_confirmation": self.requires_confirmation,
        }


class _ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a text file."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    risk_level = "read_only"

    async def execute(self, arguments, context=None):
        return _Result(data={"content": "hello world"})


class _DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Delete a file. Requires confirmation."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    risk_level = "destructive"

    async def execute(self, arguments, context=None):
        return _Result(data={"deleted": arguments.get("path")})


class _Registry:
    def __init__(self, *tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools.get(name)

    def list_tools(self):
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    async def execute_tool(self, name, args, context=None):
        return await self._tools[name].execute(args, context=context)


class _FakeLLM:
    provider = "mistral"
    api_key = "test"
    api_url = "http://127.0.0.1:9"
    model = "x"


def _make_orchestrator(*tools):
    return Orchestrator(_FakeLLM(), _Registry(*tools), CapabilityPolicy())


def _patch(monkeypatch, decision_text):
    async def fake_chat(self, messages):
        return decision_text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)


def test_reply_decision(monkeypatch):
    _patch(monkeypatch, '{"reply": "Hello! How can I help?"}')
    decision = run(_make_orchestrator().run("hi", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert decision.text == "Hello! How can I help?"


def test_clarify_decision_is_reply(monkeypatch):
    _patch(monkeypatch, '{"clarify": "Do you mean the folder or the file?"}')
    decision = run(_make_orchestrator().run("open that", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "folder or the file" in decision.text


def test_unknown_tool_rejected(monkeypatch):
    _patch(monkeypatch, '{"tool": "fly_to_mars", "arguments": {}}')
    decision = run(_make_orchestrator().run("fly", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "don't have a way" in decision.text.lower()


def test_invalid_arguments_rejected(monkeypatch):
    _patch(monkeypatch, '{"tool": "read_file", "arguments": {}}')
    decision = run(
        _make_orchestrator(_ReadFileTool()).run("read", "s1", SessionContext("s1"), {})
    )
    assert decision.kind == "reply"
    assert "Missing required argument" in decision.text


def test_read_only_tool_executes(monkeypatch):
    _patch(monkeypatch, '{"tool": "read_file", "arguments": {"path": "/tmp/a"}}')
    ctx = SessionContext("s1")
    decision = run(_make_orchestrator(_ReadFileTool()).run("read /tmp/a", "s1", ctx, {}))
    # Tool ran and looped; the stub re-requests the same tool until MAX_STEPS.
    assert len(ctx.tool_results) == 4
    assert decision.kind == "reply"


def test_destructive_tool_requires_confirm(monkeypatch):
    _patch(monkeypatch, '{"tool": "delete_file", "arguments": {"path": "/tmp/a"}}')
    policy = CapabilityPolicy()
    orch = Orchestrator(_FakeLLM(), _Registry(_DeleteFileTool()), policy)
    ctx = SessionContext("s1")
    decision = run(orch.run("delete /tmp/a", "s1", ctx, {}))
    assert decision.kind == "confirm"
    assert decision.tool == "delete_file"
    assert ctx.pending_tool == "delete_file"
    assert policy.has_pending("s1", "delete_file")


def test_respond_to_confirmed_executes_and_consumes(monkeypatch):
    _patch(monkeypatch, '{"tool": "delete_file", "arguments": {"path": "/tmp/a"}}')
    policy = CapabilityPolicy()
    orch = Orchestrator(_FakeLLM(), _Registry(_DeleteFileTool()), policy)
    ctx = SessionContext("s1")
    run(orch.run("delete /tmp/a", "s1", ctx, {}))

    _patch(monkeypatch, '{"reply": "Deleted /tmp/a."}')
    reply = run(orch.respond_to_confirmed("s1", ctx, {}))
    assert "Deleted" in reply
    assert not policy.has_pending("s1", "delete_file")
    assert ctx.pending_tool is None
    assert ctx.pending_args is None


def test_respond_to_confirmed_missing_approval(monkeypatch):
    _patch(monkeypatch, '{"reply": "done"}')
    orch = _make_orchestrator(_DeleteFileTool())
    ctx = SessionContext("s1")
    ctx.pending_tool = "delete_file"
    ctx.pending_args = {"path": "/tmp/a"}
    reply = run(orch.respond_to_confirmed("s1", ctx, {}))
    assert "can't find a pending action" in reply.lower()


def test_respond_to_confirmed_failure_is_reported(monkeypatch):
    class _FailingTool(BaseTool):
        name = "delete_file"
        description = "Delete a file. Requires confirmation."
        parameters = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        risk_level = "destructive"

        async def execute(self, arguments, context=None):
            return _Result(success=False, error="permission denied")

    _patch(monkeypatch, '{"tool": "delete_file", "arguments": {"path": "/tmp/a"}}')
    orch = Orchestrator(_FakeLLM(), _Registry(_FailingTool()), CapabilityPolicy())
    ctx = SessionContext("s1")
    run(orch.run("delete /tmp/a", "s1", ctx, {}))
    _patch(monkeypatch, '{"reply": "done"}')
    reply = run(orch.respond_to_confirmed("s1", ctx, {}))
    assert "permission denied" in reply


def test_parse_decision_strips_markdown_fences():
    assert Orchestrator._parse_decision('```json\n{"reply": "hi"}\n```') == {
        "kind": "reply",
        "text": "hi",
    }
    assert Orchestrator._parse_decision('{"tool": "read_file", "args": {"path": "/a"}}') == {
        "kind": "tool",
        "tool": "read_file",
        "arguments": {"path": "/a"},
    }


def test_parse_decision_natural_language_fallback():
    parsed = Orchestrator._parse_decision("Sure, I can help with that.")
    assert parsed is None


def test_strip_markdown_for_speech():
    assert strip_markdown_for_speech("**Hello** _world_ `code`") == "Hello world code"
    assert strip_markdown_for_speech("- item\n- item2") == "item item2"