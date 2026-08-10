"""Proactive AI Manager — AI-powered proactive suggestions and smart notifications."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ProactiveAIManager:
    """Generates AI-powered proactive suggestions based on context, patterns, and calendar."""

    def __init__(self, llm_provider: Any, memory_manager: Any, adaptive_intelligence: Any):
        self.llm = llm_provider
        self.memory = memory_manager
        self.adaptive = adaptive_intelligence
        self._suggestion_cache: list[dict[str, Any]] = []
        self._last_generation: float = 0.0
        self._cache_ttl: float = 1800.0

    async def generate_suggestions(
        self, context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Generate proactive suggestions based on current context."""
        now = datetime.now()
        if self._suggestion_cache and (now.timestamp() - self._last_generation) < self._cache_ttl:
            return self._suggestion_cache

        suggestions: list[dict[str, Any]] = []

        try:
            time_of_day = self._get_time_of_day()
            suggestions.extend(self._time_based_suggestions(time_of_day))

            try:
                behavior = await self.adaptive.analyze_behavior()
                if behavior.get("suggested_actions"):
                    for action in behavior["suggested_actions"][:3]:
                        suggestions.append(
                            {
                                "id": f"behavior_{datetime.now().timestamp()}",
                                "type": "behavior",
                                "text": action,
                                "priority": "medium",
                                "action": action,
                            }
                        )
            except Exception:
                pass

            if context:
                suggestions.extend(self._context_suggestions(context))

            suggestions = self._prioritize_and_deduplicate(suggestions)[:5]
            self._suggestion_cache = suggestions
            self._last_generation = now.timestamp()

        except Exception as e:
            logger.error("Failed to generate suggestions: %s", e)

        return suggestions

    def _get_time_of_day(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 22:
            return "evening"
        return "night"

    def _time_based_suggestions(self, time_of_day: str) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        hour = datetime.now().hour

        if time_of_day == "morning":
            suggestions.append(
                {
                    "id": f"morning_{hour}",
                    "type": "routine",
                    "text": "Good morning! Would you like to check your calendar and emails?",
                    "priority": "low",
                    "action": "check_calendar_and_email",
                }
            )
        elif time_of_day == "afternoon":
            suggestions.append(
                {
                    "id": f"afternoon_{hour}",
                    "type": "productivity",
                    "text": "Afternoon check-in. Need help with any tasks?",
                    "priority": "low",
                    "action": "productivity_check",
                }
            )
        elif time_of_day == "evening":
            suggestions.append(
                {
                    "id": f"evening_{hour}",
                    "type": "summary",
                    "text": "Evening summary. Would you like a recap of today's activity?",
                    "priority": "low",
                    "action": "daily_summary",
                }
            )

        return suggestions

    def _context_suggestions(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []

        if context.get("calendar_events"):
            suggestions.append(
                {
                    "id": "calendar_context",
                    "type": "calendar",
                    "text": f"You have {len(context['calendar_events'])} upcoming events. Want me to prepare?",
                    "priority": "medium",
                    "action": "prepare_for_events",
                }
            )

        if context.get("unread_emails", 0) > 0:
            suggestions.append(
                {
                    "id": "email_context",
                    "type": "email",
                    "text": f"You have {context['unread_emails']} unread emails. Want to triage them?",
                    "priority": "medium",
                    "action": "triage_emails",
                }
            )

        if context.get("cpu_percent", 0) > 85:
            suggestions.append(
                {
                    "id": "system_context",
                    "type": "system",
                    "text": "CPU usage is high. Want me to close unused applications?",
                    "priority": "high",
                    "action": "optimize_system",
                }
            )

        return suggestions

    def _prioritize_and_deduplicate(
        self, suggestions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seen = set()
        unique = []
        priority_order = {"high": 0, "medium": 1, "low": 2}

        for s in sorted(suggestions, key=lambda x: priority_order.get(x.get("priority", "low"), 3)):
            key = s.get("text", "")[:50]
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return unique

    async def generate_notification(
        self, title: str, body: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Generate a smart notification."""
        notification: dict[str, Any] = {
            "id": f"notif_{datetime.now().timestamp()}",
            "title": title,
            "body": body,
            "timestamp": datetime.now().isoformat(),
            "priority": "medium",
            "actions": ["dismiss", "action"],
        }

        try:
            hour = datetime.now().hour
            if hour >= 23 or hour < 7:
                notification["priority"] = "low"
                notification["silent"] = True

            if context and context.get("urgent"):
                notification["priority"] = "high"
                notification["actions"] = ["dismiss", "action", "snooze"]
        except Exception:
            pass

        return notification

    async def record_suggestion_feedback(self, suggestion_id: str, user_action: str) -> None:
        """Record user feedback on a suggestion."""
        try:
            await self.memory.record_feedback(
                session_id="proactive",
                prediction=suggestion_id,
                actual=user_action,
                correct=user_action != "dismiss",
            )
            self._suggestion_cache = []
        except Exception as e:
            logger.error("Failed to record suggestion feedback: %s", e)
