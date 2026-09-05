"""Short-term session context for the conversational orchestrator.

Keeps the minimal in-memory state JARVIS needs to resolve references across a
conversation and a multi-step task:

* a bounded rolling turn history (older turns are summarized, never sent raw),
* the most recent tool results (bounded, size-capped),
* paths referenced during the conversation,
* an optional active task label and selected project,
* the last launched application,
* pending approval / clarification references.

Context is keyed by session id, pruned aggressively, and isolated per session:
an older session's context can never contaminate a new one.  Structured fields
(selected_project, last_launched_app, resolved paths) are derived ONLY from
verified tool results -- an LLM-generated claim is stored as conversation text,
never as actionable context.

This is explicitly *not* long-term memory: nothing here is persisted beyond the
process lifetime and the store is capped.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

MAX_TOOL_RESULTS = 6
MAX_RECENT_PATHS = 10
MAX_CONTEXT_AGE_SECONDS = 30 * 60
MAX_SESSIONS = 200
MAX_RESULT_CHARS = 2000
MAX_PROMPT_CHARS = 2500

# Bounded conversation history: recent turns stay verbatim (capped per turn),
# anything older is folded into a compact running summary instead of growing
# the prompt indefinitely.
MAX_TURNS = 8
MAX_TURN_CHARS = 400
MAX_SUMMARY_CHARS = 700


def _cap(value: Any, limit: int = MAX_RESULT_CHARS) -> Any:
    """Truncate a tool result to keep the LLM prompt small."""
    import json

    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    else:
        text = str(value)
    if len(text) > limit:
        return {"truncated": True, "preview": text[:limit]}
    return value


class SessionContext:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.monotonic()
        self.last_active = time.monotonic()
        self.tool_results: deque[dict] = deque(maxlen=MAX_TOOL_RESULTS)
        self.recent_paths: deque[str] = deque(maxlen=MAX_RECENT_PATHS)
        self.turns: deque[dict] = deque(maxlen=MAX_TURNS)
        self.older_summary: str = ""
        self.active_task: str | None = None
        self.selected_project: str | None = None
        self.last_launched_app: str | None = None
        self.pending_tool: str | None = None
        self.pending_args: dict | None = None
        self.pending_clarification: str | None = None
        self.last_reply: str | None = None
        self.last_user_input: str | None = None

    def touch(self) -> None:
        self.last_active = time.monotonic()

    def reset(self) -> None:
        """Clear everything except identity -- used when a session restarts."""
        created = self.created_at
        sid = self.session_id
        self.__init__(sid)
        self.created_at = created

    # ------------------------------------------------------------------ turns

    def _fold_oldest_turn(self) -> None:
        """Move the oldest turn into the compact running summary."""
        if len(self.turns) < self.turns.maxlen:
            return
        oldest = self.turns.popleft()
        role = "user" if oldest.get("role") == "user" else "jarvis"
        line = f"{role}: {oldest.get('text', '')[:120]}"
        parts = [p for p in (self.older_summary, line) if p]
        self.older_summary = "\n".join(parts)[-MAX_SUMMARY_CHARS:]

    def record_turn(self, role: str, text: str) -> None:
        clean = (text or "").strip()[:MAX_TURN_CHARS]
        if not clean:
            return
        while len(self.turns) >= self.turns.maxlen:
            self._fold_oldest_turn()
        self.turns.append({"role": role, "text": clean})
        self.touch()

    def record_exchange(self, user_input: str, reply: str | None = None) -> None:
        """Record one user/assistant exchange in the bounded history."""
        self.last_user_input = (user_input or "").strip()[-1000:] or None
        if user_input:
            self.record_turn("user", user_input)
        if reply is not None:
            self.last_reply = reply.strip()[-1500:] or None
            if reply.strip():
                self.record_turn("assistant", reply)
        self.touch()

    def set_pending_clarification(self, question: str | None) -> None:
        self.pending_clarification = (question or "").strip()[:300] or None
        self.touch()

    # ------------------------------------------------------------ tool results

    def record_tool_result(self, tool: str, args: dict, result: dict) -> None:
        self.tool_results.append(
            {
                "tool": tool,
                "args": args,
                "result": _cap(result),
                "ts": time.monotonic(),
            }
        )
        # Remember paths that were referenced so pronouns like "that folder"
        # can be resolved without re-stating the full path.
        for key in ("path", "source", "destination", "directory"):
            value = (args or {}).get(key)
            if isinstance(value, str) and value.strip():
                self.remember_path(value.strip())
        # Structured context comes ONLY from verified results -- never from
        # model text.
        if isinstance(result, dict) and result.get("success"):
            data = result.get("data")
            data = data if isinstance(data, dict) else {}
            for key in ("opened", "resolved", "path", "directory", "canonical_path"):
                value = data.get(key) if isinstance(data, dict) else None
                if isinstance(value, str) and value.strip():
                    self.remember_path(value.strip())
            if tool == "launch_application":
                app = data.get("launched") or (args or {}).get("app") or ""
                if isinstance(app, str) and app.strip():
                    self.last_launched_app = app.strip()[:100]
        self.touch()

    def remember_path(self, path: str) -> None:
        if isinstance(path, str) and path.strip():
            self.recent_paths.appendleft(path.strip())

    def resolve_path(self, reference: str) -> str | None:
        """Best-effort resolution of a fuzzy path reference to a recent path."""
        ref = (reference or "").strip()
        if not ref:
            return None
        lowered = ref.lower()
        for candidate in self.recent_paths:
            base = candidate.split("/")[-1].lower()
            if lowered in candidate.lower() or lowered == base or base in lowered:
                return candidate
        return None

    # ----------------------------------------------------------------- output

    def context_summary(self) -> dict:
        """Bounded machine-readable summary (for get_current_context)."""
        return {
            "active_task": self.active_task,
            "selected_project": self.selected_project,
            "last_launched_app": self.last_launched_app,
            "pending_clarification": self.pending_clarification,
            "recent_paths": list(self.recent_paths)[:4],
            "turn_count": len(self.turns),
            "has_older_history": bool(self.older_summary),
        }

    def to_prompt(self) -> str:
        """Compact, bounded summary for injection into the orchestrator prompt."""
        lines: list[str] = []
        if self.active_task:
            lines.append(f"Active task: {self.active_task}")
        if self.selected_project:
            lines.append(f"Selected project: {self.selected_project}")
        if self.last_launched_app:
            lines.append(f"Last launched app: {self.last_launched_app}")
        if self.pending_clarification:
            lines.append(f"Open clarification: {self.pending_clarification}")
        if self.older_summary:
            lines.append("Earlier in this conversation (summary):\n" + self.older_summary)
        if self.turns:
            rendered = [
                f"{'user' if t['role'] == 'user' else 'jarvis'}: {t['text']}" for t in self.turns
            ]
            lines.append("Recent turns:\n" + "\n".join(rendered))
        if self.recent_paths:
            lines.append("Recently referenced paths: " + ", ".join(list(self.recent_paths)[:4]))
        if self.tool_results:
            for item in self.tool_results:
                tool = item["tool"]
                result = item["result"]
                ok = result.get("success") if isinstance(result, dict) else True
                snippet = ""
                data = result.get("data") if isinstance(result, dict) else None
                if isinstance(data, dict):
                    text = data.get("text") or data.get("content") or data.get("preview") or ""
                    snippet = text if isinstance(text, str) else ""
                elif isinstance(result, dict) and result.get("error"):
                    snippet = str(result["error"])[:200]
                status = "ok" if ok else "error"
                lines.append(f"[tool:{tool} status={status}] {snippet[:300]}")
        return "\n".join(lines)[:MAX_PROMPT_CHARS]


class SessionContextStore:
    def __init__(self):
        self._contexts: dict[str, SessionContext] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> SessionContext:
        with self._lock:
            self._prune_locked()
            ctx = self._contexts.get(session_id)
            if ctx is None:
                ctx = SessionContext(session_id)
                self._contexts[session_id] = ctx
            ctx.touch()
            return ctx

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._contexts.pop(session_id, None)

    def _prune_locked(self) -> None:
        now = time.monotonic()
        if len(self._contexts) <= MAX_SESSIONS:
            stale = [
                sid
                for sid, ctx in self._contexts.items()
                if now - ctx.last_active > MAX_CONTEXT_AGE_SECONDS
            ]
        else:
            stale = sorted(self._contexts, key=lambda sid: self._contexts[sid].last_active)[
                : len(self._contexts) - MAX_SESSIONS
            ]
        for sid in stale:
            self._contexts.pop(sid, None)
