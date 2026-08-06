"""Tests for the auth layer — password hashing, sessions, and middleware enforcement."""

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from starlette.routing import Route

from modules.auth import AuthMiddleware, AuthService, hash_password, verify_password
from modules.memory import MemoryManager


def run(mm, coro):
    async def wrapped():
        try:
            return await coro
        finally:
            await mm.close()
            await asyncio.sleep(0.02)

    return asyncio.run(wrapped())


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "auth.db"))


@pytest.fixture
def auth(manager):
    return AuthService(manager, enabled=True)


def auth_run(auth, coro):
    """Run a coroutine against the AuthService, closing its DB connection after."""
    return run(auth.memory, coro)


# --- Password hashing -------------------------------------------------------
def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", stored) is True


def test_password_wrong_value_rejected():
    stored = hash_password("right")
    assert verify_password("wrong", stored) is False


def test_password_empty_stored_rejected():
    assert verify_password("anything", "") is False
    assert verify_password("anything", "garbage") is False


def test_hashes_are_salted():
    first = hash_password("same")
    second = hash_password("same")
    assert first != second


# --- Account lifecycle ------------------------------------------------------
def test_register_and_login(auth):
    auth_run(auth, auth.register("alice", "secret123"))
    token = auth_run(auth, auth.login("alice", "secret123"))
    assert token
    user = auth_run(auth, auth.current_user(token))
    assert user["username"] == "alice"


def test_register_duplicate_username(auth):
    auth_run(auth, auth.register("bob", "pw1"))
    with pytest.raises(HTTPException):
        auth_run(auth, auth.register("bob", "pw2"))


def test_login_wrong_password(auth):
    auth_run(auth, auth.register("carol", "right"))
    with pytest.raises(HTTPException):
        auth_run(auth, auth.login("carol", "wrong"))


def test_login_unknown_user(auth):
    with pytest.raises(HTTPException):
        auth_run(auth, auth.login("ghost", "pw"))


def test_logout_invalidates_token(auth):
    auth_run(auth, auth.register("dave", "pw"))
    token = auth_run(auth, auth.login("dave", "pw"))
    auth_run(auth, auth.logout(token))
    with pytest.raises(HTTPException):
        auth_run(auth, auth.current_user(token))


def test_current_user_unknown_token(auth):
    with pytest.raises(HTTPException):
        auth_run(auth, auth.current_user("not-a-real-token"))


def test_bootstrap_user_from_env(monkeypatch, manager, tmp_path):
    monkeypatch.setenv("JARVIS_AUTH_USERNAME", "admin")
    monkeypatch.setenv("JARVIS_AUTH_PASSWORD", "adminpw")
    service = AuthService(manager, enabled=True)
    auth_run(service, service.bootstrap_user())
    token = auth_run(service, service.login("admin", "adminpw"))
    assert token


def test_disabled_service_skips_bootstrap(monkeypatch, manager):
    monkeypatch.setenv("JARVIS_AUTH_USERNAME", "admin")
    monkeypatch.setenv("JARVIS_AUTH_PASSWORD", "adminpw")
    service = AuthService(manager, enabled=False)
    auth_run(service, service.bootstrap_user())
    with pytest.raises(HTTPException):
        auth_run(service, service.login("admin", "adminpw"))


def test_memory_user_schema(manager):
    user_id = run(manager, manager.create_user("zed", "hash"))
    assert user_id is not None
    user = run(manager, manager.get_user("zed"))
    assert user["password_hash"] == "hash"
    assert run(manager, manager.get_user_by_id(user_id))["username"] == "zed"


# --- HTTP middleware --------------------------------------------------------
def _make_app(auth) -> FastAPI:
    async def protected(request):
        return JSONResponse({"ok": True})

    async def open_route(request):
        return JSONResponse({"open": True})

    app = FastAPI()
    app.router.routes = [
        Route("/api/secret", protected, methods=["GET"]),
        Route("/api/auth/login", open_route, methods=["POST"]),
    ]
    app.add_middleware(AuthMiddleware, auth=auth)
    return app


def test_middleware_blocks_unauthenticated(auth):
    client = TestClient(_make_app(auth))
    response = client.get("/api/secret")
    assert response.status_code == 401


def test_middleware_allows_valid_token(auth):
    auth_run(auth, auth.register("eve", "pw"))
    token = auth_run(auth, auth.login("eve", "pw"))
    client = TestClient(_make_app(auth))
    response = client.get("/api/secret", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_middleware_allows_login_route(auth):
    client = TestClient(_make_app(auth))
    response = client.post("/api/auth/login")
    assert response.status_code != 401


def test_disabled_middleware_does_not_block(manager, tmp_path):
    service = AuthService(manager, enabled=False)
    client = TestClient(_make_app(service))
    assert client.get("/api/secret").status_code == 200
