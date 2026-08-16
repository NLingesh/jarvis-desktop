"""Short-term session context for the conversational orchestrator.

Keeps the minimal in-memory state JARVIS needs to resolve references across a
conversation and a multi-step task:

* the most recent tool results (bounded, size-capped),
* paths referenced during the conversation,
* an optional active task label,
* the most recent assistant/user exchange tail,
* pending approval references.

This is explicitly *not* long-term memory: nothing here is persisted and the
store is pruned aggressively.
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


def _cap(value: Any, limit: int = MAX_RESULT_CHARS) -> Any:
    """Truncate a tool result to keep the LLM prompt small."""
    import json

    if isinstance(value, dict) or isinstance(value, list):
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
        self.active_task: str | None = None
        self.selected_project: str | None = None
        self.pending_tool: str | None = None
        self.pending_args: dict | None = None
        self.last_reply: str | None = None

    def touch(self) -> None:
        self.last_active = time.monotonic()

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
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                self.recent_paths.appendleft(value.strip())
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

    def to_prompt(self) -> str:
        """Compact, bounded summary for injection into the orchestrator prompt."""
        lines: list[str] = []
        if self.active_task:
            lines.append(f"Active task: {self.active_task}")
        if self.selected_project:
            lines.append(f"Selected project: {self.selected_project}")
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
                lines.append(
                    f"[tool:{tool} status={status}] {snippet[:300]}"
                )
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
            stale = sorted(
                self._contexts, key=lambda sid: self._contexts[sid].last_active
            )[: len(self._contexts) - MAX_SESSIONS]
        for sid in stale:
            self._contexts.pop(sid, None)