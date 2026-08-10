"""Proactive reminders: upcoming events, unread email, system health, and smart nudges."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DeliverFn = Callable[[str], Awaitable[None]]


class ProactiveMonitor:
    """Periodic proactive monitor with smarter triggers and timing.

    Checks:
    - Calendar events within lookahead window
    - Unread email
    - System health (CPU, memory, disk)
    - Battery status
    - Time-aware greetings

    Delivers spoken summaries via the configured callback.
    """

    def __init__(
        self,
        calendar,
        mail_sessions,
        system_actions=None,
        memory_manager=None,
        deliver: DeliverFn | None = None,
        interval_seconds: int = 300,
        lookahead_minutes: int = 30,
    ) -> None:
        self._calendar = calendar
        self._mail_sessions = mail_sessions
        self._system_actions = system_actions
        self._memory_manager = memory_manager
        self._deliver = deliver
        self.interval_seconds = interval_seconds
        self.lookahead_minutes = lookahead_minutes
        self._reported_events: set[str] = set()
        self._reported_unread: set[str] = set()
        self._reported_system: set[str] = set()
        self._last_battery_pct: float | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            logger.info("Proactive monitor started (every %ss)", self.interval_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                text = await self.check_once()
                if text and self._deliver is not None:
                    await self._deliver(text)
            except Exception as e:
                logger.error("Proactive check failed: %s", e)
            await asyncio.sleep(self.interval_seconds)

    async def check_once(self) -> str | None:
        """Run one check; return spoken summary or None."""
        now = datetime.now()
        parts: list[str] = []

        # Calendar events
        try:
            events = await self._calendar.get_upcoming_events(days_ahead=1)
        except Exception as e:
            logger.warning("Proactive calendar fetch failed: %s", e)
            events = []

        horizon = now + timedelta(minutes=self.lookahead_minutes)
        fresh_events = []
        for ev in events:
            start = ev.get("start")
            if not start:
                continue
            try:
                start_dt = datetime.fromisoformat(start)
            except ValueError:
                continue
            if start_dt.tzinfo is not None:
                start_dt = start_dt.replace(tzinfo=None)
            if now <= start_dt <= horizon:
                key = f"{ev.get('title')}|{start}"
                if key not in self._reported_events:
                    self._reported_events.add(key)
                    fresh_events.append(ev)

        for ev in fresh_events:
            try:
                minutes = int((datetime.fromisoformat(ev["start"]) - now).total_seconds() // 60)
            except (KeyError, ValueError):
                minutes = 0
            when = "now" if minutes <= 1 else f"in about {minutes} minutes"
            parts.append(f"{ev.get('title')} starts {when}.")

        # Unread email
        try:
            session = await self._mail_sessions.most_recent()
            unread = await session.get_unread_emails(limit=10) if session is not None else []
        except Exception as e:
            logger.warning("Proactive mail fetch failed: %s", e)
            unread = []

        fresh_unread = [m for m in unread if m.get("id") not in self._reported_unread]
        for m in fresh_unread:
            self._reported_unread.add(m.get("id"))
        if fresh_unread:
            label = "email" if len(fresh_unread) == 1 else "emails"
            parts.append(f"You have {len(fresh_unread)} unread {label}.")

        if not parts:
            return None

        # System health (only when there are already findings, to avoid noise)
        try:
            if self._system_actions is not None:
                sys_info = await self._system_actions.get_system_info()
                cpu_pct = sys_info.get("cpu", {}).get("percent", 0)
                mem_pct = sys_info.get("memory", {}).get("percent", 0)
                disk_pct = sys_info.get("disk", {}).get("percent", 0)

                if cpu_pct > 90:
                    key = f"cpu_high_{int(cpu_pct)}"
                    if key not in self._reported_system:
                        self._reported_system.add(key)
                        parts.append(f"CPU usage is high at {int(cpu_pct)} percent.")
                if mem_pct > 90:
                    key = f"mem_high_{int(mem_pct)}"
                    if key not in self._reported_system:
                        self._reported_system.add(key)
                        parts.append(f"Memory usage is high at {int(mem_pct)} percent.")
                if disk_pct > 95:
                    key = f"disk_high_{int(disk_pct)}"
                    if key not in self._reported_system:
                        self._reported_system.add(key)
                        parts.append(
                            f"Disk space is critically low at {int(disk_pct)} percent full."
                        )
        except Exception:
            pass

        # Battery (only when there are already findings)
        if parts:
            try:
                import psutil

                battery = psutil.sensors_battery()
                if battery:
                    pct = battery.percent
                    if self._last_battery_pct is None or abs(pct - self._last_battery_pct) > 5:
                        self._last_battery_pct = pct
                        if pct <= 10 and not battery.power_plugged:
                            parts.append(f"Battery is at {int(pct)} percent and not charging.")
                        elif pct >= 95 and battery.power_plugged:
                            parts.append("Battery is fully charged.")
            except Exception:
                pass

        # Time-aware greeting (only when there are already findings)
        if parts:
            try:
                hour = now.hour
                greeting_key = f"greeting_{now.strftime('%Y-%m-%d')}"
                if greeting_key not in self._reported_system:
                    self._reported_system.add(greeting_key)
                    if 5 <= hour < 12:
                        parts.append("Good morning.")
                    elif 12 <= hour < 17:
                        parts.append("Good afternoon.")
                    elif 17 <= hour < 22:
                        parts.append("Good evening.")
                    else:
                        parts.append("Working late?")
            except Exception:
                pass

        if not parts:
            return None
        return " ".join(parts)
