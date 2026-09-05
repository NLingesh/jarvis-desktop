"""Central personality configuration for JARVIS.

Every user-facing canned phrase is defined here instead of being scattered
through the orchestrator, so the assistant keeps one consistent voice:

* calm, intelligent, precise, concise, respectful;
* natural professional wording, slightly witty only when appropriate;
* no exaggerated movie dialogue and no repetitive confirmations;
* no robotic "command executed successfully" status phrasing;
* concise by default, detailed only when asked;
* success is never claimed without a verified tool result.
"""

from __future__ import annotations

import re

# Phrases JARVIS must never emit.  Used by ``is_in_style`` so tests (and any
# future reply-sanitizing pass) can assert the voice stays clean.
FORBIDDEN_PHRASES = (
    "command executed successfully",
    "operation completed successfully",
    "task completed successfully",
    "as you wish",
    "at your service, sir",
    "i am jarvis",  # self-introduction theatrics
    "sir, yes sir",
)

_STYLE_NOTE = (
    "Voice: calm, precise, concise, respectful. Plain professional wording, "
    "slightly witty when it fits. Never use movie catchphrases, theatrics, or "
    'robotic status language like "command executed successfully". Confirm an '
    'action with a short natural sentence ("Opened the folder.", "Done.") or '
    'report the honest failure ("I couldn\'t find that file."). Never repeat '
    "the same confirmation twice in a row."
)

# Appended to the orchestrator system prompt so model-generated replies follow
# the same voice as the canned responses below.
PERSONALITY_PROMPT = _STYLE_NOTE


def done() -> str:
    """Short verified-completion acknowledgement."""
    return "Done."


def failure(detail: str) -> str:
    """Honest, specific failure line. Never blames the user."""
    detail = (detail or "").strip().rstrip(".")
    if not detail:
        return "I couldn't complete that."
    return f"I couldn't complete that — {detail}."


def unknown_tool() -> str:
    return "I don't have a way to do that yet."


def clarify(question: str | None = None) -> str:
    q = (question or "").strip()
    return q if q else "Could you clarify that?"


def saved(what: str = "") -> str:
    what = (what or "").strip()
    return f"Saved: {what}." if what else "Saved to memory."


def already_saved() -> str:
    return "That's already in memory."


def forgotten(count: int = 1) -> str:
    if count <= 0:
        return "I couldn't find that in memory."
    return "Forgotten." if count == 1 else f"Forgot {count} items."


def nothing_found(query: str = "") -> str:
    query = (query or "").strip()
    if query:
        return f"I have nothing saved about {query}."
    return "Memory is empty."


def confirm_save(fact: str) -> str:
    """Ask before persisting information JARVIS inferred on its own."""
    fact = (fact or "").strip().rstrip(".")
    preview = fact if len(fact) <= 120 else fact[:117] + "..."
    return f'I picked up a possible preference: "{preview}". Save it to memory?'


def confirm_action() -> str:
    return "I need your confirmation before I run that."


def confirm_clear_all() -> str:
    return "This clears everything I've remembered. Are you sure?"


def cancelled() -> str:
    return "Cancelled."


_REPETITION_RE = re.compile(r"(\b\w+(?:\s+\w+){0,6}\b)(?:[.,]?\s+\1){2,}", re.IGNORECASE)


def is_in_style(text: str) -> bool:
    """Whether a candidate reply obeys the hard voice rules.

    Checks the mechanical rules only (banned phrases, stuttering repetition);
    tone quality itself is enforced by the prompt and review.
    """
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in FORBIDDEN_PHRASES):
        return False
    return not _REPETITION_RE.search(lowered or "")
