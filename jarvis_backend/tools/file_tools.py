import logging
import os
from pathlib import Path

from modules.desktop_open import desktop_open, failure_diagnostics
from modules.known_locations import resolve_known_location
from modules.path_policy import (
    is_sensitive_path,
    redact_content,
    resolve_within_roots,
)
from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _safe_canonical(raw: str) -> Path:
    """Canonicalize a path for reporting even when it does not exist."""
    try:
        return Path(raw or "").expanduser().resolve()
    except OSError:
        return Path(raw or "").absolute()


def _resolve_target(raw: str, expect: str) -> Path:
    """Resolve a path argument, falling back to known-location names.

    ``expect`` is ``"file"`` or ``"folder"``.  Raises ``PermissionError`` when
    the resolved path escapes the approved roots and ``FileNotFoundError`` when
    the target does not exist.
    """
    raw = (raw or "").strip()
    if not raw:
        raise FileNotFoundError("Empty path")
    known = None
    if not raw.startswith("/") and not raw.startswith("~"):
        known = resolve_known_location(raw)
    try:
        resolved = resolve_within_roots(known and str(known) or raw)
    except PermissionError:
        # The model may invent a plausible-looking absolute path (e.g.
        # "/home/user/Downloads"). Before refusing, try resolving the basename
        # against known locations so "Downloads" still opens the real folder.
        base = Path(raw).name
        if base and base != raw:
            known2 = resolve_known_location(base)
            if known2 is not None:
                resolved = known2
            else:
                raise
        else:
            raise
    exists = resolved.is_file() if expect == "file" else resolved.is_dir()
    if not exists:
        label = "File" if expect == "file" else "Directory"
        raise FileNotFoundError(f"{label} not found: {raw}")
    return resolved


class FileSearchTool(BaseTool):
    name = "file_search"
    risk_level = "read_only"
    capability = "filesystem"
    description = "Search for files by name under a directory"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Filename or pattern"},
            "directory": {
                "type": "string",
                "description": "Directory to search",
                "default": str(Path.home()),
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = arguments.get("query", "")
        directory = arguments.get("directory", str(Path.home()))
        if not query:
            return ToolResult(False, error="Missing query")
        try:
            root = resolve_within_roots(directory)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        try:
            matches = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for f in filenames:
                    if query.lower() in f.lower():
                        full = os.path.join(dirpath, f)
                        if is_sensitive_path(Path(full)):
                            continue
                        matches.append(full)
                if len(matches) >= 20:
                    break
            return ToolResult(True, data={"matches": matches[:20], "count": len(matches)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class OpenFileTool(BaseTool):
    name = "open_file"
    risk_level = "reversible"
    capability = "filesystem"
    description = "Open a file with the default application"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute file path or a friendly name like 'Downloads'",
            },
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path") or arguments.get("name") or ""
        try:
            resolved = _resolve_target(path, expect="file")
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        except FileNotFoundError as exc:
            return ToolResult(
                False,
                error=str(exc),
                data={
                    "target_type": "file",
                    "canonical_path": str(_safe_canonical(path)),
                    "exists": False,
                    "complete": True,
                },
            )
        if is_sensitive_path(resolved):
            return ToolResult(
                False,
                error=f"Refusing to open a sensitive file: {path}",
                data={
                    "target_type": "file",
                    "canonical_path": str(resolved),
                    "exists": True,
                    "complete": True,
                },
            )
        try:
            desktop_open(str(resolved))
            return ToolResult(
                True,
                data={
                    "opened": str(resolved),
                    "resolved": str(resolved),
                    "target_type": "file",
                    "canonical_path": str(resolved),
                    "exists": True,
                    "complete": True,
                },
            )
        except Exception as exc:
            return ToolResult(
                False,
                error=str(exc),
                data={
                    "target_type": "file",
                    "canonical_path": str(resolved),
                    "exists": True,
                    "complete": True,
                    "diagnostics": failure_diagnostics(
                        "file", str(resolved), exc, permission_result="approved"
                    ),
                },
            )


class OpenFolderTool(BaseTool):
    name = "open_folder"
    risk_level = "reversible"
    capability = "filesystem"
    description = "Open a folder in the file manager"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute folder path or a friendly name like 'Downloads'",
            },
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path") or arguments.get("name") or ""
        try:
            resolved = _resolve_target(path, expect="folder")
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        except FileNotFoundError as exc:
            return ToolResult(False, error=str(exc))
        try:
            desktop_open(str(resolved))
            return ToolResult(True, data={"opened": str(resolved), "resolved": str(resolved)})
        except Exception as exc:
            return ToolResult(
                False,
                error=str(exc),
                data={
                    "opened": str(resolved),
                    "resolved": str(resolved),
                    "diagnostics": failure_diagnostics(
                        "folder", str(resolved), exc, permission_result="approved"
                    ),
                },
            )


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    risk_level = "read_only"
    capability = "filesystem"
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
        try:
            resolved = resolve_within_roots(path)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if not resolved.is_dir():
            return ToolResult(False, error=f"Not a directory: {path}")
        try:
            entries = []
            for entry in sorted(os.listdir(resolved))[:50]:
                if entry.startswith("."):
                    continue
                full = resolved / entry
                entries.append({"name": entry, "type": "directory" if full.is_dir() else "file"})
            return ToolResult(True, data={"entries": entries, "count": len(entries)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ReadFileTool(BaseTool):
    name = "read_file"
    risk_level = "read_only"
    capability = "filesystem"
    description = "Read the contents of a text file (secret files are redacted)"
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
        max_bytes = min(max_bytes, 64 * 1024)
        try:
            resolved = resolve_within_roots(path)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if not resolved.is_file():
            return ToolResult(False, error=f"File not found: {path}")
        if resolved.is_dir():
            return ToolResult(False, error=f"Path is a directory: {path}")
        sensitive = is_sensitive_path(resolved)
        if sensitive:
            return ToolResult(False, error=f"Refusing to read a sensitive file: {path}")
        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            content = redact_content(content)
            return ToolResult(
                True,
                data={
                    "path": str(resolved),
                    "content": content,
                    "truncated": len(content) >= max_bytes,
                },
            )
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class FindRecentFilesTool(BaseTool):
    name = "find_recent_files"
    risk_level = "read_only"
    capability = "filesystem"
    description = "Find recently modified files under a directory"
    parameters = {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to search",
                "default": str(Path.home()),
            },
            "hours": {"type": "integer", "description": "Look back this many hours", "default": 24},
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        directory = arguments.get("directory", str(Path.home()))
        hours = int(arguments.get("hours", 24))
        limit = int(arguments.get("limit", 20))
        try:
            root = resolve_within_roots(directory)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        try:
            cutoff = __import__("time").time() - hours * 3600
            matches = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for f in filenames:
                    full = os.path.join(dirpath, f)
                    if is_sensitive_path(Path(full)):
                        continue
                    try:
                        mtime = os.path.getmtime(full)
                        if mtime >= cutoff:
                            matches.append({"path": full, "mtime": mtime})
                    except Exception:
                        continue
                if len(matches) >= limit:
                    break
            matches.sort(key=lambda x: x["mtime"], reverse=True)
            return ToolResult(True, data={"files": matches[:limit], "count": len(matches)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class FindByExtensionTool(BaseTool):
    name = "find_by_extension"
    risk_level = "read_only"
    capability = "filesystem"
    description = "Find files by extension under a directory"
    parameters = {
        "type": "object",
        "properties": {
            "extension": {
                "type": "string",
                "description": "Extension without dot, e.g. py, pdf, jpg",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search",
                "default": str(Path.home()),
            },
            "limit": {"type": "integer", "description": "Max results", "default": 30},
        },
        "required": ["extension"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        ext = arguments.get("extension", "").lower().lstrip(".")
        directory = arguments.get("directory", str(Path.home()))
        limit = int(arguments.get("limit", 30))
        if not ext:
            return ToolResult(False, error="Missing extension")
        try:
            root = resolve_within_roots(directory)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        try:
            matches = []
            suffix = f".{ext}"
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for f in filenames:
                    if f.lower().endswith(suffix):
                        full = os.path.join(dirpath, f)
                        if is_sensitive_path(Path(full)):
                            continue
                        matches.append(full)
                if len(matches) >= limit:
                    break
            return ToolResult(True, data={"files": matches[:limit], "count": len(matches)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class IdentifyFileTypeTool(BaseTool):
    name = "identify_file_type"
    risk_level = "read_only"
    capability = "filesystem"
    description = "Return the file extension/MIME type for a path"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        try:
            resolved = resolve_within_roots(path)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        try:
            if not resolved.exists():
                return ToolResult(False, error=f"Path not found: {path}")
            import mimetypes

            mime, _ = mimetypes.guess_type(str(resolved))
            ext = resolved.suffix.lower()
            return ToolResult(
                True, data={"path": str(resolved), "extension": ext, "mime": mime or "unknown"}
            )
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class CreateFolderTool(BaseTool):
    name = "create_folder"
    risk_level = "reversible"
    capability = "filesystem"
    description = "Create a new directory"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute directory path to create"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        try:
            resolved = resolve_within_roots(path, allow_missing=True)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        try:
            resolved.mkdir(parents=True, exist_ok=False)
            return ToolResult(True, data={"created": str(resolved)})
        except FileExistsError:
            return ToolResult(False, error=f"Already exists: {resolved}")
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class CreateFileTool(BaseTool):
    name = "create_file"
    risk_level = "reversible"
    capability = "filesystem"
    description = "Create a new file with optional content (overwriting an existing file requires confirmation)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute file path"},
            "content": {"type": "string", "description": "Optional initial content", "default": ""},
            "confirm": {
                "type": "boolean",
                "description": "Confirm if overwriting",
                "default": False,
            },
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        confirm = bool(arguments.get("confirm", False))
        try:
            resolved = resolve_within_roots(path, allow_missing=True)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if is_sensitive_path(resolved):
            return ToolResult(False, error=f"Refusing to write a sensitive path: {path}")
        if resolved.exists() and not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt=f"{resolved} already exists. Overwrite it?",
                data={"path": str(resolved)},
            )
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(True, data={"created": str(resolved)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class DeleteFileTool(BaseTool):
    name = "delete_file"
    risk_level = "destructive"
    capability = "filesystem"
    description = "Delete a file or empty directory. Requires confirmation."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path"},
            "confirm": {
                "type": "boolean",
                "description": "Must be true to execute",
                "default": False,
            },
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        path = arguments.get("path", "")
        confirm = bool(arguments.get("confirm", False))
        if not path:
            return ToolResult(False, error="Missing path")
        try:
            resolved = resolve_within_roots(path)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt=f"Do you want me to permanently delete {resolved}?",
                data={"path": str(resolved)},
            )
        if is_sensitive_path(resolved):
            return ToolResult(False, error=f"Refusing to delete a sensitive path: {path}")
        try:
            if resolved.is_dir():
                resolved.rmdir()
            else:
                resolved.unlink()
            return ToolResult(True, data={"deleted": str(resolved)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class MoveFileTool(BaseTool):
    name = "move_file"
    risk_level = "reversible"
    capability = "filesystem"
    description = "Move or rename a file or directory"
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path"},
            "destination": {"type": "string", "description": "Destination path"},
            "confirm": {
                "type": "boolean",
                "description": "Confirm if overwriting",
                "default": False,
            },
        },
        "required": ["source", "destination"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        source = arguments.get("source", "")
        destination = arguments.get("destination", "")
        confirm = bool(arguments.get("confirm", False))
        if not source or not destination:
            return ToolResult(False, error="Missing source or destination")
        try:
            src = resolve_within_roots(source)
            dst = resolve_within_roots(destination, allow_missing=True)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if is_sensitive_path(src) or is_sensitive_path(dst):
            return ToolResult(False, error="Refusing to move a sensitive path")
        if dst.exists() and not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt=f"{dst} already exists. Overwrite?",
                data={"source": str(src), "destination": str(dst)},
            )
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            return ToolResult(True, data={"moved": str(src), "to": str(dst)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class CopyFileTool(BaseTool):
    name = "copy_file"
    risk_level = "reversible"
    capability = "filesystem"
    description = "Copy a file or directory"
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path"},
            "destination": {"type": "string", "description": "Destination path"},
            "confirm": {
                "type": "boolean",
                "description": "Confirm if overwriting",
                "default": False,
            },
        },
        "required": ["source", "destination"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        source = arguments.get("source", "")
        destination = arguments.get("destination", "")
        confirm = bool(arguments.get("confirm", False))
        if not source or not destination:
            return ToolResult(False, error="Missing source or destination")
        try:
            src = resolve_within_roots(source)
            dst = resolve_within_roots(destination, allow_missing=True)
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))
        if is_sensitive_path(src) or is_sensitive_path(dst):
            return ToolResult(False, error="Refusing to copy a sensitive path")
        if dst.exists() and not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt=f"{dst} already exists. Overwrite?",
                data={"source": str(src), "destination": str(dst)},
            )
        try:
            import shutil

            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=confirm)
            else:
                shutil.copy2(src, dst)
            return ToolResult(True, data={"copied": str(src), "to": str(dst)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
