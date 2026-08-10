import logging

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class RememberMemoryTool(BaseTool):
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
            from routes.state import PROFILE_NOTE_PATH, vault
            note = await vault.get_note(PROFILE_NOTE_PATH)
            body = (note or {}).get("body") or ""
            line = f"- [{category}] {fact}"
            if line in body:
                return ToolResult(True, data={"action": "already_remembered", "fact": fact})
            new_body = f"{body}\n{line}" if body.strip() else f"## About\n{line}"
            await vault.update_note(PROFILE_NOTE_PATH, content=new_body)
            return ToolResult(True, data={"action": "remembered", "fact": fact})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class RecallMemoryTool(BaseTool):
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
            from routes.state import PROFILE_NOTE_PATH, vault
            note = await vault.get_note(PROFILE_NOTE_PATH)
            body = (note or {}).get("body") or ""
            lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("##")]
            if query:
                lines = [ln for ln in lines if query in ln.lower()]
            return ToolResult(True, data={"facts": lines[:20], "count": len(lines)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
