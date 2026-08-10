from managers.memory_manager import MemoryManager

try:
    from .claude_api import ClaudeAPI
except ImportError:
    # Anthropic not installed - ok if using Mistral provider
    ClaudeAPI = None
from .calendar_module import CalendarModule
from .llm_provider import LLMProvider
from .mail_module import MailModule
from .notes_module import NotesModule
from .system_actions import SystemActions
from .tts import TextToSpeechModule
from .web_browse import WebBrowseModule

__all__ = [
    "MemoryManager",
    "ClaudeAPI",
    "CalendarModule",
    "MailModule",
    "NotesModule",
    "WebBrowseModule",
    "TextToSpeechModule",
    "SystemActions",
    "LLMProvider",
]
