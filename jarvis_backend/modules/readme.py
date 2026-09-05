"""README discovery for the orchestrator's file-open flow.

The weak model stops after resolving the project instead of continuing to
``open_file``.  This module gives the orchestrator a deterministic way to
search a project root for README variants so the next step can be steered
(exactly one candidate -> open it, several -> clarify, none -> truthful
not-found).

The search is deliberately shallow and confined: it only looks in the project
root and the immediate ``docs``/``doc`` subdirectories, never recursing.  All
returned paths are canonicalized with ``resolve()`` and are therefore safe to
hand to ``open_file`` (which re-validates against approved roots).
"""

from __future__ import annotations

from pathlib import Path

# README variants per the documented contract: README.md, README, README.txt,
# and any case variants of those three.
_README_BASENAMES = {"readme", "readme.md", "readme.txt"}

# Reasonable immediate documentation locations searched alongside the root.
_DOC_DIRS = ("docs", "doc")


def find_readme(project_root: str | Path) -> list[Path]:
    """Return canonical paths of README candidates under ``project_root``.

    Candidates are looked up in the project root and its immediate
    ``docs``/``doc`` subdirectories only.  The result is sorted by path for a
    deterministic order; duplicates (e.g. a symlinked path) are removed.
    """
    root = Path(project_root)
    if not root.is_dir():
        return []

    dirs = [root] + [root / d for d in _DOC_DIRS if (root / d).is_dir()]
    found: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            try:
                if not entry.is_file() or entry.name.lower() not in _README_BASENAMES:
                    continue
                canonical = entry.resolve()
            except OSError:
                continue
            key = str(canonical)
            if key not in seen:
                seen.add(key)
                found.append(canonical)
    return found
