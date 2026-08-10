import logging
import os
import platform
from pathlib import Path

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class FileSearchTool(BaseTool):
    name = "file_search"
    description = "Search for files by name under a directory"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Filename or pattern"},
            "directory": {"type": "string", "description": "Directory to search", "default": str(Path.home())},
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = arguments.get("query", "")
        directory = arguments.get("directory", str(Path.home()))
        if not query:
            return ToolResult(False, error="Missing query")
        try:
            matches = []
            for root, _dirs, files in os.walk(directory):
                for f in files:
                    if query.lower() in f.lower():
                        matches.append(os.path.join(root, f))
                if len(matches) >= 20:
                    break
            return ToolResult(True, data={"matches": matches[:20], "count": len(matches)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class OpenFileTool(BaseTool):
    name = "open_file"
    description = "Open a file with the default application"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        if not os.path.exists(path):
            return ToolResult(False, error=f"File not found: {path}")
        try:
            if platform.system() == "Linux":
                os.system(f'xdg-open "{path}" &')
            elif platform.system() == "Darwin":
                os.system(f'open "{path}"')
            else:
                os.startfile(path)
            return ToolResult(True, data={"opened": path})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class OpenFolderTool(BaseTool):
    name = "open_folder"
    description = "Open a folder in the file manager"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute folder path"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        if not os.path.isdir(path):
            return ToolResult(False, error=f"Directory not found: {path}")
        try:
            if platform.system() == "Linux":
                os.system(f'xdg-open "{path}" &')
            elif platform.system() == "Darwin":
                os.system(f'open "{path}"')
            return ToolResult(True, data={"opened": path})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List files and folders in a directory"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute directory path"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        if not os.path.isdir(path):
            return ToolResult(False, error=f"Not a directory: {path}")
        try:
            entries = []
            for entry in sorted(os.listdir(path))[:50]:
                full = os.path.join(path, entry)
                entries.append({"name": entry, "type": "directory" if os.path.isdir(full) else "file"})
            return ToolResult(True, data={"entries": entries, "count": len(entries)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a text file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path"},
            "max_bytes": {"type": "integer", "description": "Max bytes to read", "default": 20000},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        max_bytes = int(arguments.get("max_bytes", 20000))
        if not os.path.exists(path):
            return ToolResult(False, error=f"File not found: {path}")
        if os.path.isdir(path):
            return ToolResult(False, error=f"Path is a directory: {path}")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            return ToolResult(True, data={"path": path, "content": content, "truncated": len(content) >= max_bytes})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
