"""Filesystem path policy — approved roots, symlink protection, secret redaction.

JARVIS can touch the user's filesystem, so every path passed to a filesystem
tool must be canonicalized and confined to approved roots.  This module also
blocks access to known credential/private locations and redacts secret-looking
content from file reads before it can reach the LLM.

Design notes
------------
* All paths are resolved with ``Path.resolve()`` (which resolves symlinks), so
  ``/home/u/link -> /etc/passwd`` cannot escape an approved root.
* Traversal such as ``root/../..`` is neutralized by resolve().
* The realpath check uses ``os.path.commonpath`` to avoid prefix-matching bugs
  like ``/home/user`` vs ``/home/user2``.
* Reads of secret files are refused outright unless the user explicitly
  requests them (handled at the orchestrator layer); the denylist here is the
  last line of defense.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Denylist of path fragments that are almost always credentials or private
# material and should never be read by default.
SENSITIVE_PATH_MARKERS = (
    "/.ssh/",
    "/.gnupg/",
    "/.aws/",
    "/.config/gh/",
    "/.config/gcloud/",
    "/.docker/",
    "/keyrings/",
    "/keyring/",
    "/.mozilla/",
    "/.pki/",
    "/.netrc",
    "/.npmrc",
    "/.env",
    "/.env.local",
    "/.env.production",
    "secret.key",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "*.pem",
    "*.key",
    ".kube/",
    "/AppData/Local/Google/",
)

# Secret-looking content markers used to redact file content.
SECRET_LINE_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|credential|client[_-]?secret"
    r"|private[_-]?key|auth)['\"]?\s*[:=]\s*\S+"
)
SECRET_VALUE_RE = re.compile(
    r"\b(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|nvapi-[A-Za-z0-9]{8,}"
    r"|xox[baprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16})\b"
)


def approved_roots() -> list[Path]:
    """Return the filesystem roots JARVIS is allowed to touch."""
    home = Path.home().resolve()
    roots = [home]
    env_roots = os.getenv("JARVIS_APPROVED_ROOTS", "")
    for entry in env_roots.split(os.pathsep):
        if not entry.strip():
            continue
        try:
            p = Path(entry).expanduser().resolve()
            roots.append(p)
        except Exception:
            continue
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique = []
    for r in roots:
        if str(r) not in seen:
            seen.add(str(r))
            unique.append(r)
    return unique


def is_within_roots(path: Path, roots: list[Path] | None = None) -> bool:
    roots = roots or approved_roots()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    for root in roots:
        try:
            common = os.path.commonpath([str(resolved), str(root)])
        except ValueError:
            continue
        if common == str(root):
            return True
    return False


def resolve_within_roots(raw: str, allow_missing: bool = False) -> Path:
    """Canonicalize ``raw`` and confine it to approved roots.

    Raises ``PermissionError`` if the resolved path escapes the approved roots.
    """
    if not raw or not raw.strip():
        raise PermissionError("Empty path")
    p = Path(raw).expanduser()
    try:
        resolved = p.resolve(strict=False)
    except OSError:
        resolved = p.absolute()
    if not is_within_roots(resolved):
        raise PermissionError(f"Path is outside the approved roots: {raw}")
    return resolved


def is_sensitive_path(path: Path) -> bool:
    """Whether a canonical path points at credentials/private material."""
    text = str(path)
    lower = text.lower()
    for marker in SENSITIVE_PATH_MARKERS:
        if marker.lower() in lower:
            return True
    name = path.name.lower()
    if name in ("id_rsa", "id_ed25519", "id_dsa", ".netrc", ".npmrc"):
        return True
    if name.endswith((".pem", ".key", ".pfx", ".p12")):
        return True
    return False


def redact_content(content: str) -> str:
    """Redact secret-looking values from file content before model processing."""
    if not content:
        return content
    redacted = SECRET_LINE_RE.sub(r"\1 = [redacted]", content)
    redacted = SECRET_VALUE_RE.sub("[redacted]", redacted)
    return redacted