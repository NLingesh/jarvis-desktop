"""Adaptive Intelligence Manager — behavior learning, predictions, and context-aware adaptation."""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AdaptiveIntelligenceManager:
    """Learns from user behavior to provide predictive suggestions and adaptive responses."""

    def __init__(self, memory_manager: Any, preference_manager: Any, context_manager: Any):
        self.memory = memory_manager
        self.preferences = preference_manager
        self.context = context_manager
        self._pattern_cache: dict[str, dict[str, Any]] = {}
        self._last_analysis: float = 0.0
        self._analysis_interval: float = 3600.0

    async def analyze_behavior(self, session_id: str | None = None) -> dict[str, Any]:
        """Analyze recent behavior to identify patterns."""
        now = time.time()
        if now - self._last_analysis < self._analysis_interval and self._pattern_cache:
            return self._pattern_cache

        patterns: dict[str, Any] = {
            "frequent_commands": [],
            "time_preferences": {},
            "tool_usage": {},
            "response_preferences": {},
            "suggested_actions": [],
        }

        try:
            command_patterns = await self.memory.get_patterns(pattern_type="command", limit=20)
            if command_patterns:
                patterns["frequent_commands"] = [
                    {"trigger": p["trigger"], "action": p["action"], "confidence": p["confidence"]}
                    for p in command_patterns[:5]
                ]

            time_patterns = await self.memory.get_patterns(pattern_type="time_based", limit=20)
            if time_patterns:
                hour_counts: Counter = Counter()
                for p in time_patterns:
                    try:
                        hour = datetime.fromisoformat(p["trigger"]).hour
                        hour_counts[str(hour)] += 1
                    except Exception:
                        continue
                patterns["time_preferences"] = dict(hour_counts.most_common(5))

            tool_patterns = await self.memory.get_patterns(pattern_type="tool_usage", limit=30)
            if tool_patterns:
                tool_counts: Counter = Counter(p["action"] for p in tool_patterns)
                patterns["tool_usage"] = dict(tool_counts.most_common(10))

            try:
                prefs = await self.preferences.get_preferences()
                if prefs:
                    patterns["response_preferences"] = {
                        k: v for k, v in prefs.items() if not k.startswith("inferred_")
                    }
            except Exception:
                pass

            patterns["suggested_actions"] = await self._generate_suggestions(patterns, session_id)

        except Exception as e:
            logger.error("Behavior analysis failed: %s", e)

        self._pattern_cache = patterns
        self._last_analysis = now
        return patterns

    async def _generate_suggestions(
        self, patterns: dict[str, Any], session_id: str | None
    ) -> list[str]:
        """Generate proactive suggestions based on patterns."""
        suggestions: list[str] = []

        try:
            hour = datetime.now().hour
            time_prefs = patterns.get("time_preferences", {})
            if time_prefs:
                top_hour = max(time_prefs.items(), key=lambda x: x[1])[0]
                if str(hour) == top_hour:
                    suggestions.append("You're often active now. Need help with your usual tasks?")

            frequent = patterns.get("frequent_commands", [])
            if frequent:
                suggestions.append(f"Would you like to run '{frequent[0]['action']}' again?")

            tool_usage = patterns.get("tool_usage", {})
            if "weather" in tool_usage and "calendar" in tool_usage:
                suggestions.append("Check today's weather and calendar?")
        except Exception as e:
            logger.error("Suggestion generation failed: %s", e)

        return suggestions[:3]

    async def learn_from_interaction(
        self, session_id: str, user_input: str, response: str, tool_used: str | None = None
    ) -> None:
        """Learn from a user interaction."""
        try:
            command_patterns = await self.memory.get_patterns(pattern_type="command", limit=1)
            exists = False
            for p in command_patterns:
                if p["trigger"] == user_input and p["action"] == (tool_used or response[:50]):
                    exists = True
                    break

            if not exists and (tool_used or len(user_input) > 3):
                await self.memory.record_pattern(
                    pattern_type="command",
                    trigger=user_input[:200],
                    action=(tool_used or response[:200]),
                    confidence=0.5,
                )

            if tool_used:
                await self.memory.record_pattern(
                    pattern_type="tool_usage",
                    trigger=datetime.now().isoformat(),
                    action=tool_used,
                    confidence=0.8,
                )

            if "morning" in user_input.lower() or "evening" in user_input.lower():
                await self.memory.record_pattern(
                    pattern_type="time_based",
                    trigger=datetime.now().isoformat(),
                    action=user_input[:100],
                    confidence=0.6,
                )

            self._pattern_cache = {}
        except Exception as e:
            logger.error("Learning from interaction failed: %s", e)

    async def record_feedback(
        self, session_id: str, prediction: str, actual: str, correct: bool
    ) -> dict:
        """Record feedback on a prediction."""
        try:
            return await self.memory.record_feedback(session_id, prediction, actual, correct)
        except Exception as e:
            logger.error("Recording feedback failed: %s", e)
            return {"error": str(e)}

    async def get_insights(self) -> dict[str, Any]:
        """Get adaptive intelligence insights."""
        try:
            patterns = await self.memory.get_patterns(limit=100)
            pattern_types = Counter(p["pattern_type"] for p in patterns)
            feedback_stats = await self.memory.get_feedback_stats(limit=200)

            return {
                "total_patterns": len(patterns),
                "pattern_types": dict(pattern_types.most_common(10)),
                "feedback_accuracy": feedback_stats.get("accuracy", 0.0),
                "top_patterns": [
                    {
                        "type": p["pattern_type"],
                        "trigger": p["trigger"],
                        "action": p["action"],
                        "confidence": p["confidence"],
                    }
                    for p in patterns[:10]
                ],
            }
        except Exception as e:
            logger.error("Getting insights failed: %s", e)
            return {"error": str(e)}

    async def get_suggestions(self, session_id: str | None = None) -> list[str]:
        """Get current suggestions."""
        patterns = await self.analyze_behavior(session_id)
        return patterns.get("suggested_actions", [])
