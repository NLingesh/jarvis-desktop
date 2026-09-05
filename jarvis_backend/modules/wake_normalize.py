"""Wake-phrase normalization for spoken utterances.

The STT engine sometimes transcribes the spoken wake name "JARVIS" as phonetic
variants ("jahvis", "jay er vis", "jar vus", ...).  This module strips a
leading wake phrase from a *final* transcript so the remainder -- the actual
command -- is dispatched verbatim.  It is deliberately narrow:

* only the leading position of an utterance is considered;
* only a conservative set of spoken variants is recognized, with the rest of
  the text preserved exactly (case, paths, URLs, app names untouched);
* typed input never passes through here -- this only runs on finalized spoken
  transcripts right before dispatch, never on partial STT hypotheses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Spoken variants of "JARVIS" the STT engine has been observed to produce.
# Longest forms first so a split pronunciation wins over a partial match.
_WAKE_ALTERNATIONS: tuple[str, ...] = (
    "jay er vi us",
    "jay of us",
    "jay er vis",
    "jar vus",
    "jarv is",
    "jayvis",
    "jahvis",
    "jervis",
    "jarvis",
)

# Short attention words that may immediately precede the name ("Hey JARVIS").
_WAKE_PREFIXES: tuple[str, ...] = ("hey", "hi")

_WAKE_PATTERN = re.compile(
    rf"^(?:(?:{'|'.join(_WAKE_PREFIXES)})\s+)?"
    rf"(?P<variant>\b(?:{'|'.join(_WAKE_ALTERNATIONS)})\b)"
    r"(?:\s*[,;:.!?]+)?"
    r"(?P<command>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WakeNormalization:
    """Result of normalizing one final spoken transcript."""

    matched: bool
    wake: str | None = None
    variant: str | None = None
    command: str = ""
    wake_only: bool = False


def normalize_wake_phrase(text: str) -> WakeNormalization:
    """Recognize a leading phonetic wake phrase and return the bare command.

    When ``matched`` is true, ``command`` is the remainder of the utterance
    with the wake phrase removed and the rest preserved verbatim.  A
    ``wake_only`` result means the utterance was just the wake phrase and has
    no command to dispatch.
    """
    if not text or not text.strip():
        return WakeNormalization(matched=False, command=text.strip())
    match = _WAKE_PATTERN.match(text)
    if match is None:
        return WakeNormalization(matched=False, command=text.strip())
    command = (match.group("command") or "").strip()
    return WakeNormalization(
        matched=True,
        wake="JARVIS",
        variant=(match.group("variant") or "").lower(),
        command=command,
        wake_only=not command,
    )
