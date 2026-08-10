"""Workflow Manager — rule-based automation (if/then logic)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Manages rule-based workflows: if/then/else automation."""

    def __init__(
        self, memory_manager: Any, deliver: Callable[[str], Coroutine[Any, Any, None]] | None = None
    ):
        self.memory = memory_manager
        self.deliver = deliver
        self._workflows: dict[str, dict[str, Any]] = {}

    async def create_workflow(
        self,
        name: str,
        trigger: dict[str, Any],
        actions: list[dict[str, Any]],
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new workflow."""
        workflow_id = f"wf_{name.lower().replace(' ', '_')}"
        workflow = {
            "id": workflow_id,
            "name": name,
            "trigger": trigger,
            "actions": actions,
            "enabled": enabled,
            "created_at": datetime.now().isoformat(),
        }
        self._workflows[workflow_id] = workflow
        logger.info("Created workflow: %s", workflow_id)
        return workflow

    async def execute_workflow(
        self, workflow_id: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a workflow by ID."""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return {"error": f"Workflow {workflow_id} not found"}

        if not workflow.get("enabled"):
            return {"error": f"Workflow {workflow_id} is disabled"}

        trigger = workflow.get("trigger", {})
        actions = workflow.get("actions", [])
        context = context or {}

        if not self._evaluate_condition(trigger, context):
            return {"skipped": True, "reason": "Trigger condition not met"}

        results = []
        for action in actions:
            try:
                result = await self._execute_action(action, context)
                results.append(result)
            except Exception as e:
                logger.error("Workflow %s action failed: %s", workflow_id, e)
                results.append({"error": str(e)})

        return {"workflow_id": workflow_id, "executed": len(results), "results": results}

    def _evaluate_condition(self, trigger: dict[str, Any], context: dict[str, Any]) -> bool:
        """Evaluate a simple trigger condition."""
        condition = trigger.get("condition")
        if not condition:
            return True

        if condition == "always":
            return True

        key = condition.get("key")
        operator = condition.get("operator")
        value = condition.get("value")

        if not key or operator is None or value is None:
            return False

        context_value = context.get(key)
        if operator == "eq":
            return context_value == value
        elif operator == "neq":
            return context_value != value
        elif operator == "gt":
            try:
                return float(context_value) > float(value)
            except (TypeError, ValueError):
                return False
        elif operator == "lt":
            try:
                return float(context_value) < float(value)
            except (TypeError, ValueError):
                return False
        elif operator == "contains":
            return value in str(context_value)
        elif operator == "not_contains":
            return value not in str(context_value)
        return False

    async def _execute_action(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a single workflow action."""
        action_type = action.get("type")
        if action_type == "notify":
            message = action.get("message", "")
            if self.deliver:
                await self.deliver(message)
            return {"type": "notify", "message": message}
        elif action_type == "log":
            logger.info("Workflow log: %s", action.get("message", ""))
            return {"type": "log", "message": action.get("message")}
        elif action_type == "set_variable":
            key = action.get("key")
            value = action.get("value")
            context[key] = value
            return {"type": "set_variable", "key": key, "value": value}
        elif action_type == "delay":
            import asyncio

            seconds = action.get("seconds", 1)
            await asyncio.sleep(min(float(seconds), 60))
            return {"type": "delay", "seconds": seconds}
        else:
            return {"error": f"Unknown action type: {action_type}"}

    def list_workflows(self) -> list[dict[str, Any]]:
        """List all registered workflows."""
        return list(self._workflows.values())

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            logger.info("Deleted workflow: %s", workflow_id)
            return True
        return False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None
