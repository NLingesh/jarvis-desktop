"""Tests for SystemManager.open_application (await/coroutine handling).

Regression coverage for the fix where the async ``SystemActions.open_application``
was wrapped in ``asyncio.to_thread`` producing an unawaited truthy coroutine that
always reported success. Covers success, launch failure, missing application,
timeout, and coroutine cleanup (no "never awaited" warnings).
"""

import asyncio
import warnings

import pytest

from managers.system_manager import SystemManager


def run(coro):
    return asyncio.run(coro)


class _MemoryStub:
    pass


def make_manager(monkeypatch, action_impl=None):
    import modules.system_actions

    if action_impl is not None:
        monkeypatch.setattr(modules.system_actions.SystemActions, "open_application", action_impl)
    manager = SystemManager(_MemoryStub())
    return manager


async def _noop_audit(self, *args, **kwargs):
    return None


def test_open_application_requires_confirm():
    manager = SystemManager(_MemoryStub())
    result = run(manager.open_application("firefox"))
    assert "error" in result
    assert "confirm" in result["error"]


def test_open_application_success(monkeypatch):
    async def fake_action(self, app_name):
        return True

    manager = make_manager(monkeypatch, fake_action)
    result = run(manager.open_application("firefox", confirm=True))
    assert result == {"opened": "firefox"}


def test_open_application_launch_failure(monkeypatch):
    async def fake_action(self, app_name):
        return False

    manager = make_manager(monkeypatch, fake_action)
    result = run(manager.open_application("firefox", confirm=True))
    assert "error" in result
    assert result["reason"] == "launch_failed"
    assert "firefox" in result["error"]


def test_open_application_missing_application(monkeypatch):
    """A non-whitelisted / non-installed app must not be reported as opened."""

    async def fake_action(self, app_name):
        # Mirrors SystemActions: unknown app -> False
        return False

    manager = make_manager(monkeypatch, fake_action)
    result = run(manager.open_application("definitely_not_an_app_xyz", confirm=True))
    assert "error" in result
    assert result["reason"] == "launch_failed"
    assert "opened" not in result


def test_open_application_timeout(monkeypatch):
    async def hanging_action(self, app_name):
        await asyncio.sleep(10)
        return True

    manager = make_manager(monkeypatch, hanging_action)
    result = run(manager.open_application("firefox", confirm=True, timeout=0.05))
    assert "error" in result
    assert result["reason"] == "timeout"
    assert "opened" not in result


def test_open_application_exception_reported(monkeypatch):
    async def broken_action(self, app_name):
        raise RuntimeError("boom")

    manager = make_manager(monkeypatch, broken_action)
    result = run(manager.open_application("firefox", confirm=True))
    assert "error" in result
    assert result["reason"] == "launch_error"


def test_open_application_no_unawaited_coroutine_warning(monkeypatch):
    """The action coroutine must be awaited — no RuntimeWarning, no false success."""

    async def fake_action(self, app_name):
        return False

    manager = make_manager(monkeypatch, fake_action)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = run(manager.open_application("firefox", confirm=True))
    assert "error" in result
    assert not any("never awaited" in str(w.message) for w in caught)


def test_close_application_still_works(monkeypatch):
    import psutil

    manager = SystemManager(_MemoryStub())
    result = run(manager.close_application(app_name="", pid=0, confirm=True))
    assert "error" in result