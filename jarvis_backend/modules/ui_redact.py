"""Secret redaction for captured UI content.

Anything read from a window (accessibility text, values, OCR output) passes
through :func:`redact_text` before it is stored in memory, shown to the model,
or included in a tool result.  Password fields are never read at all; this
layer catches secrets that appear inside ordinary visible content.
"""

from __future__ import annotations

import re

from modules.memory_safety import _SECRET_PATTERNS

_REDACTED = "[redacted]"

# Field-name heuristics: "Password: hunter2" / "api_key=sk-..." style pairs.
_FIELD_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|api[\s_-]?key|access[\s_-]?token|secret|"
    r"credential|authorization|private[\s_-]?key)\b(\s*[:=]\s*)(\S+)"
)

_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)(token|secret|password|passwd|api[_-]?key)\s*([=:]\s*|\s+)([A-Za-z0-9+/_\-.]{12,})"
)


def _redact_match(match: re.Match) -> str:
    return f"{match.group(1)}{match.group(2)}{_REDACTED}"


def redact_text(text: str) -> str:
    """Redact secret-shaped content from captured UI text. Bounded input."""
    if not text:
        return ""
    out = str(text)[:5000]
    for pattern in _SECRET_PATTERNS:
        # Named-credential patterns keep the label but drop any value.
        lowered_groups = pattern.groups
        if lowered_groups:

            def _sub(m: re.Match) -> str:
                return "".join(m.group(i) or "" for i in range(1, lowered_groups + 1)) + _REDACTED

            out = pattern.sub(_sub, out)
        else:
            out = pattern.sub(_REDACTED, out)
    out = _FIELD_SECRET_RE.sub(_redact_match, out)
    out = _ASSIGNMENT_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", out)
    return out


def is_secret_field(name: str | None) -> bool:
    """Whether an element name/label looks like a credential field."""
    lowered = (name or "").lower()
    return any(
        word in lowered
        for word in ("password", "passwd", "passphrase", "api key", "apikey", "token", "secret", "credential")
    )
