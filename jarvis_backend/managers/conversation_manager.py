"""Memory Manager — unified interface for conversation, project, task, and knowledge memory.

This manager wraps the existing MemoryManager and adds:
- Conversation summaries
- Topic extraction
- Preference learning
- Vector DB adapter interface (future-ready)
"""

import json
import logging
from typing import Any

from managers.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation memory with auto-summarization."""

    def __init__(self, memory_manager: MemoryManager, llm_provider: Any):
        self.memory = memory_manager
        self.llm = llm_provider

    async def summarize_session(self, session_id: str) -> str | None:
        """Generate a summary of a conversation session."""
        messages = await self.memory.get_conversation(session_id, limit=50)
        if not messages:
            return None

        try:
            conversation_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
            )
            summary = await self.llm.get_response(
                f"Summarize this conversation in 2-3 sentences:\n{conversation_text}",
                [],
                {"task": "summarize"},
            )
            return summary
        except Exception as e:
            logger.error("Failed to summarize session %s: %s", session_id, e)
            return None

    async def extract_topics(self, session_id: str) -> list[str]:
        """Extract main topics from a conversation session."""
        messages = await self.memory.get_conversation(session_id, limit=50)
        if not messages:
            return []

        try:
            conversation_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages[-10:]
            )
            response = await self.llm.get_response(
                f"Extract 3-5 main topics from this conversation as a comma-separated list:\n{conversation_text}",
                [],
                {"task": "extract_topics"},
            )
            topics = [t.strip() for t in response.split(",") if t.strip()]
            return topics[:5]
        except Exception as e:
            logger.error("Failed to extract topics from session %s: %s", session_id, e)
            return []

    async def get_recent_summaries(self, limit: int = 10) -> list[dict]:
        """Get recent conversation summaries."""
        conn = await self.memory._get_conn()
        cursor = await conn.execute(
            "SELECT id, session_id, role, content, timestamp, metadata FROM conversations "
            "WHERE role = 'summary' ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "role": r[2],
                "content": r[3],
                "timestamp": r[4],
                "metadata": json.loads(r[5]) if r[5] else {},
            }
            for r in rows
        ]


class PreferenceManager:
    """Learns user preferences from interactions."""

    def __init__(self, memory_manager: MemoryManager, llm_provider: Any):
        self.memory = memory_manager
        self.llm = llm_provider

    async def infer_preferences(self, session_id: str) -> dict[str, Any]:
        """Infer user preferences from recent conversation."""
        messages = await self.memory.get_conversation(session_id, limit=30)
        if not messages:
            return {}

        try:
            conversation_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
            )
            response = await self.llm.get_response(
                "Analyze this conversation and extract user preferences as JSON: "
                "response_length (brief/detailed), communication_style (formal/casual), "
                "working_hours, preferred_tools, interests, etc.\n"
                f"Conversation:\n{conversation_text}",
                [],
                {"task": "infer_preferences"},
            )
            try:
                prefs = json.loads(response)
                for key, value in prefs.items():
                    await self.memory.set_preference(f"inferred_{key}", value)
                return prefs
            except json.JSONDecodeError:
                return {}
        except Exception as e:
            logger.error("Failed to infer preferences: %s", e)
            return {}

    async def get_preferences(self) -> dict[str, Any]:
        """Get all stored preferences."""
        return await self.memory.list_preferences()

    async def set_preference(self, key: str, value: Any) -> None:
        """Set a user preference."""
        await self.memory.set_preference(key, value)


class ContextManager:
    """Builds rich context for the LLM from memory, calendar, email, system state."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        conversation_manager: ConversationManager,
        calendar: Any,
        mail: Any,
        system_actions: Any,
    ):
        self.memory = memory_manager
        self.conversation = conversation_manager
        self.calendar = calendar
        self.mail = mail
        self.system_actions = system_actions

    async def build_context(self, session_id: str | None = None, query: str = "") -> dict[str, Any]:
        """Build comprehensive context for LLM."""
        context: dict[str, Any] = {}

        try:
            if session_id:
                recent = await self.memory.get_conversation(session_id, limit=5)
                if recent:
                    context["recent_conversation"] = recent

            memory_results = await self.memory.search_memory(query, session_id=session_id)
            if memory_results:
                context["memory_results"] = memory_results[:5]

            try:
                events = await self.calendar.get_upcoming_events(days_ahead=1)
                if events:
                    context["calendar"] = events[:3]
            except Exception:
                pass

            try:
                system_info = await self.system_actions.get_system_info()
                if system_info:
                    context["system"] = system_info
            except Exception:
                pass

        except Exception as e:
            logger.error("Failed to build context: %s", e)

        return context
