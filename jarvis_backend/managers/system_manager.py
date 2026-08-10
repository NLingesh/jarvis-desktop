"""System Manager — unified system control with confirmation gating, undo, and audit trail.

This manager wraps SystemActions and adds:
- Confirmation gating for destructive actions
- Undo support (trash instead of delete)
- Permission scopes
- Audit trail integration
"""

import asyncio
import contextlib
import logging
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any

from modules.system_actions import ALLOWED_COMMANDS, SystemActions

logger = logging.getLogger(__name__)


class SystemManager:
    """Unified system control with safety gates."""

    def __init__(self, memory_manager: Any, audit_enabled: bool = True):
        self.actions = SystemActions()
        self.memory = memory_manager
        self.audit_enabled = audit_enabled
        self._undo_stack: list[dict] = []
        self._max_undo = 50

    async def execute_command(self, command: str, confirm: bool = False) -> dict:
        """Execute a system command with optional confirmation."""
        if not confirm:
            return {"error": "confirm=true is required for command execution"}

        if command not in ALLOWED_COMMANDS:
            return {"error": f"Command not allowed. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"}

        output = await self.actions.execute_command(command)
        await self._audit(
            "command.execute", command, "success" if not output.startswith("Error") else "failed"
        )
        return {"command": command, "output": output}

    async def open_application(self, app_name: str, confirm: bool = False) -> dict:
        """Open an application."""
        if not confirm:
            return {"error": "confirm=true is required for opening applications"}

        success = await asyncio.to_thread(self.actions.open_application, app_name)
        await self._audit("apps.open", app_name, "success" if success else "failed")
        return {"opened": app_name} if success else {"error": f"Failed to open {app_name}"}

    async def close_application(
        self, app_name: str = "", pid: int = 0, confirm: bool = False
    ) -> dict:
        """Close an application by name or PID."""
        if not confirm:
            return {"error": "confirm=true is required for closing applications"}

        if not app_name and not pid:
            return {"error": "app_name or pid is required"}

        target = app_name or str(pid)
        await self._audit("apps.close", target, "started")

        try:
            if pid:
                os.kill(int(pid), 9)
                await self._audit("apps.close", str(pid), "success")
                return {"closed": str(pid)}

            if not app_name:
                return {"error": "app_name is required when pid is not provided"}

            import psutil

            closed = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["name"] and proc.info["name"].lower() == app_name.lower():
                        proc.terminate()
                        closed.append(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            await self._audit("apps.close", app_name, f"closed {len(closed)} processes")
            return {"closed": closed}
        except Exception as e:
            await self._audit("apps.close", target, f"error: {e}")
            return {"error": str(e)}

    async def delete_file(self, path: str, confirm: bool = False) -> dict:
        """Delete a file (moves to trash for undo support)."""
        if not confirm:
            return {"error": "confirm=true is required for file deletion"}

        p = Path(path).expanduser().resolve()
        base = Path(os.getenv("ALLOWED_FILE_BASE", os.path.expanduser("~"))).resolve()
        if not str(p).startswith(str(base)):
            return {"error": "Path outside allowed scope"}

        if not p.exists():
            return {"error": "File not found"}

        trash_dir = Path(tempfile.gettempdir()) / "jarvis_trash"
        trash_dir.mkdir(exist_ok=True)
        trash_path = trash_dir / f"{p.name}.{secrets.token_hex(4)}"

        try:
            shutil.move(str(p), str(trash_path))
            self._push_undo({"action": "delete", "original": str(p), "trashed": str(trash_path)})
            await self._audit("files.delete", str(p), "success")
            return {"deleted": str(p), "trashed": str(trash_path), "undoable": True}
        except Exception as e:
            await self._audit("files.delete", str(p), f"error: {e}")
            return {"error": str(e)}

    async def rename_file(self, old_path: str, new_path: str, confirm: bool = False) -> dict:
        """Rename a file."""
        if not confirm:
            return {"error": "confirm=true is required for file rename"}

        src = Path(old_path).expanduser().resolve()
        dst = Path(new_path).expanduser().resolve()
        base = Path(os.getenv("ALLOWED_FILE_BASE", os.path.expanduser("~"))).resolve()
        if not str(src).startswith(str(base)) or not str(dst).startswith(str(base)):
            return {"error": "Path outside allowed scope"}

        if not src.exists():
            return {"error": "Source file not found"}

        if dst.exists():
            return {"error": "Destination already exists"}

        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            src.rename(dst)
            self._push_undo({"action": "rename", "original": str(src), "new": str(dst)})
            await self._audit("files.rename", f"{old_path} -> {new_path}", "success")
            return {"old_path": str(src), "new_path": str(dst), "undoable": True}
        except Exception as e:
            await self._audit("files.rename", f"{old_path} -> {new_path}", f"error: {e}")
            return {"error": str(e)}

    async def create_folder(self, path: str, confirm: bool = False) -> dict:
        """Create a folder."""
        if not confirm:
            return {"error": "confirm=true is required for folder creation"}

        p = Path(path).expanduser().resolve()
        base = Path(os.getenv("ALLOWED_FILE_BASE", os.path.expanduser("~"))).resolve()
        if not str(p).startswith(str(base)):
            return {"error": "Path outside allowed scope"}

        try:
            p.mkdir(parents=True, exist_ok=True)
            await self._audit("files.mkdir", str(p), "success")
            return {"created": str(p)}
        except Exception as e:
            await self._audit("files.mkdir", str(p), f"error: {e}")
            return {"error": str(e)}

    async def read_clipboard(self) -> dict:
        """Read clipboard content."""
        await self._audit("clipboard.read", "clipboard", "started")
        try:
            proc = await asyncio.create_subprocess_exec(
                "xclip",
                "-selection",
                "clipboard",
                "-o",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            text = stdout.decode(errors="replace") if stdout else ""
            if proc.returncode != 0:
                text = stderr.decode(errors="replace") if stderr else ""
            await self._audit("clipboard.read", "clipboard", "success" if text else "empty")
            return {"text": text}
        except FileNotFoundError:
            await self._audit("clipboard.read", "clipboard", "xclip_not_found")
            return {"error": "xclip not available on this system"}
        except Exception as e:
            await self._audit("clipboard.read", "clipboard", f"error: {e}")
            return {"error": str(e)}

    async def write_clipboard(self, text: str, confirm: bool = False) -> dict:
        """Write text to clipboard."""
        if not confirm:
            return {"error": "confirm=true is required for clipboard write"}

        await self._audit("clipboard.write", "clipboard", "started")
        try:
            proc = await asyncio.create_subprocess_exec(
                "xclip",
                "-selection",
                "clipboard",
                "-i",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=text.encode("utf-8")), timeout=5
            )
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode(errors="replace"))
            await self._audit("clipboard.write", "clipboard", "success")
            return {"written": len(text)}
        except FileNotFoundError:
            await self._audit("clipboard.write", "clipboard", "xclip_not_found")
            return {"error": "xclip not available on this system"}
        except Exception as e:
            await self._audit("clipboard.write", "clipboard", f"error: {e}")
            return {"error": str(e)}

    async def take_screenshot(self, confirm: bool = False) -> dict:
        """Take a screenshot."""
        if not confirm:
            return {"error": "confirm=true is required for screenshot"}

        await self._audit("screenshot", "display", "started")
        tmp_path = f"/tmp/jarvis_screenshot_{secrets.token_hex(8)}.png"
        try:
            proc = await asyncio.create_subprocess_exec(
                "gnome-screenshot",
                "-f",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode(errors="replace") or "gnome-screenshot failed")
        except FileNotFoundError:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "scrot",
                    tmp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode != 0:
                    raise RuntimeError(stderr.decode(errors="replace") or "scrot failed")
            except FileNotFoundError:
                await self._audit("screenshot", "display", "no_tool_available")
                return {"error": "No screenshot tool available"}
        except Exception as e:
            await self._audit("screenshot", "display", f"error: {e}")
            return {"error": str(e)}

        try:
            import base64
            import io

            from PIL import Image

            img = Image.open(tmp_path)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            await self._audit("screenshot", "display", f"success size={len(b64)}")
            return {"image_base64": b64, "format": "png"}
        finally:
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)

    async def undo_last(self) -> dict:
        """Undo the last reversible action."""
        if not self._undo_stack:
            return {"error": "Nothing to undo"}

        action = self._undo_stack.pop()
        try:
            if action["action"] == "delete":
                src = Path(action["original"])
                trash = Path(action["trashed"])
                if trash.exists():
                    shutil.move(str(trash), str(src))
                    await self._audit("undo", action["action"], "success")
                    return {"undone": action["action"], "restored": str(src)}
            elif action["action"] == "rename":
                src = Path(action["original"])
                dst = Path(action["new"])
                if dst.exists():
                    dst.rename(src)
                    await self._audit("undo", action["action"], "success")
                    return {"undone": action["action"], "restored": str(src)}
        except Exception as e:
            await self._audit("undo", action["action"], f"error: {e}")
            return {"error": str(e)}

        return {"error": "Cannot undo this action"}

    def _push_undo(self, action: dict) -> None:
        self._undo_stack.append(action)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)

    async def _audit(self, command: str, target: str, result: str) -> None:
        if self.audit_enabled:
            try:
                from modules.audit import log_action

                await log_action(command, target, "system_manager", result)
            except Exception:
                pass
