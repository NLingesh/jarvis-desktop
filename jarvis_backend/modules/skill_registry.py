import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class Skill:
    """Declarative skill metadata."""

    def __init__(
        self,
        name: str,
        intents: list[str],
        handler: Callable[[str, str | None], dict[str, Any]],
        description: str = "",
    ):
        self.name = name
        self.intents = [i.lower() for i in intents]
        self.handler = handler
        self.description = description


class SkillRegistry:
    """Registry for routing user utterances to skills.

    Skills are matched by intent keywords. Multiple skills can be
    orchestrated sequentially when the utterance contains multiple
    intent signals.
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def detect_intents(self, user_input: str) -> list[str]:
        """Return skill names whose intents match the user input."""
        lower = user_input.lower()
        matches = []
        for name, skill in self._skills.items():
            if any(i in lower for i in skill.intents):
                matches.append(name)
        return matches

    async def execute(self, user_input: str, session_id: str | None = None) -> dict[str, Any]:
        """Run matched skills sequentially and merge results.

        Returns a context dict with per-skill outputs.
        """
        intents = self.detect_intents(user_input)
        if not intents:
            return {}

        merged: dict[str, Any] = {}
        for name in intents:
            skill = self._skills.get(name)
            if not skill:
                continue
            try:
                if asyncio.iscoroutinefunction(skill.handler):
                    result = await skill.handler(user_input, session_id)
                else:
                    result = skill.handler(user_input, session_id)
                merged[name] = result
            except Exception as e:
                logger.error("Skill %s failed: %s", name, e)
                merged[name] = {"error": str(e)}
        return merged

    def list_skills(self) -> list[dict[str, str]]:
        return [
            {"name": s.name, "description": s.description, "intents": s.intents}
            for s in self._skills.values()
        ]
