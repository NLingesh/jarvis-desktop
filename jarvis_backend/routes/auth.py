"""Authentication routes: register, login, logout, and current-user lookup."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from routes.state import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

CurrentUser = Annotated[dict, Depends(auth_service.require_user)]


def _credentials(body: dict) -> tuple[str, str]:
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    return username, password


@router.post("/register")
async def register(request: Request):
    """Create a user account. Only meaningful when auth is enabled."""
    body = await request.json()
    username, password = _credentials(body)
    user_id = await auth_service.register(username, password)
    return {"success": True, "user_id": user_id, "username": username}


@router.post("/login")
async def login(request: Request):
    """Authenticate and return a bearer session token."""
    body = await request.json()
    username, password = _credentials(body)
    token = await auth_service.login(username, password)
    return {"success": True, "token": token, "token_type": "bearer"}


@router.post("/logout")
async def logout(request: Request, user: CurrentUser):
    token = auth_service.extract_bearer(request)
    await auth_service.logout(token)
    return {"success": True}


@router.get("/me")
async def me(user: CurrentUser):
    return {"user": user}
