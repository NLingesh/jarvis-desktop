import asyncio
import os
import re
import secrets
import logging
from contextlib import asynccontextmanager
from typing import Dict, Optional, Callable, List

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from modules.memory import MemoryManager
from modules.calendar_module import CalendarModule
from modules.mail_module import MailModule
from modules.notes_module import NotesModule
from modules.web_browse import WebBrowseModule
from modules.llm_provider import LLMProvider
from modules.tts import TextToSpeechModule
from modules.system_actions import SystemActions
from modules.documents_module import DocumentsModule
from modules.stt import SpeechToTextModule
from modules.skill_registry import Skill, SkillRegistry

env_path = os.getenv("ENV_PATH")
if env_path:
    load_dotenv(env_path)
else:
    load_dotenv()

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
        logger.warning(f"Failed to write session token file: {e}")

def _require_session_token(request: Request) -> None:
    if not SESSION_TOKEN_PATH:
        return
    token = request.headers.get("X-Jarvis-Token", "")
    if not token or token != SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing session token")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory mail session tokens removed; mail sessions are now persisted in SQLite via MemoryManager.

# Pending document actions awaiting confirmation: session_id -> action callable
pending_documents_actions: Dict[str, Callable] = {}

# Initialize modules
memory_manager = MemoryManager(db_path=os.getenv("DATABASE_PATH", "jarvis_memory.db"))
memory_manager.cleanup_expired_mail_sessions()
calendar = CalendarModule()
mail = MailModule()
notes = NotesModule()
web_browse = WebBrowseModule()
llm = LLMProvider()
tts = TextToSpeechModule()
system_actions = SystemActions()
documents = DocumentsModule()
stt = SpeechToTextModule()

skill_registry = SkillRegistry()

async def _skill_calendar(user_input: str, session_id: Optional[str]) -> Dict:
    return {"calendar": await calendar.get_upcoming_events()}

skill_registry.register(Skill(
    "calendar",
    ["calendar", "schedule", "meeting", "event"],
    _skill_calendar,
    "Calendar events and scheduling",
))

async def _skill_email(user_input: str, session_id: Optional[str]) -> Dict:
    return {"emails": await mail.get_recent_emails(limit=5)}

skill_registry.register(Skill(
    "email",
    ["email", "mail", "inbox", "message"],
    _skill_email,
    "Email reading and management",
))

async def _skill_web_search(user_input: str, session_id: Optional[str]) -> Dict:
    return {"web_results": await web_browse.search(user_input)}

skill_registry.register(Skill(
    "web_search",
    ["search", "browse", "look up", "find", "what is"],
    _skill_web_search,
    "Web search and browsing",
))

def _skill_system(user_input: str, session_id: Optional[str]) -> Dict:
    return {"system_info": system_actions.get_system_info()}

skill_registry.register(Skill(
    "system",
    ["system", "status", "cpu", "memory", "disk"],
    _skill_system,
    "System information and status",
))

async def _skill_notes(user_input: str, session_id: Optional[str]) -> Dict:
    note_match = re.search(
        r"(?:remember|note|take a note|create note|save note|write down|jot down)\s+(?:that\s+)?(.+)",
        user_input,
        re.IGNORECASE,
    )
    if note_match:
        note_text = note_match.group(1).strip()
        title = note_text[:60].strip() or "Note"
        note = await notes.create_note(title, note_text)
        return {"notes": {"action": "created", "note": note} if note else {"action": "failed", "error": "Could not save note"}}
    return {"notes": {"action": "no_match"}}

skill_registry.register(Skill(
    "notes",
    ["remember", "note", "take a note", "create note", "save note", "write down", "jot down"],
    _skill_notes,
    "Note creation and organization",
))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("JARVIS Backend starting up...")
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and not (os.getenv("SSL_KEYFILE") and os.getenv("SSL_CERTFILE")):
        logger.warning(
            "Server is bound to non-localhost (%s) without SSL. "
            "Set SSL_KEYFILE and SSL_CERTFILE env vars to enable HTTPS.", host
        )
    memory_manager.load_history()
    yield
    # Shutdown
    logger.info("JARVIS Backend shutting down...")
    memory_manager.save_history()

app = FastAPI(title="JARVIS Voice Assistant", lifespan=lifespan)

# Enable CORS
allow_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "JARVIS Backend"}

@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = memory_manager.create_session()
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "text":
                user_input = data.get("content", "").strip()
                if not user_input:
                    continue
                await handle_user_input(user_input, session_id, websocket)
            elif msg_type == "audio":
                audio_base64 = data.get("audio_base64") or data.get("audio")
                if not audio_base64:
                    await websocket.send_json({
                        "type": "error",
                        "message": "audio_base64 is required",
                    })
                    continue
                await websocket.send_json({"type": "status", "status": "transcribing"})
                try:
                    user_input = stt.transcribe_base64(audio_base64)
                except Exception as e:
                    logger.error(f"STT failed on websocket: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Speech recognition failed: {e}",
                    })
                    continue
                if not user_input:
                    await websocket.send_json({
                        "type": "error",
                        "message": "I could not hear anything. Please try again.",
                    })
                    continue
                logger.info(f"User (voice): {user_input}")
                await handle_user_input(user_input, session_id, websocket)
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected, session {session_id} saved")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except Exception:
            pass


async def handle_user_input(user_input: str, session_id: str, websocket: WebSocket):
    """Process a single user utterance: gather context, stream LLM reply and TTS."""
    memory_manager.add_message(session_id, "user", user_input)

    await websocket.send_json({
        "type": "status",
        "status": "processing"
    })

    context = await process_command(user_input, session_id=session_id)
    conversation = memory_manager.get_conversation(session_id)

    memory_results = []
    try:
        memory_results = memory_manager.search_memory(user_input, session_id=session_id)
    except Exception:
        pass

    buffer = ""
    full_text = ""
    sentences: List[str] = []
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
                match = re.search(r'[.!?]\s+', buffer)
                if not match:
                    break
                sentence = buffer[: match.end()].strip()
                buffer = buffer[match.end():]
                sentences.append(sentence)

                await websocket.send_json({"type": "partial", "text": full_text.strip()})
                await asyncio.sleep(0.01)
    except Exception as e:
        llm_failed = True
        logger.error(f"LLM streaming failed: {e}")

    if buffer.strip():
        sentences.append(buffer.strip())
        await websocket.send_json({"type": "partial", "text": full_text.strip()})

    if not full_text.strip():
        if not llm_failed:
            full_text = "I couldn't generate a response. Please try again."
        else:
            await websocket.send_json({
                "type": "error",
                "message": "The AI backend is not responding. Check your API keys in .env and try again.",
            })
            return

    logger.info(f"LLM: {full_text.strip()}")
    memory_manager.add_message(session_id, "assistant", full_text.strip())

    if sentences:
        await websocket.send_json({"type": "audio_queue", "count": len(sentences)})

        for sentence in sentences:
            await websocket.send_json({"type": "audio_segment_start"})
            try:
                async for audio_chunk in tts.stream_speech(sentence):
                    await websocket.send_json({"type": "audio_chunk", "chunk": audio_chunk})
            except Exception:
                try:
                    audio_base64 = await tts.generate_speech(sentence)
                    if audio_base64:
                        await websocket.send_json({"type": "audio_chunk", "chunk": audio_base64})
                except Exception as e:
                    logger.error(f"TTS failed for sentence: {e}")
            await websocket.send_json({"type": "audio_segment_end"})

    await websocket.send_json({
        "type": "response",
        "text": full_text.strip(),
        "audio": None,
    })

async def process_command(user_input: str, session_id: Optional[str] = None) -> dict:
    """Parse command and gather context using skill registry + document confirmation."""
    context = {
        "calendar": None,
        "emails": None,
        "web_results": None,
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
    document_keywords = [
        "document", "file", "open my", "create a document", "read document",
        "list documents", "show documents", "search document", "edit document",
        "append document", "replace document", "delete document"
    ]

    if any(word in user_lower for word in document_keywords):
        doc_context: Dict = {"action": "pending", "query": user_input}

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
                    pending_documents_actions[session_id] = lambda fn=filename, ct=content or " ": documents.create_document(fn, ct, overwrite=True)
                doc_context["confirmation_required"] = f"File {filename} already exists. Overwrite?"
        elif append_match:
            filename, content = _parse_document_command(user_input)
            result = documents.append_document(filename, content or " ")
            doc_context["append"] = result.__dict__ if hasattr(result, "__dict__") else str(result)
        elif replace_match:
            filename, content = _parse_document_command(user_input)
            if session_id:
                pending_documents_actions[session_id] = lambda fn=filename, ct=content or " ": documents.replace_document(fn, ct)
            doc_context["confirmation_required"] = f"Replace contents of {filename}?"
            doc_context["replace_pending"] = filename
        elif delete_match:
            filename = _normalize_filename(delete_match.group(1).strip().strip("\"'"))
            if session_id:
                pending_documents_actions[session_id] = lambda fn=filename: documents.delete_document(fn)
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


def _normalize_filename(filename: str) -> str:
    """Append a .txt extension when the filename has none."""
    filename = filename.strip().strip("\"'")
    if filename and "." not in os.path.basename(filename):
        filename += ".txt"
    return filename


def _parse_document_command(user_input: str):
    """Split a document command into (filename, content).

    Handles forms like:
    - "create document test.md with content hello"
    - "create document named notes.txt containing foo"
    - "append to document todo.txt buy milk"
    - "replace document config.txt with the text X"
    """
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


def require_document_confirmation(session_id: str, action: callable, reason: str) -> Dict:
    if session_id:
        pending_documents_actions[session_id] = action
    return {"action": "confirmation_required", "reason": reason}

@app.post("/api/stt")
async def api_speech_to_text(request: dict):
    """Transcribe audio to text using offline speech recognition.

    Expected JSON body:
    - `audio_base64`: base64-encoded WAV (PCM16, mono, 16kHz) audio

    Returns `{"text": "..."}`. An optional `language` field is accepted for
    forward compatibility.
    """
    audio_base64 = request.get("audio_base64") or request.get("audio")
    if not audio_base64:
        raise HTTPException(status_code=400, detail="audio_base64 is required")

    if not stt.available:
        detail = "Speech-to-text model not installed. Run scripts/download-vosk-model.sh"
        if not stt.has_cloud_fallback:
            detail += ", or set OPENAI_API_KEY for cloud fallback"
        raise HTTPException(
            status_code=503,
            detail=detail,
        )

    try:
        text = stt.transcribe_base64(audio_base64)
        return {"text": text}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"STT failed: {e}")
        raise HTTPException(status_code=500, detail=f"Speech-to-text failed: {e}")


@app.get("/api/stt/status")
async def api_stt_status():
    """Check whether offline speech recognition is ready."""
    return {"available": stt.available, "cloud_fallback": stt.has_cloud_fallback}

@app.get("/api/skills")
async def api_list_skills():
    """List available skills and their intents."""
    return {"skills": skill_registry.list_skills()}

@app.get("/api/memory/{session_id}")
async def get_memory(session_id: str):
    """Retrieve conversation history"""
    return {"conversation": memory_manager.get_conversation(session_id)}

@app.post("/api/notes")
async def create_note(request: dict):
    """Create a new note"""
    title = request.get("title", "Untitled")
    content = request.get("content", "")
    return await notes.create_note(title, content)

@app.get("/api/calendar/events")
async def get_calendar_events():
    """Get upcoming calendar events"""
    return await calendar.get_upcoming_events()

@app.post("/api/mail/auth")
async def authenticate_mail(request: Request):
    """Authenticate to IMAP mail provider and return a session token."""
    body = await request.json()
    email_address = body.get("email")
    password = body.get("password")
    imap_server = body.get("imap_server", "imap.gmail.com")
    imap_port = body.get("imap_port", 993)

    if not email_address or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    mail.imap_server = imap_server
    mail.imap_port = imap_port
    success = mail.authenticate(email_address, password)
    if not success:
        raise HTTPException(status_code=401, detail="Authentication failed")

    token = memory_manager.create_mail_session(email_address)
    return {"success": True, "token": token}


def _get_mail_session(token: Optional[str]) -> str:
    email = memory_manager.get_mail_session(token)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or missing mail session token")
    return email

@app.get("/api/mail/inbox")
async def get_inbox(request: Request):
    """Get recent emails"""
    _get_mail_session(request.headers.get("Authorization", "").replace("Bearer ", ""))
    return {"emails": await mail.get_recent_emails(limit=10)}


@app.get("/api/mail/unread")
async def get_unread_inbox(request: Request, limit: int = 10):
    """Get unread emails"""
    _get_mail_session(request.headers.get("Authorization", "").replace("Bearer ", ""))
    return {"emails": await mail.get_unread_emails(limit=limit)}

@app.get("/api/notes")
async def get_notes(notebook: str = "default"):
    """Get saved notes"""
    return {"notes": await notes.get_notes(notebook)}

@app.get("/api/system/info")
async def get_system_info():
    """Get current system information"""
    return system_actions.get_system_info()

@app.post("/api/system/execute")
async def execute_system_command(request: Request):
    """Execute a safe system command"""
    _require_session_token(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")

    output = await system_actions.execute_command(command)
    return {"output": output}


@app.post("/api/llm/generate")
async def api_llm_generate(request: dict):
    """Generate text from configured LLM provider.

    Expected JSON body:
    - `prompt` or `message`: the user's input text
    - `conversation` (optional): list of {role, content} dicts to use as history
    - `model` (optional): override model name
    """
    prompt = request.get("prompt") or request.get("message")
    conversation = request.get("conversation") or []
    model = request.get("model")

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    # If a model override is provided, set temporarily on provider
    orig_model = None
    if model:
        orig_model = llm.model
        llm.model = model

    try:
        resp = await llm.get_response(user_message=prompt, conversation_history=conversation, context=None)
        return {"text": resp}
    finally:
        if model and orig_model is not None:
            llm.model = orig_model


@app.post("/api/llm/rerank")
async def api_llm_rerank(request: dict):
    """Rerank a set of passages using the configured reranker (NVIDIA etc).

    Expected JSON body:
    - `query`: the query string
    - `passages`: list of passage strings
    - `model` (optional): override reranker model
    """
    query = request.get("query")
    passages = request.get("passages")
    model = request.get("model")

    if not query or not passages:
        raise HTTPException(status_code=400, detail="query and passages are required")

    result = await llm.rerank(query=query, passages=passages, model=model)
    return {"result": result}

# Determine frontend dist path - works in both dev and packaged modes
_this_dir = os.path.dirname(os.path.abspath(__file__))
frontend_dist = os.path.join(_this_dir, "..", "jarvis_frontend", "dist")
if not os.path.isdir(frontend_dist):
    # In packaged mode, extraFiles may place dist at a different relative location
    _alt = os.path.join(_this_dir, "jarvis_frontend", "dist")
    if os.path.isdir(_alt):
        frontend_dist = _alt
if os.path.isdir(frontend_dist):
    app.mount("/static", StaticFiles(directory=frontend_dist), name="static")

    from starlette.responses import FileResponse

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve frontend SPA - all non-API routes return index.html"""
        file_path = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    ssl_certfile = os.getenv("SSL_CERTFILE")
    uvicorn.run(
        app,
        host=host,
        port=port,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
    )
