"""Tests for the typed conversational orchestrator."""

import asyncio

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
    decision = run(_make_orchestrator(_ReadFileTool()).run("read", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "Missing required argument" in decision.text


def test_read_only_tool_executes(monkeypatch):
    _patch(monkeypatch, '{"tool": "read_file", "arguments": {"path": "/tmp/a"}}')
    ctx = SessionContext("s1")
    decision = run(_make_orchestrator(_ReadFileTool()).run("read /tmp/a", "s1", ctx, {}))
    # The tool runs exactly once; a repeated identical tool call is
    # short-circuited into a forced reply instead of looping to MAX_STEPS.
    assert len(ctx.tool_results) == 1
    assert ctx.tool_results[0]["tool"] == "read_file"
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


def test_open_the_window_never_hallucinates(monkeypatch):
    """'open the window' must clarify, even if the model claims a terminal."""

    _patch(monkeypatch, '{"reply": "the terminal is already open"}')
    decision = run(_make_orchestrator().run("open the window", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "Which window should I open" in decision.text


def test_open_a_window_clarifies():
    orch = _make_orchestrator()
    decision = orch._route_desktop_intent("open a window")
    assert decision is not None
    assert decision.kind == "reply"
    assert "Which window should I open" in decision.text


def test_open_jarvis_window_routes_to_tool():
    orch = _make_orchestrator()
    decision = orch._route_desktop_intent("open the jarvis window")
    assert decision is not None
    assert decision.kind == "tool"
    assert decision.tool == "control_app_window"
    assert decision.arguments == {"action": "show_main"}


def test_vague_window_not_confused_with_concrete_target():
    orch = _make_orchestrator()
    # "terminal" and a known folder are concrete targets and now route
    # deterministically (they are real tools), while a bare "a window"
    # still clarifies.
    d = orch._route_desktop_intent("open the terminal")
    assert d is not None
    assert d.kind == "tool"
    assert d.tool == "open_terminal"
    assert d.arguments == {}
    d = orch._route_desktop_intent("open my Downloads folder")
    assert d is not None
    assert d.kind == "tool"
    assert d.tool == "open_folder"
    assert d.arguments == {"path": "downloads"}


def test_deterministic_desktop_routing():
    orch = _make_orchestrator()
    cases = {
        "Open my Downloads folder.": ("open_folder", {"path": "downloads"}),
        "Open the Downloads folder.": ("open_folder", {"path": "downloads"}),
        "Open Downloads": ("open_folder", {"path": "downloads"}),
        "open the project": ("open_folder", {"path": "project"}),
        "Open VS Code.": ("launch_application", {"app": "vs code"}),
        "Open the terminal.": ("open_terminal", {}),
        "launch a terminal": ("open_terminal", {}),
        "open the calculator": ("launch_application", {"app": "calculator"}),
    }
    for phrase, (tool, args) in cases.items():
        d = orch._route_desktop_intent(phrase)
        assert d is not None, phrase
        assert d.kind == "tool", phrase
        assert d.tool == tool, phrase
        assert d.arguments == args, phrase
        assert d.deterministic is True, phrase

    url_cases = {
        "Open this URL: https://example.com": ("open_url", {"url": "https://example.com"}),
        "Open https://example.com": ("open_url", {"url": "https://example.com"}),
        "go to example.com": ("open_url", {"url": "https://example.com"}),
        "visit https://example.com/path?q=1": (
            "open_url",
            {"url": "https://example.com/path?q=1"},
        ),
    }
    for phrase, (tool, args) in url_cases.items():
        d = orch._route_desktop_intent(phrase)
        assert d is not None, phrase
        assert d.kind == "tool", phrase
        assert d.tool == tool, phrase
        assert d.arguments == args, phrase
        assert d.deterministic is True, phrase


def test_desktop_routing_falls_through_for_unknown_targets():
    orch = _make_orchestrator()
    for phrase in [
        "open the mystery thing",
        "open my project files",
        "open the thingamajig",
        "what is the weather",
    ]:
        assert orch._route_desktop_intent(phrase) is None, phrase


def test_deterministic_folder_reply_uses_verified_path():
    orch = _make_orchestrator()
    result = _Result(success=True, data={"opened": "/home/wiz/Downloads"})
    d = orch._deterministic_reply("open_folder", {"path": "my Downloads folder"}, result)
    assert d.kind == "reply"
    assert d.text == "Opened /home/wiz/Downloads."

    result = _Result(success=True, data={"launched": "VS Code", "pid": 123})
    d = orch._deterministic_reply("launch_application", {"app": "vs code"}, result)
    assert d.kind == "reply"
    assert d.text == "VS Code has been launched."

    result = _Result(
        success=True,
        data={"launched": "VS Code", "already_running": True, "focused": False, "pids": [91]},
    )
    d = orch._deterministic_reply("launch_application", {"app": "vs code"}, result)
    assert d.kind == "reply"
    assert d.text == "VS Code is already running."

    result = _Result(
        success=True,
        data={"launched": "VS Code", "already_running": True, "focused": True, "pids": [91]},
    )
    d = orch._deterministic_reply("launch_application", {"app": "vs code"}, result)
    assert d.kind == "reply"
    assert d.text == "VS Code is already running, so I brought it to the front."

    result = _Result(success=True, data={"url": "https://example.com"})
    d = orch._deterministic_reply("open_url", {"url": "https://example.com"}, result)
    assert d.kind == "reply"
    assert d.text == "Opened https://example.com in your browser."


class _OpenFolderTool(BaseTool):
    name = "open_folder"
    description = "Open a folder in the file manager."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    risk_level = "action"

    async def execute(self, arguments, context=None):
        return _Result(data={"opened": "/home/wiz/Downloads"})


def test_deterministic_folder_run_returns_reply_without_model(monkeypatch):
    import pathlib

    from modules import orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod,
        "resolve_known_location",
        lambda name: pathlib.Path("/home/wiz/Downloads"),
    )
    orch = _make_orchestrator(_OpenFolderTool())

    async def _no_model(*args, **kwargs):
        raise AssertionError("deterministic path must not call the model")

    orch._decide = _no_model
    ctx = SessionContext("s1")
    decision = run(orch.run("open my Downloads folder", "s1", ctx, {}))
    assert decision.kind == "reply"
    assert decision.text == "Opened /home/wiz/Downloads."
    assert len(ctx.tool_results) == 1
    assert ctx.tool_results[0]["tool"] == "open_folder"


def test_deterministic_folder_failure_reports_detail(monkeypatch):
    import pathlib

    from modules import orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod,
        "resolve_known_location",
        lambda name: pathlib.Path("/home/wiz/Downloads"),
    )

    class _FailingOpenFolderTool(BaseTool):
        name = "open_folder"
        description = "Open a folder in the file manager."
        parameters = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        risk_level = "action"

        async def execute(self, arguments, context=None):
            return _Result(success=False, error="directory not found")

    orch = _make_orchestrator(_FailingOpenFolderTool())

    async def _no_model(*args, **kwargs):
        raise AssertionError("deterministic path must not call the model")

    orch._decide = _no_model
    decision = run(orch.run("open my Downloads folder", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "directory not found" in decision.text


def test_open_the_files_app_routes_to_validated_launcher():
    orch = _make_orchestrator()
    for phrase in [
        "open the files app",
        "open files",
        "open the file manager",
        "open the file explorer",
        "open files app",
    ]:
        d = orch._route_desktop_intent(phrase)
        assert d is not None, phrase
        assert d.kind == "tool"
        assert d.tool == "launch_application"
        assert d.arguments == {"app": "files"}


def test_vosk_v_code_transcription_routes_to_launcher():
    orch = _make_orchestrator()
    for phrase in ["open v code", "open v code.", "launch v code"]:
        d = orch._route_desktop_intent(phrase)
        assert d is not None, phrase
        assert d.kind == "tool"
        assert d.tool == "launch_application"
        assert d.arguments == {"app": "vs code"}
