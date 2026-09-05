"""Local-first UI observation through AT-SPI2 (the Linux accessibility bus).

Layer 1 source for every screen question: reads the live accessibility tree of
real applications (roles, names, states, text, actions) without screenshots,
coordinates, or shell commands.  Interaction is performed through the toolkit
exposed accessibility actions (click/press/activate) and editable-text APIs --
never synthesized mouse coordinates from stale captures.

Everything here is synchronous and thread-hostile-safe; callers wrap calls in
an executor with deadlines (see managers/ui_interaction.py).  Any failure is
reported as "unavailable", never guessed around.

Bounded by construction: node budget, depth cap, per-node text cap, total text
budget.  Password roles are never read; other content is redacted upstream.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MAX_NODES = 140
MAX_DEPTH = 12
MAX_NODE_TEXT_CHARS = 160
MAX_TOTAL_TEXT_CHARS = 2600
MAX_MATCHES = 8

# JARVIS's own windows must never become automation targets by default.
_SELF_MARKERS = ("jarvis",)

_CLICK_ACTION_NAMES = ("press", "click", "activate", "toggle", "open")

_KEY_ALIASES = {
    "enter": "Return",
    "return": "Return",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "space": "space",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "pageup": "Page_Up",
    "page up": "Page_Up",
    "pagedown": "Page_Down",
    "page down": "Page_Down",
    "home": "Home",
    "end": "End",
    "backspace": "BackSpace",
    "delete": "Delete",
}


class UiAccessUnavailable(RuntimeError):
    """Raised when AT-SPI2 cannot be used on this system."""


def _atspi():
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        return Atspi
    except Exception as exc:  # pragma: no cover - depends on host
        raise UiAccessUnavailable(f"AT-SPI2 bindings unavailable: {exc}") from exc


def available() -> bool:
    try:
        _atspi()
        return True
    except UiAccessUnavailable:
        return False


def _desktop():
    Atspi = _atspi()
    return Atspi.get_desktop(0)


def _state_flags(obj) -> dict:
    try:
        st = obj.get_state_set()
        return {
            "showing": bool(_contains(st, "SHOWING")),
            "sensitive": bool(_contains(st, "SENSITIVE")),
            "focused": bool(_contains(st, "FOCUSED")),
            "active": bool(_contains(st, "ACTIVE")),
            "checked": bool(_contains(st, "CHECKED")),
            "editable": bool(_contains(st, "EDITABLE")),
        }
    except Exception:
        return {"showing": False, "sensitive": True, "focused": False, "active": False, "checked": False, "editable": False}


def _contains(state_set, name: str) -> bool:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return bool(state_set.contains(getattr(Atspi.StateType, name)))


def _safe_text(obj) -> str:
    """Read bounded text from a node's Text interface (never for passwords)."""
    try:
        if obj.get_role_name().lower() in ("password text",):
            return "[redacted]"
        t = obj.query_text()
        count = t.character_count
        if not count:
            return ""
        raw = t.get_text(0, min(count, MAX_NODE_TEXT_CHARS))
        return (raw or "").replace("\n", " ").replace("\r", " ")
    except Exception:
        return ""


def _bbox_of(obj):
    try:
        comp = obj.query_component()
        ext = comp.get_extents(_coord_screen())
        if ext and ext.width > 0 and ext.height > 0:
            return (int(ext.x), int(ext.y), int(ext.width), int(ext.height))
    except Exception:
        pass
    return None


def _coord_screen():
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return Atspi.CoordType.SCREEN


def _node_summary(obj, path: tuple, include_bbox: bool = False) -> dict | None:
    try:
        role = obj.get_role_name() or ""
        raw_name = obj.get_name() or ""
        flags = _state_flags(obj)
        value = ""
        if role.lower() not in ("password text",) and flags["showing"]:
            value = _safe_text(obj)
        entry: dict = {
            "path": list(path),
            "role": role,
            "name": raw_name[:80],
            "showing": flags["showing"],
            "enabled": flags["sensitive"],
            "focused": flags["focused"],
            "checked": flags["checked"],
            "editable": flags["editable"],
        }
        if value.strip():
            entry["text"] = value.strip()
        if include_bbox:
            box = _bbox_of(obj)
            if box:
                entry["bbox"] = list(box)
        try:
            actions = [obj.get_action_name(i) for i in range(min(obj.get_n_actions(), 6))]
            entry["actions"] = [a for a in actions if a]
        except Exception:
            entry["actions"] = []
        return entry
    except Exception:
        return None


def _fingerprint(summary: dict) -> tuple:
    return (summary.get("role"), summary.get("name"))


def iter_apps():
    desk = _desktop()
    try:
        count = desk.get_child_count()
    except Exception as exc:
        raise UiAccessUnavailable(f"accessibility desktop unreadable: {exc}") from exc
    for i in range(min(count, 40)):
        try:
            yield desk.get_child_at_index(i)
        except Exception:
            continue


def list_windows(include_self: bool = False) -> list[dict]:
    """All visible top-level frames: {window_key, app, title, active, pid}."""
    my_pid = os.getpid()
    windows: list[dict] = []
    for app in iter_apps():
        try:
            app_name = app.get_name() or ""
            if not include_self and any(m in app_name.lower() for m in _SELF_MARKERS):
                continue
            try:
                pid = app.get_process_id()
            except Exception:
                pid = None
            for j in range(min(app.get_child_count() or 0, 12)):
                try:
                    frame = app.get_child_at_index(j)
                    if frame is None:
                        continue
                    if frame.get_role_name().lower() not in ("frame", "window", "dialog"):
                        continue
                    flags = _state_flags(frame)
                    if not flags["showing"]:
                        continue
                    title = (frame.get_name() or "")[:100]
                    windows.append(
                        {
                            "window_key": f"{app_name}|{title}",
                            "app": app_name,
                            "title": title,
                            "active": flags["active"] or flags["focused"],
                            "pid": pid,
                            "path": (j,),
                        }
                    )
                except Exception:
                    continue
        except Exception:
            continue
    # Stable ordering: active window first.
    windows.sort(key=lambda w: not w["active"])
    return windows


def resolve_window(window_id: str | None = None, include_self: bool = False) -> tuple[object, dict]:
    """Resolve a window_key (or the active window) to (frame_object, info)."""
    wins = list_windows(include_self=include_self)
    if not wins:
        raise UiAccessUnavailable("No readable application windows found.")
    if window_id:
        for w in wins:
            if w["window_key"] == window_id:
                break
        else:
            raise KeyError(f"Window '{window_id}' is not currently available.")
    else:
        w = wins[0]
    app = None
    for cand in iter_apps():
        try:
            if (cand.get_name() or "") == w["app"]:
                app = cand
                break
        except Exception:
            continue
    if app is None:
        raise UiAccessUnavailable(f"Application '{w['app']}' is no longer accessible.")
    frame = app.get_child_at_index(w["path"][0])
    if frame is None:
        raise UiAccessUnavailable(f"Window '{w['title']}' just closed.")
    return frame, w


def read_tree(window_id: str | None = None, max_nodes: int = MAX_NODES):
    """Structured bounded snapshot of a window's accessibility tree."""
    frame, info = resolve_window(window_id)
    nodes: list[dict] = []

    def walk(obj, path: tuple, depth: int) -> int:
        if len(nodes) >= max_nodes or depth > MAX_DEPTH:
            return 0
        summary = _node_summary(obj, path)
        if summary is None:
            return 0
        nodes.append(summary)
        added = 1
        try:
            child_count = obj.get_child_count()
        except Exception:
            child_count = 0
        for i in range(min(child_count, 30)):
            try:
                child = obj.get_child_at_index(i)
            except Exception:
                continue
            if child is None:
                continue
            added += walk(child, path + (i,), depth + 1)
            if len(nodes) >= max_nodes:
                break
        return added

    walk(frame, (), 0)
    return {
        "window": {k: info[k] for k in ("window_key", "app", "title", "active")},
        "nodes": nodes,
        "truncated": len(nodes) >= max_nodes,
    }


def read_visible_text(window_id: str | None = None, budget: int = MAX_TOTAL_TEXT_CHARS) -> dict:
    """Visible text content only (SHOWING text-capable nodes), bounded."""
    frame, info = resolve_window(window_id)
    lines: list[str] = []
    used = 0
    truncated = False

    def walk(obj, depth: int) -> None:
        nonlocal used, truncated
        if truncated or depth > MAX_DEPTH:
            return
        try:
            summary = _node_summary(obj, ())
        except Exception:
            return
        if summary and summary["showing"]:
            text = summary.get("text") or summary.get("name") or ""
            text = text.strip()
            if text:
                line = text[:200]
                if used + len(line) > budget:
                    truncated = True
                    return
                lines.append(line)
                used += len(line) + 1
        try:
            child_count = obj.get_child_count()
        except Exception:
            child_count = 0
        for i in range(min(child_count, 30)):
            try:
                child = obj.get_child_at_index(i)
            except Exception:
                continue
            if child is not None:
                walk(child, depth + 1)
            if truncated:
                return

    walk(frame, 0)
    return {
        "window": {k: info[k] for k in ("window_key", "app", "title")},
        "lines": lines,
        "chars": used,
        "truncated": truncated,
    }


def find_elements(query: str, role: str | None = None, window_id: str | None = None) -> list[dict]:
    """Find visible elements by accessible name / label / visible text."""
    lowered = (query or "").strip().lower()
    role_filter = (role or "").strip().lower()
    frame, info = resolve_window(window_id)
    matches: list[dict] = []

    def walk(obj, path: tuple, depth: int) -> None:
        if len(matches) >= MAX_MATCHES or depth > MAX_DEPTH:
            return
        summary = _node_summary(obj, path)
        if summary is None:
            return
        haystack = " ".join(
            part for part in (summary.get("name"), summary.get("text")) if part
        ).lower()
        if lowered and lowered in haystack and (not role_filter or role_filter in summary["role"].lower()):
            if summary["showing"]:
                match = dict(summary)
                match["bbox"] = _bbox_of(obj)
                match["fingerprint"] = list(_fingerprint(summary))
                matches.append(match)
        try:
            child_count = obj.get_child_count()
        except Exception:
            child_count = 0
        for i in range(min(child_count, 30)):
            try:
                child = obj.get_child_at_index(i)
            except Exception:
                continue
            if child is not None:
                walk(child, path + (i,), depth + 1)

    walk(frame, (), 0)
    return [
        {
            "app": info["app"],
            "window_key": info["window_key"],
            "window_title": info["title"],
            **m,
        }
        for m in matches
    ]


def node_from_path(app_name: str, frame_index: int, path: tuple):
    """Re-resolve a live object from app/frame/index-path (freshness check)."""
    for app in iter_apps():
        try:
            if (app.get_name() or "") != app_name:
                continue
            frame = app.get_child_at_index(frame_index)
            if frame is None:
                return None
            node = frame
            for idx in path:
                try:
                    if idx >= node.get_child_count():
                        return None
                    node = node.get_child_at_index(idx)
                except Exception:
                    return None
                if node is None:
                    return None
            return node
        except Exception:
            continue
    return None


def click_node(node) -> str:
    """Invoke the node's primary action; returns the action name used."""
    try:
        action = node.query_action()
        count = action.n_actions
        for i in range(count):
            name = (action.get_name(i) or "").lower()
            if name in _CLICK_ACTION_NAMES:
                if action.do_action(i):
                    return name
        # Fallback: any action at all.
        if count > 0 and action.do_action(0):
            return action.get_name(0) or "action"
    except Exception as exc:
        raise RuntimeError(f"Element exposes no clickable action ({exc.__class__.__name__}).") from exc
    raise RuntimeError("Element exposes no clickable action.")


def grab_focus(node) -> bool:
    try:
        comp = node.query_component()
        return bool(comp.grab_focus())
    except Exception:
        return False


def activate_frame(frame) -> bool:
    """Raise/activate a window frame without synthetic mouse input."""
    try:
        action = frame.query_action()
        for i in range(action.n_actions):
            name = (action.get_name(i) or "").lower()
            if name in ("activate", "raise", "click"):
                if action.do_action(i):
                    return True
    except Exception:
        pass
    return grab_focus(frame)


def set_text(node, text: str) -> bool:
    """Replace an editable element's contents via its EditableText interface."""
    try:
        editable = node.query_editable_text()
        return bool(editable.set_text_contents(text))
    except Exception:
        return False


def read_value(node) -> str:
    return _safe_text(node)


def press_key(key: str) -> bool:
    """Synthesize one allowed key press-release into the FOCUSED window."""
    Atspi = _atspi()
    canonical = _KEY_ALIASES.get((key or "").strip().lower())
    if not canonical:
        raise ValueError(f"Key '{key}' is not on the allowed key list.")
    try:
        # SYNTH_TYPE_KEYSYM = 1: send keysym string (no raw keycodes).
        return bool(Atspi.generate_keyboard_event(0, canonical, 1))
    except Exception as exc:
        raise RuntimeError(f"Key synthesis failed: {exc.__class__.__name__}") from exc


def screenshot_region(bbox: tuple | None) -> bytes:
    """Capture a screen region (active window rect) in-memory as PNG bytes."""
    from io import BytesIO

    from PIL import ImageGrab

    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ocr_png(png_bytes: bytes) -> tuple[str, float]:
    """Local OCR (pytesseract). Returns (text, mean_confidence)."""
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes))
    try:
        import pytesseract

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        words = [w for w in data.get("text", []) if str(w).strip()]
        confs = [float(c) for c, w in zip(data.get("conf", []), data.get("text", [])) if str(w).strip() and float(c) >= 0]
        text = pytesseract.image_to_string(img)
        confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.5
        return text, round(confidence, 2)
    except Exception as exc:
        raise UiAccessUnavailable(f"OCR unavailable: {exc.__class__.__name__}") from exc
