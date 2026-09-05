"""Verified desktop opener (xdg-open) without a shell.

Returns success only after the platform opener (xdg-open / open) has actually
been invoked and exited cleanly, so callers never report a window as "opened"
when the desktop handler refused or was missing.  No ``shell=True`` anywhere:
targets are passed as a single argument to the opener binary.

Every failed open attempt carries diagnostic metadata (action type, resolved
executable or canonical path, current user id, whether a graphical session is
present, exit code, safe stderr category, timeout/permission result) so callers
and audits can see exactly why the open failed without leaking environment
values.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field

# Bounded ceiling for a desktop-handoff.  xdg-open normally exits in well under
# a second, but a cold application start or a busy D-Bus can take a few seconds;
# a shorter hard timeout (the old 2.0s) turns slow-but-successful opens into
# false "cannot open" failures.
DEFAULT_TIMEOUT = 5.0

# GUI session variables whose PRESENCE is reported in diagnostics.  Values are
# never read or logged.
_GUI_ENV_VARS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_TYPE",
)

# Safe, low-cardinality stderr categories for diagnostics (never raw stderr).
_STDERR_CATEGORIES = (
    (
        "no-application-registered",
        ("no method available", "no application registered", "no handler"),
    ),
    ("no-graphical-session", ("cannot open display", "no protocol specified", "wayland display")),
    ("permission-denied", ("permission denied", "not authorized", "access denied")),
)


@dataclass
class OpenDiagnostics:
    """Safe, value-free metadata for a desktop-open attempt."""

    action_type: str
    target: str
    resolved_executable: str | None = None
    canonical_path: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    gui_env: dict[str, bool] = field(default_factory=dict)
    exit_code: int | None = None
    stderr_category: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT
    timed_out: bool = False
    permission_result: str | None = None

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "resolved_executable": self.resolved_executable,
            "canonical_path": self.canonical_path,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "gui_env": self.gui_env,
            "exit_code": self.exit_code,
            "stderr_category": self.stderr_category,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "permission_result": self.permission_result,
        }


class DesktopOpenError(OSError):
    """An open attempt failed; ``diagnostics`` carries the safe metadata."""

    def __init__(self, message: str, diagnostics: OpenDiagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics.to_dict()


def gui_env_presence() -> dict[str, bool]:
    """Presence flags for graphical-session variables (values are never read)."""
    return {var: bool(os.environ.get(var)) for var in _GUI_ENV_VARS}


def has_graphical_session() -> bool:
    """Whether the current process could reach a display server."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def base_diagnostics(
    action_type: str,
    target: str,
    *,
    permission_result: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> OpenDiagnostics:
    """Build a diagnostics record with the environment/user fields filled in."""
    diag = OpenDiagnostics(
        action_type=action_type,
        target=target,
        timeout_seconds=timeout,
        permission_result=permission_result,
    )
    diag.user_id, diag.user_name = _current_user()
    diag.gui_env = gui_env_presence()
    return diag


def failure_diagnostics(
    action_type: str,
    target: str,
    exc: Exception,
    *,
    permission_result: str | None = None,
) -> dict:
    """Return the best available diagnostics for a failed open.

    Prefers the rich metadata attached by ``DesktopOpenError`` and stamps the
    caller-accurate ``action_type``/``permission_result`` onto it; falls back to
    environment/user fields for unexpected errors.
    """
    if isinstance(exc, DesktopOpenError) and exc.diagnostics:
        diag = dict(exc.diagnostics)
        diag["action_type"] = action_type
        diag["permission_result"] = permission_result
        return diag
    return base_diagnostics(action_type, target, permission_result=permission_result).to_dict()


def classify_stderr(stderr: str) -> str | None:
    """Map stderr text to a safe, low-cardinality category (or None)."""
    text = (stderr or "").lower()
    if not text.strip():
        return None
    for category, markers in _STDERR_CATEGORIES:
        if any(marker in text for marker in markers):
            return category
    return "other"


def desktop_open(
    target: str,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    action_type: str = "target",
    permission_result: str | None = None,
) -> None:
    """Open ``target`` (path or URL) with the default desktop handler.

    Raises ``DesktopOpenError`` (an ``OSError``) whose ``.diagnostics`` field
    carries the diagnostic metadata when the opener is missing, there is no
    graphical session, the opener times out, or it exits non-zero.
    """
    target = (target or "").strip()
    diag = base_diagnostics(
        action_type, target, permission_result=permission_result, timeout=timeout
    )
    if not target:
        diag.permission_result = "empty-target"
        raise DesktopOpenError("Empty target", diag)

    system = platform.system()
    if system == "Windows":
        try:
            os.startfile(target)  # noqa: S606  (Windows-only, no shell)
            diag.exit_code = 0
            return
        except OSError as exc:
            diag.stderr_category = "other"
            raise DesktopOpenError(str(exc), diag) from None

    opener = _pick_opener(system)
    diag.resolved_executable = opener
    if opener is None:
        message = (
            "xdg-open is not installed, so I can't open this with the desktop handler"
            if system == "Linux"
            else "The 'open' command is not available"
        )
        raise DesktopOpenError(message, diag)

    if system == "Linux" and not has_graphical_session():
        diag.stderr_category = "no-graphical-session"
        diag.permission_result = "no-graphical-session"
        raise DesktopOpenError(
            "I can't open this because JARVIS is running without a graphical session "
            "(no DISPLAY or WAYLAND_DISPLAY is set), so there is no desktop to show a window in.",
            diag,
        )

    diag.canonical_path = _canonicalize(target)
    _run(opener, [target], timeout, diag)


def _pick_opener(system: str) -> str | None:
    if system == "Linux":
        return shutil.which("xdg-open")
    if system == "Darwin":
        return shutil.which("open")
    return None


def _run(opener: str, args: list[str], timeout: float, diag: OpenDiagnostics) -> None:
    stderr_path = None
    try:
        fd, stderr_path = tempfile.mkstemp(prefix="jarvis-open-", suffix=".err")
        os.close(fd)
        with open(stderr_path, "wb") as stderr_f:
            try:
                proc = subprocess.Popen(
                    [opener, *args],
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_f,
                    start_new_session=True,
                )
            except OSError as exc:
                diag.stderr_category = "spawn-failed"
                raise DesktopOpenError(
                    f"The desktop handler could not be started: {exc}", diag
                ) from None

        # Wait only for the opener process itself.  Redirecting stderr through
        # a pipe would be inherited by the launched application, so
        # ``communicate()`` would block until the app exits; ``wait()`` returns
        # as soon as the desktop handoff is done.
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            diag.timed_out = True
            diag.stderr_category = "timeout"
            # The handler may have already dispatched the application before the
            # timeout; claim nothing rather than asserting "nothing was opened".
            raise DesktopOpenError(
                f"The desktop handler took longer than {timeout:g} seconds to respond. "
                "The application may still have opened.",
                diag,
            ) from None

        stderr = _read_stderr(stderr_path)
        diag.exit_code = rc
        if rc != 0:
            diag.stderr_category = classify_stderr(stderr)
            raise DesktopOpenError(
                f"The desktop handler exited with code {rc}; nothing was opened.{_exit_hint(rc, stderr)}",
                diag,
            )
    finally:
        if stderr_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(stderr_path)


def _read_stderr(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(2048).decode(errors="replace")
    except OSError:
        return ""


def _exit_hint(rc: int, stderr: str) -> str:
    if rc == 3:
        return " The desktop has no application registered to open this type."
    category = classify_stderr(stderr)
    if category == "no-application-registered":
        return " The desktop has no application registered to open this type."
    if category == "no-graphical-session":
        return " The desktop reported no display available."
    if category == "permission-denied":
        return " The desktop denied permission to open this."
    return ""


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the opener's process group so no spawned child survives."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=2.0)


def _canonicalize(target: str) -> str | None:
    if "://" in target:
        return target
    try:
        from pathlib import Path

        return str(Path(target).expanduser().resolve())
    except OSError:
        return target


def _current_user() -> tuple[int | None, str | None]:
    try:
        uid = os.getuid()
    except AttributeError:
        return None, None
    name = None
    try:
        import pwd

        name = pwd.getpwuid(uid).pw_name
    except Exception:
        try:
            name = os.getenv("USER") or os.getenv("LOGNAME")
        except Exception:
            name = None
    return uid, name
