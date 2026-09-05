import asyncio
import logging
import platform
import re
import subprocess

import psutil

from tools.app_tools import resolve_launch_target

logger = logging.getLogger(__name__)

SHELL_METACHARACTERS = re.compile(r"[;&|><`$()]")

# Single source of truth for commands that may be executed. The API layer
# (routes/state.validate_system_command) and SystemActions both read this set.
ALLOWED_COMMANDS = frozenset(
    {"echo", "cat", "ls", "pwd", "whoami", "date", "uname", "uptime", "df", "free", "ps"}
)


class SystemActions:
    def __init__(self):
        self.allowed_commands = ALLOWED_COMMANDS

    def get_system_info(self) -> dict:
        """Get comprehensive system information"""
        try:
            return {
                "hostname": self._get_hostname(),
                "os": self._get_os(),
                "cpu": self._get_cpu_info(),
                "memory": self._get_memory_info(),
                "disk": self._get_disk_info(),
                "uptime": self._get_uptime(),
                "network": self._get_network_info(),
            }
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return {}

    def _get_hostname(self) -> str:
        """Get system hostname"""
        try:
            return platform.node() or "Unknown"
        except Exception:
            return "Unknown"

    def _get_os(self) -> dict:
        """Get OS information"""
        try:
            import platform

            return {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "platform": platform.platform(),
            }
        except Exception:
            return {}

    def _get_cpu_info(self) -> dict:
        """Get CPU information"""
        try:
            return {
                "count": psutil.cpu_count(),
                "percent": psutil.cpu_percent(interval=1),
                "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
            }
        except Exception:
            return {}

    def _get_memory_info(self) -> dict:
        """Get memory information"""
        try:
            memory = psutil.virtual_memory()
            return {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used,
                "free": memory.free,
            }
        except Exception:
            return {}

    def _get_disk_info(self) -> dict:
        """Get disk information"""
        try:
            disk = psutil.disk_usage("/")
            return {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent,
            }
        except Exception:
            return {}

    def _get_uptime(self) -> float:
        """Get system uptime in seconds"""
        try:
            with open("/proc/uptime") as f:
                return float(f.readline().split()[0])
        except Exception:
            return 0.0

    def _get_network_info(self) -> dict:
        """Get network information"""
        try:
            net = psutil.net_if_stats()
            return {
                "interfaces": list(net.keys()),
                "stats": {name: stats._asdict() for name, stats in net.items()},
            }
        except Exception:
            return {}

    async def execute_command(self, command: str) -> str:
        """Execute a safe, allowlisted system command without blocking the loop."""
        if SHELL_METACHARACTERS.search(command):
            return "Command not allowed: shell metacharacters detected"

        cmd_parts = command.split()
        if not cmd_parts or cmd_parts[0] not in self.allowed_commands:
            return "Command not allowed"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode(errors="replace") if stdout else ""
            if proc.returncode != 0:
                output = stderr.decode(errors="replace") if stderr else "Error"
            return output
        except TimeoutError:
            return "Command timed out"
        except Exception as e:
            logger.error("Command execution failed: %s", e)
            return f"Error: {str(e)}"

    async def get_processes(self) -> list[dict]:
        """Get list of running processes"""
        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    processes.append(
                        {
                            "pid": proc.info["pid"],
                            "name": proc.info["name"],
                            "cpu_percent": proc.info["cpu_percent"],
                            "memory_percent": proc.info["memory_percent"],
                        }
                    )
                except Exception:
                    continue

            # Sort by memory usage
            processes.sort(key=lambda x: x["memory_percent"], reverse=True)
            return processes[:10]  # Top 10

        except Exception as e:
            logger.error(f"Failed to get processes: {e}")
            return []

    async def get_open_ports(self) -> list[dict]:
        """Get list of open network ports"""
        try:
            connections = psutil.net_connections()
            ports = []

            for conn in connections:
                if conn.laddr:
                    ports.append(
                        {
                            "ip": conn.laddr.ip,
                            "port": conn.laddr.port,
                            "status": conn.status,
                            "type": conn.type,
                        }
                    )

            return ports

        except Exception as e:
            logger.error(f"Failed to get open ports: {e}")
            return []

    async def open_application(self, app_name: str) -> bool:
        """Open an application (allowlist-validated)"""

        try:
            if SHELL_METACHARACTERS.search(app_name):
                return False
            if not app_name or len(app_name) > 100:
                return False
            if "/" in app_name or "\\" in app_name:
                return False
            executable = resolve_launch_target(app_name)
            if not executable:
                return False
            subprocess.Popen([executable])
            logger.info(f"Opening application: {app_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to open application: {e}")
            return False
