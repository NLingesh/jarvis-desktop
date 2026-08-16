import asyncio
import base64
import io
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from PIL import Image

from managers.memory_manager import ALLOWED_FILE_BASE
from modules.audit import log_action
from modules.capability import APPROVAL_TTL_SECONDS, SOURCE_USER
from modules.limits import MAX_CREATE_FILE_BYTES, MAX_OCR_B64_CHARS
from modules.path_policy import is_sensitive_path
from routes.state import (
    capability_policy,
    memory_manager,
    require_session_token,
    system_manager,
)

TERMINAL_ALLOWLIST = {
    "ls", "pwd", "whoami", "uname", "date", "uptime", "df", "du", "free",
    "ps", "top", "stat", "echo", "cat", "head", "tail", "grep", "find",
    "wc", "tree", "env", "id", "hostname", "who", "which", "locale",
    "sysctl", "nproc", "printenv", "history",
}
for _extra in (os.getenv("TERMINAL_ALLOWLIST_EXTRA", "") or "").split(","):
    if _extra.strip():
        TERMINAL_ALLOWLIST.add(_extra.strip())

TERMINAL_EXEC_TIMEOUT = float(os.getenv("TERMINAL_EXEC_TIMEOUT", "60"))
TERMINAL_OUTPUT_CAP = 1_048_576  # bytes of accumulated output kept per task
_TERMINAL_METACHARS = set(";&|<>`$()\n\r")

ALLOWED_APPS = {
    "firefox",
    "chrome",
    "chromium",
    "chromium-browser",
    "thunderbird",
    "evolution",
    "nautilus",
    "dolphin",
    "code",
    "code-oss",
    "vim",
    "nvim",
    "nano",
    "gedit",
    "terminal",
    "konsole",
    "alacritty",
    "kitty",
    "tilix",
    "libreoffice",
    "libreoffice-writer",
    "libreoffice-calc",
    "vlc",
    "audacious",
    "rhythmbox",
    "spotify",
    "gnome-settings",
    "systemsettings",
    "blender",
    "gimp",
    "inkscape",
    "file-roller",
    "evince",
    "okular",
    "gnome-calculator",
    "xfce4-terminal",
    "xterm",
    "wezterm",
    "sublime_text",
    "atom",
    "figma",
}

router = APIRouter(prefix="/api/tools", tags=["tools"])

_task_registry: dict[str, dict] = {}


def _safe_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    base = Path(ALLOWED_FILE_BASE).resolve()
    if not _within(p, base):
        raise HTTPException(status_code=403, detail="Path outside allowed scope")
    return p


def _within(p: Path, base: Path) -> bool:
    """Prefix-safe containment check (avoids /home/user matching /home/user2)."""
    try:
        return os.path.commonpath([str(p), str(base)]) == str(base)
    except ValueError:
        return False


def _http_session_id(request: Request) -> str:
    """Session binding for HTTP tool calls.

    Uses the session token when one is presented (packaged mode); a fixed dev
    identity otherwise (loopback-only dev context, where no token is set).
    """
    return request.headers.get("X-Jarvis-Token") or "dev-http"


def _consume_or_issue_approval(
    request: Request, body: dict, tool_name: str, args: dict
) -> dict | None:
    """Server-authoritative confirmation gate.

    A client-sent ``confirm`` boolean is NOT treated as authorization.  If the
    request carries an ``approval_id``, the matching pending approval is
    consumed (bound to this session, tool, and normalized arguments; single-use;
    TTL-bounded) and ``None`` is returned so the caller may execute.  Otherwise
    a pending approval is issued and returned so the caller can respond without
    executing.
    """
    approval_id = (body.get("approval_id") or "").strip()
    if approval_id:
        approval = capability_policy.consume_approval(
            _http_session_id(request), tool_name, args
        )
        if approval is None:
            raise HTTPException(
                status_code=401,
                detail="Approval is missing, expired, already used, or does not match this action",
            )
        return None
    approval = capability_policy.request_approval(
        _http_session_id(request), tool_name, args, SOURCE_USER
    )
    return {
        "approval_required": True,
        "approval_id": approval.id,
        "tool": tool_name,
        "expires_in": APPROVAL_TTL_SECONDS,
    }


def _validate_terminal_command(command: str) -> str:
    """Allowlist + single-command enforcement for /terminal/execute.

    The command must be a single invocation of an allowlisted binary with
    plain-token arguments: no shell metacharacters (pipes, redirects,
    subshells, variable expansion), so the executed argv can never be
    augmented by shell features.
    """
    cmd = command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="command is required")
    if any(c in _TERMINAL_METACHARS for c in cmd):
        raise HTTPException(
            status_code=400, detail="Shell metacharacters are not allowed in terminal commands"
        )
    first, _, args = cmd.partition(" ")
    if first.startswith("-"):
        raise HTTPException(status_code=400, detail="Command may not start with an option flag")
    name = first.rsplit("/", 1)[-1]
    if name not in TERMINAL_ALLOWLIST:
        allowed = ", ".join(sorted(TERMINAL_ALLOWLIST))
        raise HTTPException(
            status_code=403,
            detail=f"Command '{first}' is not in the allowed terminal list. Allowed: {allowed}",
        )
    return cmd


# --- File Tools -------------------------------------------------------------
@router.get("/files/search")
async def search_files(q: str, request: Request):
    require_session_token(request)
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    await log_action("files.search", q, "session_token", "started")
    base = Path(ALLOWED_FILE_BASE).expanduser().resolve()
    q_lower = q.lower()
    matches = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if q_lower in fname.lower():
                full = Path(root) / fname
                rel = str(full.relative_to(base))
                try:
                    size = full.stat().st_size
                except OSError:
                    size = 0
                matches.append({"path": rel, "name": fname, "size": size})
        if len(matches) >= 50:
            break
    await log_action("files.search", q, "session_token", f"found {len(matches)}")
    return {"results": matches[:50]}


@router.get("/files/read")
async def read_file(path: str, request: Request):
    require_session_token(request)
    p = _safe_path(path)
    if is_sensitive_path(p):
        raise HTTPException(status_code=403, detail="Refusing to read a sensitive path")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    size = p.stat().st_size
    if size > 1_048_576:
        raise HTTPException(status_code=413, detail="File exceeds 1MB limit")
    content = p.read_text(encoding="utf-8", errors="replace")
    await log_action(
        "files.read",
        str(p.relative_to(Path(ALLOWED_FILE_BASE).resolve())),
        "session_token",
        "success",
    )
    return {"path": str(p), "content": content, "size": size}


@router.post("/files/create")
async def create_file(request: Request):
    require_session_token(request)
    body = await request.json()
    path = body.get("path", "")
    content = body.get("content", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    p = _safe_path(path)
    if is_sensitive_path(p):
        raise HTTPException(status_code=403, detail="Refusing to write a sensitive path")
    if len(content) > MAX_CREATE_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Content exceeds 1MB limit")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    await log_action(
        "files.create",
        str(p.relative_to(Path(ALLOWED_FILE_BASE).resolve())),
        "session_token",
        "success",
    )
    return {"path": str(p), "size": len(content)}


@router.post("/files/info")
async def file_info(request: Request):
    require_session_token(request)
    body = await request.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    p = _safe_path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    stat = p.stat()
    mime = "application/octet-stream"
    try:
        import mimetypes

        mime = mimetypes.guess_type(str(p))[0] or mime
    except Exception:
        pass
    await log_action(
        "files.info",
        str(p.relative_to(Path(ALLOWED_FILE_BASE).resolve())),
        "session_token",
        "success",
    )
    return {
        "path": str(p),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "type": mime,
        "is_dir": p.is_dir(),
    }


# --- Desktop Tools ----------------------------------------------------------
@router.post("/clipboard/read")
async def clipboard_read(request: Request):
    require_session_token(request)
    await log_action("clipboard.read", "clipboard", "session_token", "started")
    try:
        proc = await asyncio.create_subprocess_exec(
            "xclip",
            "-selection",
            "clipboard",
            "-o",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        text = stdout.decode(errors="replace") if stdout else ""
        if proc.returncode != 0:
            text = stderr.decode(errors="replace") if stderr else ""
        await log_action(
            "clipboard.read", "clipboard", "session_token", "success" if text else "empty"
        )
        return {"text": text}
    except FileNotFoundError:
        await log_action("clipboard.read", "clipboard", "session_token", "xclip_not_found")
        raise HTTPException(status_code=501, detail="xclip not available on this system") from None
    except Exception as e:
        await log_action("clipboard.read", "clipboard", "session_token", f"error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/ocr")
async def ocr_image(request: Request):
    require_session_token(request)
    body = await request.json()
    image_b64 = body.get("image_base64", "")
    if not image_b64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    if len(image_b64) > MAX_OCR_B64_CHARS:
        raise HTTPException(status_code=413, detail="Image exceeds size limit")
    await log_action("ocr", "image", "session_token", "started")
    try:
        raw = base64.b64decode(image_b64)
        Image.MAX_IMAGE_PIXELS = 50_000_000
        img = Image.open(io.BytesIO(raw))
        try:
            import pytesseract

            text = pytesseract.image_to_string(img)
        except Exception:
            text = "[OCR unavailable: pytesseract not installed]"
        await log_action("ocr", "image", "session_token", "success")
        return {"text": text}
    except Exception as e:
        await log_action("ocr", "image", "session_token", f"error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/terminal/execute")
async def terminal_execute(request: Request):
    require_session_token(request)
    body = await request.json()
    command = _validate_terminal_command(body.get("command", ""))
    gate = _consume_or_issue_approval(request, body, "execute_terminal", {"command": command})
    if gate:
        return gate
    task_id = secrets.token_urlsafe(16)
    _task_registry[task_id] = {
        "status": "running",
        "preview": command,
        "output": "",
        "returncode": None,
        "command": command,
    }
    await log_action("terminal.execute", command, "session_token", f"started task={task_id}")

    async def _run():
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            chunks = []
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=TERMINAL_EXEC_TIMEOUT)
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    chunks.append(decoded)
                    joined = "".join(chunks)
                    if len(joined) > TERMINAL_OUTPUT_CAP:
                        joined = joined[-TERMINAL_OUTPUT_CAP:] + "\n[output truncated]\n"
                        chunks = [joined]
                    _task_registry[task_id]["output"] = joined
                await proc.wait()
                _task_registry[task_id]["returncode"] = proc.returncode
                _task_registry[task_id]["status"] = "completed"
            except asyncio.TimeoutError:
                if hasattr(os, "killpg") and proc.pid and proc.returncode is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except (ProcessLookupError, PermissionError):
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                else:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                _task_registry[task_id]["status"] = "timed_out"
                _task_registry[task_id]["returncode"] = -1
                _task_registry[task_id]["output"] += "\n[timed out]\n"
            await log_action(
                "terminal.execute",
                command,
                "session_token",
                f"finished status={_task_registry[task_id]['status']}",
            )
        except Exception as e:
            _task_registry[task_id]["status"] = "failed"
            _task_registry[task_id]["output"] = str(e)
            _task_registry[task_id]["returncode"] = -1
            await log_action("terminal.execute", command, "session_token", f"error: {e}")

    asyncio.get_running_loop().create_task(_run())
    return {"task_id": task_id, "preview": command, "status": "running"}


@router.get("/terminal/status/{task_id}")
async def terminal_status(task_id: str, request: Request):
    require_session_token(request)
    task = _task_registry.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task_id,
        "status": task["status"],
        "preview": task["preview"],
        "output": task["output"],
        "returncode": task["returncode"],
    }


@router.get("/audit")
async def get_audit(request: Request):
    require_session_token(request)
    entries = await memory_manager.get_audit_log(limit=200)
    return {"audit": entries}


@router.post("/audit/clear")
async def clear_audit(request: Request):
    require_session_token(request)
    gate = _consume_or_issue_approval(request, await request.json(), "audit_clear", {})
    if gate:
        return gate
    await memory_manager.clear_audit_log()
    await log_action("audit.clear", "audit_log", "session_token", "success")
    return {"cleared": True}


# --- System Control via SystemManager ----------------------------------------
@router.post("/system/command")
async def system_command(request: Request):
    require_session_token(request)
    body = await request.json()
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    gate = _consume_or_issue_approval(request, body, "system_command", {"command": command})
    if gate:
        return gate
    result = await system_manager.execute_command(command, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@router.post("/apps/open")
async def open_app(request: Request):
    require_session_token(request)
    body = await request.json()
    app_name = (body.get("app_name") or "").strip().lower()
    if not app_name:
        raise HTTPException(status_code=400, detail="app_name is required")
    gate = _consume_or_issue_approval(request, body, "open_app", {"app_name": app_name})
    if gate:
        return gate
    result = await system_manager.open_application(app_name, confirm=True)
    if "error" in result:
        raise HTTPException(
            status_code=403, detail=result["error"], headers={"X-Jarvis-Reason": result.get("reason", "launch_failed")}
        )
    return result


@router.post("/apps/close")
async def close_app(request: Request):
    require_session_token(request)
    body = await request.json()
    app_name = (body.get("app_name") or "").strip()
    pid = body.get("pid")
    gate = _consume_or_issue_approval(
        request, body, "close_app", {"app_name": app_name, "pid": pid}
    )
    if gate:
        return gate
    result = await system_manager.close_application(app_name=app_name, pid=pid, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/files/delete")
async def delete_file(request: Request):
    require_session_token(request)
    body = await request.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    gate = _consume_or_issue_approval(request, body, "delete_file", {"path": path})
    if gate:
        return gate
    result = await system_manager.delete_file(path, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/files/rename")
async def rename_file(request: Request):
    require_session_token(request)
    body = await request.json()
    old_path = body.get("old_path", "")
    new_path = body.get("new_path", "")
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="old_path and new_path are required")
    gate = _consume_or_issue_approval(
        request, body, "rename_file", {"old_path": old_path, "new_path": new_path}
    )
    if gate:
        return gate
    result = await system_manager.rename_file(old_path, new_path, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/files/folder")
async def create_folder(request: Request):
    require_session_token(request)
    body = await request.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    gate = _consume_or_issue_approval(request, body, "create_folder", {"path": path})
    if gate:
        return gate
    result = await system_manager.create_folder(path, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/clipboard/write")
async def clipboard_write(request: Request):
    require_session_token(request)
    body = await request.json()
    text = body.get("text", "")
    gate = _consume_or_issue_approval(request, body, "clipboard_write", {"text": text})
    if gate:
        return gate
    result = await system_manager.write_clipboard(text, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/screenshot")
async def take_screenshot(request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    gate = _consume_or_issue_approval(request, body, "screenshot", {})
    if gate:
        return gate
    result = await system_manager.take_screenshot(confirm=True)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/undo")
async def undo_last(request: Request):
    require_session_token(request)
    result = await system_manager.undo_last()
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
