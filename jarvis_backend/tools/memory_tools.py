import logging

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class RememberMemoryTool(BaseTool):
    risk_level = "reversible"
    capability = "memory"
    name = "remember_memory"
    description = "Persist a user-provided fact or preference to long-term memory"
    parameters = {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "Fact or preference to remember"},
            "category": {"type": "string", "description": "Optional category", "default": "preference"},
        },
        "required": ["fact"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        fact = arguments.get("fact", "").strip()
        category = arguments.get("category", "preference")
        if not fact:
            return ToolResult(False, error="Missing fact")
        try:
            from routes.state import ensure_profile_note, resolve_profile_note_path, vault
            note = await ensure_profile_note()
            if not note:
                return ToolResult(False, error="Could not access the profile note")
            body = (note or {}).get("body") or ""
            line = f"- [{category}] {fact}"
            if line in body:
                return ToolResult(True, data={"action": "already_remembered", "fact": fact})
            new_body = f"{body}\n{line}" if body.strip() else f"## About\n{line}"
            await vault.update_note(resolve_profile_note_path(), content=new_body)
            return ToolResult(True, data={"action": "remembered", "fact": fact})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class RecallMemoryTool(BaseTool):
    risk_level = "read_only"
    capability = "memory"
    name = "recall_memory"
    description = "Recall stored user preferences and facts"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional search query", "default": ""},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = (arguments.get("query") or "").strip().lower()
        try:
            from routes.state import resolve_profile_note_path, vault
            note = await vault.get_note(resolve_profile_note_path())
            body = (note or {}).get("body") or ""
            lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("##")]
            if query:
                lines = [ln for ln in lines if query in ln.lower()]
            return ToolResult(True, data={"facts": lines[:20], "count": len(lines)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ForgetMemoryTool(BaseTool):
    risk_level = "reversible"
    capability = "memory"
    name = "forget_memory"
    description = "Forget a stored memory item"
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
            from routes.state import resolve_profile_note_path, vault
            note = await vault.get_note(resolve_profile_note_path())
            body = (note or {}).get("body") or ""
            lines = body.splitlines()
            kept = []
            removed = 0
            for ln in lines:
                if query in ln.lower():
                    removed += 1
                    continue
                kept.append(ln)
            new_body = "\n".join(kept).strip()
            await vault.update_note(resolve_profile_note_path(), content=new_body)
            return ToolResult(True, data={"removed": removed})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
