import logging

import psutil

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class SystemInfoTool(BaseTool):
    name = "system_info"
    description = "Get CPU, RAM, disk, uptime, and process information"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional focus: cpu, memory, disk, processes, uptime"},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        query = (arguments.get("query") or "").lower()
        data: dict = {}
        try:
            if not query or query in ("cpu", "processor"):
                data["cpu"] = {
                    "count": psutil.cpu_count(),
                    "percent": psutil.cpu_percent(interval=1),
                    "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
                }
            if not query or query in ("memory", "ram"):
                mem = psutil.virtual_memory()
                data["memory"] = {
                    "total": mem.total,
                    "available": mem.available,
                    "percent": mem.percent,
                    "used": mem.used,
                    "free": mem.free,
                }
            if not query or query in ("disk",):
                disk = psutil.disk_usage("/")
                data["disk"] = {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent,
                }
            if not query or query in ("uptime",):
                with open("/proc/uptime") as f:
                    data["uptime_seconds"] = float(f.readline().split()[0])
            if not query or query in ("processes", "process"):
                procs = []
                for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                    try:
                        procs.append(proc.info)
                    except Exception:
                        continue
                procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)
                data["processes"] = procs[:15]
            return ToolResult(True, data=data)
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class RunningProcessesTool(BaseTool):
    name = "running_processes"
    description = "List top running processes by memory usage"
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Number of processes to return", "default": 10},
        },
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        limit = int(arguments.get("limit", 10))
        try:
            procs = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    procs.append(proc.info)
                except Exception:
                    continue
            procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)
            return ToolResult(True, data={"processes": procs[:limit]})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
