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
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, Response

from managers.native_audio import list_input_devices
from managers.native_voice import NativeVoiceSession
from modules.proactive import ProactiveMonitor
from routes.adaptive import router as adaptive_router
from routes.auth import router as auth_router
from routes.automation import router as automation_router
from routes.calendar import router as calendar_router
from routes.code_routes import router as code_router
from routes.git_routes import router as git_router
from routes.llm import router as llm_router
from routes.mail import router as mail_router
from routes.memory import router as memory_router
from routes.models import router as models_router
from routes.notes import router as notes_router
from routes.performance import router as performance_router
from routes.plugins import router as plugins_router
from routes.proactive_ai import router as proactive_ai_router
from routes.projects import router as projects_router
from routes.search import router as search_router
from routes.security import router as security_router
from routes.settings import router as settings_router
from routes.state import (
    audio_manager,
    auth_service,
    calendar,
    get_dev_session_token,
    handle_user_input,
    handle_ws_confirm,
    llm,
    mail_sessions,
    memory_manager,
    model_manager,
    pending_tool_confirmations,
    plugin_registry,
    stream_speech_to_socket,
    stt,
    stt_manager,
    system_actions,
    task_manager,
    tool_registry,
    tts,
    tts_manager,
    validate_ws_token,
    vault,
    vision_manager,
    voice_manager,
    workflow_manager,
)
from modules.limits import audio_chunk_allowed, legacy_audio_blob_allowed
from routes.stt import router as stt_router
from routes.system import router as system_router
from routes.tasks import router as tasks_router
from routes.tools import router as tools_router
from routes.vault import router as vault_router
from routes.vision import router as vision_router
from routes.voice import router as voice_router

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
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
            )
        self._requests[client_ip].append(now)
        return await call_next(request)


class PerformanceTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        try:
            from routes.state import performance_manager

            performance_manager.record_request(request.url.path, duration_ms, response.status_code)
        except Exception:
            pass
        return response


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
        system_actions=system_actions,
        memory_manager=memory_manager,
        deliver=_deliver_proactive,
    )
    if not os.getenv("JARVIS_SKIP_PROACTIVE"):
        await proactive.start()

    async def _deliver_automation(text: str) -> None:
        sockets = list(_connected_sockets)
        for socket in sockets:
            with contextlib.suppress(Exception):
                await socket.send_json({"type": "automation", "text": text})

    task_manager.deliver = _deliver_automation
    workflow_manager.deliver = _deliver_automation

    await task_manager.start()
    await workflow_manager.start()

    from plugins.builtin.skills import (
        CalendarPlugin,
        EmailPlugin,
        NotesPlugin,
        SystemPlugin,
        TranslatePlugin,
        WeatherPlugin,
        WebSearchPlugin,
    )

    builtin_plugins = [
        CalendarPlugin,
        EmailPlugin,
        WebSearchPlugin,
        WeatherPlugin,
        TranslatePlugin,
        SystemPlugin,
        NotesPlugin,
    ]
    for plugin_cls in builtin_plugins:
        try:
            await plugin_registry.load_plugin(plugin_cls)
        except Exception as exc:
            logger.error("Failed to load builtin plugin %s: %s", plugin_cls.__name__, exc)

    yield
    logger.info("JARVIS Backend shutting down...")
    await proactive.stop()
    await task_manager.stop()
    await workflow_manager.stop()
    await plugin_registry.shutdown()
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
app.include_router(tools_router)
app.include_router(search_router)
app.include_router(voice_router)
app.include_router(automation_router)
app.include_router(adaptive_router)
app.include_router(proactive_ai_router)
app.include_router(security_router)
app.include_router(performance_router)
app.include_router(projects_router)
app.include_router(git_router)
app.include_router(code_router)
app.include_router(models_router)
app.include_router(tasks_router)
app.include_router(plugins_router)

# Middleware (order matters: CSP / rate-limit wrap CORS)
app.add_middleware(CSPMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)
app.add_middleware(PerformanceTrackingMiddleware)
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
    return {
        "status": "healthy",
        "service": "JARVIS Backend",
        "stt": stt.available,
        "ws_connections": len(_connected_sockets),
        "managers": {
            "audio": audio_manager.diagnostics(),
            "stt": stt_manager.diagnostics(),
            "tts": tts_manager.diagnostics(),
            "voice": voice_manager.diagnostics(),
            "model": model_manager.diagnostics(),
            "vision": vision_manager.diagnostics(),
        },
    }


@app.get("/api/session-token")
async def session_token(request: Request):
    data = get_dev_session_token(request)
    if data is None:
        raise HTTPException(
            status_code=403,
            detail="Session token is only served to loopback clients in the local development context",
        )
    return data


@app.get("/api/voice/diagnostics")
async def voice_diagnostics():
    """Structured pipeline health for startup checks and debugging.

    The frontend calls this at startup to report whether the backend,
    speech recognition, and TTS are ready, and to surface actionable
    guidance instead of generic "Failed to fetch" / "Couldn't listen" errors.
    """
    return {
        "backend": {"status": "ok", "service": "JARVIS Backend"},
        "ws_connections": len(_connected_sockets),
        "stt": stt.diagnostics(),
        "tts": tts.diagnostics(),
        "llm": {
            "provider": getattr(llm, "provider", None),
            "model": getattr(llm, "model", None),
            "configured": bool(
                getattr(llm, "api_key", None)
                or getattr(getattr(llm, "client", None), "api_key", None)
                or getattr(llm, "client", None) is not None
            ),
        },
    }


# ---------------------------------------------------------------------------
# WebSocket — voice pipeline
# ---------------------------------------------------------------------------
# Bound the number of simultaneous Vosk/cloud transcriptions so many concurrent
# utterances cannot exhaust worker threads.
STT_SEMAPHORE = asyncio.Semaphore(4)
WS_IDLE_TIMEOUT = 90


async def _finalize_audio_stream(stream, websocket, voice_uid: str) -> str:
    """Finalize a streaming recognizer and return its transcription."""
    try:
        async with STT_SEMAPHORE:
            user_input = await asyncio.to_thread(stream.finish)
    except TimeoutError:
        logger.error("[voice:%s] STT finish timed out", voice_uid)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Speech recognition timed out. Please try again.",
                }
            )
        return ""
    except Exception as e:
        message = str(e)
        logger.error("[voice:%s] STT failed: %s", voice_uid, message)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": f"Speech recognition failed: {message}"}
            )
        return ""
    if not user_input:
        if not stt.available:
            detail = (
                "Speech recognition engine is not ready. Install a Vosk model via "
                "scripts/download-vosk-model.sh, or set OPENAI_API_KEY for cloud fallback."
            )
        elif stt.available and not stt.has_cloud_fallback:
            detail = (
                "I heard audio but could not transcribe it. Vosk returned no text and no "
                "cloud fallback (OPENAI_API_KEY) is configured."
            )
        else:
            detail = "I could not hear any speech. Please speak again."
        logger.info("[voice:%s] STT returned no text (%s)", voice_uid, detail)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": detail})
    return user_input


@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await validate_ws_token(websocket)
    await websocket.accept()
    _connected_sockets.add(websocket)
    voice_uid = uuid.uuid4().hex[:8]
    logger.info("[voice:%s] connection open (peer=%s)", voice_uid, websocket.client)
    session_id = await memory_manager.create_session()
    pending_stream = None
    wake_detector = None
    loop = asyncio.get_running_loop()
    audio_bytes = 0

    def send_partial(text: str) -> None:
        """Deliver a live STT hypothesis from the recognizer thread to the socket."""

        async def _send() -> None:
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "transcript", "text": text})

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_send()))

    def send_wake_word(phrase: str) -> None:
        """Deliver a wake-word hit from the spotter thread to the socket."""

        async def _send() -> None:
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "wake_word", "phrase": phrase})

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
                logger.info("[voice:%s] text input (%d chars)", voice_uid, len(user_input))
                await handle_user_input(user_input, session_id, websocket, voice_uid)
            elif msg_type == "wake_start":
                if wake_detector is not None:
                    wake_detector.close()
                phrase = (data.get("phrase") or os.getenv("WAKE_WORD", "computer")).strip()
                sample_rate = int(data.get("sample_rate") or 16000)
                logger.info(
                    "[voice:%s] wake_start phrase=%r sample_rate=%d", voice_uid, phrase, sample_rate
                )
                wake_detector = stt.wake_word(
                    on_detected=send_wake_word, phrase=phrase, sample_rate=sample_rate
                )
                await websocket.send_json({"type": "wake_ready", "phrase": phrase})
            elif msg_type == "wake_chunk":
                if wake_detector is None:
                    await websocket.send_json(
                        {"type": "error", "message": "wake_start must precede wake_chunk"}
                    )
                    continue
                chunk_b64 = data.get("data")
                if not chunk_b64:
                    continue
                try:
                    pcm = base64.b64decode(chunk_b64)
                except Exception as e:
                    logger.warning("[voice:%s] invalid wake chunk: %s", voice_uid, e)
                    continue
                wake_detector.feed(pcm)
            elif msg_type == "wake_stop":
                if wake_detector is not None:
                    wake_detector.close()
                    wake_detector = None
            elif msg_type == "audio_start":
                # A new utterance while one is still open: finalize the old one first.
                if pending_stream is not None:
                    await _finalize_audio_stream(pending_stream, websocket, voice_uid)
                sample_rate = int(data.get("sample_rate") or 16000)
                pending_stream = stt.stream(sample_rate, on_partial=send_partial)
                audio_bytes = 0
                logger.info("[voice:%s] audio_start sample_rate=%d", voice_uid, sample_rate)
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
                    logger.warning("[voice:%s] invalid audio chunk: %s", voice_uid, e)
                    await websocket.send_json({"type": "error", "message": "Invalid audio chunk"})
                    continue
                if not audio_chunk_allowed(len(pcm), audio_bytes):
                    logger.warning(
                        "[voice:%s] audio chunk exceeds limits, discarding utterance", voice_uid
                    )
                    await websocket.send_json(
                        {"type": "error", "message": "Audio chunk too large"}
                    )
                    pending_stream.abandon()
                    pending_stream = None
                    continue
                audio_bytes += len(pcm)
                pending_stream.feed(pcm)
            elif msg_type == "audio_end":
                if pending_stream is None:
                    await websocket.send_json(
                        {"type": "error", "message": "audio_end without audio_start"}
                    )
                    continue
                logger.info(
                    "[voice:%s] audio_end received %.1f KB",
                    voice_uid,
                    audio_bytes / 1024,
                )
                user_input = await _finalize_audio_stream(pending_stream, websocket, voice_uid)
                pending_stream = None
                if not user_input:
                    continue
                logger.info("[voice:%s] User (voice) %d chars", voice_uid, len(user_input))
                await handle_user_input(user_input, session_id, websocket, voice_uid)
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
                # Bound the decoded payload before it reaches the recognizer.
                if not legacy_audio_blob_allowed(len(audio_base64)):
                    await websocket.send_json(
                        {"type": "error", "message": "Audio payload too large"}
                    )
                    continue
                await websocket.send_json({"type": "status", "status": "transcribing"})
                try:
                    async with STT_SEMAPHORE:
                        user_input = await asyncio.to_thread(stt.transcribe_base64, audio_base64)
                except Exception as e:
                    logger.error("[voice:%s] STT failed on websocket: %s", voice_uid, e)
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
                            "message": "I could not hear any speech. Please try again.",
                        }
                    )
                    continue
                logger.info("[voice:%s] User (voice) %d chars", voice_uid, len(user_input))
                await handle_user_input(user_input, session_id, websocket, voice_uid)
            elif msg_type == "confirm":
                tool_name = data.get("tool")
                confirm = bool(data.get("confirm", False))
                pending = pending_tool_confirmations.get(session_id)
                if pending and pending.get("tool") == tool_name:
                    if confirm:
                        tool_args = pending.get("args", {})
                        tool_args["confirm"] = True
                        try:
                            result = await tool_registry.execute_tool(tool_name, tool_args)
                            await websocket.send_json({
                                "type": "response",
                                "text": f"Done. {result.data if result.success else result.error}",
                            })
                        except Exception as exc:
                            await websocket.send_json({
                                "type": "response",
                                "text": f"Action failed: {exc}",
                            })
                    else:
                        await websocket.send_json({
                            "type": "response",
                            "text": "Action cancelled.",
                        })
                    pending_tool_confirmations.pop(session_id, None)
                else:
                    await handle_ws_confirm(session_id, tool_name, confirm, websocket, voice_uid)

    except TimeoutError:
        logger.info("[voice:%s] idle timeout, closing session %s", voice_uid, session_id)
    except WebSocketDisconnect:
        logger.info("[voice:%s] client disconnected, session %s saved", voice_uid, session_id)
    except Exception as e:
        logger.error("[voice:%s] websocket error: %s", voice_uid, e)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        _connected_sockets.discard(websocket)
        if pending_stream is not None:
            # The utterance never finished cleanly; abandon the worker thread.
            pending_stream.abandon()
        if wake_detector is not None:
            wake_detector.close()


# ---------------------------------------------------------------------------
# WebSocket — native voice (backend-owned microphone)
# ---------------------------------------------------------------------------
NATIVE_VOICE_TIMEOUT = 120

# An utterance whose peak-normalized RMS stays below this is effectively
# silence — report "no usable signal" instead of a generic transcription error.
NO_USABLE_SIGNAL_RMS = 0.005


async def _native_transcribe(session, pcm: bytes, websocket, voice_uid: str) -> str:
    """Transcribe a captured utterance using the STT manager.

    Reports precise, local-first failure messages instead of a generic error
    when the microphone path is at fault (no device / muted / no signal).
    """
    if not pcm:
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": "I didn't catch any audio. Please speak again."}
            )
        return ""
    rms, peak = _pcm_level(pcm)
    muted = _source_muted(session)
    try:
        async with STT_SEMAPHORE:
            started = time.monotonic()
            user_input = await asyncio.to_thread(stt_manager.transcribe_pcm16, pcm, 16000)
            took_ms = (time.monotonic() - started) * 1000
    except Exception as e:
        logger.error("[voice:%s] native STT failed: %s", voice_uid, e)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": f"Speech recognition failed: {e}"}
            )
        return ""
    _log_native_stt_diagnostic(session, pcm, rms, peak, muted, user_input, took_ms, voice_uid)
    if not user_input:
        if muted is True:
            detail = "Microphone is muted."
        elif rms < NO_USABLE_SIGNAL_RMS:
            detail = "No usable microphone signal detected."
        else:
            detail = "Audio received, but no speech was recognized."
        logger.info(
            "[voice:%s] native STT no text (rms=%.4f peak=%.4f muted=%s): %s",
            voice_uid,
            rms,
            peak,
            muted,
            detail,
        )
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": detail})
    return user_input


def _pcm_level(pcm: bytes) -> tuple[float, float]:
    """Compute (rms, peak) of PCM16 audio without logging any samples."""
    if not pcm:
        return 0.0, 0.0
    try:
        import array

        samples = array.array("h", pcm)
        n = len(samples)
        if n == 0:
            return 0.0, 0.0
        total = 0.0
        peak = 0
        for v in samples:
            av = abs(v)
            total += av * av
            if av > peak:
                peak = av
        rms = (total / n) ** 0.5 / 32768.0
        return rms, peak / 32768.0
    except Exception:
        return 0.0, 0.0


def _source_muted(session) -> bool | None:
    """Best-effort mute detection for the active input source (never raises)."""
    try:
        if session is None or session.mic is None:
            return None
        device_id = session.mic.device_info().get("id")
        from managers.native_audio import source_mute_state

        return source_mute_state(device_id)
    except Exception:
        return None


def _native_connect_message(reason: str, session) -> str:
    """Map a microphone open failure to a clear, local-first message.

    Local microphone problems must not be reported as generic network/STT
    errors — the user needs to know it is the input device that failed.
    """
    low = reason.lower()
    if "no input device" in low or "no usable input" in low:
        return "No microphone detected."
    if "sounddevice" in low or "portaudio" in low:
        return "No microphone detected."
    muted = _source_muted(session)
    if muted is True:
        return "Microphone is muted."
    if "device" in low and ("invalid" in low or "error" in low or "unavailable" in low):
        return "No microphone detected."
    return f"Could not open the microphone: {reason}"


def _log_native_stt_diagnostic(
    session, pcm: bytes, rms: float, peak: float, muted: bool | None, user_input: str,
    took_ms: float, voice_uid: str,
) -> None:
    """Log safe STT diagnostics: device/source, selected status, level, timing.

    Logs device id + name, whether the device is the PortAudio default,
    capture sample rate, channel count, RMS/peak, byte count, chunk count,
    mute state, model state, and transcript length.  Never logs raw audio,
    API keys, credentials, or transcript content.
    """
    device_id = None
    device_name = ""
    capture_rate = 16000
    sample_rate = 16000
    channels = 1
    is_default = None
    with contextlib.suppress(Exception):
        info = session.mic.device_info() if session is not None else {}
        device_id = info.get("id")
        device_name = info.get("name") or ""
        capture_rate = info.get("capture_rate") or 16000
        sample_rate = info.get("sample_rate") or 16000
        channels = 1
        devices = list_input_devices()
        if device_id is not None:
            is_default = any(d.get("is_default") for d in devices if d.get("id") == device_id)
    samples = len(pcm) // 2
    block_samples = max(int(sample_rate * 30 / 1000), 1)
    chunks = (samples + block_samples - 1) // block_samples
    model_ready = None
    model_loaded = None
    with contextlib.suppress(Exception):
        diag = stt_manager.diagnostics()
        model_ready = diag.get("ready")
        model_loaded = diag.get("vosk_loaded")
    logger.info(
        "[voice:%s] stt: device=%s name=%r default=%s sr=%d capture_rate=%d ch=%d "
        "samples=%d bytes=%d chunks=%d rms=%.4f peak=%.4f muted=%s "
        "model_ready=%s model_loaded=%s took=%.0fms transcript_chars=%d",
        voice_uid,
        device_id,
        device_name,
        is_default,
        sample_rate,
        capture_rate,
        channels,
        samples,
        len(pcm),
        chunks,
        rms,
        peak,
        muted,
        model_ready,
        model_loaded,
        took_ms,
        len(user_input),
    )


@app.websocket("/ws/voice/native")
async def native_voice_endpoint(websocket: WebSocket):
    """Backend-owned microphone voice endpoint.

    The backend captures audio directly from the local microphone (sounddevice)
    so the browser never touches getUserMedia.  Commands:

    * ``{"type": "connect"}``            — open the mic, enter READY
    * ``{"type": "start_listening", "mode": "ptt"|"tap"|"hands_free"}``
    * ``{"type": "stop_listening"}``      — PTT release / tap again
    * ``{"type": "cancel"}``              — discard current utterance
    * ``{"type": "set_device", "device": int|str}``
    * ``{"type": "get_devices"}``
    * ``{"type": "mic_test_start"}`` / ``{"type": "mic_test_stop"}``
    * ``{"type": "ping"}``

    Server events: ``state``, ``level``, ``devices``, then the standard
    transcript/response/audio_segment_* flow from ``handle_user_input``.
    """
    await validate_ws_token(websocket)
    await websocket.accept()
    voice_uid = uuid.uuid4().hex[:8]
    logger.info("[voice:%s] native connection open (peer=%s)", voice_uid, websocket.client)
    session_id = await memory_manager.create_session()
    loop = asyncio.get_running_loop()
    session = None
    mic_testing = False

    def _emit_state(state: str, detail: str) -> None:
        async def _send() -> None:
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {"type": "state", "state": state, "detail": detail or None}
                )

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_send()))

    def _emit_level(level: dict) -> None:
        async def _send() -> None:
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "level", **level})

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_send()))

    def _on_utterance(pcm: bytes) -> None:
        loop.call_soon_threadsafe(lambda: asyncio.create_task(_process_utterance(pcm)))

    async def _process_utterance(pcm: bytes) -> None:
        user_input = await _native_transcribe(session, pcm, websocket, voice_uid)
        if not user_input:
            _emit_state("IDLE", "no speech detected")
            return
        logger.info("[voice:%s] User (native voice) %d chars", voice_uid, len(user_input))
        _emit_state("PROCESSING", "stt complete")
        await handle_user_input(user_input, session_id, websocket, voice_uid)
        _emit_state("IDLE", "utterance complete")

    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=NATIVE_VOICE_TIMEOUT)
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "connect":
                if session is None:
                    session = NativeVoiceSession(
                        device=data.get("device"),
                        on_state=_emit_state,
                        on_level=_emit_level,
                        on_utterance=_on_utterance,
                    )
                else:
                    session.set_device(data.get("device") or session._device)
                await websocket.send_json({"type": "devices", "devices": list_input_devices()})
                if not session.connect():
                    reason = session.diagnostics().get("error") or "failed to open microphone"
                    message = _native_connect_message(reason, session)
                    await websocket.send_json({"type": "error", "message": message})
            elif msg_type == "get_devices":
                await websocket.send_json({"type": "devices", "devices": list_input_devices()})
            elif msg_type == "set_device":
                if session is None:
                    session = NativeVoiceSession(
                        device=data.get("device"),
                        on_state=_emit_state,
                        on_level=_emit_level,
                        on_utterance=_on_utterance,
                    )
                result = session.set_device(data.get("device"))
                await websocket.send_json({"type": "devices", **result})
            elif msg_type == "start_listening":
                if session is None:
                    session = NativeVoiceSession(
                        device=data.get("device"),
                        on_state=_emit_state,
                        on_level=_emit_level,
                        on_utterance=_on_utterance,
                    )
                mode = data.get("mode", "ptt")
                ok = session.start_listening(mode)
                if not ok:
                    reason = session.diagnostics().get("error") or "failed to start listening"
                    await websocket.send_json(
                        {"type": "error", "message": _native_connect_message(reason, session)}
                    )
            elif msg_type == "stop_listening":
                if session is not None:
                    pcm = session.stop_listening()
                    if session._mode in ("ptt", "tap") and pcm:
                        loop.call_soon_threadsafe(
                            lambda pcm=pcm: asyncio.create_task(_process_utterance(pcm))
                        )
            elif msg_type == "cancel":
                if session is not None:
                    session.cancel()
            elif msg_type == "mic_test_start":
                if session is None:
                    session = NativeVoiceSession(
                        device=data.get("device"),
                        on_state=_emit_state,
                        on_level=_emit_level,
                        on_utterance=_on_utterance,
                    )
                mic_testing = session.mic_test()
                if mic_testing:
                    await websocket.send_json({"type": "mic_test", "status": "started"})
            elif msg_type == "mic_test_stop":
                mic_testing = False
                if session is not None:
                    session.disconnect()
                await websocket.send_json({"type": "mic_test", "status": "stopped"})
            elif msg_type == "confirm":
                tool_name = data.get("tool")
                confirm = bool(data.get("confirm", False))
                pending = pending_tool_confirmations.get(session_id)
                if pending and pending.get("tool") == tool_name:
                    if confirm:
                        tool_args = pending.get("args", {})
                        tool_args["confirm"] = True
                        try:
                            result = await tool_registry.execute_tool(tool_name, tool_args)
                            await websocket.send_json({
                                "type": "response",
                                "text": f"Done. {result.data if result.success else result.error}",
                            })
                        except Exception as exc:
                            await websocket.send_json({
                                "type": "response",
                                "text": f"Action failed: {exc}",
                            })
                    else:
                        await websocket.send_json({
                            "type": "response",
                            "text": "Action cancelled.",
                        })
                    pending_tool_confirmations.pop(session_id, None)
                else:
                    await handle_ws_confirm(session_id, tool_name, confirm, websocket, voice_uid)

    except TimeoutError:
        logger.info("[voice:%s] native idle timeout, closing session %s", voice_uid, session_id)
    except WebSocketDisconnect:
        logger.info(
            "[voice:%s] native client disconnected, session %s saved", voice_uid, session_id
        )
    except Exception as e:
        logger.error("[voice:%s] native websocket error: %s", voice_uid, e)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        if session is not None:
            session.disconnect()


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
        if not full_path or full_path.startswith("api/"):
            return FileResponse(os.path.join(frontend_dist, "index.html"))
        requested = os.path.abspath(os.path.join(frontend_dist, full_path))
        dist_root = os.path.abspath(frontend_dist)
        # Refuse traversal: only files physically inside the dist tree are served.
        if requested != dist_root and not requested.startswith(dist_root + os.sep):
            return FileResponse(os.path.join(frontend_dist, "index.html"))
        if os.path.isfile(requested):
            return FileResponse(requested)
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
