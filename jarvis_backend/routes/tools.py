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
from routes.state import memory_manager, require_session_token, system_manager

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
    if not str(p).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Path outside allowed scope")
    return p


def _require_confirm(body: dict) -> None:
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm=true is required for this action")


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
    await log_action("ocr", "image", "session_token", "started")
    try:
        raw = base64.b64decode(image_b64)
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
    _require_confirm(body)
    command = body.get("command", "")
    if not command.strip():
        raise HTTPException(status_code=400, detail="command is required")
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
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                chunks.append(decoded)
                _task_registry[task_id]["output"] = "".join(chunks)
            await proc.wait()
            _task_registry[task_id]["returncode"] = proc.returncode
            _task_registry[task_id]["status"] = "completed"
            await log_action(
                "terminal.execute", command, "session_token", f"completed rc={proc.returncode}"
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
    _require_confirm(await request.json())
    await memory_manager.clear_audit_log()
    await log_action("audit.clear", "audit_log", "session_token", "success")
    return {"cleared": True}


# --- System Control via SystemManager ----------------------------------------
@router.post("/system/command")
async def system_command(request: Request):
    require_session_token(request)
    body = await request.json()
    command = body.get("command", "").strip()
    confirm = body.get("confirm", False)
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    result = await system_manager.execute_command(command, confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@router.post("/apps/open")
async def open_app(request: Request):
    require_session_token(request)
    body = await request.json()
    app_name = (body.get("app_name") or "").strip().lower()
    confirm = body.get("confirm", False)
    if not app_name:
        raise HTTPException(status_code=400, detail="app_name is required")
    result = await system_manager.open_application(app_name, confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@router.post("/apps/close")
async def close_app(request: Request):
    require_session_token(request)
    body = await request.json()
    app_name = (body.get("app_name") or "").strip()
    pid = body.get("pid")
    confirm = body.get("confirm", False)
    result = await system_manager.close_application(app_name=app_name, pid=pid, confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/files/delete")
async def delete_file(request: Request):
    require_session_token(request)
    body = await request.json()
    path = body.get("path", "")
    confirm = body.get("confirm", False)
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    result = await system_manager.delete_file(path, confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/files/rename")
async def rename_file(request: Request):
    require_session_token(request)
    body = await request.json()
    old_path = body.get("old_path", "")
    new_path = body.get("new_path", "")
    confirm = body.get("confirm", False)
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="old_path and new_path are required")
    result = await system_manager.rename_file(old_path, new_path, confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/files/folder")
async def create_folder(request: Request):
    require_session_token(request)
    body = await request.json()
    path = body.get("path", "")
    confirm = body.get("confirm", False)
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    result = await system_manager.create_folder(path, confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/clipboard/write")
async def clipboard_write(request: Request):
    require_session_token(request)
    body = await request.json()
    text = body.get("text", "")
    confirm = body.get("confirm", False)
    result = await system_manager.write_clipboard(text, confirm=confirm)
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
    confirm = body.get("confirm", True)
    result = await system_manager.take_screenshot(confirm=confirm)
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
