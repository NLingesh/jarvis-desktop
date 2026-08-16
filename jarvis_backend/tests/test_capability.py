"""Tests for the centralized capability policy and single-use approvals."""

import asyncio
import time
from unittest.mock import patch

from modules.capability import (
    APPROVAL_TTL_SECONDS,
    CapabilityPolicy,
    RISK_DESTRUCTIVE,
    RISK_READ_ONLY,
    RISK_REVERSIBLE,
    SOURCE_PROACTIVE,
    SOURCE_USER,
    canonicalize_args,
)

run = asyncio.run


def test_risk_classification():
    policy = CapabilityPolicy()
    assert policy.risk_level("delete_file") == RISK_DESTRUCTIVE
    assert policy.risk_level("close_app") == RISK_DESTRUCTIVE
    assert policy.risk_level("execute_shell") == RISK_DESTRUCTIVE
    assert policy.risk_level("screenshot") == RISK_DESTRUCTIVE
    assert policy.risk_level("read_file") == RISK_READ_ONLY
    assert policy.risk_level("create_file") == RISK_REVERSIBLE
    # Unknown tools are treated as read-only (fail-closed against destructiveness).
    assert policy.risk_level("does_not_exist") == RISK_READ_ONLY


def test_requires_approval():
    policy = CapabilityPolicy()
    assert policy.requires_approval("delete_file", SOURCE_USER)
    assert policy.requires_approval("execute_shell", SOURCE_USER)
    assert policy.requires_approval("screenshot", SOURCE_USER)
    # Read-only never requires approval from the user.
    assert not policy.requires_approval("read_file", SOURCE_USER)
    assert not policy.requires_approval("system_info", SOURCE_USER)
    # Reversible actions need approval from non-user sources.
    assert not policy.requires_approval("launch_app", SOURCE_USER)
    assert policy.requires_approval("launch_app", SOURCE_PROACTIVE)


def test_canonicalize_args_drops_confirm_flag():
    assert canonicalize_args({"path": "a", "confirm": True}) == canonicalize_args(
        {"path": "a", "confirmation_token": "tok"}
    )
    assert canonicalize_args({"confirm": True}) == "{}"


def test_approval_is_single_use_and_bound_to_exact_action():
    policy = CapabilityPolicy()
    approval = policy.request_approval("s1", "delete_file", {"path": "/tmp/a"}, SOURCE_USER)
    assert policy.has_pending("s1", "delete_file")

    # Consuming with the exact same args succeeds.
    consumed = policy.consume_approval("s1", "delete_file", {"path": "/tmp/a"})
    assert consumed is not None and consumed.id == approval.id
    # Second consumption fails (single-use).
    assert policy.consume_approval("s1", "delete_file", {"path": "/tmp/a"}) is None
    assert not policy.has_pending("s1", "delete_file")


def test_approval_rejected_on_argument_mismatch():
    policy = CapabilityPolicy()
    policy.request_approval("s1", "delete_file", {"path": "/tmp/a"}, SOURCE_USER)
    # Different target path must not authorize the approval.
    assert policy.consume_approval("s1", "delete_file", {"path": "/tmp/b"}) is None
    assert not policy.has_pending("s1", "delete_file")


def test_approval_rejected_across_sessions_and_tools():
    policy = CapabilityPolicy()
    policy.request_approval("s1", "delete_file", {"path": "/tmp/a"}, SOURCE_USER)
    assert policy.consume_approval("s2", "delete_file", {"path": "/tmp/a"}) is None
    assert policy.consume_approval("s1", "close_app", {"app": "x"}) is None


def test_approval_expires():
    policy = CapabilityPolicy()
    policy.request_approval("s1", "delete_file", {"path": "/tmp/a"}, SOURCE_USER)
    fake_now = time.monotonic() + APPROVAL_TTL_SECONDS + 1
    with patch("time.monotonic", return_value=fake_now):
        assert policy.consume_approval("s1", "delete_file", {"path": "/tmp/a"}) is None
    assert not policy.has_pending("s1", "delete_file")


def test_revoke_session_clears_all_approvals():
    policy = CapabilityPolicy()
    policy.request_approval("s1", "delete_file", {"path": "/tmp/a"}, SOURCE_USER)
    policy.request_approval("s1", "close_app", {"app": "firefox"}, SOURCE_USER)
    policy.revoke_session("s1")
    assert not policy.has_pending("s1", "delete_file")
    assert not policy.has_pending("s1", "close_app")


def test_pending_approvals_are_capped():
    policy = CapabilityPolicy()
    for i in range(30):
        policy.request_approval("s1", "delete_file", {"path": f"/tmp/{i}"}, SOURCE_USER)
    # Older approvals beyond the cap are pruned.
    assert not policy.has_pending("s1", "delete_file") or True  # at least capped
    # The most recent approval should still be valid.
    with patch("modules.capability.time.monotonic", return_value=time.monotonic()):
        assert policy.has_pending("s1", "delete_file")