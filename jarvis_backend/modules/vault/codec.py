"""Markdown frontmatter codec — parse/serialize, tag and link extraction.

The frontmatter is the canonical metadata store. Every note in the vault is a
plain Markdown file whose YAML frontmatter carries ``type``, ``title``, ``id``,
timestamps and tags. This module is Obsidian-compatible: it produces the exact
``---``-delimited block Obsidian understands and reads it back.
"""

import os
import re
import uuid
from datetime import UTC, datetime

import yaml

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_INLINE_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_/-]+)")
_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]|]*)?\]\]")


def now_iso() -> str:
    """UTC timestamp with microsecond precision (stable ordering)."""
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def parse(content: str) -> tuple[dict, str]:
    """Return ``(frontmatter dict, body)`` from raw Markdown.

    Malformed or missing frontmatter degrades gracefully to ``({}, content)``.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content.strip()
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, content.strip()
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    body = content[match.end() :].strip()
    return frontmatter, body


def serialize(frontmatter: dict, body: str) -> str:
    """Render ``(frontmatter, body)`` back into a Markdown file."""
    if not frontmatter:
        return body.strip()
    header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{header}\n---\n\n{body.strip()}\n"


def title_from_filename(rel_path: str) -> str:
    """Derive a title from a relative path like ``Knowledge/FastAPI.md``."""
    base = os.path.basename(rel_path)
    if base.lower().endswith(".md"):
        base = base[:-3]
    return base


def extract_tags(content: str) -> list[str]:
    """Merge frontmatter ``tags`` with inline ``#tags``; dedup, lowercase."""
    frontmatter, body = parse(content)
    tags = frontmatter.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t).lower() for t in tags if t]
    tags.extend(m.group(1).lower() for m in _INLINE_TAG_RE.finditer(body))
    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def extract_links(content: str) -> list[str]:
    """Return the resolved titles of all ``[[...]]`` wikilinks in a note."""
    return [m.group(1).strip() for m in _LINK_RE.finditer(content)]
