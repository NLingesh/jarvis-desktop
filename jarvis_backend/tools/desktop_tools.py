import base64
import logging
import os
import platform
import subprocess

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CloseAppTool(BaseTool):
    name = "close_app"
    risk_level = "destructive"
    capability = "applications"
    description = "Close a running application by name. Requires confirmation."
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "Application name to close"},
            "confirm": {"type": "boolean", "description": "Must be true to execute", "default": False},
        },
        "required": ["app"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        app = arguments.get("app", "").strip().lower()
        confirm = bool(arguments.get("confirm", False))
        if not app:
            return ToolResult(False, error="Missing app name")
        if not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt=f"Do you want me to close all running {app} processes?",
                data={"app": app},
            )
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
            return ToolResult(True, data={"killed": killed, "count": len(killed)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class ScreenshotTool(BaseTool):
    name = "screenshot"
    risk_level = "destructive"
    capability = "screen"
    description = "Take a screenshot and optionally analyze it (external vision provider only when requested)"
    parameters = {
        "type": "object",
        "properties": {
            "analyze": {"type": "boolean", "description": "Analyze the screenshot with vision", "default": False},
            "prompt": {"type": "string", "description": "Analysis prompt when analyze=true", "default": "Describe what is on this screen."},
            "confirm": {"type": "boolean", "description": "Required for capture", "default": False},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        analyze = bool(arguments.get("analyze", False))
        prompt = arguments.get("prompt", "Describe what is on this screen.")
        confirm = bool(arguments.get("confirm", False))
        if not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt="Do you want me to capture your screen? This image stays on this computer unless a vision provider is requested.",
                data={"analyze": analyze},
            )
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
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                return ToolResult(False, error="Screenshot capture produced an empty image")
            if not analyze:
                return ToolResult(True, data={"path": path})
            try:
                from routes.state import llm as _llm

                if not getattr(_llm, "supports_vision", lambda: False)():
                    return ToolResult(
                        True,
                        data={
                            "path": path,
                            "analysis": "Screenshot captured. No vision-capable model is configured, so I did not send it anywhere.",
                        },
                    )
                # External transfer: the user explicitly requested screen analysis.
                # Only the image and the user's own prompt leave this machine.
                vm = _llm
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                analysis = await vm.analyze_image(b64, prompt)
                if isinstance(analysis, dict):
                    analysis = analysis.get("analysis") or analysis.get("error") or str(analysis)
                elif not isinstance(analysis, str):
                    analysis = str(analysis)
                return ToolResult(
                    True,
                    data={
                        "path": path,
                        "analysis": analysis,
                        "privacy": "Screenshot sent to the configured vision provider because you asked me to analyze your screen.",
                    },
                )
            except Exception as exc:
                return ToolResult(
                    True,
                    data={
                        "path": path,
                        "analysis": f"Screenshot captured, but analysis failed: {exc}",
                    },
                )
        except Exception as exc:
            return ToolResult(False, error=str(exc))