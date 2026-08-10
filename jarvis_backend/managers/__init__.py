"""JARVIS managers package.

Each manager owns one concern and exposes a clean interface to routes and
the frontend. Managers are instantiated as singletons in routes/state.py.
"""

from managers.conversation_manager import ContextManager, ConversationManager, PreferenceManager
from managers.memory_manager import MemoryManager

__all__ = [
    "MemoryManager",
    "ConversationManager",
    "PreferenceManager",
    "ContextManager",
]
