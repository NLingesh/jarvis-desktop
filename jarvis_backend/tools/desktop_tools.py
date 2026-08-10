import logging
import os
import platform
import subprocess

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CloseAppTool(BaseTool):
    name = "close_app"
    description = "Close a running application by name"
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "Application name to close"},
        },
        "required": ["app"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        app = arguments.get("app", "").lower()
        try:
            import psutil
            killed = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["name"] and proc.info["name"].lower() == app:
                        proc.terminate()
                        killed.append(proc.info["pid"])
                except Exception:
                    continue
            return ToolResult(True, data={"killed": killed})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ScreenshotTool(BaseTool):
    name = "screenshot"
    description = "Take a screenshot and save it to the Pictures directory"
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        try:
            out_dir = os.path.expanduser("~/Pictures")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "jarvis_screenshot.png")
            if platform.system() == "Linux":
                subprocess.run(["gnome-screenshot", "-f", path], check=False)
            elif platform.system() == "Darwin":
                subprocess.run(["screencapture", path], check=False)
            else:
                return ToolResult(False, error="Screenshot not supported on this platform")
            return ToolResult(True, data={"path": path})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
