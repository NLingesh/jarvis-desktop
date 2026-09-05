import base64
import logging
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import psutil

from modules.desktop_open import desktop_open, failure_diagnostics
from modules.known_locations import PROJECT_ROOT as KNOWN_PROJECT_ROOT
from modules.known_locations import resolve_known_location
from tools import BaseTool, ToolResult
from tools.app_tools import ALLOWED_APPS

logger = logging.getLogger(__name__)


class OpenUrlTool(BaseTool):
    name = "open_url"
    risk_level = "reversible"
    capability = "applications"
    description = "Open a web address (http, https, or mailto) in the default browser"
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Web address to open, e.g. https://example.com",
            },
        },
        "required": ["url"],
    }

    _ALLOWED_SCHEMES = {"http", "https", "mailto"}
    _SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
    _HOSTISH_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+([/:?#][^\s]*)?$", re.IGNORECASE)

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        url = (arguments.get("url") or arguments.get("name") or "").strip()
        if not url:
            return ToolResult(False, error="Missing url")
        if any(ch in url for ch in " \t\n\r"):
            return ToolResult(False, error="That doesn't look like a valid web address")
        if self._SCHEME_RE.match(url):
            scheme = url.split(":", 1)[0].lower()
        elif self._HOSTISH_RE.match(url):
            url = "https://" + url
            scheme = "https"
        else:
            return ToolResult(False, error="That doesn't look like a valid web address")
        if scheme not in self._ALLOWED_SCHEMES:
            return ToolResult(False, error=f"Refusing to open a {scheme}:// address")
        try:
            desktop_open(url)
            return ToolResult(True, data={"opened": url, "resolved": url})
        except Exception as exc:
            return ToolResult(
                False,
                error=str(exc),
                data={
                    "diagnostics": failure_diagnostics(
                        "url", url, exc, permission_result="approved"
                    )
                },
            )


class ResolveKnownLocationTool(BaseTool):
    name = "resolve_known_location"
    risk_level = "read_only"
    capability = "filesystem"
    description = "Resolve a friendly location name (Downloads, Desktop, Documents, Home, the project) to an absolute path"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Location name, e.g. Downloads, Desktop, Home, the project",
            },
        },
        "required": ["name"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        name = (
            arguments.get("name") or arguments.get("location") or arguments.get("path") or ""
        ).strip()
        resolved = resolve_known_location(name)
        if resolved is None:
            return ToolResult(False, error=f"Unknown location: {name}")
        canonical = str(resolved)
        project_root = (
            Path(os.getenv("JARVIS_PROJECT_ROOT") or KNOWN_PROJECT_ROOT).expanduser().resolve()
        )
        return ToolResult(
            True,
            data={
                "name": name,
                "path": canonical,
                "resolved": canonical,
                "canonical_path": canonical,
                "target_type": "project" if resolved == project_root else "folder",
                "exists": resolved.exists(),
                # Resolving a directory is a building block, never a task
                # finish: the caller must still open/act on the path.
                "continue_required": True,
            },
        )


_GUI_APP_NAMES = ALLOWED_APPS | {
    "google-chrome",
    "microsoft-edge",
    "brave",
    "opera",
    "org.gnome.Nautilus",
    "org.gnome.Terminal",
    "gnome-terminal-server",
    "discord",
    "slack",
    "teams-for-linux",
    "signal-desktop",
    "telegram-desktop",
    "1password",
    "keepassxc",
    "bitwarden",
    "pycharm",
    "idea",
    "webstorm",
    "goland",
    "android-studio",
    "steam",
    "zoom",
    "obs-studio",
    "mpv",
    "kdenlive",
    "ardour",
    "gnome-shell",
    "gnome-calculator",
    "gnome-screenshot",
}


class ListRunningApplicationsTool(BaseTool):
    name = "list_running_applications"
    risk_level = "read_only"
    capability = "system"
    description = "List currently running desktop applications"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        try:
            running = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                except Exception:
                    continue
                if name and name in _GUI_APP_NAMES:
                    running.append({"name": proc.info["name"], "pid": proc.info["pid"]})
            running.sort(key=lambda x: (x["name"].lower(), x["pid"]))
            return ToolResult(True, data={"applications": running[:40], "count": len(running)})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class CloseAppTool(BaseTool):
    name = "close_app"
    risk_level = "destructive"
    capability = "applications"
    description = "Close a running application by name. Requires confirmation."
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "Application name to close"},
            "confirm": {
                "type": "boolean",
                "description": "Must be true to execute",
                "default": False,
            },
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
    risk_level = "read_only"
    capability = "screen"
    description = "Capture the screen on request; analyze it only when explicitly requested and a vision provider is configured"
    parameters = {
        "type": "object",
        "properties": {
            "analyze": {
                "type": "boolean",
                "description": "Analyze the screenshot with vision",
                "default": False,
            },
            "prompt": {
                "type": "string",
                "description": "Analysis prompt when analyze=true",
                "default": "Describe what is on this screen.",
            },
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        analyze = bool(arguments.get("analyze", False))
        prompt = arguments.get("prompt", "Describe what is on this screen.")
        try:
            out_dir = os.path.expanduser("~/Pictures")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "jarvis_screenshot.png")
            if platform.system() == "Linux":
                if shutil.which("gnome-screenshot"):
                    subprocess.run(["gnome-screenshot", "-f", path], check=True)
                elif shutil.which("scrot"):
                    subprocess.run(["scrot", path], check=True)
                elif shutil.which("import"):
                    subprocess.run(["import", "-window", "root", path], check=True)
                else:
                    return ToolResult(
                        False,
                        error="No supported Linux screenshot utility found. Install gnome-screenshot, scrot, or ImageMagick import.",
                    )
            elif platform.system() == "Darwin":
                subprocess.run(["screencapture", path], check=True)
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
