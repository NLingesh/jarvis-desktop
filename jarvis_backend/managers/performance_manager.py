"""Performance Manager — metrics, health tracking, and resource monitoring."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PerformanceManager:
    """Tracks performance metrics and system health."""

    def __init__(self):
        self._request_times: deque[float] = deque(maxlen=200)
        self._slow_requests: deque[dict[str, Any]] = deque(maxlen=50)
        self._error_counts: dict[str, int] = {}
        self._manager_health: dict[str, dict[str, Any]] = {}
        self._start_time = time.time()
        self._last_cleanup = time.time()

    def record_request(self, path: str, duration_ms: float, status: int) -> None:
        self._request_times.append(time.time())
        if duration_ms > 1000:
            self._slow_requests.append(
                {
                    "path": path,
                    "duration_ms": duration_ms,
                    "status": status,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        if status >= 500:
            self._error_counts[path] = self._error_counts.get(path, 0) + 1

    def update_manager_health(self, name: str, health: dict[str, Any]) -> None:
        self._manager_health[name] = {
            **health,
            "last_check": datetime.now().isoformat(),
        }

    def get_metrics(self) -> dict[str, Any]:
        now = time.time()
        window = 60.0
        recent = [t for t in self._request_times if now - t < window]
        throughput = len(recent) / window if window > 0 else 0

        latencies = []
        for i in range(1, len(self._request_times)):
            latencies.append(self._request_times[i] - self._request_times[i - 1])
        avg_latency = (sum(latencies) / len(latencies) * 1000) if latencies else 0

        return {
            "uptime_seconds": now - self._start_time,
            "requests_per_minute": round(throughput * 60, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "slow_requests": list(self._slow_requests)[-10:],
            "error_counts": dict(self._error_counts),
            "manager_health": self._manager_health,
            "timestamp": datetime.now().isoformat(),
        }

    def get_system_health(self) -> dict[str, Any]:
        health: dict[str, Any] = {
            "status": "healthy",
            "checks": {},
        }
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(str(Path.home()))
            health["checks"] = {
                "cpu_percent": cpu,
                "memory_percent": mem.percent,
                "disk_percent": disk.percent,
                "memory_available_mb": round(mem.available / 1024 / 1024, 1),
            }
            if cpu > 90 or mem.percent > 90 or disk.percent > 95:
                health["status"] = "degraded"
        except Exception:
            health["checks"] = {"error": "psutil not available"}
        return health

    async def cleanup(self) -> None:
        now = time.time()
        if now - self._last_cleanup > 3600:
            self._error_counts.clear()
            self._last_cleanup = now
