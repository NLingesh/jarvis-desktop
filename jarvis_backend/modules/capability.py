"""Centralized capability authorization for privileged local tools.

JARVIS is a privileged local agent, so authorization must not rely on a bare
``confirm=true`` boolean.  This module implements a centralized policy that
evaluates the current session, the requested capability, the normalized
arguments, the risk level, and the source of the instruction.

Approval model
--------------
* Read-only capabilities execute when the scope is clear.
* Reversible side effects execute with verification.
* Destructive or sensitive capabilities require an explicit, **single-use**
  approval that is bound to the exact normalized action (tool + canonical
  arguments) and expires after a short period.

An approval is created server-side and consumed exactly once.  The caller must
present the stored approval id *and* a fresh copy of the arguments, which are
re-hashed and compared before execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# --- Risk levels ------------------------------------------------------------
RISK_READ_ONLY = "read_only"
RISK_REVERSIBLE = "reversible"
RISK_DESTRUCTIVE = "destructive"

# --- Instruction sources ----------------------------------------------------
SOURCE_USER = "user"            # voice/text from the trusted user
SOURCE_SCHEDULED = "scheduled"  # timer/task/workflow automation
SOURCE_PROACTIVE = "proactive"  # background monitor
SOURCE_PLUGIN = "plugin"        # loaded plugin request

USER_SOURCES = {SOURCE_USER}

APPROVAL_TTL_SECONDS = 120
MAX_PENDING_APPROVALS = 20

# Risk classification per tool.  Everything not listed here is treated as
# read-only (fail-closed against unknown tools being destructive).
TOOL_RISK: dict[str, str] = {
    # Read-only
    "system_info": RISK_READ_ONLY,
    "running_processes": RISK_READ_ONLY,
    "file_search": RISK_READ_ONLY,
    "list_directory": RISK_READ_ONLY,
    "read_file": RISK_READ_ONLY,
    "read_document": RISK_READ_ONLY,
    "find_recent_files": RISK_READ_ONLY,
    "find_by_extension": RISK_READ_ONLY,
    "identify_file_type": RISK_READ_ONLY,
    "recall_memory": RISK_READ_ONLY,
    "web_search": RISK_READ_ONLY,
    # Reversible side effects (with verification)
    "create_file": RISK_REVERSIBLE,
    "create_folder": RISK_REVERSIBLE,
    "move_file": RISK_REVERSIBLE,
    "copy_file": RISK_REVERSIBLE,
    "launch_app": RISK_REVERSIBLE,
    "open_terminal": RISK_REVERSIBLE,
    "open_file": RISK_REVERSIBLE,
    "open_folder": RISK_REVERSIBLE,
    "remember_memory": RISK_REVERSIBLE,
    "forget_memory": RISK_REVERSIBLE,
    # Destructive / sensitive
    "delete_file": RISK_DESTRUCTIVE,
    "close_app": RISK_DESTRUCTIVE,
    "execute_shell": RISK_DESTRUCTIVE,
    "screenshot": RISK_DESTRUCTIVE,  # captures screen; sensitive
}

# Capabilities that always need explicit user approval regardless of risk.
ALWAYS_CONFIRM: set[str] = {
    "execute_shell",
    "close_app",
    "delete_file",
    "screenshot",
}


def canonicalize_args(args: dict | None) -> str:
    """Stable, secret-free fingerprint of normalized arguments.

    The ``confirm`` flag is intentionally dropped: approval is about the
    action, not about re-passing a boolean.
    """
    clean = {}
    for key, value in (args or {}).items():
        if key in ("confirm", "confirmation_token"):
            continue
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (int, float)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


@dataclass
class Approval:
    id: str
    session_id: str
    tool: str
    args_hash: str
    source: str
    created_at: float = field(default_factory=time.monotonic)
    consumed: bool = False

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created_at > APPROVAL_TTL_SECONDS


class CapabilityPolicy:
    """Centralized risk evaluation and single-use approval management."""

    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}
        self._session_approvals: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- risk model

    def risk_level(self, tool_name: str) -> str:
        return TOOL_RISK.get(tool_name, RISK_READ_ONLY)

    def requires_approval(self, tool_name: str, source: str) -> bool:
        """Whether a tool call needs explicit approval for this source."""
        risk = self.risk_level(tool_name)
        if risk == RISK_DESTRUCTIVE or tool_name in ALWAYS_CONFIRM:
            return True
        if risk == RISK_REVERSIBLE and source not in USER_SOURCES:
            return True
        return False

    # ---------------------------------------------------------------- approve

    def request_approval(self, session_id: str, tool_name: str, args: dict, source: str) -> Approval:
        """Create a single-use approval bound to this exact action."""
        approval = Approval(
            id=self._make_id(),
            session_id=session_id,
            tool=tool_name,
            args_hash=canonicalize_args(args),
            source=source,
        )
        with self._lock:
            self._prune_locked()
            self._approvals[approval.id] = approval
            self._session_approvals.setdefault(session_id, set()).add(approval.id)
            pending = self._session_approvals.get(session_id, set())
            if len(pending) > MAX_PENDING_APPROVALS:
                oldest = sorted(pending, key=lambda aid: self._approvals[aid].created_at)
                for stale in oldest[: len(pending) - MAX_PENDING_APPROVALS]:
                    self._revoke_locked(stale)
        return approval

    def consume_approval(self, session_id: str, tool_name: str, args: dict) -> Approval | None:
        """Validate and single-use consume the approval for this exact action.

        The approval must exist, belong to this session, target this tool,
        still be unexpired, and match the canonical arguments.  It is consumed
        on success; an expired or mismatched approval is removed.
        """
        args_hash = canonicalize_args(args)
        with self._lock:
            self._prune_locked()
            for approval in list(self._approvals.values()):
                if approval.session_id != session_id:
                    continue
                if approval.tool != tool_name:
                    continue
                if approval.expired or approval.consumed:
                    self._revoke_locked(approval.id)
                    continue
                if approval.args_hash != args_hash:
                    self._revoke_locked(approval.id)
                    continue
                approval.consumed = True
                self._revoke_locked(approval.id)
                return approval
        return None

    def has_pending(self, session_id: str, tool_name: str) -> bool:
        with self._lock:
            for aid in self._session_approvals.get(session_id, set()):
                approval = self._approvals.get(aid)
                if approval and not approval.expired and not approval.consumed:
                    if approval.tool == tool_name:
                        return True
        return False

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            for aid in list(self._session_approvals.get(session_id, set())):
                self._revoke_locked(aid)
            self._session_approvals.pop(session_id, None)

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _make_id() -> str:
        return hashlib.sha256(f"{time.monotonic_ns()}{threading.get_ident()}".encode()).hexdigest()[:16]

    def _prune_locked(self) -> None:
        expired = [
            aid for aid, appr in self._approvals.items() if appr.expired or appr.consumed
        ]
        for aid in expired:
            self._revoke_locked(aid)

    def _revoke_locked(self, approval_id: str) -> None:
        approval = self._approvals.pop(approval_id, None)
        if approval is not None:
            pending = self._session_approvals.get(approval.session_id)
            if pending:
                pending.discard(approval_id)
                if not pending:
                    self._session_approvals.pop(approval.session_id, None)

    def audit_record(self, session_id: str, tool_name: str, args: dict, source: str, result: str) -> dict:
        return {
            "session_id": session_id,
            "tool": tool_name,
            "risk": self.risk_level(tool_name),
            "args": canonicalize_args(args),
            "source": source,
            "result": result,
        }
