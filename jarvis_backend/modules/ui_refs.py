"""Short-lived, single-use element references for UI interaction.

A reference is bound to a fresh observation: the exact window, the element's
accessibility path, a role+name fingerprint, and its bounding box.  Actions
must present a live reference; stale (expired), already-used, or
no-longer-matching references are rejected.  This prevents clicks from stale
screenshots, guessed coordinates, and duplicate executions.
"""

from __future__ import annotations

import secrets
import threading
import time

REF_TTL_SECONDS = 12.0
_MAX_REFS = 64


class ElementRef:
    __slots__ = (
        "token",
        "window_key",
        "app_name",
        "window_title",
        "path",
        "fingerprint",
        "label",
        "role",
        "bbox",
        "created_at",
        "used",
    )

    def __init__(
        self,
        window_key: str,
        app_name: str,
        window_title: str,
        path: tuple,
        fingerprint: tuple,
        label: str,
        role: str,
        bbox: tuple | None = None,
    ):
        self.token = f"el_{secrets.token_hex(5)}"
        self.window_key = window_key
        self.app_name = app_name
        self.window_title = window_title
        self.path = path
        self.fingerprint = fingerprint
        self.label = label
        self.role = role
        self.bbox = bbox
        self.created_at = time.monotonic()
        self.used = False

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created_at > REF_TTL_SECONDS

    def public(self) -> dict:
        return {
            "element_ref": self.token,
            "role": self.role,
            "label": self.label,
            "app": self.app_name,
            "window": self.window_title,
            "expires_in_ms": max(0, int((REF_TTL_SECONDS - (time.monotonic() - self.created_at)) * 1000)),
        }


class ElementRefRegistry:
    def __init__(self) -> None:
        self._refs: dict[str, ElementRef] = {}
        self._lock = threading.Lock()

    def bind(
        self,
        window_key: str,
        app_name: str,
        window_title: str,
        path: tuple,
        fingerprint: tuple,
        label: str,
        role: str,
        bbox: tuple | None = None,
    ) -> ElementRef:
        ref = ElementRef(window_key, app_name, window_title, path, fingerprint, label, role, bbox)
        with self._lock:
            self._prune_locked()
            if len(self._refs) >= _MAX_REFS:
                oldest = min(self._refs.values(), key=lambda r: r.created_at)
                self._refs.pop(oldest.token, None)
            self._refs[ref.token] = ref
        return ref

    def peek(self, token: str) -> ElementRef | None:
        """Look up without consuming (for classification/verification)."""
        with self._lock:
            self._prune_locked()
            return self._refs.get(token)

    def resolve_for_action(self, token: str) -> ElementRef:
        """Validate a reference for one action.

        Raises ValueError with a safe message when the reference is unknown,
        expired, or already consumed.
        """
        with self._lock:
            self._prune_locked()
            ref = self._refs.get(token)
            if ref is None:
                raise ValueError("That on-screen target has expired. Let me look again.")
            if ref.used:
                raise ValueError("That target was already used. I'll re-check before repeating an action.")
            ref.used = True
            return ref

    def drop(self, token: str) -> None:
        with self._lock:
            self._refs.pop(token, None)

    def _prune_locked(self) -> None:
        expired = [t for t, r in self._refs.items() if r.expired]
        for t in expired:
            self._refs.pop(t, None)


registry = ElementRefRegistry()
