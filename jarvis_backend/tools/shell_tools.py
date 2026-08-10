import asyncio
import logging
import os
import re

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DESTRUCTIVE_PATTERNS = [
    r"rm\s+-rf", r"rm\s+-fr", r"rm\s+-r", r"rm\s+-f",
    r"dd\s+if=", r"mkfs", r"fdisk", r"sudo", r"su\s+-",
    r":(){", r">\s*/dev/sd", r"chmod\s+-R\s+000",
]


class ExecuteShellTool(BaseTool):
    name = "execute_shell"
    description = "Execute a safe shell command and return stdout/stderr"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "cwd": {"type": "string", "description": "Working directory", "default": ""},
            "timeout": {"type": "integer", "description": "Timeout seconds", "default": 15},
        },
        "required": ["command"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        command = arguments.get("command", "")
        cwd = arguments.get("cwd") or os.getcwd()
        timeout = int(arguments.get("timeout", 15))
        if not command.strip():
            return ToolResult(False, error="Empty command")
        lowered = command.lower()
        for pat in DESTRUCTIVE_PATTERNS:
            if re.search(pat, lowered):
                return ToolResult(
                    True,
                    requires_confirmation=True,
                    confirmation_prompt=f"This command may be destructive: {command}. Run it anyway?",
                    data={"command": command, "cwd": cwd},
                )
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode(errors="replace") if stdout else ""
            err = stderr.decode(errors="replace") if stderr else ""
            return ToolResult(True, data={"stdout": out, "stderr": err, "returncode": proc.returncode})
        except TimeoutError:
            return ToolResult(False, error="Command timed out")
        except Exception as exc:
            return ToolResult(False, error=str(exc))
