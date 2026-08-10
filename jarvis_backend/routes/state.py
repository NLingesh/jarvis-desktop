"""Shared singleton instances used across route modules and main.py.

Creating the module-level singletons here avoids each route file
instantiating its own copy of MemoryManager, LLMProvider, etc.
"""

import asyncio
import contextlib
import logging
import os
import re
import secrets
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
from modules.documents_module import DocumentsModule
from modules.llm_provider import LLMProvider
from modules.mail_module import MailModule, MailSessionStore
from modules.notes_module import NotesModule
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
from tools.app_tools import LaunchAppTool, OpenTerminalTool
from tools.desktop_tools import CloseAppTool, ScreenshotTool
from tools.document_tools import ReadDocumentTool
from tools.file_tools import (
    FileSearchTool,
    ListDirectoryTool,
    OpenFileTool,
    OpenFolderTool,
    ReadFileTool,
)
from tools.memory_tools import RecallMemoryTool, RememberMemoryTool
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
tool_registry.register(LaunchAppTool())
tool_registry.register(OpenTerminalTool())
tool_registry.register(CloseAppTool())
tool_registry.register(ScreenshotTool())
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
PROFILE_NOTE_PATH = "People/me.md"
_PROFILE_NOTE_BODY = "## About\n(Add things to remember about the user here.)"


async def get_profile_note() -> dict | None:
    """Return the user profile/preferences note, or None if it does not exist."""
    try:
        return await vault.get_note(PROFILE_NOTE_PATH)
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
        await vault.update_note(PROFILE_NOTE_PATH, content=_PROFILE_NOTE_BODY)
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

    user_lower = user_input.lower()

    # --- Profile / preferences commands --------------------------------------
    remember_match = re.match(
        r"(?:remember|note down|don't forget|please remember)\s+(?:that\s+)?(.*)",
        user_input,
        re.IGNORECASE,
    )
    if remember_match and remember_match.group(1).strip():
        fact = remember_match.group(1).strip().strip(".")
        note = await ensure_profile_note()
        if note:
            existing = (note.get("body") or "").rstrip()
            line = f"- {fact}"
            if line not in existing:
                new_body = f"{existing}\n{line}" if existing.strip() else f"## About\n{line}"
                with contextlib.suppress(Exception):
                    await vault.update_note(PROFILE_NOTE_PATH, content=new_body)
        context["profile"] = {"action": "remembered", "fact": fact}
        return context

    if re.search(r"forget (?:my )?(?:preferences|profile|about me)", user_lower) or user_lower in (
        "forget me",
        "reset profile",
        "clear my profile",
    ):
        await reset_profile_note()
        context["profile"] = {"action": "forgotten"}
        return context

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


async def _stream_sentence_audio(websocket, sentence: str, voice_uid: str) -> None:
    """Stream TTS audio for one sentence using the standard segment flow.

    Sends ``audio_segment_start`` → ``audio_chunk``* → ``audio_segment_end``.
    If the TTS pipeline produces no audio, sends an ``error`` message so the
    frontend can transition out of the speaking state instead of hanging.
    """
    await websocket.send_json({"type": "audio_segment_start"})
    chunks = 0
    try:
        async for audio_chunk in tts.stream_speech(sentence):
            chunks += 1
            await websocket.send_json({"type": "audio_chunk", "chunk": audio_chunk})
    except Exception as e:
        logger.error("[voice:%s] TTS streaming failed for sentence: %s", voice_uid, e)

    if chunks == 0:
        logger.warning(
            "[voice:%s] TTS produced no audio — sending error so UI recovers",
            voice_uid,
        )
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Speech generation failed. Check your TTS configuration.",
                }
            )
    await websocket.send_json({"type": "audio_segment_end"})


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


async def _route_tools(user_input: str, session_id: str) -> dict | None:
    """Match natural-language input to tools and execute them when confident."""
    lower = user_input.lower()
    tool_results: dict = {}

    async def _maybe(tool_name: str, args: dict) -> None:
        result = await tool_registry.execute_tool(tool_name, args)
        tool_results[tool_name] = result.to_dict()

    if any(k in lower for k in ["cpu", "memory", "disk", "uptime", "gpu", "processes", "system info", "status"]):
        await _maybe("system_info", {"query": lower})
    elif "launch " in lower or "open " in lower:
        app = lower.split("open ")[-1].split("launch ")[-1].strip()
        await _maybe("launch_app", {"app": app})
    elif "terminal" in lower and ("open" in lower or "launch" in lower):
        await _maybe("open_terminal", {})
    elif "close" in lower:
        app = lower.replace("close", "").strip()
        await _maybe("close_app", {"app": app})
    elif "screenshot" in lower:
        await _maybe("screenshot", {})
    elif any(k in lower for k in ["find file", "search file", "locate file"]):
        query = re.sub(r"(find|search|locate)\s+(file|files)\s*(named|called)?\s*", "", lower).strip()
        await _maybe("file_search", {"query": query, "directory": str(Path.home())})
    elif "list files" in lower or "list directory" in lower or "what files" in lower:
        await _maybe("list_directory", {"path": str(Path.home())})
    elif "read file" in lower or "open file" in lower:
        path = re.sub(r"(read|open)\s+(the\s+)?file\s+", "", lower).strip().strip("\"'")
        await _maybe("read_file", {"path": path})
    elif "open folder" in lower or "open downloads" in lower or "open documents" in lower:
        path_map = {
            "downloads": os.path.expanduser("~/Downloads"),
            "documents": os.path.expanduser("~/Documents"),
            "home": os.path.expanduser("~"),
            "desktop": os.path.expanduser("~/Desktop"),
            "pictures": os.path.expanduser("~/Pictures"),
        }
        for key, val in path_map.items():
            if key in lower:
                await _maybe("open_folder", {"path": val})
                break
    elif "run " in lower or "execute " in lower:
        cmd = re.sub(r"^(run|execute)\s+", "", lower).strip()
        await _maybe("execute_shell", {"command": cmd})
    elif "web search" in lower or "search web" in lower or "look up" in lower:
        query = re.sub(r"(web\s+search|search\s+web|look\s+up)\s+(for\s+)?", "", lower).strip()
        await _maybe("web_search", {"query": query})
    elif "read document" in lower or "summarize" in lower or "summarise" in lower:
        path = re.sub(r"(read|summarize|summarise)\s+(document|file|pdf)?\s*", "", lower).strip().strip("\"'")
        await _maybe("read_document", {"path": path})
    elif "remember " in lower:
        fact = re.sub(r"^remember\s+(that\s+)?", "", lower).strip().strip(".")
        await _maybe("remember_memory", {"fact": fact})
    elif "what do you remember" in lower or "recall" in lower:
        await _maybe("recall_memory", {"query": lower})

    if tool_results:
        return {"tool_results": tool_results}
    return None


async def handle_user_input(
    user_input: str, session_id: str, websocket, voice_uid: str = ""
) -> None:
    """Process a single user utterance: gather context, stream LLM reply and TTS."""
    from starlette.websockets import WebSocketDisconnect  # noqa: F401

    await memory_manager.add_message(session_id, "user", user_input)

    await websocket.send_json({"type": "status", "status": "processing"})

    terminal_sent = False

    def mark_terminal() -> None:
        nonlocal terminal_sent
        terminal_sent = True

    try:
        context = await process_command(user_input, session_id=session_id)

        tool_result = await _route_tools(user_input, session_id)
        if tool_result:
            context.setdefault("tools", {})
            context["tools"].update(tool_result)

        context_manager_result = await context_manager.build_context(
            session_id=session_id, query=user_input
        )
        context.setdefault("intelligence", context_manager_result)

        profile = await get_profile_note()
        if profile and profile.get("body"):
            context["profile"] = profile["body"]

        conversation = await memory_manager.get_conversation(session_id)

        memory_results = []
        with contextlib.suppress(Exception):
            memory_results = await memory_manager.search_memory(user_input, session_id=session_id)

        buffer = ""
        full_text = ""
        sentences: list[str] = []
        llm_failed = False

        try:
            async for chunk in llm.get_response_stream(
                user_message=user_input,
                conversation_history=conversation,
                context=context,
                memory_results=memory_results,
            ):
                buffer += chunk
                full_text += chunk

                while True:
                    match = re.search(r"[.!?]\s+", buffer)
                    if not match:
                        break
                    sentence = buffer[: match.end()].strip()
                    buffer = buffer[match.end() :]
                    sentences.append(sentence)

                    await websocket.send_json({"type": "partial", "text": full_text.strip()})
                    await asyncio.sleep(0.01)
        except Exception as e:
            llm_failed = True
            logger.error("[voice:%s] LLM streaming failed: %s", voice_uid, e)

        if buffer.strip():
            sentences.append(buffer.strip())
            await websocket.send_json({"type": "partial", "text": full_text.strip()})

        if not full_text.strip():
            if not llm_failed:
                full_text = "I couldn't generate a response. Please try again."
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "The AI backend is not responding. Check your API keys in .env and try again.",
                    }
                )
                mark_terminal()
                return

        logger.info("[voice:%s] LLM: %s", voice_uid, full_text.strip())
        await memory_manager.add_message(session_id, "assistant", full_text.strip())

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
