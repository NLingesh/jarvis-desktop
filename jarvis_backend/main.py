"""JARVIS Backend — FastAPI entry-point.

The HTTP routes now live in :mod:`routes` sub-modules (system, memory, mail,
notes, calendar, llm, stt, settings).  Shared singletons and business-logic
functions live in :mod:`routes.state`.  This file wires everything together:
logging, middleware, lifespan, the WebSocket handler, and router inclusion.
"""

import asyncio
import base64
import contextlib
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, Response

from modules.proactive import ProactiveMonitor
from routes.auth import router as auth_router
from routes.calendar import router as calendar_router
from routes.llm import router as llm_router
from routes.mail import router as mail_router
from routes.memory import router as memory_router
from routes.notes import router as notes_router
from routes.settings import router as settings_router
from routes.state import (
    auth_service,
    calendar,
    handle_user_input,
    mail_sessions,
    memory_manager,
    stream_speech_to_socket,
    stt,
    validate_ws_token,
    vault,
)
from routes.stt import router as stt_router
from routes.system import router as system_router
from routes.vault import router as vault_router
from routes.vision import router as vision_router

logger = logging.getLogger(__name__)

# Connected /ws/voice sockets, used to broadcast proactive reminders.
_connected_sockets: set[WebSocket] = set()

# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------
allow_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]


# ---------------------------------------------------------------------------
# Security middlewares
# ---------------------------------------------------------------------------
class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws:; "
            "font-src 'self' data:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self.window_seconds
        self._requests.setdefault(client_ip, [])
        self._requests[client_ip] = [t for t in self._requests[client_ip] if t > window_start]
        if len(self._requests[client_ip]) >= self.max_requests:
            raise HTTPException(status_code=429, detail="Too many requests")
        self._requests[client_ip].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("JARVIS Backend starting up...")
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and not (
        os.getenv("SSL_KEYFILE") and os.getenv("SSL_CERTFILE")
    ):
        logger.warning(
            "Server is bound to non-localhost (%s) without SSL. "
            "Set SSL_KEYFILE and SSL_CERTFILE env vars to enable HTTPS.",
            host,
        )
    await memory_manager.cleanup_expired_mail_sessions()
    await auth_service.bootstrap_user()
    await auth_service.cleanup()
    await vault.initialize()
    # Warm up the Vosk model off the event loop so the first utterance is fast.
    if stt.available and not os.getenv("JARVIS_SKIP_STT_PRELOAD"):
        threading.Thread(target=stt.preload, daemon=True).start()
        logger.info("Vosk model found at %s — preloading in background", stt.model_dir)
    elif not stt.available:
        logger.warning(
            "Vosk model not found at %s — speech-to-text will fall back to cloud (or be unavailable)",
            stt.model_dir,
        )

    async def _deliver_proactive(text: str) -> None:
        sockets = list(_connected_sockets)
        for socket in sockets:
            with contextlib.suppress(Exception):
                await socket.send_json({"type": "proactive", "text": text})
                await stream_speech_to_socket(socket, text)

    proactive = ProactiveMonitor(
        calendar=calendar,
        mail_sessions=mail_sessions,
        deliver=_deliver_proactive,
    )
    if not os.getenv("JARVIS_SKIP_PROACTIVE"):
        await proactive.start()

    yield
    logger.info("JARVIS Backend shutting down...")
    await proactive.stop()
    await memory_manager.close()
    await vault.close()


app = FastAPI(title="JARVIS Voice Assistant", lifespan=lifespan)

# Register route modules
app.include_router(auth_router)
app.include_router(system_router)
app.include_router(memory_router)
app.include_router(mail_router)
app.include_router(notes_router)
app.include_router(calendar_router)
app.include_router(llm_router)
app.include_router(stt_router)
app.include_router(settings_router)
app.include_router(vision_router)
app.include_router(vault_router)

# Middleware (order matters: CSP / rate-limit wrap CORS)
app.add_middleware(CSPMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if auth_service.enabled:
    from modules.auth import AuthMiddleware

    app.add_middleware(AuthMiddleware, auth=auth_service)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "JARVIS Backend"}


# ---------------------------------------------------------------------------
# WebSocket — voice pipeline
# ---------------------------------------------------------------------------
# Bound the number of simultaneous Vosk/cloud transcriptions so many concurrent
# utterances cannot exhaust worker threads.
STT_SEMAPHORE = asyncio.Semaphore(4)
WS_IDLE_TIMEOUT = 90


async def _finalize_audio_stream(stream, websocket) -> str:
    """Finalize a streaming recognizer and return its transcription."""
    try:
        async with STT_SEMAPHORE:
            user_input = await asyncio.to_thread(stream.finish)
    except Exception as e:
        logger.error("STT failed on websocket: %s", e)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": f"Speech recognition failed: {e}"}
            )
        return ""
    if not user_input:
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": "I could not hear anything. Please try again."}
            )
    return user_input


@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await validate_ws_token(websocket)
    await websocket.accept()
    _connected_sockets.add(websocket)
    session_id = await memory_manager.create_session()
    pending_stream = None
    loop = asyncio.get_running_loop()

    def send_partial(text: str) -> None:
        """Deliver a live STT hypothesis from the recognizer thread to the socket."""

        async def _send() -> None:
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "transcript", "text": text})

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_send()))

    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=WS_IDLE_TIMEOUT)
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "text":
                user_input = data.get("content", "").strip()
                if not user_input:
                    continue
                await handle_user_input(user_input, session_id, websocket)
            elif msg_type == "audio_start":
                # A new utterance while one is still open: finalize the old one first.
                if pending_stream is not None:
                    await _finalize_audio_stream(pending_stream, websocket)
                sample_rate = int(data.get("sample_rate") or 16000)
                pending_stream = stt.stream(sample_rate, on_partial=send_partial)
                await websocket.send_json({"type": "status", "status": "transcribing"})
            elif msg_type == "audio_chunk":
                if pending_stream is None:
                    await websocket.send_json(
                        {"type": "error", "message": "audio_start must precede audio_chunk"}
                    )
                    continue
                chunk_b64 = data.get("data")
                if not chunk_b64:
                    continue
                try:
                    pcm = base64.b64decode(chunk_b64)
                except Exception as e:
                    logger.warning("Invalid audio chunk: %s", e)
                    await websocket.send_json({"type": "error", "message": "Invalid audio chunk"})
                    continue
                pending_stream.feed(pcm)
            elif msg_type == "audio_end":
                if pending_stream is None:
                    await websocket.send_json(
                        {"type": "error", "message": "audio_end without audio_start"}
                    )
                    continue
                user_input = await _finalize_audio_stream(pending_stream, websocket)
                pending_stream = None
                if not user_input:
                    continue
                logger.info("User (voice): %s", user_input)
                await handle_user_input(user_input, session_id, websocket)
            elif msg_type == "audio":
                # Legacy whole-blob payload (backwards compatible).
                audio_base64 = data.get("audio_base64") or data.get("audio")
                if not audio_base64:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "audio_base64 is required",
                        }
                    )
                    continue
                await websocket.send_json({"type": "status", "status": "transcribing"})
                try:
                    async with STT_SEMAPHORE:
                        user_input = await asyncio.to_thread(stt.transcribe_base64, audio_base64)
                except Exception as e:
                    logger.error("STT failed on websocket: %s", e)
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Speech recognition failed: {e}",
                        }
                    )
                    continue
                if not user_input:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "I could not hear anything. Please try again.",
                        }
                    )
                    continue
                logger.info("User (voice): %s", user_input)
                await handle_user_input(user_input, session_id, websocket)

    except TimeoutError:
        logger.info("WebSocket idle timeout, closing session %s", session_id)
    except WebSocketDisconnect:
        logger.info("Client disconnected, session %s saved", session_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        _connected_sockets.discard(websocket)
        if pending_stream is not None:
            # The utterance never finished cleanly; abandon the worker thread.
            pending_stream.abandon()


# ---------------------------------------------------------------------------
# Frontend SPA fallback
# ---------------------------------------------------------------------------
_this_dir = os.path.dirname(os.path.abspath(__file__))
frontend_dist = os.path.join(_this_dir, "..", "jarvis_frontend", "dist")
if not os.path.isdir(frontend_dist):
    _alt = os.path.join(_this_dir, "jarvis_frontend", "dist")
    if os.path.isdir(_alt):
        frontend_dist = _alt

if os.path.isdir(frontend_dist):
    app.mount("/static", StaticFiles(directory=frontend_dist), name="static")

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
