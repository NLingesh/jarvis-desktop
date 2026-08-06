"""Tests for settings helper functions: key masking, .env editing, session-token check."""

import os
import tempfile

import pytest
from fastapi import HTTPException, Request

from routes.state import (
    _mask_secret,
    _write_env_keys,
    require_session_token,
    validate_system_command,
)


def test_mask_secret_normal():
    masked = _mask_secret("sk-ant-api03-abc123")
    assert "****" in masked
    assert masked.endswith("123")


def test_mask_secret_short():
    assert _mask_secret("short") == "****"


def test_mask_secret_empty():
    assert _mask_secret("") == ""
    assert _mask_secret(None) == ""


def test_write_env_keys_new_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# config\nDEBUG=False\n")
        path = f.name
    try:
        _write_env_keys(path, {"MY_KEY": "secret123"})
        with open(path) as f:
            content = f.read()
        assert "MY_KEY=secret123" in content
        assert "DEBUG=False" in content
    finally:
        os.unlink(path)


def test_write_env_keys_updates_existing():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("MY_KEY=old_value\nDEBUG=True\n")
        path = f.name
    try:
        _write_env_keys(path, {"MY_KEY": "new_value"})
        with open(path) as f:
            content = f.read()
        assert "MY_KEY=new_value" in content
        assert "DEBUG=True" in content
        assert "old_value" not in content
    finally:
        os.unlink(path)


def test_validate_system_command_allows_echo():
    assert validate_system_command("echo hello") == "echo hello"


def test_validate_system_command_rejects_rm():
    with pytest.raises(HTTPException):
        validate_system_command("rm -rf /")


def test_validate_system_command_rejects_empty():
    with pytest.raises(HTTPException):
        validate_system_command("")


def _make_request(headers=None):
    return Request(
        {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()]}
    )


def test_require_session_token_without_path_allows(monkeypatch):
    """When SESSION_TOKEN_PATH is None, no auth is required (dev mode)."""
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", None)
    req = _make_request({"X-Jarvis-Token": "anything"})
    require_session_token(req)  # should not raise
