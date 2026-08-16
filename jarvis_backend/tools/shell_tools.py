import asyncio
import logging
import os
from pathlib import Path

from modules.path_policy import is_sensitive_path, resolve_within_roots
from modules.system_actions import ALLOWED_COMMANDS, SHELL_METACHARACTERS
from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# The developer command runner is restricted to a small allowlist of read-only,
# non-destructive commands.  Shell metacharacters and arbitrary scripts are
# never executed.  Every invocation requires explicit user approval.
SAFE_SHELL_COMMANDS = frozenset(ALLOWED_COMMANDS)

# Commands whose arguments may be file paths whose content is exposed.
PATH_READING_COMMANDS = frozenset({"cat", "echo"})

MAX_OUTPUT_BYTES = 64 * 1024
MAX_TIMEOUT = 30


def _reject_sensitive_args(command: str) -> str | None:
    """Return an error string if a path-reading command targets material that
    the path policy would refuse (outside approved roots or sensitive)."""
    parts = command.split()
    if not parts or parts[0] not in PATH_READING_COMMANDS:
        return None
    for arg in parts[1:]:
        if arg.startswith("-") or arg == ">":
            continue
        try:
            resolve_within_roots(arg)  # raises PermissionError if outside roots
        except PermissionError:
            return f"Refusing to read a path outside the approved roots: {arg}"
        candidate = Path(arg).expanduser()
        if is_sensitive_path(candidate):
            return f"Refusing to read a sensitive path: {arg}"
    return None


class ExecuteShellTool(BaseTool):
    name = "execute_shell"
    risk_level = "destructive"
    capability = "developer"
    description = (
        "Run one allowlisted read-only system command (ls, cat, echo, pwd, whoami, "
        "date, uname, uptime, df, free, ps). Requires confirmation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Allowlisted command and its arguments"},
            "cwd": {"type": "string", "description": "Working directory within approved roots", "default": ""},
            "timeout": {"type": "integer", "description": "Timeout seconds (max 30)", "default": 15},
        },
        "required": ["command"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        command = (arguments.get("command") or "").strip()
        cwd = (arguments.get("cwd") or "").strip()
        timeout = min(int(arguments.get("timeout", 15) or 15), MAX_TIMEOUT)

        if not command:
            return ToolResult(False, error="Empty command")
        if SHELL_METACHARACTERS.search(command):
            return ToolResult(False, error="Shell metacharacters are not allowed")
        parts = command.split()
        if parts[0] not in SAFE_SHELL_COMMANDS:
            return ToolResult(
                False,
                error=(
                    f"Command not allowed. Only: {', '.join(sorted(SAFE_SHELL_COMMANDS))}"
                ),
            )
        sensitive = _reject_sensitive_args(command)
        if sensitive:
            return ToolResult(False, error=sensitive)

        # Every invocation of the shell runner requires explicit approval.
        confirm = bool(arguments.get("confirm", False))
        if not confirm:
            return ToolResult(
                True,
                requires_confirmation=True,
                confirmation_prompt=f"Run the command '{command}' on this machine?",
                data={"command": command, "cwd": cwd},
            )

        try:
            resolved_cwd = os.getcwd()
            if cwd:
                resolved_cwd = str(resolve_within_roots(cwd))
        except PermissionError as exc:
            return ToolResult(False, error=str(exc))

        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                cwd=resolved_cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode(errors="replace")[:MAX_OUTPUT_BYTES]
            err = stderr.decode(errors="replace")[:MAX_OUTPUT_BYTES]
            if len(out) >= MAX_OUTPUT_BYTES:
                out += "\n[output truncated]"
            try:
                from modules.audit import log_action

                await log_action(
                    "execute_shell",
                    f"{command} (cwd={resolved_cwd})",
                    "session_token",
                    f"rc={proc.returncode}",
                )
            except Exception:
                pass
            return ToolResult(
                True, data={"stdout": out, "stderr": err, "returncode": proc.returncode}
            )
        except TimeoutError:
            return ToolResult(False, error="Command timed out")
        except Exception as exc:
            return ToolResult(False, error=f"Internal error running command")