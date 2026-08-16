import logging
import os

import psutil

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _read_first(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.readline().strip()
    except Exception:
        return None


def _amd_gpu_info() -> dict:
    info = {"vendor": "amd", "cards": []}
    drm = "/sys/class/drm"
    try:
        if os.path.isdir(drm):
            for entry in sorted(os.listdir(drm)):
                if not entry.startswith("card"):
                    continue
                base = os.path.join(drm, entry)
                vendor = _read_first(os.path.join(base, "device", "vendor"))
                if not vendor or not ("amd" in vendor.lower() or vendor.lower() in ("0x1002", "1002")):
                    continue
                card = {"path": entry}
                name = _read_first(os.path.join(base, "device", "product_name"))
                if name:
                    card["name"] = name
                gpu_clock = _read_first(os.path.join(base, "device", "gt_busy_percent"))
                if gpu_clock is None:
                    gpu_clock = _read_first(os.path.join(base, "gpu_busy_percent"))
                if gpu_clock is not None:
                    card["usage_percent"] = gpu_clock
                mem_info = _read_first(os.path.join(base, "device", "mem_info_vram_total"))
                if mem_info:
                    card["memory_total"] = mem_info
                vram_used = _read_first(os.path.join(base, "device", "mem_info_vram_used"))
                if vram_used:
                    card["memory_used"] = vram_used
                info["cards"].append(card)
    except Exception:
        pass
    return info if info["cards"] else {}


def _intel_gpu_info() -> dict:
    info = {"vendor": "intel", "cards": []}
    drm = "/sys/class/drm"
    try:
        if os.path.isdir(drm):
            for entry in sorted(os.listdir(drm)):
                if not entry.startswith("card"):
                    continue
                base = os.path.join(drm, entry)
                vendor = _read_first(os.path.join(base, "device", "vendor"))
                if not vendor or "intel" not in vendor.lower():
                    continue
                card = {"path": entry}
                name = _read_first(os.path.join(base, "device", "product_name"))
                if name:
                    card["name"] = name
                gpu_clock = _read_first(os.path.join(base, "gt_busy_percent"))
                if gpu_clock is not None:
                    card["usage_percent"] = gpu_clock
                mem_info = _read_first(os.path.join(base, "device", "mem_info_vram_total"))
                if mem_info:
                    card["memory_total"] = mem_info
                vram_used = _read_first(os.path.join(base, "device", "mem_info_vram_used"))
                if vram_used:
                    card["memory_used"] = vram_used
                info["cards"].append(card)
    except Exception:
        pass
    return info if info["cards"] else {}


def _hwmon_temp() -> dict:
    data = {"cpu_temp_c": "not available", "gpu_temp_c": "not available", "sources": []}
    base = "/sys/class/hwmon"
    try:
        if os.path.isdir(base):
            for hw in sorted(os.listdir(base)):
                hw_path = os.path.join(base, hw)
                name = _read_first(os.path.join(hw_path, "name")) or ""
                label_prefix = os.path.join(hw_path, "label")
                temp_input = os.path.join(hw_path, "temp1_input")
                if not os.path.exists(temp_input):
                    continue
                try:
                    with open(temp_input, encoding="utf-8", errors="ignore") as f:
                        raw = f.readline().strip()
                    temp_c = round(int(raw) / 1000, 1) if raw.isdigit() else "not available"
                except Exception:
                    temp_c = "not available"
                label = ""
                if os.path.exists(label_prefix + "1"):
                    label = _read_first(label_prefix + "1") or ""
                elif os.path.exists(label_prefix + "0"):
                    label = _read_first(label_prefix + "0") or ""
                if not label:
                    label = name
                source = {"hwmon": hw, "name": name, "label": label, "temp_c": temp_c}
                data["sources"].append(source)
                label_lower = label.lower()
                if ("cpu" in label_lower or "package" in label_lower or "core" in label_lower or "k10temp" in name.lower()) and data["cpu_temp_c"] == "not available":
                    data["cpu_temp_c"] = temp_c
                if ("gpu" in label_lower or "radeon" in label_lower or "amdgpu" in label_lower or "amdgpu" in name.lower()) and data["gpu_temp_c"] == "not available":
                    data["gpu_temp_c"] = temp_c
    except Exception:
        pass
    return data


class SystemInfoTool(BaseTool):
    risk_level = "read_only"
    capability = "system"
    name = "system_info"
    description = "Get CPU, RAM, disk, uptime, GPU, temperature, and process information"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional focus: cpu, memory, ram, disk, storage, uptime, gpu, temperature, temp, processes, process, system info, system status, how much ram, how much cpu, how much memory, what's using the most ram, what's using the most cpu, is my gpu, what gpu, laptop temperature, temperature"},
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
            if not query or query in ("disk", "storage"):
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
            if not query or any(k in query for k in ["gpu", "temperature", "temp", "how much gpu", "is my gpu", "what gpu"]):
                amd = _amd_gpu_info()
                intel = _intel_gpu_info()
                gpu = amd or intel or {"vendor": "unknown", "cards": [], "note": "not available"}
                data["gpu"] = gpu
                temps = _hwmon_temp()
                data["temperature"] = temps
            return ToolResult(True, data=data)
        except Exception as exc:
            return ToolResult(False, error=str(exc))


class RunningProcessesTool(BaseTool):
    risk_level = "read_only"
    capability = "system"
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
