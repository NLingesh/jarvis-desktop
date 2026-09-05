import logging
import os
import shutil
import subprocess
import time

from modules.desktop_open import base_diagnostics, failure_diagnostics
from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Single source of truth for launchable applications.  The HTTP tools route
# (routes/tools.py) and SystemActions both import this set so the allowlist
# cannot drift across call paths.
ALLOWED_APPS = {
    "firefox",
    "chrome",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
    "brave",
    "opera",
    "thunderbird",
    "evolution",
    "nautilus",
    "dolphin",
    "pcmanfm",
    "thunar",
    "code",
    "code-oss",
    "sublime_text",
    "atom",
    "vim",
    "nvim",
    "nano",
    "gedit",
    "kate",
    "terminal",
    "konsole",
    "alacritty",
    "kitty",
    "tilix",
    "gnome-terminal",
    "xfce4-terminal",
    "xterm",
    "wezterm",
    "libreoffice",
    "libreoffice-writer",
    "libreoffice-calc",
    "libreoffice-impress",
    "vlc",
    "audacious",
    "rhythmbox",
    "spotify",
    "gnome-settings",
    "systemsettings",
    "gnome-calculator",
    "kcalc",
    "blender",
    "gimp",
    "inkscape",
    "file-roller",
    "evince",
    "okular",
    "figma",
}

# User-facing names -> ordered list of allowed candidate executables.
APP_ALIASES = {
    "vscode": ["code", "code-oss"],
    "vs code": ["code", "code-oss"],
    "visual studio code": ["code", "code-oss"],
    "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "browser": ["firefox", "google-chrome", "chromium"],
    "web browser": ["firefox", "google-chrome", "chromium"],
    "files": ["nautilus", "dolphin", "thunar", "pcmanfm"],
    "file manager": ["nautilus", "dolphin", "thunar", "pcmanfm"],
    "file explorer": ["nautilus", "dolphin", "thunar", "pcmanfm"],
    "text editor": ["gedit", "kate", "nano"],
    "editor": ["code", "code-oss", "gedit", "nano"],
    "calculator": ["gnome-calculator", "kcalc"],
    "terminal emulator": ["gnome-terminal", "konsole", "alacritty", "kitty", "xterm"],
    "settings": ["gnome-settings", "systemsettings"],
    "mail": ["thunderbird", "evolution"],
    "mail client": ["thunderbird", "evolution"],
    "pdf viewer": ["evince", "okular"],
    "word processor": ["libreoffice-writer"],
    "spreadsheet": ["libreoffice-calc"],
    "music player": ["rhythmbox", "audacious"],
    "video player": ["vlc"],
}


def resolve_launch_target(app: str) -> str | None:
    """Resolve a user-supplied app name to an installed, allowlisted executable.

    Returns the absolute executable path, or None when the name is not allowed,
    has no alias, or is not installed.  No shell is ever involved.
    """
    key = (app or "").strip().lower()
    if not key:
        return None
    candidates = APP_ALIASES.get(key, [key])
    for candidate in candidates:
        if candidate not in ALLOWED_APPS:
            continue
        executable = shutil.which(candidate)
        if executable:
            return executable
    return None


def find_running_app(executable: str) -> list[int]:
    """Return PIDs of processes matching a resolved launchable executable.

    Matches by process name and by cmdline/executable basename so a wrapper
    binary (e.g. ``/usr/bin/code``) is detected through its real running
    child (``/usr/share/code/code``).  Read-only introspection: never
    launches, signals, or touches processes.
    """
    try:
        import psutil
    except ImportError:
        return []
    base = os.path.basename(executable)
    pids: list[int] = []
    for proc in psutil.process_iter(["name", "cmdline", "exe"]):
        try:
            if proc.pid == os.getpid():
                continue
            name = proc.info.get("name") or ""
            cmdline = proc.info.get("cmdline") or []
            exe = proc.info.get("exe") or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if not name and not cmdline and not exe:
            continue
        if name and os.path.basename(name) == base:
            pids.append(proc.pid)
            continue
        if exe and os.path.basename(exe) == base:
            pids.append(proc.pid)
            continue
        for element in cmdline:
            if element and os.path.basename(element) == base:
                pids.append(proc.pid)
                break
    return pids


def _focus_running_app(pids: list[int]) -> bool:
    """Best-effort focus of an already-running app via wmctrl, when installed.

    Returns True only when a matching window was actually activated.  When
    wmctrl is absent (the common case) this returns False and the caller
    reports the truthful "already running" state without claiming focus.
    """
    if not pids or shutil.which("wmctrl") is None:
        return False
    try:
        listing = subprocess.run(
            ["wmctrl", "-l", "-p"], capture_output=True, text=True, timeout=2
        ).stdout
        wanted = {str(pid) for pid in pids}
        for line in listing.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3 and parts[2] in wanted:
                subprocess.Popen(["wmctrl", "-i", "-a", parts[0]])
                return True
    except Exception:
        return False
    return False


def _launch(app: str, arguments: dict, context: dict | None = None) -> ToolResult:
    executable = resolve_launch_target(app)
    if executable is None:
        return ToolResult(
            False,
            error=f"{app} is not installed, or is not on the list of applications I'm allowed to launch",
            data={
                "diagnostics": base_diagnostics(
                    "application", app, permission_result="not-allowlisted-or-not-installed"
                ).to_dict()
            },
        )
    running = find_running_app(executable)
    if running:
        focused = _focus_running_app(running)
        return ToolResult(
            True,
            data={
                "launched": app,
                "executable": executable,
                "pids": running,
                "verified": True,
                "already_running": True,
                "focused": focused,
            },
        )
    try:
        proc = subprocess.Popen([executable])
        time.sleep(0.12)
        rc = proc.poll()
        if rc is not None and rc != 0:
            diag = base_diagnostics("application", app, permission_result="approved")
            diag.resolved_executable = executable
            diag.exit_code = rc
            diag.stderr_category = "immediate-exit"
            return ToolResult(
                False,
                error=f"{app} exited immediately with code {rc}",
                data={"diagnostics": diag.to_dict()},
            )
        return ToolResult(
            True,
            data={
                "launched": app,
                "executable": executable,
                "pid": proc.pid,
                "verified": True,
            },
        )
    except Exception as exc:
        return ToolResult(
            False,
            error=str(exc),
            data={
                "diagnostics": failure_diagnostics(
                    "application", app, exc, permission_result="approved"
                )
            },
        )


class LaunchAppTool(BaseTool):
    risk_level = "reversible"
    capability = "applications"
    name = "launch_app"
    description = "Launch an allowed desktop application by name"
    parameters = {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "Application name, e.g. code, firefox, nautilus",
            },
        },
        "required": ["app"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        app = (arguments.get("app") or arguments.get("name") or "").strip().lower()
        if not app:
            return ToolResult(False, error="Missing app name")
        return _launch(app, arguments, context)


class LaunchApplicationTool(LaunchAppTool):
    """Canonical tool for launching desktop applications.

    ``launch_app`` (the parent class) remains importable for tests and legacy
    callers, but ``launch_application`` is the single registered name.
    """

    name = "launch_application"


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
            if shutil.which(term):
                chosen = term
                break
        if not chosen:
            return ToolResult(
                False,
                error="No supported terminal emulator found",
                data={
                    "diagnostics": base_diagnostics(
                        "terminal", "terminal", permission_result="no-terminal-found"
                    ).to_dict()
                },
            )
        try:
            if command:
                logger.info("open_terminal: ignoring command argument (execution disabled)")
            subprocess.Popen([chosen])
            return ToolResult(True, data={"terminal": chosen})
        except Exception as exc:
            return ToolResult(
                False,
                error=str(exc),
                data={
                    "diagnostics": failure_diagnostics(
                        "terminal", chosen, exc, permission_result="approved"
                    )
                },
            )


class ControlAppWindowTool(BaseTool):
    """Show/toggle the JARVIS desktop application window.

    The backend cannot reach the Electron main process directly, so it
    broadcasts a ``window_action`` message to connected renderers over the
    WebSocket and waits for a matching ``window_action_ack`` echo (bounded) to
    verify the window command took effect.  No ack means an honest failure, never
    a claimed success.
    """

    risk_level = "reversible"
    capability = "system"
    name = "control_app_window"
    description = "Show, hide, or toggle the JARVIS desktop application window"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["show_main", "toggle_main", "hide_main"],
                "description": "Which window operation to perform on the JARVIS app itself",
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        import uuid

        from modules.window_control import broadcast, wait_for_ack

        action = (arguments.get("action") or "show_main").strip()
        if action not in ("show_main", "toggle_main", "hide_main"):
            return ToolResult(False, error=f"Unknown window action: {action}")
        request_id = uuid.uuid4().hex[:12]
        sent = await broadcast(
            {"type": "window_action", "action": action, "request_id": request_id}
        )
        if sent == 0:
            return ToolResult(
                False,
                error="No desktop app window is connected, so I could not open the JARVIS window.",
                data={"action": action, "requested": True, "verified": False, "renderers": 0},
            )
        verified = await wait_for_ack(request_id, timeout=3.0)
        return ToolResult(
            verified,
            error=(
                None if verified else "Sent the command, but could not confirm the window opened."
            ),
            data={
                "action": action,
                "requested": True,
                "verified": verified,
                "renderers": sent,
                "request_id": request_id,
            },
        )
