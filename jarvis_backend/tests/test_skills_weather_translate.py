"""Tests for the weather and translate skills registered in routes.state."""

import asyncio

from routes import state


def run(coro):
    return asyncio.run(coro)


def test_weather_skill_registered():
    assert state.skill_registry.get("weather") is not None


def test_translate_skill_registered():
    assert state.skill_registry.get("translate") is not None


def test_weather_skill_matches_intent():
    assert "weather" in state.skill_registry.detect_intents("what is the weather in Paris")


def test_translate_skill_matches_intent():
    assert "translate" in state.skill_registry.detect_intents("translate hello to french")


def test_weather_skill_executes(monkeypatch):
    async def fake_weather(location):
        return {"location": location, "temperature": 18.0}

    monkeypatch.setattr(state.web_browse, "get_weather", fake_weather)
    result = run(state.skill_registry.execute("weather in Paris"))
    payload = result["weather"]["weather"]
    assert payload["location"] == "Paris"
    assert payload["temperature"] == 18.0


def test_weather_skill_handles_failure(monkeypatch):
    async def fake_weather(location):
        return None

    monkeypatch.setattr(state.web_browse, "get_weather", fake_weather)
    result = run(state.skill_registry.execute("weather in nowhere"))
    assert "error" in result["weather"]["weather"]


def test_translate_skill_executes(monkeypatch):
    async def fake_translate(text, target):
        return "bonjour"

    monkeypatch.setattr(state.web_browse, "translate_text", fake_translate)
    result = run(state.skill_registry.execute("translate 'hello' to fr"))
    payload = result["translate"]["translate"]
    assert payload["text"] == "bonjour"
    assert payload["target_language"] == "fr"


def test_translate_skill_bad_usage():
    result = run(state.skill_registry.execute("translate something"))
    assert "error" in result["translate"]["translate"]


def test_context_includes_weather_and_translate_keys():
    context = asyncio.run(state.process_command("what is the weather in Berlin"))
    assert "weather" in context
    assert "translate" in context
