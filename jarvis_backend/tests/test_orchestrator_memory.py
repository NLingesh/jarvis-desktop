"""Memory flows through the orchestrator: explicit saves, inferred-save gate."""

import asyncio

from modules.capability import CapabilityPolicy
from modules.orchestrator import Orchestrator
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


class _Registry:
    def __init__(self, *tools):
        self._tools = {t.name: t for t in tools}
        self.calls: list[tuple[str, dict]] = []

    def get_tool(self, name):
        return self._tools.get(name)

    def list_tools(self):
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    async def execute_tool(self, name, args, context=None):
        self.calls.append((name, args))
        return await self._tools[name].execute(args, context=context)


class _RememberTool(BaseTool):
    name = "remember_memory"
    description = "Persist a fact."
    parameters = {
        "type": "object",
        "properties": {"fact": {"type": "string"}},
        "required": ["fact"],
    }
    risk_level = "reversible"
    saved: list[str] = []

    async def execute(self, arguments, context=None):
        fact = arguments.get("fact", "")
        _RememberTool.saved.append(fact)
        return _Result(data={"action": "remembered", "fact": fact})


class _ForgetTool(BaseTool):
    name = "forget_memory"
    description = "Forget a memory."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    risk_level = "reversible"

    async def execute(self, arguments, context=None):
        return _Result(data={"removed": 1 if "voice" in arguments.get("query", "") else 0})


class _RecallTool(BaseTool):
    name = "recall_memory"
    description = "List memories."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}
    risk_level = "read_only"

    async def execute(self, arguments, context=None):
        query = arguments.get("query") or ""
        if query and "voice" not in query.lower():
            return _Result(data={"facts": [], "count": 0})
        return _Result(data={"facts": ["[preference] I prefer a male voice"], "count": 1})


class _ClearTool(BaseTool):
    name = "clear_all_memories"
    description = "Erase all memories."
    parameters = {"type": "object", "properties": {}}
    risk_level = "destructive"

    async def execute(self, arguments, context=None):
        return _Result(data={"cleared": True})


def _make(*tools):
    return Orchestrator(_FakeLLM(), _Registry(*tools), CapabilityPolicy())


class _FakeLLM:
    provider = "mistral"
    api_key = "test"
    api_url = "http://127.0.0.1:9"
    model = "x"


def _patch(monkeypatch, decision_text):
    async def fake_chat(self, messages):
        return decision_text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)


def _patch_queue(monkeypatch, *responses):
    """LLM fake that replays responses in order, repeating the last one."""
    queue = list(responses)

    async def fake_chat(self, messages):
        return queue[-1] if len(queue) == 1 else queue.pop(0)

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)


# --- explicit user commands save directly -------------------------------------


def test_explicit_remember_saves_without_extra_prompt():
    _RememberTool.saved.clear()
    orch = _make(_RememberTool(), _ForgetTool(), _RecallTool())
    decision = run(orch.run("Remember that I prefer a male voice.", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert decision.text and "Saved" in decision.text
    assert _RememberTool.saved == ["I prefer a male voice"]


def test_explicit_forget_routes_deterministically():
    orch = _make(_RememberTool(), _ForgetTool(), _RecallTool())
    decision = run(
        orch.run("Forget that preference about the male voice.", "s1", SessionContext("s1"), {})
    )
    assert decision.kind == "reply"
    assert decision.text == "Forgotten."


def test_forget_with_no_match_reports_honestly():
    orch = _make(_ForgetTool())
    decision = run(orch.run("Forget the moon landing.", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "nothing saved" in decision.text.lower()


def test_recall_lists_saved_memories():
    registry = _Registry(_RecallTool())
    orch = Orchestrator(_FakeLLM(), registry, CapabilityPolicy())
    decision = run(orch.run("What do you remember?", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "male voice" in decision.text
    # A scoped question passes the filter text through to the tool.
    decision2 = run(
        orch.run("What do you remember about my project?", "s1", SessionContext("s1"), {})
    )
    assert decision2.kind == "reply"
    assert registry.calls[-1] == ("recall_memory", {"query": "my project"})


# --- inferred (model-initiated) saves require approval --------------------------


def test_model_initiated_save_requires_confirmation(monkeypatch):
    _RememberTool.saved.clear()
    _patch(monkeypatch, '{"tool": "remember_memory", "arguments": {"fact": "likes short replies"}}')
    orch = _make(_RememberTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("I guess I like short replies.", "s1", ctx, {}))
    assert decision.kind == "confirm"
    assert decision.tool == "remember_memory"
    assert ctx.pending_tool == "remember_memory"
    assert "Save it to memory?" in (decision.reason or "")
    # Nothing persisted before approval.
    assert _RememberTool.saved == []


def test_clear_all_requires_confirmation():
    orch = _make(_ClearTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Clear your memory.", "s1", ctx, {}))
    assert decision.kind == "confirm"
    assert decision.tool == "clear_all_memories"
    assert ctx.pending_tool == "clear_all_memories"


# --- aliases -------------------------------------------------------------------


def test_model_alias_remember_fact_resolves(monkeypatch):
    _patch(monkeypatch, '{"tool": "remember_fact", "arguments": {"fact": "x"}}')
    orch = _make(_RememberTool())
    decision = run(orch.run("whatever", "s1", SessionContext("s1"), {}))
    # Alias resolves to remember_memory -> still gated behind confirmation.
    assert decision.kind == "confirm"
    assert decision.tool == "remember_memory"


def test_model_alias_list_memories_executes_read_only(monkeypatch):
    _patch_queue(
        monkeypatch,
        '{"tool": "list_memories", "arguments": {}}',
        '{"reply": "You prefer a male voice."}',
    )
    orch = _make(_RecallTool())
    decision = run(orch.run("what do you know", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "male voice" in decision.text


# --- clarification tracking ------------------------------------------------------


def test_clarification_sets_and_clears_pending_context(monkeypatch):
    _patch(monkeypatch, '{"clarify": "Which folder did you mean?"}')
    orch = _make()
    ctx = SessionContext("s1")
    decision = run(orch.run("open that thing", "s1", ctx, {}))
    assert decision.clarify is True
    assert ctx.pending_clarification == "Which folder did you mean?"

    _patch(monkeypatch, '{"reply": "Opened."}')
    decision2 = run(orch.run("the downloads folder", "s1", ctx, {}))
    assert decision2.clarify is False
    assert ctx.pending_clarification is None
