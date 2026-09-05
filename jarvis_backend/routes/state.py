"""Shared singleton instances used across route modules and main.py.

Creating the module-level singletons here avoids each route file
instantiating its own copy of MemoryManager, LLMProvider, etc.
"""

import base64
import contextlib
import logging
import os
import re
import secrets
import time
import uuid
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from managers.adaptive_intelligence import AdaptiveIntelligenceManager
from managers.audio_manager import AudioManager
from managers.code_manager import CodeManager
from managers.conversation_manager import ContextManager, ConversationManager, PreferenceManager
from managers.git_manager import GitManager
from managers.memory_manager import MemoryManager
from managers.model_manager import ModelManager
from managers.performance_manager import PerformanceManager
from managers.proactive_ai import ProactiveAIManager
from managers.project_manager import ProjectManager
from managers.security_manager import SecurityManager
from managers.stt_manager import STTManager
from managers.system_manager import SystemManager
from managers.task_manager import TaskManager
from managers.tts_manager import TTSManager
from managers.vision_manager import VisionManager
from managers.voice_manager import VoiceManager
from managers.workflow_manager import WorkflowManager
from modules.auth import AuthService
from modules.calendar_module import CalendarModule
from modules.capability import CapabilityPolicy
from modules.documents_module import DocumentsModule
from modules.llm_provider import LLMProvider
from modules.mail_module import MailModule, MailSessionStore
from modules.memory_safety import is_sensitive_memory  # noqa: F401 (re-exported for tools)
from modules.notes_module import NotesModule
from modules.orchestrator import Orchestrator, strip_markdown_for_speech
from modules.session_context import SessionContextStore
from modules.settings import (  # noqa: F401  (re-exported for routes.deps / tests)
    KEY_NAMES,
    _mask_secret,
    _write_env_keys,
)
from modules.skill_registry import Skill, SkillRegistry
from modules.stt import SpeechToTextModule
from modules.system_actions import ALLOWED_COMMANDS, SystemActions
from modules.vault.manager import VaultManager
from modules.vision_module import VisionModule
from modules.web_browse import WebBrowseModule
from plugins.permissions import PermissionManager
from plugins.registry import PluginRegistry
from tools import ToolRegistry
from tools.app_tools import ControlAppWindowTool, LaunchApplicationTool, OpenTerminalTool
from tools.desktop_tools import (
    CloseAppTool,
    ListRunningApplicationsTool,
    OpenUrlTool,
    ResolveKnownLocationTool,
    ScreenshotTool,
)
from tools.document_tools import ReadDocumentTool
from tools.file_tools import (
    CopyFileTool,
    CreateFileTool,
    CreateFolderTool,
    DeleteFileTool,
    FileSearchTool,
    FindByExtensionTool,
    FindRecentFilesTool,
    IdentifyFileTypeTool,
    ListDirectoryTool,
    MoveFileTool,
    OpenFileTool,
    OpenFolderTool,
    ReadFileTool,
)
from tools.memory_tools import (
    ClearAllMemoriesTool,
    ForgetMemoryTool,
    GetCurrentContextTool,
    RecallMemoryTool,
    RememberMemoryTool,
    UpdateMemoryTool,
)
from tools.shell_tools import ExecuteShellTool
from tools.system_tools import RunningProcessesTool, SystemInfoTool
from tools.web_tools import WebSearchTool

logger = logging.getLogger("jarvis")


def configure_logging() -> str:
    env_path = os.getenv("ENV_PATH")
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    log_path = os.getenv("LOG_PATH")
    if not log_path:
        db_path = os.getenv("DATABASE_PATH")
        if db_path:
            log_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "jarvis.log")
        elif env_path:
            log_path = os.path.join(os.path.dirname(os.path.abspath(env_path)), "jarvis.log")
        else:
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis.log")

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            RotatingFileHandler(
                log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            ),
            logging.StreamHandler(),
        ],
    )
    logger.info("Logging to %s (rotating, 5MB x 3 backups)", log_path)
    return log_path


# Load .env and configure logging before any singletons are created
LOG_PATH = configure_logging()

# --- Session token ----------------------------------------------------------
SESSION_TOKEN_PATH = os.getenv("SESSION_TOKEN_PATH")
SESSION_TOKEN = os.getenv("SESSION_TOKEN")
if not SESSION_TOKEN:
    SESSION_TOKEN = secrets.token_hex(32)

if SESSION_TOKEN_PATH:
    try:
        os.makedirs(os.path.dirname(SESSION_TOKEN_PATH), exist_ok=True)
        with open(SESSION_TOKEN_PATH, "w") as f:
            f.write(SESSION_TOKEN)
        os.chmod(SESSION_TOKEN_PATH, 0o600)
    except Exception as e:
        logger.warning("Failed to write session token file: %s", e)

# --- Environment file path for settings persistence -------------------------
ENV_FILE_PATH = (
    os.path.abspath(os.getenv("ENV_PATH"))
    if os.getenv("ENV_PATH")
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
)

# --- Pending document confirmations -----------------------------------------
pending_documents_actions: dict[str, Callable] = {}

# --- Pending tool confirmations ---------------------------------------------
pending_tool_confirmations: dict[str, dict] = {}

# --- Security helpers (command allowlist, session-token checks) -------------
# Single allowlist lives in modules.system_actions; re-exported here for
# backward compatibility with routes.deps and openapi.py.
ALLOWED_SYSTEM_COMMANDS = ALLOWED_COMMANDS


def require_session_token(request) -> None:
    """Reject the request if a session token is expected but missing/invalid."""
    if not SESSION_TOKEN_PATH:
        return
    token = request.headers.get("X-Jarvis-Token", "")
    if not token or token != SESSION_TOKEN:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid or missing session token")


# Origins the local dev tooling may use to fetch the dev session token.
DEV_WEB_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


def _is_loopback_host(host: str) -> bool:
    hostname = host.rsplit(":", 1)[0].strip("[]").lower()
    return hostname in ("localhost", "127.0.0.1", "::1", "")


def session_token_available(request) -> bool:
    """Whether the dev-only /api/session-token endpoint may serve the token.

    Fails closed unless every condition holds:
    * not packaged (no SESSION_TOKEN_PATH);
    * the backend is bound to a loopback interface (SERVER_HOST);
    * the caller's Host header is loopback;
    * if an Origin header is present, it is a known local dev origin.
    """
    if SESSION_TOKEN_PATH:
        return False
    server_host = os.getenv("SERVER_HOST", "127.0.0.1").strip()
    if not _is_loopback_host(server_host):
        return False
    if not _is_loopback_host(request.headers.get("host", "")):
        return False
    origin = request.headers.get("origin")
    if origin and origin not in DEV_WEB_ORIGINS:
        return False
    return True


def get_dev_session_token(request) -> dict | None:
    """Return the dev session token, or None when not in the dev context."""
    if not session_token_available(request):
        return None
    return {"token": SESSION_TOKEN}


def validate_system_command(command: str) -> str:
    """Validate a system command against the allowlist."""
    from fastapi import HTTPException

    parts = command.strip().split()
    if not parts:
        raise HTTPException(status_code=400, detail="Command is required")
    base = os.path.basename(parts[0])
    if base not in ALLOWED_SYSTEM_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"Command not allowed. Allowed: {', '.join(sorted(ALLOWED_SYSTEM_COMMANDS))}",
        )
    return command


async def validate_ws_token(websocket) -> None:
    """Validate session token during WebSocket handshake."""
    from fastapi import WebSocketDisconnect

    token = websocket.query_params.get("token")
    if not token or token != SESSION_TOKEN:
        await websocket.close(code=4001, reason="Invalid or missing session token")
        raise WebSocketDisconnect()

    if auth_service.enabled:
        access_token = websocket.query_params.get("access_token")
        try:
            await auth_service.current_user(access_token or "")
        except Exception:
            await websocket.close(code=4001, reason="Invalid or missing session token")
            raise WebSocketDisconnect() from None


# --- Settings helpers (key masking, .env editing, backend restart) ----------
# Canonical implementations live in modules.settings and are re-exported above
# for backward compatibility with routes.deps and the tests.
SETTING_KEY_NAMES = KEY_NAMES


# --- Module singletons ------------------------------------------------------
memory_manager = MemoryManager(db_path=os.getenv("DATABASE_PATH", "jarvis_memory.db"))

auth_service = AuthService(memory_manager)

calendar = CalendarModule()
mail = MailModule()
mail_sessions = MailSessionStore(memory_manager)
web_browse = WebBrowseModule()
llm = LLMProvider()
system_actions = SystemActions()
documents = DocumentsModule()
stt = SpeechToTextModule()
vision = VisionModule()

# --- Manager singletons -----------------------------------------------------
audio_manager = AudioManager()
stt_manager = STTManager()
tts_manager = TTSManager()
tts = tts_manager
voice_manager = VoiceManager(audio_manager, stt_manager, tts_manager, llm)
model_manager = ModelManager()

conversation_manager = ConversationManager(memory_manager, llm)
preference_manager = PreferenceManager(memory_manager, llm)
context_manager = ContextManager(
    memory_manager, conversation_manager, calendar, mail, system_actions
)
system_manager = SystemManager(memory_manager)
vision_manager = VisionManager(memory_manager)
security_manager = SecurityManager(memory_manager)
performance_manager = PerformanceManager()
project_manager = ProjectManager(memory_manager)
git_manager = GitManager(memory_manager)
code_manager = CodeManager(memory_manager, llm)

task_manager = TaskManager(memory_manager)
workflow_manager = WorkflowManager(memory_manager)

adaptive_intelligence = AdaptiveIntelligenceManager(
    memory_manager, preference_manager, context_manager
)
proactive_ai = ProactiveAIManager(llm, memory_manager, adaptive_intelligence)

plugin_registry = PluginRegistry()
permission_manager = PermissionManager()

tool_registry = ToolRegistry()
tool_registry.register(SystemInfoTool())
tool_registry.register(RunningProcessesTool())
tool_registry.register(LaunchApplicationTool())
tool_registry.register(OpenTerminalTool())
tool_registry.register(ControlAppWindowTool())
tool_registry.register(CloseAppTool())
tool_registry.register(ScreenshotTool())
tool_registry.register(OpenUrlTool())
tool_registry.register(ResolveKnownLocationTool())
tool_registry.register(ListRunningApplicationsTool())
tool_registry.register(FileSearchTool())
tool_registry.register(ListDirectoryTool())
tool_registry.register(ReadFileTool())
tool_registry.register(OpenFileTool())
tool_registry.register(OpenFolderTool())
tool_registry.register(ExecuteShellTool())
tool_registry.register(WebSearchTool())
tool_registry.register(ReadDocumentTool())
tool_registry.register(RememberMemoryTool())
tool_registry.register(RecallMemoryTool())
tool_registry.register(ForgetMemoryTool())
tool_registry.register(UpdateMemoryTool())
tool_registry.register(ClearAllMemoriesTool())
tool_registry.register(GetCurrentContextTool())
tool_registry.register(FindRecentFilesTool())
tool_registry.register(FindByExtensionTool())
tool_registry.register(IdentifyFileTypeTool())
tool_registry.register(CreateFileTool())
tool_registry.register(CreateFolderTool())
tool_registry.register(MoveFileTool())
tool_registry.register(CopyFileTool())
tool_registry.register(DeleteFileTool())

# --- Orchestration singletons ------------------------------------------------
capability_policy = CapabilityPolicy()
session_context_store = SessionContextStore()
orchestrator = Orchestrator(llm, tool_registry, capability_policy)

# --- Markdown vault ---------------------------------------------------------
MEMORY_VAULT_PATH = os.getenv("MEMORY_VAULT_PATH") or os.path.join(
    os.path.expanduser("~"), "Documents", "JARVIS Memory"
)
if os.getenv("VAULT_SEARCH_BACKEND", "fts").lower() == "scan":
    from modules.vault.search import ScanSearchBackend

    vault = VaultManager(MEMORY_VAULT_PATH, search_backend=ScanSearchBackend())
else:
    vault = VaultManager(MEMORY_VAULT_PATH)
notes = NotesModule(vault=vault)

# --- User profile note (vault-backed preferences) ---------------------------
PROFILE_NOTE_PATH = "People/Me.md"
_PROFILE_NOTE_LEGACY_PATHS = ("People/me.md", "people/me.md", "people/Me.md")
_PROFILE_NOTE_BODY = "## About\n(Add things to remember about the user here.)"


def resolve_profile_note_path() -> str:
    """Return the profile note path, preferring whatever casing already exists.

    ``create_note(title="Me")`` produces ``People/Me.md`` (slugify preserves
    case). On case-insensitive filesystems all casings are the same file; on
    Linux they are distinct, so existing installs may hold ``People/me.md``.
    This resolves to the existing path (migration/fallback) or the canonical
    ``People/Me.md`` when nothing exists yet.
    """
    for candidate in (PROFILE_NOTE_PATH, *_PROFILE_NOTE_LEGACY_PATHS):
        try:
            if vault.store.exists(candidate):
                return candidate
        except Exception:
            continue
    return PROFILE_NOTE_PATH


async def get_profile_note() -> dict | None:
    """Return the user profile/preferences note, or None if it does not exist."""
    try:
        return await vault.get_note(resolve_profile_note_path())
    except FileNotFoundError:
        return None
    except Exception:
        return None


async def ensure_profile_note() -> dict | None:
    """Create the profile note if missing and return it (None on failure)."""
    note = await get_profile_note()
    if note:
        return note
    try:
        return await vault.create_note(
            title="Me",
            folder="People",
            note_type="person",
            tags=["profile"],
            content=_PROFILE_NOTE_BODY,
        )
    except Exception:
        return None


async def reset_profile_note() -> bool:
    """Clear the profile note back to its empty scaffold."""
    try:
        await vault.update_note(resolve_profile_note_path(), content=_PROFILE_NOTE_BODY)
        return True
    except Exception:
        return False


skill_registry = SkillRegistry()


# --- Skill registrations ----------------------------------------------------
async def _skill_calendar(user_input: str, session_id: str | None) -> dict:
    return {"calendar": await calendar.get_upcoming_events()}


skill_registry.register(
    Skill(
        "calendar",
        ["calendar", "schedule", "meeting", "event"],
        _skill_calendar,
        "Calendar events and scheduling",
    )
)


async def _skill_email(user_input: str, session_id: str | None) -> dict:
    session = await mail_sessions.most_recent()
    if session is None:
        return {"emails": {"error": "No email session configured. Authenticate in Settings."}}
    return {"emails": await session.get_recent_emails(limit=5)}


skill_registry.register(
    Skill(
        "email",
        ["email", "mail", "inbox", "message"],
        _skill_email,
        "Email reading and management",
    )
)


async def _skill_web_search(user_input: str, session_id: str | None) -> dict:
    return {"web_results": await web_browse.search(user_input)}


skill_registry.register(
    Skill(
        "web_search",
        ["search", "browse", "look up", "find", "what is"],
        _skill_web_search,
        "Web search and browsing",
    )
)


async def _skill_weather(user_input: str, session_id: str | None) -> dict:
    location_match = re.search(
        r"(?:weather|forecast)\s+(?:in|for|at)\s+(.+)", user_input, re.IGNORECASE
    )
    location = location_match.group(1).strip() if location_match else "local"
    weather = await web_browse.get_weather(location)
    if weather is None:
        return {"weather": {"error": "Could not fetch weather."}}
    return {"weather": weather}


skill_registry.register(
    Skill(
        "weather",
        ["weather", "forecast", "temperature", "how is the"],
        _skill_weather,
        "Weather forecast and conditions",
    )
)


async def _skill_translate(user_input: str, session_id: str | None) -> dict:
    match = re.search(r"translate\s+['\"](.+)['\"]\s+to\s+(\w+)", user_input, re.IGNORECASE)
    if not match:
        match = re.search(r"translate\s+(.+)\s+to\s+(\w+)$", user_input, re.IGNORECASE)
    if not match:
        return {"translate": {"error": "Usage: translate '<text>' to <language>"}}
    text, target = match.group(1).strip(), match.group(2).strip()
    translated = await web_browse.translate_text(text, target)
    if translated is None:
        return {"translate": {"error": "Translation failed."}}
    return {"translate": {"source": text, "target_language": target, "text": translated}}


skill_registry.register(
    Skill(
        "translate",
        ["translate"],
        _skill_translate,
        "Translate text to another language",
    )
)


def _skill_system(user_input: str, session_id: str | None) -> dict:
    return {"system_info": system_actions.get_system_info()}


skill_registry.register(
    Skill(
        "system",
        ["system", "status", "cpu", "memory", "disk"],
        _skill_system,
        "System information and status",
    )
)


async def _skill_notes(user_input: str, session_id: str | None) -> dict:
    note_match = re.search(
        r"(?:remember|note|take a note|create note|save note|write down|jot down)\s+(?:that\s+)?(.+)",
        user_input,
        re.IGNORECASE,
    )
    if note_match:
        note_text = note_match.group(1).strip()
        title = note_text[:60].strip() or "Note"
        note = await notes.create_note(title, note_text)
        return {
            "notes": (
                {
                    "action": "created",
                    "note": note,
                }
                if note
                else {"action": "failed", "error": "Could not save note"}
            )
        }
    return {"notes": {"action": "no_match"}}


skill_registry.register(
    Skill(
        "notes",
        ["remember", "note", "take a note", "create note", "save note", "write down", "jot down"],
        _skill_notes,
        "Note creation and organization",
    )
)


def _normalize_filename(filename: str) -> str:
    filename = filename.strip().strip("\"'")
    if filename and "." not in os.path.basename(filename):
        filename += ".txt"
    return filename


def _parse_document_command(user_input: str):
    text = user_input.strip()
    text = re.sub(
        r"^(create|append to|replace|delete|read|open|make|write to|add to|update|overwrite)\s+(a\s+|the\s+)?(document|file)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(?:named|called)\s+", "", text, flags=re.IGNORECASE)

    parts = text.split(None, 1)
    if not parts:
        return "", ""
    filename = _normalize_filename(parts[0])
    content = parts[1] if len(parts) > 1 else ""
    content = re.sub(
        r"^(with content|with text|with the content|with the text|containing|that says|saying|which says|whose content is|content is|text is)\s+",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"^(the text|the content)\s+", "", content, flags=re.IGNORECASE)
    return filename, content


def require_document_confirmation(session_id: str, action: Callable, reason: str) -> dict:
    if session_id:
        pending_documents_actions[session_id] = action
    return {"action": "confirmation_required", "reason": reason}


async def process_command(user_input: str, session_id: str | None = None) -> dict:
    """Parse command and gather context using skill registry + document confirmation."""
    context = {
        "calendar": None,
        "emails": None,
        "web_results": None,
        "weather": None,
        "translate": None,
        "system_info": None,
        "documents": None,
        "notes": None,
    }

    if session_id and session_id in pending_documents_actions:
        lower = user_input.lower()
        if lower in ("yes", "yeah", "yep", "sure", "okay", "do it", "confirm", "proceed"):
            action = pending_documents_actions.pop(session_id)
            try:
                result = action()
                context["documents"] = {
                    "action": "confirmed_executed",
                    "result": result.__dict__ if hasattr(result, "__dict__") else result,
                }
            except Exception as e:
                context["documents"] = {"action": "execution_failed", "error": str(e)}
            return context
        if lower in ("no", "nope", "cancel", "stop", "don't"):
            pending_documents_actions.pop(session_id, None)
            context["documents"] = {"action": "cancelled", "message": "Action cancelled."}
            return context

    if session_id and session_id in pending_tool_confirmations:
        lower = user_input.lower()
        if lower in ("yes", "yeah", "yep", "sure", "okay", "do it", "confirm", "proceed"):
            pending = pending_tool_confirmations.pop(session_id)
            tool_name = pending.get("tool")
            tool_args = pending.get("args", {})
            if tool_name:
                tool_args["confirm"] = True
                result = await tool_registry.execute_tool(tool_name, tool_args)
                context.setdefault("tools", {})
                context["tools"][tool_name] = result.to_dict()
            return context
        if lower in ("no", "nope", "cancel", "stop", "don't"):
            pending_tool_confirmations.pop(session_id, None)
            context["tools"] = {"action": "cancelled", "message": "Action cancelled."}
            return context

    user_lower = user_input.lower()

    # --- Profile reads only -----------------------------------------------------
    # Memory WRITES and destructive resets are owned exclusively by the typed
    # tool pipeline (remember_memory / clear_all_memories) so that secret
    # filtering, deduplication, retention, and single-use approval always
    # apply.  This legacy context builder must never persist directly.
    if "know about me" in user_lower or ("about me" in user_lower and "know" in user_lower):
        note = await get_profile_note()
        context["profile"] = {
            "action": "read",
            "content": (note or {}).get("body") or "No profile saved yet.",
        }
        return context

    document_keywords = [
        "document",
        "file",
        "open my",
        "create a document",
        "read document",
        "list documents",
        "show documents",
        "search document",
        "edit document",
        "append document",
        "replace document",
        "delete document",
    ]

    if any(word in user_lower for word in document_keywords):
        doc_context: dict = {"action": "pending", "query": user_input}

        read_match = re.search(r"read document (?:named )?(.+)", user_lower)
        open_match = re.search(r"open document (?:named )?(.+)", user_lower)
        create_match = re.search(r"create document (?:named )?(.+)", user_lower)
        append_match = re.search(r"append to document (?:named )?(.+)", user_lower)
        replace_match = re.search(r"replace document (?:named )?(.+)", user_lower)
        delete_match = re.search(r"delete document (?:named )?(.+)", user_lower)

        if read_match:
            filename = _normalize_filename(read_match.group(1).strip().strip("\"'"))
            result = documents.read_document(filename)
            doc_context["read"] = result.__dict__ if hasattr(result, "__dict__") else str(result)
        elif open_match:
            filename = _normalize_filename(open_match.group(1).strip().strip("\"'"))
            result = documents.open_document(filename)
            doc_context["open"] = result.__dict__ if hasattr(result, "__dict__") else str(result)
        elif create_match:
            filename, content = _parse_document_command(user_input)
            result = documents.create_document(filename, content or " ")
            doc_context["create"] = result.__dict__ if hasattr(result, "__dict__") else str(result)
            if not result.success and "already exists" in (result.error or "").lower():
                if session_id:
                    pending_documents_actions[session_id] = (
                        lambda fn=filename, ct=content or " ": documents.create_document(
                            fn, ct, overwrite=True
                        )
                    )
                doc_context["confirmation_required"] = f"File {filename} already exists. Overwrite?"
        elif append_match:
            filename, content = _parse_document_command(user_input)
            result = documents.append_document(filename, content or " ")
            doc_context["append"] = result.__dict__ if hasattr(result, "__dict__") else str(result)
        elif replace_match:
            filename, content = _parse_document_command(user_input)
            if session_id:
                pending_documents_actions[session_id] = (
                    lambda fn=filename, ct=content or " ": documents.replace_document(fn, ct)
                )
            doc_context["confirmation_required"] = f"Replace contents of {filename}?"
            doc_context["replace_pending"] = filename
        elif delete_match:
            filename = _normalize_filename(delete_match.group(1).strip().strip("\"'"))
            if session_id:
                pending_documents_actions[session_id] = (
                    lambda fn=filename: documents.delete_document(fn)
                )
            doc_context["confirmation_required"] = f"Delete {filename} permanently?"
            doc_context["delete_pending"] = filename
        else:
            list_match = re.search(r"list documents(?: named (.+))?", user_input, re.IGNORECASE)
            if list_match:
                q = list_match.group(1)
                doc_context["files"] = documents.list_documents(q)
            else:
                doc_context["files"] = documents.list_documents()

        context["documents"] = doc_context

    skill_results = await skill_registry.execute(user_input, session_id)
    for key, value in skill_results.items():
        if key in context and context[key] is None:
            context[key] = value.get(key) if isinstance(value, dict) else value
        elif key in context and isinstance(value, dict):
            context[key] = value

    return context


def _safe_audio_meta(chunk_b64: str) -> dict:
    """Safe metadata for a TTS audio chunk.

    Returns format/sample-rate/channel metadata only. Never logs raw audio,
    transcripts, or tokens. Non-WAV payloads are reported as ``mp3-like``
    (MP3/ADTS/M4A) because the exact codec is not sniffed here.
    """
    try:
        data = base64.b64decode(chunk_b64)
    except Exception:
        return {}
    if len(data) < 12 or data[:4] != b"RIFF":
        return {"format": "mp3-like"}
    import struct

    with contextlib.suppress(Exception):
        channels = struct.unpack_from("<H", data, 22)[0]
        sample_rate = struct.unpack_from("<I", data, 24)[0]
        bits = struct.unpack_from("<H", data, 34)[0]
        data_size = struct.unpack_from("<I", data, 40)[0] if len(data) >= 44 else 0
        duration = 0.0
        byte_rate = max(channels * (bits // 8), 1)
        if sample_rate and byte_rate:
            duration = data_size / (sample_rate * byte_rate)
        return {
            "format": "wav",
            "channels": channels,
            "sample_rate": sample_rate,
            "bits_per_sample": bits,
            "pcm_bytes": data_size,
            "duration_s": round(duration, 3),
        }
    return {"format": "wav"}


async def _stream_sentence_audio(websocket, sentence: str, voice_uid: str) -> None:
    """Stream TTS audio for one sentence using the standard segment flow.

    Sends ``audio_segment_start`` → ``audio_chunk``* → ``audio_segment_end``.
    If the TTS pipeline produces no audio, sends an ``error`` message so the
    frontend can transition out of the speaking state instead of hanging.

    Every emitted segment contains exactly one complete, decodable audio file:
    providers that yield whole files per chunk (Kokoro WAV) emit one segment
    per chunk, while stream providers that yield fragments of a single file
    (edge-tts MP3) are joined into one segment.  This keeps concatenated
    RIFF/WAV blobs out of the renderer's decoder.

    Logs safe diagnostics only: TTS start/end, chunk/byte counts, format,
    sample rate, channel count, duration, and error category.
    """
    chunks = 0
    total_bytes = 0
    first_chunk = ""
    segments = 0
    pending: list[str] = []
    started = time.monotonic()
    logger.info("[voice:%s] tts start chars=%d", voice_uid, len(sentence))

    async def _send(message: dict) -> None:
        await websocket.send_json(message)

    try:
        async for audio_chunk in tts.stream_speech(sentence):
            chunks += 1
            if not first_chunk:
                first_chunk = audio_chunk
            try:
                raw = base64.b64decode(audio_chunk)
            except Exception as e:
                logger.warning("[voice:%s] invalid TTS chunk dropped: %s", voice_uid, e)
                continue
            total_bytes += len(raw)
            if raw.startswith(b"RIFF"):
                # Whole-file chunk (e.g. Kokoro WAV): emit as its own segment so
                # the frontend never has to decode concatenated RIFF blobs.
                if segments > 0:
                    await _send({"type": "audio_segment_end"})
                await _send({"type": "audio_segment_start"})
                await _send({"type": "audio_chunk", "chunk": audio_chunk})
                segments += 1
            else:
                # Fragment of a single streamed file (e.g. edge-tts MP3):
                # accumulate and flush as one segment.
                pending.append(audio_chunk)
    except Exception as e:
        logger.error("[voice:%s] TTS streaming failed for sentence: %s", voice_uid, e)
        with contextlib.suppress(Exception):
            await _send(
                {
                    "type": "error",
                    "message": "Speech generation failed. Check your TTS configuration.",
                }
            )

    if pending:
        if segments > 0:
            await _send({"type": "audio_segment_end"})
        await _send({"type": "audio_segment_start"})
        await _send({"type": "audio_chunk", "chunk": "".join(pending)})
        segments += 1

    took_ms = (time.monotonic() - started) * 1000
    if segments == 0:
        logger.warning(
            "[voice:%s] TTS produced no audio — sending error so UI recovers",
            voice_uid,
        )
        with contextlib.suppress(Exception):
            await _send(
                {
                    "type": "error",
                    "message": "Speech generation failed. Check your TTS configuration.",
                }
            )
    else:
        meta = _safe_audio_meta(first_chunk)
        logger.info(
            "[voice:%s] tts end chunks=%d segments=%d bytes=%d %s took=%.0fms",
            voice_uid,
            chunks,
            segments,
            total_bytes,
            " ".join(f"{k}={v}" for k, v in meta.items()),
            took_ms,
        )
    await _send({"type": "audio_segment_end"})


async def stream_speech_to_socket(websocket, text: str, voice_uid: str) -> None:
    """Speak ``text`` over a websocket using the standard TTS segment flow."""
    text = (text or "").strip()
    if not text:
        return
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        sentences = [text]
    await websocket.send_json({"type": "audio_queue", "count": len(sentences)})
    for sentence in sentences:
        await _stream_sentence_audio(websocket, sentence, voice_uid)


_last_action_context: dict[str, dict] = {}


def _get_last_context(session_id: str) -> dict | None:
    return _last_action_context.get(session_id)


def _set_last_context(session_id: str, context: dict) -> None:
    _last_action_context[session_id] = context
    if len(_last_action_context) > 200:
        keys = list(_last_action_context.keys())
        for k in keys[:100]:
            _last_action_context.pop(k, None)


async def _route_tools(user_input: str, session_id: str) -> dict | None:
    """Match natural-language input to tools and execute them when confident."""
    lower = user_input.lower().strip()
    tool_results: dict = {}
    confirmations: dict = {}

    async def _maybe(tool_name: str, args: dict) -> None:
        result = await tool_registry.execute_tool(tool_name, args)
        if result.requires_confirmation:
            pending_tool_confirmations[session_id] = {
                "tool": tool_name,
                "args": args,
                "prompt": result.confirmation_prompt,
            }
        tool_results[tool_name] = result.to_dict()
        if result.success:
            _set_last_context(
                session_id,
                {
                    "tool": tool_name,
                    "args": args,
                    "result": result.to_dict(),
                    "timestamp": __import__("time").time(),
                },
            )

    def _first_match(patterns: list[str], text: str) -> bool:
        return any(p in text for p in patterns)

    def _after_phrases(text: str, phrases: list[str]) -> str:
        for p in phrases:
            if p in text:
                return text.split(p, 1)[-1].strip().strip(".\"'?!")
        return text

    # System information
    if _first_match(
        [
            "cpu",
            "memory",
            "ram",
            "disk",
            "storage",
            "uptime",
            "gpu",
            "processes",
            "system info",
            "system status",
            "how much ram",
            "how much cpu",
            "how much memory",
            "what's using the most ram",
            "what's using the most cpu",
            "is my gpu",
            "what gpu",
            "laptop temperature",
            "temperature",
        ],
        lower,
    ):
        await _maybe("system_info", {"query": lower})
    # Application control
    elif _first_match(
        [
            "launch ",
            "open ",
            "start ",
            "run ",
            "firefox",
            "chrome",
            "chromium",
            "vs code",
            "code ",
            "terminal",
            "nautilus",
            "dolphin",
            "spotify",
            "vlc",
            "opera",
        ],
        lower,
    ):
        app = _after_phrases(lower, ["launch ", "open ", "start ", "run "])
        app = app.strip(".\"'?!").strip()
        if app in ["terminal", "the terminal"]:
            await _maybe("open_terminal", {})
        else:
            await _maybe("launch_application", {"app": app})
    elif _first_match(["close ", "kill "], lower) and not _first_match(
        ["close all", "kill all"], lower
    ):
        app = _after_phrases(lower, ["close ", "kill "])
        await _maybe("close_app", {"app": app})
    elif _first_match(
        ["what applications", "what's running", "list apps", "running apps", "what processes"],
        lower,
    ):
        await _maybe("running_processes", {"limit": 15})
    elif _first_match(
        [
            "look at my screen",
            "what is on my screen",
            "what's on my screen",
            "read my screen",
            "read the screen",
            "explain what i'm seeing",
            "explain this screen",
            "what do you see",
            "what is this",
            "look at my",
            "see what i'm",
            "analyze my screen",
            "analyze the screen",
            "what's on the screen",
            "what is on the screen",
            "look at the screen",
            "read this",
            "look at this",
            "what is this image",
            "what's in this image",
            "describe my screen",
            "describe the screen",
            "what is happening on my screen",
            "what's happening on my screen",
            "what is displayed",
            "what's displayed",
            "check my screen",
            "see my screen",
            "view my screen",
            "what's open on my screen",
            "what is open on my screen",
        ],
        lower,
    ):
        await _maybe(
            "screenshot",
            {
                "analyze": True,
                "prompt": "Describe what is on this screen in detail, including any errors, text, windows, or important visual elements.",
            },
        )
    elif "screenshot" in lower:
        await _maybe("screenshot", {})
    # File operations
    elif _first_match(
        [
            "find file",
            "search file",
            "locate file",
            "find my ",
            "search for file",
            "where is my",
            "locate my",
            "find the ",
            "search the ",
            "find all ",
        ],
        lower,
    ):
        query = _after_phrases(
            lower,
            [
                "find file",
                "search file",
                "locate file",
                "find my ",
                "search for file",
                "where is my",
                "locate my",
                "find the ",
                "search the ",
                "find all ",
            ],
        )
        query = query.strip(".\"'?!").strip()
        if query:
            await _maybe("file_search", {"query": query, "directory": str(Path.home())})
    elif _first_match(
        [
            "list files",
            "list directory",
            "show files",
            "show directory",
            "what files",
            "what's inside",
            "what is inside",
            "contents of",
            "show me the files",
            "show inside",
            "list inside",
        ],
        lower,
    ):
        path = str(Path.home())
        for keyword in ["downloads", "documents", "desktop", "pictures", "home", "project"]:
            if keyword in lower:
                path = os.path.expanduser(f"~/{keyword.capitalize()}")
                if keyword == "project":
                    path = os.path.expanduser("~/Desktop/Project Folder")
                break
        await _maybe("list_directory", {"path": path})
    elif _first_match(
        ["read file", "open file", "read ", "show me ", "open the ", "open ", "read the "], lower
    ) and not _first_match(
        [
            "open folder",
            "open downloads",
            "open documents",
            "open desktop",
            "open home",
            "open project",
        ],
        lower,
    ):
        path = _after_phrases(
            lower,
            ["read file", "open file", "read the ", "read ", "show me ", "open the ", "open "],
        )
        path = path.strip(".\"'?!").strip()
        if path:
            await _maybe("read_file", {"path": path})
    elif _first_match(
        [
            "open folder",
            "open downloads",
            "open documents",
            "open desktop",
            "open home",
            "open project",
        ],
        lower,
    ):
        path_map = {
            "downloads": os.path.expanduser("~/Downloads"),
            "documents": os.path.expanduser("~/Documents"),
            "home": os.path.expanduser("~"),
            "desktop": os.path.expanduser("~/Desktop"),
            "pictures": os.path.expanduser("~/Pictures"),
            "project": os.path.expanduser("~/Desktop/Project Folder"),
        }
        for key, val in path_map.items():
            if key in lower:
                await _maybe("open_folder", {"path": val})
                break
    elif _first_match(
        ["find recent", "recent files", "modified today", "recently modified"], lower
    ):
        await _maybe("find_recent_files", {"directory": str(Path.home()), "hours": 24, "limit": 20})
    elif _first_match(
        ["find all ", "all python files", "all pdf", "all images", "all jpg", "all png"], lower
    ):
        ext = _after_phrases(lower, ["find all ", "all "])
        ext = ext.split()[0] if ext.split() else "py"
        await _maybe(
            "find_by_extension", {"extension": ext, "directory": str(Path.home()), "limit": 30}
        )
    elif _first_match(
        ["create folder", "create directory", "make folder", "new folder", "make directory"], lower
    ):
        path = _after_phrases(
            lower,
            ["create folder", "create directory", "make folder", "new folder", "make directory"],
        )
        path = path.strip(".\"'?!").strip()
        if path:
            await _maybe("create_folder", {"path": path})
    elif _first_match(["create file", "new file", "make file"], lower):
        path = _after_phrases(lower, ["create file", "new file", "make file"])
        path = path.strip(".\"'?!").strip()
        if path:
            await _maybe("create_file", {"path": path})
    elif _first_match(
        ["delete file", "delete ", "remove file", "remove ", "trash "], lower
    ) and not _first_match(["delete folder", "delete directory", "delete all"], lower):
        path = _after_phrases(lower, ["delete file", "delete ", "remove file", "remove ", "trash "])
        path = path.strip(".\"'?!").strip()
        if path:
            await _maybe("delete_file", {"path": path})
    elif _first_match(
        ["delete folder", "delete directory", "remove folder", "remove directory"], lower
    ):
        path = _after_phrases(
            lower, ["delete folder", "delete directory", "remove folder", "remove directory"]
        )
        path = path.strip(".\"'?!").strip()
        if path:
            await _maybe("delete_file", {"path": path})
    elif (
        "web search" in lower
        or "search web" in lower
        or "look up" in lower
        or "search the internet" in lower
        or "search for" in lower
    ):
        query = _after_phrases(
            lower, ["web search", "search web", "look up", "search the internet", "search for"]
        )
        query = query.strip(".\"'?!").strip()
        if query:
            await _maybe("web_search", {"query": query})
    elif (
        "remember " in lower
        and "what do you remember" not in lower
        and "recall" not in lower
        and "forget" not in lower
    ):
        fact = _after_phrases(lower, ["remember ", "remember that "])
        fact = fact.strip(".\"'?!").strip()
        if fact:
            await _maybe("remember_memory", {"fact": fact})
    elif "forget " in lower or "forget that " in lower:
        query = _after_phrases(lower, ["forget ", "forget that "])
        query = query.strip(".\"'?!").strip()
        if query:
            await _maybe("forget_memory", {"query": query})
    elif (
        "what do you remember" in lower
        or "recall" in lower
        or "what is my" in lower
        or "do you remember" in lower
    ):
        await _maybe("recall_memory", {"query": lower})
    else:
        last = _get_last_context(session_id)
        if last:
            last_tool = last.get("tool")
            if last_tool == "open_folder" and _first_match(
                [
                    "what's inside",
                    "what is inside",
                    "show inside",
                    "list inside",
                    "contents",
                    "what files",
                ],
                lower,
            ):
                await _maybe("list_directory", {"path": last["args"].get("path", str(Path.home()))})
            elif last_tool in ("read_file", "read_document") and _first_match(
                ["explain", "what is this", "summarize", "summarise", "what does this do"], lower
            ):
                content = last.get("result", {}).get("data", {}).get("content") or ""
                if content:
                    tool_results["explain_context"] = {
                        "path": last["args"].get("path"),
                        "content": content[:4000],
                        "instruction": "explain" if "explain" in lower else "summarize",
                    }

    if confirmations:
        return {"tool_results": tool_results, "confirmations": confirmations}
    if tool_results:
        return {"tool_results": tool_results}
    return None


def _plain_reply_from_tool_results(tool_results: dict) -> str:
    """Offline fallback: build a concise, honest reply from verified tool results."""
    parts = []
    for tool, result in tool_results.items():
        if tool in ("available",) or not isinstance(result, dict):
            continue
        data = result.get("data") or {}
        if result.get("success"):
            if tool in ("launch_app", "launch_application"):
                parts.append(f"Opened {data.get('launched')}.")
            elif tool == "open_file":
                parts.append(f"Opened {data.get('opened')}.")
            elif tool == "open_folder":
                parts.append(f"Opened {data.get('opened')}.")
            elif tool == "close_app":
                parts.append(f"Closed {len(data.get('killed') or [])} running process(es).")
            elif tool == "create_file":
                parts.append(f"Created {data.get('created')}.")
            elif tool == "create_folder":
                parts.append(f"Created {data.get('created')}.")
            elif tool == "delete_file":
                parts.append(f"Deleted {data.get('deleted')}.")
            elif tool == "move_file":
                parts.append(f"Moved {data.get('moved')} to {data.get('to')}.")
            elif tool == "copy_file":
                parts.append(f"Copied {data.get('copied')} to {data.get('to')}.")
            elif tool == "remember_memory":
                parts.append(
                    "Saved to memory."
                    if data.get("action") != "already_remembered"
                    else "That was already saved."
                )
            elif tool == "update_memory":
                parts.append("Updated that memory.")
            elif tool == "clear_all_memories":
                parts.append("Memory cleared.")
            elif tool == "get_current_context":
                bits = [f"{k}: {v}" for k, v in data.items() if v and k != "recent_paths"]
                parts.append("Context: " + "; ".join(bits[:4]) if bits else "No active context.")
            elif tool == "forget_memory":
                removed = data.get("removed") or 0
                parts.append("Forgotten." if removed else "I couldn't find that in memory.")
            elif tool == "recall_memory":
                facts = data.get("facts") or []
                parts.append("Here's what I remember: " + "; ".join(facts[:5]))
            elif tool == "find_recent_files":
                files = data.get("files") or []
                parts.append(f"Found {len(files)} recently modified file(s).")
            elif tool == "find_by_extension":
                files = data.get("files") or []
                parts.append(f"Found {len(files)} matching file(s).")
            elif tool == "file_search":
                parts.append(f"Found {data.get('count', 0)} matching file(s).")
            elif tool == "list_directory":
                parts.append(f"Listed {data.get('count', 0)} item(s).")
            elif tool == "read_file":
                content = (data.get("content") or "").strip()
                parts.append((content[:400] or "That file is empty."))
            elif tool == "system_info" or tool == "running_processes":
                parts.append("Here's the current system information.")
            elif tool == "screenshot":
                parts.append("Screenshot captured.")
            else:
                parts.append(f"{tool.replace('_', ' ').capitalize()} completed.")
        else:
            parts.append(f"I couldn't complete that: {result.get('error')}")
    return " ".join(parts) if parts else "I couldn't complete that."


async def handle_ws_confirm(
    session_id: str, tool_name: str, confirm: bool, websocket, voice_uid: str = ""
) -> None:
    """Handle a single-use confirmation for an orchestrator-requested tool."""
    session_ctx = session_context_store.get(session_id)
    if session_ctx.pending_tool != tool_name:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "response", "text": "No pending action to confirm."})
        return
    if not confirm:
        session_ctx.pending_tool = None
        session_ctx.pending_args = None
        capability_policy.revoke_session(session_id)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "response", "text": "Action cancelled."})
        return
    context: dict = {"tools": {}}
    profile = await get_profile_note()
    if profile and profile.get("body"):
        context["profile"] = profile["body"]
    reply = await orchestrator.respond_to_confirmed(session_id, session_ctx, context)
    full_text = strip_markdown_for_speech(reply or "")
    if not full_text.strip():
        full_text = "Done."
    logger.info("[voice:%s] Confirmed action reply: %s", voice_uid, full_text)
    session_context_store.get(session_id).record_exchange("", full_text)
    await memory_manager.add_message(session_id, "assistant", full_text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()] or [
        full_text
    ]
    await websocket.send_json({"type": "status", "status": "generating_speech"})
    await websocket.send_json({"type": "audio_queue", "count": len(sentences)})
    for sentence in sentences:
        await _stream_sentence_audio(websocket, sentence, voice_uid)
    await websocket.send_json({"type": "response", "text": full_text, "audio": None})


async def handle_user_input(
    user_input: str,
    session_id: str,
    websocket,
    voice_uid: str = "",
    voice_cycle_id: str = "",
) -> None:
    """Process a single user utterance via the typed orchestrator, then TTS."""
    from starlette.websockets import WebSocketDisconnect  # noqa: F401

    interaction_id = uuid.uuid4().hex[:12]

    async def _tool_results_payload(tools_this: list[dict]) -> list[dict]:
        payload = []
        for item in tools_this:
            result = item.get("result") or {}
            payload.append(
                {
                    "tool": item.get("tool") or "",
                    "args": item.get("args") or {},
                    "verified": bool(result.get("success")) if isinstance(result, dict) else True,
                }
            )
        return payload

    await memory_manager.add_message(session_id, "user", user_input)

    await websocket.send_json({"type": "status", "status": "processing"})

    terminal_sent = False

    def mark_terminal() -> None:
        nonlocal terminal_sent
        terminal_sent = True

    try:
        # --- voice/text confirmation of a pending orchestrator approval ---------
        session_ctx = session_context_store.get(session_id)
        session_ctx.record_exchange(user_input)
        pending_tool = session_ctx.pending_tool
        if pending_tool and capability_policy.has_pending(session_id, pending_tool):
            lowered = user_input.strip().lower().rstrip(".!?")
            if lowered in (
                "yes",
                "yeah",
                "yep",
                "sure",
                "okay",
                "ok",
                "do it",
                "confirm",
                "proceed",
                "go ahead",
                "please",
                "yes please",
                "go",
            ):
                await handle_ws_confirm(session_id, pending_tool, True, websocket, voice_uid)
                return
            if lowered in ("no", "nope", "cancel", "stop", "don't", "no don't", "don't do it"):
                await handle_ws_confirm(session_id, pending_tool, False, websocket, voice_uid)
                return

        context = await process_command(user_input, session_id=session_id)

        before_tools = len(session_ctx.tool_results)
        decision = await orchestrator.run(user_input, session_id, session_ctx, context)
        tools_this = list(session_ctx.tool_results)[before_tools:]

        if decision.kind == "confirm":
            await websocket.send_json(
                {
                    "type": "confirmations",
                    "confirmations": {
                        decision.tool: {
                            "tool": decision.tool,
                            "args": decision.arguments or {},
                            "confirmation_prompt": decision.reason or "Please confirm this action.",
                        }
                    },
                    "message": decision.reason or "Please confirm this action.",
                }
            )
            return

        if decision.kind == "error":
            # Offline resilience: fall back to the legacy keyword router.
            fallback = await _route_tools(user_input, session_id)
            if fallback:
                context.setdefault("tools", {})
                context["tools"].update(fallback)
                pending = pending_tool_confirmations.get(session_id)
                if pending:
                    await websocket.send_json(
                        {
                            "type": "confirmations",
                            "confirmations": {
                                pending.get("tool", "action"): {
                                    "tool": pending.get("tool"),
                                    "args": pending.get("args", {}),
                                    "confirmation_prompt": pending.get(
                                        "prompt", "Please confirm this action."
                                    ),
                                }
                            },
                            "message": pending.get("prompt", "Please confirm this action."),
                        }
                    )
                    return
                full_text = strip_markdown_for_speech(_plain_reply_from_tool_results(fallback))
                if full_text:
                    logger.info("[voice:%s] Fallback reply: %s", voice_uid, full_text[:200])
                    await memory_manager.add_message(session_id, "assistant", full_text)
                    await websocket.send_json({"type": "status", "status": "generating_speech"})
                    sentences = [
                        s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()
                    ] or [full_text]
                    await websocket.send_json({"type": "audio_queue", "count": len(sentences)})
                    for sentence in sentences:
                        await _stream_sentence_audio(websocket, sentence, voice_uid)
                    await websocket.send_json(
                        {
                            "type": "response",
                            "text": full_text,
                            "audio": None,
                            "interaction_id": interaction_id,
                            "voice_cycle_id": voice_cycle_id or None,
                            "tool_results": await _tool_results_payload(tools_this),
                        }
                    )
                    mark_terminal()
                    return
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "The AI backend is not responding. Check your API keys in .env and try again.",
                }
            )
            return

        # --- natural reply (decision.kind in {"reply", "clarify"}) --------------
        full_text = strip_markdown_for_speech(decision.text or "")
        if not full_text.strip():
            full_text = "I couldn't generate a response. Please try again."

        logger.info("[voice:%s] LLM: %s", voice_uid, full_text.strip())
        session_ctx.record_exchange(user_input, full_text.strip())
        await memory_manager.add_message(session_id, "assistant", full_text.strip())

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()]
        if not sentences:
            sentences = [full_text]

        if sentences:
            await websocket.send_json({"type": "status", "status": "generating_speech"})
            await websocket.send_json({"type": "audio_queue", "count": len(sentences)})
            for sentence in sentences:
                await _stream_sentence_audio(websocket, sentence, voice_uid)

        await websocket.send_json(
            {
                "type": "response",
                "text": full_text.strip(),
                "audio": None,
                "interaction_id": interaction_id,
                "voice_cycle_id": voice_cycle_id or None,
                "tool_results": await _tool_results_payload(tools_this),
            }
        )
        mark_terminal()
    except WebSocketDisconnect:
        raise
    except Exception as e:
        logger.error("[voice:%s] handle_user_input failed: %s", voice_uid, e)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": "Something went wrong. Please try again."}
            )
        terminal_sent = True
    finally:
        if not terminal_sent:
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "The assistant did not return a complete response. Please try again.",
                    }
                )
