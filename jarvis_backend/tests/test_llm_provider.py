"""Tests for the LLMProvider module — message building and response parsing."""

import pytest

from modules.llm_provider import JARVIS_SYSTEM_PROMPT, LLMProvider


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-small")


def test_system_prompt_is_defined():
    assert "JARVIS" in JARVIS_SYSTEM_PROMPT
    assert "concis" in JARVIS_SYSTEM_PROMPT.lower()


def test_provider_defaults_to_mistral(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    provider = LLMProvider()
    assert provider.provider == "mistral"


def test_build_messages_includes_system_and_user():
    provider = LLMProvider()
    msgs = provider._build_messages(
        "Hello",
        [],
        None,
        None,
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == JARVIS_SYSTEM_PROMPT
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "Hello"


def test_build_messages_with_memory():
    provider = LLMProvider()
    memory_results = [{"role": "user", "content": "previous greeting"}]
    msgs = provider._build_messages("what did I say?", [], {"calendar": []}, memory_results)
    roles = [m["role"] for m in msgs]
    assert "system" in roles
    assert msgs[-1]["content"] == "what did I say?"
    memory_msg = next(m for m in msgs if "Relevant past" in m["content"])
    assert "previous greeting" in memory_msg["content"]


def test_build_messages_truncates_conversation():
    provider = LLMProvider()
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    msgs = provider._build_messages("hello", long_history, None, None)
    # system + last 20 + user
    assert len(msgs) == 22


@pytest.mark.asyncio
async def test_no_provider_returns_message():
    provider = LLMProvider()
    provider.provider = "unsupported"
    resp = await provider.get_response("hi", [], None, None)
    assert "No provider configured" in resp or "failed" in resp.lower()


@pytest.mark.asyncio
async def test_rerank_without_auth_warns(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_AUTH_HEADER", raising=False)
    provider = LLMProvider()
    result = await provider.rerank("test query", ["passage 1", "passage 2"])
    assert "error" in result or "status_code" in result
