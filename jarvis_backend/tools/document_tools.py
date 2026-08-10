import logging
import os

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ReadDocumentTool(BaseTool):
    name = "read_document"
    description = "Read a document file and return its text content"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path"},
            "max_chars": {"type": "integer", "description": "Max characters to read", "default": 20000},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        max_chars = int(arguments.get("max_chars", 20000))
        if not os.path.exists(path):
            return ToolResult(False, error=f"File not found: {path}")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)
            return ToolResult(True, data={"path": path, "content": content, "truncated": len(content) >= max_chars})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
