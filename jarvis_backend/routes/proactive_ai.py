from fastapi import APIRouter, HTTPException, Request

from routes.state import proactive_ai

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


@router.get("/suggestions")
async def get_suggestions(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    context = {
        "calendar_events": [],
        "unread_emails": 0,
        "cpu_percent": 0,
    }
    try:
        from routes.state import calendar, mail_sessions

        events = await calendar.get_upcoming_events(days_ahead=1)
        context["calendar_events"] = events or []
    except Exception:
        pass
    try:
        session = await mail_sessions.most_recent()
        if session:
            unread = await session.get_unread_emails(limit=10)
            context["unread_emails"] = len(unread or [])
    except Exception:
        pass
    try:
        from modules.system_actions import SystemActions

        sa = SystemActions()
        sys_info = await sa.get_system_info()
        context["cpu_percent"] = sys_info.get("cpu", {}).get("percent", 0)
    except Exception:
        pass
    suggestions = await proactive_ai.generate_suggestions(context)
    return {"suggestions": suggestions}


@router.post("/notifications")
async def create_notification(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    title = body.get("title", "")
    notif_body = body.get("body", "")
    context = body.get("context")
    if not title or not notif_body:
        raise HTTPException(status_code=400, detail="title and body are required")
    notification = await proactive_ai.generate_notification(title, notif_body, context)
    return notification


@router.post("/suggestions/{suggestion_id}/feedback")
async def suggestion_feedback(suggestion_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    user_action = body.get("action", "dismiss")
    await proactive_ai.record_suggestion_feedback(suggestion_id, user_action)
    return {"feedback_recorded": True}
