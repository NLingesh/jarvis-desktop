from .memory import MemoryManager
try:
    from .claude_api import ClaudeAPI
except ImportError:
    # Anthropic not installed - ok if using Mistral provider
    ClaudeAPI = None
from .calendar_module import CalendarModule
from .mail_module import MailModule
from .notes_module import NotesModule
from .web_browse import WebBrowseModule
from .tts import TextToSpeechModule
from .system_actions import SystemActions
from .llm_provider import LLMProvider

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
