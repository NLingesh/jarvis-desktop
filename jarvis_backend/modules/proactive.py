"""Proactive reminders: upcoming events and unread email spoken over the socket."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DeliverFn = Callable[[str], Awaitable[None]]


class ProactiveMonitor:
    """Periodically check for upcoming events and unread email.

    When something new is found, ``check_once`` returns a short spoken summary
    and the configured ``deliver`` callback is invoked with that text so the
    caller can speak it over connected sockets.
    """

    def __init__(
        self,
        calendar,
        mail_sessions,
        deliver: DeliverFn | None = None,
        interval_seconds: int = 300,
        lookahead_minutes: int = 30,
    ) -> None:
        self._calendar = calendar
        self._mail_sessions = mail_sessions
        self._deliver = deliver
        self.interval_seconds = interval_seconds
        self.lookahead_minutes = lookahead_minutes
        self._reported_events: set[str] = set()
        self._reported_unread: set[str] = set()
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
        """Run one check; return the spoken summary or None if nothing new."""
        now = datetime.now()
        horizon = now + timedelta(minutes=self.lookahead_minutes)
        parts: list[str] = []

        try:
            events = await self._calendar.get_upcoming_events(days_ahead=1)
        except Exception as e:
            logger.warning("Proactive calendar fetch failed: %s", e)
            events = []

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
        return " ".join(parts)
