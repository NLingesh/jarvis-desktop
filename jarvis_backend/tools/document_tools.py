import logging
import os

from modules.path_policy import (
    is_sensitive_path,
    redact_content,
    resolve_within_roots,
)
from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_READ_CHARS = 64 * 1024


class ReadDocumentTool(BaseTool):
    risk_level = "read_only"
    capability = "documents"
    name = "read_document"
    description = "Read a document file and return its text content (secret files are refused and content redacted)"
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
        max_chars = min(max_chars, MAX_READ_CHARS)
        try:
            resolved = resolve_within_roots(path)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if not resolved.is_file():
            return ToolResult(False, error=f"File not found: {path}")
        if resolved.is_dir():
            return ToolResult(False, error=f"Path is a directory: {path}")
        if is_sensitive_path(resolved):
            return ToolResult(False, error=f"Refusing to read a sensitive file: {path}")
        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)
            content = redact_content(content)
            return ToolResult(
                True,
                data={
                    "path": str(resolved),
                    "content": content,
                    "truncated": len(content) >= max_chars,
                },
            )
        except Exception as exc:
            return ToolResult(False, error=str(exc))