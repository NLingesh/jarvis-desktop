"""Task Manager — scheduled tasks, reminders, background jobs using APScheduler."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages scheduled tasks, reminders, and background jobs."""

    def __init__(
        self, memory_manager: Any, deliver: Callable[[str], Coroutine[Any, Any, None]] | None = None
    ):
        self.memory = memory_manager
        self.deliver = deliver
        self._scheduler: Any = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            self._scheduler = AsyncIOScheduler()
            self._scheduler.start()
            self._running = True
            logger.info("TaskManager started with APScheduler")
        except ImportError:
            logger.warning("APScheduler not installed; task scheduling disabled")

    async def stop(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("TaskManager stopped")

    async def create_task(
        self,
        title: str,
        type: str = "task",
        cron: str | None = None,
        due_date: str | None = None,
        payload: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new task, reminder, or job."""
        next_run = None
        if cron:
            try:
                from croniter import croniter

                now = datetime.now()
                cron_itr = croniter(cron, now)
                next_run = cron_itr.get_next(datetime).isoformat()
            except Exception as e:
                logger.warning("Invalid cron expression %s: %s", cron, e)

        task = await self.memory.create_task(
            title=title,
            status="pending",
            priority="medium",
            due_date=due_date,
            project_id=project_id,
        )
        if not task:
            return {"error": "Failed to create task"}

        conn = await self.memory._get_conn()
        await conn.execute(
            "UPDATE tasks SET type = ?, cron = ?, next_run = ?, payload = ? WHERE id = ?",
            (type, cron, next_run, json.dumps(payload or {}), task["id"]),
        )
        await conn.commit()

        if cron and self._scheduler:
            try:
                from apscheduler.triggers.cron import CronTrigger

                trigger = CronTrigger.from_crontab(cron)
                self._scheduler.add_job(
                    self._execute_task,
                    trigger=trigger,
                    id=task["id"],
                    args=[task["id"]],
                    replace_existing=True,
                )
            except Exception as e:
                logger.error("Failed to schedule task %s: %s", task["id"], e)

        return task

    async def _execute_task(self, task_id: str) -> None:
        """Execute a scheduled task."""
        conn = await self.memory._get_conn()
        cursor = await conn.execute(
            "SELECT title, payload, type FROM tasks WHERE id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return

        title, payload_str, task_type = row

        try:
            if self.deliver:
                await self.deliver(f"Reminder: {title}")
            logger.info("Executed task %s: %s", task_id, title)
            await self.memory.update_task(task_id, status="completed")
        except Exception as e:
            logger.error("Task %s failed: %s", task_id, e)
            await self.memory.update_task(task_id, status="failed")

    async def list_tasks(self, type: str | None = None, status: str | None = None) -> list[dict]:
        """List tasks with optional filters."""
        tasks = await self.memory.list_tasks()
        result = []
        for task in tasks:
            if type and task.get("type") != type:
                continue
            if status and task.get("status") != status:
                continue
            result.append(task)
        return result

    async def complete_task(self, task_id: str) -> dict | None:
        """Mark a task as completed."""
        return await self.memory.update_task(task_id, status="completed")

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        if self._scheduler:
            with contextlib.suppress(Exception):
                self._scheduler.remove_job(task_id)
        return await self.memory.delete_task(task_id)
