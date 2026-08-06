from fastapi import APIRouter, HTTPException, Request

from routes.state import mail_sessions

router = APIRouter(prefix="/api/mail", tags=["mail"])


@router.post("/auth")
async def authenticate_mail(request: Request):
    """Authenticate to IMAP mail provider and return a session token.

    Each authentication creates an isolated MailSession; the returned token is
    bound to that connection and is required for inbox/unread access.
    """
    body = await request.json()
    email_address = body.get("email")
    password = body.get("password")
    imap_server = body.get("imap_server", "imap.gmail.com")
    imap_port = body.get("imap_port", 993)

    if not email_address or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    token, ok = await mail_sessions.create(email_address, password, imap_server, imap_port)
    if not ok:
        raise HTTPException(status_code=401, detail="Authentication failed")

    return {"success": True, "token": token}


async def _get_session(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = await mail_sessions.get(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or missing mail session token")
    return session


@router.get("/inbox")
async def get_inbox(request: Request, limit: int = 10):
    """Get recent emails"""
    session = await _get_session(request)
    return {"emails": await session.get_recent_emails(limit=limit)}


@router.get("/unread")
async def get_unread_inbox(request: Request, limit: int = 10):
    """Get unread emails"""
    session = await _get_session(request)
    return {"emails": await session.get_unread_emails(limit=limit)}
