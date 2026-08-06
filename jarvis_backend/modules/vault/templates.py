"""Markdown body templates for the vault note types.

Templates scaffold a new blank note in the UI. The storage layer stores content
verbatim; these templates only provide a convenient starting point for the
human (or the AI) to fill in.
"""

import re

TYPES = (
    "project",
    "daily",
    "conversation",
    "knowledge",
    "person",
    "task",
    "idea",
    "note",
)

_FOLDER_BY_TYPE = {
    "project": "Projects",
    "daily": "Daily Notes",
    "conversation": "Conversations",
    "knowledge": "Knowledge",
    "person": "People",
    "task": "Tasks",
    "idea": "Ideas",
    "note": "Notes",
}

_BODY_BY_TYPE = {
    "project": "## Goal\n\n\n## Notes\n\n\n## Tasks\n\n\n## Timeline\n",
    "daily": "## Focus\n\n\n## Done\n\n\n## Notes\n\n\n## Tomorrow\n",
    "conversation": "## Summary\n\n\n## Decisions\n\n\n## Follow-ups\n\n\n## People\n",
    "knowledge": "## What\n\n\n## Details\n\n\n## Sources\n",
    "person": "## About\n\n\n## Contact\n\n\n## Interactions\n",
    "task": "## What\n\n\n## Context\n\n\n## Checklist\n\n- [ ] \n",
    "idea": "",
    "note": "",
}


def slugify(title: str) -> str:
    """Sanitize a title into a safe, readable filename (spaces preserved)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "untitled"


def default_folder(note_type: str) -> str:
    return _FOLDER_BY_TYPE.get(note_type, "Knowledge")


def body_template(note_type: str) -> str:
    return _BODY_BY_TYPE.get(note_type, "## Notes\n")


def templates() -> dict[str, dict]:
    """Return all type -> (default folder, body template) for the API/UI."""
    return {t: {"folder": default_folder(t), "body": body_template(t)} for t in _FOLDER_BY_TYPE}
