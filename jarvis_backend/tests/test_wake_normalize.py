"""Tests for the voice wake-phrase normalization layer.

Covers the phonetic STT variants, false positives, wake phrase alone, wake
phrase + command / question, and that typed input (no wake) is untouched.
"""

import importlib

import pytest

from modules.wake_normalize import normalize_wake_phrase

# (spoken variant, expected normalized command)
WAKE_VARIANTS = [
    "jarvis",
    "jahvis",
    "jervis",
    "jayvis",
    "jay er vis",
    "jar vus",
    "jarv is",
]


@pytest.mark.parametrize("variant", WAKE_VARIANTS)
def test_variant_with_desktop_command(variant):
    result = normalize_wake_phrase(f"{variant} open my Downloads folder")
    assert result.matched is True
    assert result.wake == "JARVIS"
    assert result.wake_only is False
    assert result.command == "open my Downloads folder"


def test_variant_jay_er_vis_with_uppercase_command_preserved():
    result = normalize_wake_phrase("jay er vis open my Downloads folder")
    assert result.matched is True
    assert result.command == "open my Downloads folder"


def test_plain_jarvis_command():
    result = normalize_wake_phrase("jarvis open VS Code")
    assert result.matched is True
    assert result.command == "open VS Code"


def test_hey_prefix_with_comma():
    result = normalize_wake_phrase("Hey JARVIS, open my Downloads folder")
    assert result.matched is True
    assert result.wake == "JARVIS"
    assert result.command == "open my Downloads folder"


def test_hey_prefix_multitoken_variant():
    result = normalize_wake_phrase("hey jay er vis open my Downloads folder")
    assert result.matched is True
    assert result.command == "open my Downloads folder"


def test_wake_plus_general_question():
    result = normalize_wake_phrase("jarvis what time is it?")
    assert result.matched is True
    assert result.command == "what time is it?"


@pytest.mark.parametrize(
    "text",
    ["jarvis", "hey jarvis", "jarvis.", "Hey JARVIS.", "hey jarvis!"],
)
def test_wake_phrase_alone(text):
    result = normalize_wake_phrase(text)
    assert result.matched is True
    assert result.wake == "JARVIS"
    assert result.wake_only is True
    assert result.command == ""


@pytest.mark.parametrize(
    "text",
    [
        "open my Downloads folder",
        "show me the files",
        "please open downloads",
        "can you open VS Code",
        "hey show me the files",
        "what time is it",
        "javvis open downloads",
        "ja rvis open downloads",
        "jar is it ready",
        "jarv ish open downloads",
        "jerviss open downloads",
    ],
)
def test_false_positives_never_match(text):
    result = normalize_wake_phrase(text)
    assert result.matched is False
    assert result.wake is None
    assert result.command == text


def test_command_without_wake_phrase_passes_through():
    result = normalize_wake_phrase("open my Downloads folder")
    assert result.matched is False
    assert result.command == "open my Downloads folder"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("JARVIS, open my Downloads folder", "open my Downloads folder"),
        ("jarvis open the folder /home/wiz/Downloads", "open the folder /home/wiz/Downloads"),
        ("jarvis please open https://example.com now", "please open https://example.com now"),
        ("jarvis open the file ~/.bashrc", "open the file ~/.bashrc"),
        ("jarvis tell me about the code in main.py", "tell me about the code in main.py"),
    ],
)
def test_remainder_preserved_verbatim(text, expected):
    result = normalize_wake_phrase(text)
    assert result.matched is True
    assert result.command == expected


def test_empty_input_not_matched():
    result = normalize_wake_phrase("")
    assert result.matched is False
    assert result.command == ""


def test_whitespace_only_input_not_matched():
    result = normalize_wake_phrase("   ")
    assert result.matched is False


# ---------------------------------------------------------------------------
# Dispatch integration: the final-transcript hook in main.py
# ---------------------------------------------------------------------------


@pytest.fixture
def main_mod(monkeypatch):
    import main as main_module

    importlib.reload(main_module)
    main_module._dispatch_calls = []

    async def fake_handle(user_input, session_id, websocket, voice_uid="", voice_cycle_id=""):
        main_module._dispatch_calls.append(user_input)

    monkeypatch.setattr(main_module, "handle_user_input", fake_handle)
    return main_module


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_dispatch_strips_wake_before_handle_user_input(main_mod):
    ws = _FakeWS()
    await main_mod._dispatch_user_input("jay er vis open my Downloads folder", "s1", ws, "uid")
    assert main_mod._dispatch_calls == ["open my Downloads folder"]
    assert ws.sent == []


@pytest.mark.asyncio
async def test_dispatch_wake_only_acks_without_dispatch(main_mod):
    ws = _FakeWS()
    await main_mod._dispatch_user_input("hey jarvis", "s1", ws, "uid")
    assert main_mod._dispatch_calls == []
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "response"
    assert "need" in ws.sent[0]["text"]


@pytest.mark.asyncio
async def test_dispatch_no_wake_passes_transcript_unchanged(main_mod):
    ws = _FakeWS()
    await main_mod._dispatch_user_input("open my Downloads folder", "s1", ws, "uid")
    assert main_mod._dispatch_calls == ["open my Downloads folder"]
    assert ws.sent == []


@pytest.mark.asyncio
async def test_dispatch_normalizes_variant_to_jarvis_command(main_mod):
    ws = _FakeWS()
    await main_mod._dispatch_user_input("jarvis open VS Code", "s1", ws, "uid")
    assert main_mod._dispatch_calls == ["open VS Code"]
