"""Orchestrator-backed HTTP chat endpoint.

The WebSocket voice path (``/ws/voice``) runs every utterance through the typed
orchestrator, so "open my Downloads folder" dispatches ``open_folder`` and
opens the real folder.  The typed chat path historically bypassed that pipeline
and hit a bare LLM call (``/api/llm/generate``), so desktop commands never
dispatched a tool and the model answered with a generic "can't open" refusal.
This endpoint gives the typed chat UI the same verified pipeline: tool
selection -> normalization -> dispatch -> verified result -> natural reply.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from routes.state import (
    capability_policy,
    memory_manager,
    orchestrator,
    process_command,
    require_session_token,
    session_context_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

_CONFIRM_YES = {
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
}
_CONFIRM_NO = {"no", "nope", "cancel", "stop", "don't", "no don't", "don't do it"}


@router.post("/chat")
async def api_chat(request: Request):
    """Run one user message through the same orchestrator pipeline as voice.

    Expected JSON body:
    - ``message`` or ``prompt``: the user's typed input
    - ``session_id`` (optional): reuse a chat session for follow-up context;
      a new session is created and returned when omitted.

    Returns ``{text, session_id, tool_results?, needs_confirmation?}`` where
    ``text`` is the final natural-language reply.  When the orchestrator
    dispatches tools, their verified results are included so the UI can show
    what actually ran.
    """
    require_session_token(request)
    body = await request.json()
    message = (body.get("message") or body.get("prompt") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    session_id = (body.get("session_id") or "").strip() or None
    if not session_id:
        session_id = await memory_manager.create_session()

    session_ctx = session_context_store.get(session_id)
    session_ctx.record_exchange(message)

    # --- pending single-use approval (yes/no follow-up) ----------------------
    pending_tool = session_ctx.pending_tool
    if pending_tool and capability_policy.has_pending(session_id, pending_tool):
        lowered = message.strip().lower().rstrip(".!?")
        if lowered in _CONFIRM_YES:
            context: dict = {"tools": {}}
            reply = await orchestrator.respond_to_confirmed(session_id, session_ctx, context)
            text = reply or "Done."
            session_ctx.record_exchange("", text)
            await memory_manager.add_message(session_id, "assistant", text)
            return {"text": text, "session_id": session_id, "confirmed": True}
        if lowered in _CONFIRM_NO:
            session_ctx.pending_tool = None
            session_ctx.pending_args = None
            capability_policy.revoke_session(session_id)
            text = "Action cancelled."
            await memory_manager.add_message(session_id, "assistant", text)
            return {"text": text, "session_id": session_id, "confirmed": False}

    await memory_manager.add_message(session_id, "user", message)

    context = await process_command(message, session_id=session_id)

    before = len(session_ctx.tool_results)
    decision = await orchestrator.run(message, session_id, session_ctx, context)
    tools_this = list(session_ctx.tool_results)[before:]

    # Safe operational metadata: endpoint, status, session id, and the tool
    # names/outcomes that actually ran.  Never logs the message body, API keys,
    # tokens, or absolute paths.
    if decision.kind == "error":
        logger.info(
            "chat path=POST /api/chat status=error session=%s tool_count=%d tools=%s",
            session_id,
            len(tools_this),
            [t.get("tool") for t in tools_this],
        )
    else:
        logger.info(
            "chat path=POST /api/chat status=ok session=%s tool_count=%d tools=%s",
            session_id,
            len(tools_this),
            [
                f"{t.get('tool')}:{'ok' if (t.get('result') or {}).get('success') else 'fail'}"
                for t in tools_this
            ],
        )

    if decision.kind == "confirm":
        return {
            "text": decision.reason or "This action needs your approval before I run it.",
            "session_id": session_id,
            "needs_confirmation": True,
            "tool": decision.tool,
            "arguments": decision.arguments or {},
        }

    if decision.kind == "error":
        return {
            "text": "The AI backend is not responding. Check your API keys in .env and try again.",
            "session_id": session_id,
            "error": True,
            "tool_results": tools_this,
        }

    text = (decision.text or "").strip() or "I couldn't generate a response. Please try again."
    session_ctx.record_exchange(message, text)
    await memory_manager.add_message(session_id, "assistant", text)

    return {
        "text": text,
        "session_id": session_id,
        "tool_results": tools_this,
        "needs_confirmation": False,
    }
