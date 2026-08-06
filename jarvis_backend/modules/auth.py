"""Opt-in user authentication for the JARVIS backend.

When ``JARVIS_AUTH_ENABLED=true`` every ``/api/*`` route (except login and
register) requires an ``Authorization: Bearer <token>`` header, and the
WebSocket handshake requires an ``access_token`` query parameter. Tokens are
opaque random values stored in SQLite via :class:`modules.memory.MemoryManager`
and expire after ``JARVIS_AUTH_TTL_HOURS`` (default 24).

Passwords are never stored in plain text: they are hashed with PBKDF2-HMAC-SHA256
using a per-user random salt and 200k iterations.
"""

import hashlib
import hmac
import logging
import os
import secrets

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

ENV_AUTH_ENABLED = "JARVIS_AUTH_ENABLED"
ENV_AUTH_TTL_HOURS = "JARVIS_AUTH_TTL_HOURS"
ENV_AUTH_USERNAME = "JARVIS_AUTH_USERNAME"
ENV_AUTH_PASSWORD = "JARVIS_AUTH_PASSWORD"


def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random salt.

    Returns a self-describing string ``pbkdf2_sha256$<iterations>$<salt>$<hash>``.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored hash in constant time."""
    try:
        algorithm, iterations_s, salt_hex, hash_hex = stored.split("$")
        if algorithm != _PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


class AuthService:
    """Login/logout and token verification backed by SQLite."""

    def __init__(self, memory_manager, enabled: bool | None = None):
        self.memory = memory_manager
        self.enabled = bool(
            os.getenv(ENV_AUTH_ENABLED, "false").lower() in ("1", "true", "yes")
            if enabled is None
            else enabled
        )
        self.ttl_hours = int(os.getenv(ENV_AUTH_TTL_HOURS, "24"))

    async def register(self, username: str, password: str) -> str:
        """Create a user account. Returns the user id."""
        user_id = await self.memory.create_user(username, hash_password(password))
        if user_id is None:
            raise HTTPException(status_code=409, detail="Username already exists")
        return user_id

    async def bootstrap_user(self) -> None:
        """Create the configured admin user from env vars, if auth is enabled."""
        if not self.enabled:
            return
        username = os.getenv(ENV_AUTH_USERNAME, "").strip()
        password = os.getenv(ENV_AUTH_PASSWORD, "")
        if not username or not password:
            logger.warning(
                "Auth is enabled but %s / %s are not set; use POST /api/auth/register.",
                ENV_AUTH_USERNAME,
                ENV_AUTH_PASSWORD,
            )
            return
        if await self.memory.get_user(username) is None:
            await self.memory.create_user(username, hash_password(password))
            logger.info("Created bootstrap user %r", username)

    async def login(self, username: str, password: str) -> str:
        """Authenticate and return a fresh session token."""
        user = await self.memory.get_user(username)
        if user is None or not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )
        return await self.memory.create_auth_session(user["id"], ttl_hours=self.ttl_hours)

    async def logout(self, token: str) -> None:
        if token:
            await self.memory.delete_auth_session(token)

    async def current_user(self, token: str) -> dict:
        """Resolve a bearer token to a user dict, or raise 401."""
        session = await self.memory.get_auth_session(token)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
            )
        user = await self.memory.get_user_by_id(session["user_id"])
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
            )
        return user

    def extract_bearer(self, request: Request) -> str:
        """Read the bearer token from the Authorization header, if present."""
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return ""

    async def require_user(self, request: Request) -> dict:
        """FastAPI dependency returning the authenticated user."""
        token = self.extract_bearer(request)
        return await self.current_user(token)

    async def cleanup(self) -> None:
        await self.memory.cleanup_expired_auth_sessions()


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject /api requests that lack a valid bearer token when auth is enabled."""

    OPEN_PATHS = {"/api/auth/login", "/api/auth/register"}

    def __init__(self, app, auth: AuthService):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request, call_next):
        path = request.url.path
        if (
            self.auth.enabled
            and request.method != "OPTIONS"
            and path.startswith("/api/")
            and path not in self.OPEN_PATHS
        ):
            token = self.auth.extract_bearer(request)
            try:
                await self.auth.current_user(token)
            except HTTPException:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or missing session token"},
                )
        return await call_next(request)
