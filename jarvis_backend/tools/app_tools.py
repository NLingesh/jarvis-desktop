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
    risk_level = "reversible"
    capability = "applications"
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
    risk_level = "reversible"
    capability = "applications"
    name = "open_terminal"
    description = "Open a new terminal window"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Ignored: terminals are opened interactively; command execution is not supported.",
                "default": "",
            },
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        # Intentionally no command execution: opening a terminal with an arbitrary
        # command string (`-e bash -lc <command>`) is equivalent to arbitrary
        # shell execution and would bypass the execute_shell allowlist.  Only
        # open an interactive terminal window.
        command = (arguments.get("command") or "").strip()
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
                logger.info("open_terminal: ignoring command argument (execution disabled)")
            subprocess.Popen([chosen])
            return ToolResult(True, data={"terminal": chosen})
        except Exception as exc:
            return ToolResult(False, error=str(exc))


def _which(cmd: str) -> bool:
    return subprocess.run(["bash", "-lc", f"command -v {cmd}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0