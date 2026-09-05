"""Guards for explicit long-term memory writes.

``is_sensitive_memory`` runs BEFORE anything is persisted.  It rejects
passwords, API keys, tokens, credentials, private keys, and other secret-shaped
strings so they can never reach the local memory store.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    # Named credential fields ("my password is ...", "api_key=...").
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|bearer|password|passwd|"
        r"passphrase|secret|credential|private[_ -]?key)s?\b\s*(?:is|:|=)\s*\S",
        re.I,
    ),
    # Bare mentions of credential kinds (no value required to refuse).
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|"
        r"passphrase|credential|private[_ -]?key)s?\b",
        re.I,
    ),
    # Provider token shapes.
    re.compile(r"\b(?:sk|nvapi|ghp|gho|github_pat|xox[baprs]|gsk_|sk-ant)[-_.][A-Za-z0-9._-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
    # PEM key material.
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
    # Long hex secrets (md5/sha sized opaque strings).
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    # Long random base64-ish blobs (>=24 chars, mixed case+digits) after "token/key/secret".
    re.compile(
        r"\b(?:token|secret|key)\b[:=\s]*[A-Za-z0-9+/_-]{24,}",
        re.I,
    ),
)

# Words that are fine on their own but signal a credential when paired with a
# storage verb ("save/store/remember my password").
_STORAGE_VERB_RE = re.compile(r"\b(?:remember|save|store|keep|note)\b", re.I)
_CREDENTIAL_NOUN_RE = re.compile(
    r"\b(?:password|passwd|passphrase|api[_ -]?key|access[_ -]?token|credential|"
    r"private[_ -]?key|secret[_ -]?key)\b",
    re.I,
)


def is_sensitive_memory(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return True
    return bool(_STORAGE_VERB_RE.search(text) and _CREDENTIAL_NOUN_RE.search(text))
