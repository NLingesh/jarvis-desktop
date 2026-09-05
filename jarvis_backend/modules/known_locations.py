"""Resolution of fuzzy location references to canonical absolute paths.

The model often hears things like "open my downloads folder" or "open the
JARVIS project" without an absolute path.  This module maps those friendly
names to canonical, symlink-resolved absolute paths.  It only performs
``expanduser``/``resolve`` and never touches the filesystem beyond existence
checks, so it is safe to call from any tool.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root for this project (jarvis_backend/modules/known_locations.py -> root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_KNOWN_DIR_FACTORIES = {
    "home": lambda: Path.home(),
    "downloads": lambda: Path.home() / "Downloads",
    "desktop": lambda: Path.home() / "Desktop",
    "documents": lambda: Path.home() / "Documents",
    "music": lambda: Path.home() / "Music",
    "pictures": lambda: Path.home() / "Pictures",
    "videos": lambda: Path.home() / "Videos",
}

PROJECT_ALIASES = {
    "project",
    "this project",
    "current project",
    "the project",
    "this repo",
    "the repo",
    "jarvis",
    "jarvis project",
    "the jarvis project",
    "maybe jarvis",
    "maybe jarvis project",
}

_NOISE_TOKENS = (
    "the ",
    "my ",
    "your ",
    "our ",
    "please ",
    "open ",
    "show ",
    "folder",
    "directory",
    "location",
)


def resolve_known_location(name: str) -> Path | None:
    """Return the canonical Path for a known/fuzzy location name, or None."""
    normalized = _normalize(name)
    if not normalized:
        return None

    if normalized in PROJECT_ALIASES:
        root = os.getenv("JARVIS_PROJECT_ROOT") or str(PROJECT_ROOT)
        try:
            candidate = Path(root).expanduser().resolve()
        except OSError:
            return None
        return candidate if candidate.exists() else None

    for key, factory in _KNOWN_DIR_FACTORIES.items():
        if normalized == key:
            return _existing(factory)
        if normalized in (f"{key} folder", f"{key} directory"):
            return _existing(factory)

    # Fuzzy fallback: "downloads" inside a longer phrase or vice versa.
    for key, factory in _KNOWN_DIR_FACTORIES.items():
        if key in normalized or normalized in key:
            return _existing(factory)

    return None


def _existing(factory) -> Path | None:
    candidate = factory()
    if candidate is None:
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    return resolved if resolved.exists() else None


def _normalize(name: str) -> str:
    text = (name or "").strip().lower()
    if not text:
        return ""
    for token in _NOISE_TOKENS:
        text = text.replace(token, "")
    text = " ".join(text.split())
    return text
