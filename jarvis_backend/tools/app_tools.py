import logging
import subprocess

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

ALLOWED_APPS = {
    "firefox", "chrome", "chromium", "chromium-browser",
    "thunderbird", "evolution", "nautilus", "dolphin",
    "code", "code-oss", "vim", "nvim", "nano", "gedit",
    "terminal", "konsole", "alacritty", "kitty", "tilix",
    "libreoffice", "libreoffice-writer", "libreoffice-calc",
    "vlc", "audacious", "rhythmbox", "spotify",
    "gnome-settings", "systemsettings", "blender", "gimp",
    "inkscape", "file-roller", "evince", "okular",
}


class LaunchAppTool(BaseTool):
    name = "launch_app"
    description = "Launch an allowed desktop application by name"
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "Application name, e.g. code, firefox, nautilus"},
        },
        "required": ["app"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        app = arguments.get("app", "").strip().lower()
        if app not in ALLOWED_APPS:
            return ToolResult(False, error=f"Application not allowed: {app}")
        try:
            subprocess.Popen([app])
            return ToolResult(True, data={"launched": app})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class OpenTerminalTool(BaseTool):
    name = "open_terminal"
    description = "Open a new terminal window"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Optional command to run", "default": ""},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        command = arguments.get("command", "")
        terminals = ["alacritty", "kitty", "konsole", "gnome-terminal", "xterm"]
        chosen = None
        for term in terminals:
            if _which(term):
                chosen = term
                break
        if not chosen:
            return ToolResult(False, error="No supported terminal emulator found")
        try:
            if command:
                subprocess.Popen([chosen, "-e", "bash", "-lc", command])
            else:
                subprocess.Popen([chosen])
            return ToolResult(True, data={"terminal": chosen})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


def _which(cmd: str) -> bool:
    return subprocess.run(["bash", "-lc", f"command -v {cmd}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
