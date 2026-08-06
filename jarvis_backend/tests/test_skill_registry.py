"""Tests for SkillRegistry — intent detection and async/sync handler execution."""

import asyncio

from modules.skill_registry import Skill, SkillRegistry


def test_register_and_get():
    registry = SkillRegistry()
    skill = Skill("greet", ["hello", "hi"], lambda u, s: {"greeting": "hi"})
    registry.register(skill)
    assert registry.get("greet") is skill
    assert registry.get("missing") is None


def test_detect_intents_is_case_insensitive():
    registry = SkillRegistry()
    registry.register(Skill("greet", ["Hello", "Hi"], lambda u, s: {}))
    assert registry.detect_intents("say hi there") == ["greet"]
    assert registry.detect_intents("zebra talks") == []


def test_list_skills_shape():
    registry = SkillRegistry()
    registry.register(Skill("ping", ["ping"], lambda u, s: {}, "Pings back"))
    listing = registry.list_skills()
    assert listing[0]["name"] == "ping"
    assert listing[0]["description"] == "Pings back"
    assert "ping" in listing[0]["intents"]


def test_execute_sync_handler():
    registry = SkillRegistry()
    registry.register(Skill("echo", ["echo"], lambda u, s: {"echoed": u}))
    result = asyncio.run(registry.execute("echo this"))
    assert result == {"echo": {"echoed": "echo this"}}


def test_execute_async_handler():
    registry = SkillRegistry()

    async def handler(user_input, session_id):
        return {"len": len(user_input)}

    registry.register(Skill("length", ["length"], handler))
    result = asyncio.run(registry.execute("length abc"))
    assert result["length"]["len"] == 10


def test_execute_multiple_intents_merges():
    registry = SkillRegistry()
    registry.register(Skill("one", ["one"], lambda u, s: {"a": 1}))
    registry.register(Skill("two", ["two"], lambda u, s: {"b": 2}))
    result = asyncio.run(registry.execute("one and two"))
    assert result == {"one": {"a": 1}, "two": {"b": 2}}


def test_execute_no_match_returns_empty():
    registry = SkillRegistry()
    registry.register(Skill("x", ["only"], lambda u, s: {}))
    assert asyncio.run(registry.execute("nothing matches")) == {}


def test_execute_survives_handler_error():
    registry = SkillRegistry()

    def broken(user_input, session_id):
        raise RuntimeError("boom")

    registry.register(Skill("broken", ["broken"], broken))
    result = asyncio.run(registry.execute("broken"))
    assert result["broken"] == {"error": "boom"}


def test_execute_passes_session_id():
    registry = SkillRegistry()

    def capture(user_input, session_id):
        return {"got_session": session_id}

    registry.register(Skill("cap", ["cap"], capture))
    result = asyncio.run(registry.execute("cap", "session-123"))
    assert result["cap"]["got_session"] == "session-123"
