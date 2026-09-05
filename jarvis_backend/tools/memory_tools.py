import logging
import re

from modules.memory_safety import is_sensitive_memory
from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Retention bounds for explicit long-term memory.
MAX_MEMORIES = 200  # hard ceiling on stored items (oldest dropped)
MAX_FACT_CHARS = 500  # per-item length cap
ALLOWED_CATEGORIES = {"preference", "project", "person", "general"}

_FACT_LINE_RE = re.compile(r"^-\s*\[([a-z]+)\]\s*(.+)$")


def _sanitize_category(category: str) -> str:
    cat = (category or "").strip().lower()
    return cat if cat in ALLOWED_CATEGORIES else "general"


def _clean_fact(fact: str) -> str:
    """Normalize a fact and strip control/bracket injection characters."""
    fact = re.sub(r"[\[\]\r\n\t]", " ", (fact or ""))
    fact = re.sub(r"\s+", " ", fact).strip()
    return fact[:MAX_FACT_CHARS]


def _fact_lines(body: str) -> list[tuple[int, str, str]]:
    """Parse ``- [category] fact`` lines -> [(line_index, category, fact)].

    Any other line in the note is left completely untouched by every write
    operation -- the profile note may hold free-form content beyond memory.
    """
    facts = []
    for idx, line in enumerate((body or "").splitlines()):
        match = _FACT_LINE_RE.match(line.strip())
        if match:
            facts.append((idx, match.group(1), match.group(2).strip()))
    return facts


def _apply_line_edits(body: str, edits: dict[int, str | None]) -> str:
    """Replace/remove specific fact lines; None removes the line."""
    lines = (body or "").splitlines()
    out = []
    for i, line in enumerate(lines):
        if i in edits:
            new = edits[i]
            if new is not None:
                out.append(new)
        else:
            out.append(line)
    return "\n".join(out)


class RememberMemoryTool(BaseTool):
    risk_level = "reversible"
    capability = "memory"
    name = "remember_memory"
    description = (
        "Persist an explicit user-approved fact or preference to long-term "
        "memory. Inferred information requires user confirmation first."
    )
    parameters = {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "Fact or preference to remember"},
            "category": {
                "type": "string",
                "description": "One of: preference, project, person, general",
                "default": "preference",
            },
        },
        "required": ["fact"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        raw = arguments.get("fact") or arguments.get("information") or ""
        fact = _clean_fact(raw)
        category = _sanitize_category(arguments.get("category", "preference"))
        if not fact:
            return ToolResult(False, error="Missing fact")
        if is_sensitive_memory(fact):
            logger.info("memory: refused sensitive write (%d chars)", len(fact))
            return ToolResult(
                False,
                error="I won't store passwords, API keys, tokens, or credentials in memory.",
            )
        try:
            from routes.state import ensure_profile_note, resolve_profile_note_path, vault

            note = await ensure_profile_note()
            if not note:
                return ToolResult(False, error="Could not access the profile note")
            path = resolve_profile_note_path()
            body = (note or {}).get("body") or ""
            lowered_fact = fact.lower()
            for _, cat, text in _fact_lines(body):
                if cat == category and text.lower() == lowered_fact:
                    return ToolResult(True, data={"action": "already_remembered", "fact": fact})
            new_line = (
                f"- [{category}] {fact}" if body.strip() else f"## About\n- [{category}] {fact}"
            )
            body = f"{body}\n{new_line}" if body.strip() else new_line
            # Retention: cap stored items; drop only the OLDEST fact lines and
            # never touch unrelated note content.
            facts = _fact_lines(body)
            excess = len(facts) - MAX_MEMORIES
            if excess > 0:
                oldest = {idx: None for idx, _, _ in facts[:excess]}
                body = _apply_line_edits(body, oldest)
                facts = _fact_lines(body)
            await vault.update_note(path, content=body)
            return ToolResult(
                True,
                data={
                    "action": "remembered",
                    "fact": fact,
                    "category": category,
                    "total": len(facts),
                },
            )
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class UpdateMemoryTool(BaseTool):
    risk_level = "reversible"
    capability = "memory"
    name = "update_memory"
    description = "Replace an existing memory item with corrected wording"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text matching the item to update"},
            "new_fact": {"type": "string", "description": "Replacement wording"},
        },
        "required": ["query", "new_fact"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = (arguments.get("query") or "").strip().lower()
        new_fact = _clean_fact(arguments.get("new_fact") or "")
        if not query or not new_fact:
            return ToolResult(False, error="Missing query or new_fact")
        if is_sensitive_memory(new_fact):
            return ToolResult(
                False,
                error="I won't store passwords, API keys, tokens, or credentials in memory.",
            )
        try:
            from routes.state import get_profile_note, resolve_profile_note_path, vault

            note = await get_profile_note()
            if not note:
                return ToolResult(True, data={"updated": 0})
            path = resolve_profile_note_path()
            body = (note or {}).get("body") or ""
            edits: dict[int, str] = {}
            for idx, cat, text in _fact_lines(body):
                if query in text.lower():
                    edits[idx] = f"- [{cat}] {new_fact}"
            if not edits:
                return ToolResult(True, data={"updated": 0})
            updated = len(edits)
            await vault.update_note(path, content=_apply_line_edits(body, edits))
            return ToolResult(True, data={"updated": updated, "new_fact": new_fact})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class RecallMemoryTool(BaseTool):
    risk_level = "read_only"
    capability = "memory"
    name = "recall_memory"
    description = "List and search stored user preferences and facts"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional search query", "default": ""},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = (arguments.get("query") or "").strip().lower()
        try:
            from routes.state import get_profile_note

            note = await get_profile_note()
            body = (note or {}).get("body") or ""
            facts = [(cat, text) for _, cat, text in _fact_lines(body)]
            if query:
                facts = [(c, f) for c, f in facts if query in f.lower() or query in c]
            rendered = [f"[{cat}] {text}" for cat, text in facts[:20]]
            return ToolResult(
                True,
                data={"facts": rendered, "count": len(facts), "query": query or None},
            )
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ForgetMemoryTool(BaseTool):
    risk_level = "reversible"
    capability = "memory"
    name = "forget_memory"
    description = "Forget a stored memory item by matching text"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to match the memory item to forget"},
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = (arguments.get("query") or "").strip().lower()
        if not query:
            return ToolResult(False, error="Missing query")
        try:
            from routes.state import get_profile_note, resolve_profile_note_path, vault

            note = await get_profile_note()
            if not note:
                return ToolResult(True, data={"removed": 0})
            path = resolve_profile_note_path()
            body = (note or {}).get("body") or ""
            removals = 0
            edits: dict[int, str | None] = {}
            for idx, _, text in _fact_lines(body):
                if query in text.lower():
                    edits[idx] = None
                    removals += 1
            if not edits:
                return ToolResult(True, data={"removed": 0})
            await vault.update_note(path, content=_apply_line_edits(body, edits))
            return ToolResult(True, data={"removed": removals})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ClearAllMemoriesTool(BaseTool):
    """Reset long-term memory to its empty scaffold.

    Destructive to stored preferences, so it sits behind the standard
    single-use approval flow (ALWAYS_CONFIRM).
    """

    risk_level = "destructive"
    capability = "memory"
    name = "clear_all_memories"
    description = "Erase every stored memory item after explicit user approval"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        try:
            from routes.state import reset_profile_note

            ok = await reset_profile_note()
            if not ok:
                return ToolResult(False, error="Could not clear memory")
            return ToolResult(True, data={"cleared": True})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class GetCurrentContextTool(BaseTool):
    """Report the current short-term session context (bounded, verified-only).

    Returns what JARVIS actually knows about the ongoing conversation: the
    active project/task, recently resolved paths, the last launched app, and
    pending clarification.  Nothing here comes from unverified model claims.
    """

    risk_level = "read_only"
    capability = "system"
    name = "get_current_context"
    description = (
        "Summarize the current conversation context: active project, recent "
        "paths, last launched application, pending clarifications"
    )
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        session_id = (context or {}).get("session_id") or ""
        try:
            from routes.state import session_context_store

            summary: dict = {}
            if session_id:
                ctx = session_context_store.get(session_id)
                summary = ctx.context_summary()
            return ToolResult(True, data=summary)
        except Exception as exc:
            return ToolResult(False, error=str(exc))
