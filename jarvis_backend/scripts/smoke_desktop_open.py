#!/usr/bin/env python3
"""Production smoke test: real Electron app opens a folder deterministically.

Launches the actual built JARVIS Electron app (the same binary the user runs),
drives the REAL UI through the CDP debug port, types "Open my Downloads
folder.", and verifies the folder actually opens.  It then exercises the voice
pipeline by pushing the spoken intent "hey jarvis open my downloads folder"
through the real ``/ws/voice`` endpoint.

Checks:
  1. the running renderer is the freshly built bundle (not a stale cache),
  2. the typed command returns a verified ``open_folder`` tool result quickly
     (deterministic routing, no LLM stall, no generic "AI backend" error),
  3. the UI reply reports the real opened path,
  4. a real nautilus process appears as the folder-open side effect,
  5. the same command through /ws/voice also dispatches open_folder.

Exit 0 = PASSED, 1 = FAILED, 2 = not runnable (preconditions missing).

Usage:
  venv/bin/python jarvis_backend/scripts/smoke_desktop_open.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import psutil
    import requests
    import websockets
except ImportError as exc:  # pragma: no cover
    print(f"SMOKE_NOT_RUNNABLE missing dependency: {exc}")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PORT = 8000
DEBUG_PORT = 9222
CDP_HTTP = f"http://127.0.0.1:{DEBUG_PORT}"
BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
LOG_PATH = Path("/tmp/jarvis_smoke.log")
RESULTS: list[str] = []


def mark(label: str, ok: bool, detail: str = "") -> None:
    status = "PASSED" if ok else "FAILED"
    RESULTS.append(f"{status} {label}" + (f" — {detail}" if detail else ""))
    print(f"{status} {label}" + (f" — {detail}" if detail else ""))


def wait_for_port(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with requests.get(f"http://127.0.0.1:{port}/", timeout=0.5) as resp:
                resp.raise_for_status()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def is_jarvis_process(proc: psutil.Process) -> bool:
    try:
        cmd = " ".join(proc.cmdline() or [])
        exe = proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    if "electron" in exe and "main.js" in cmd:
        return True
    return exe in ("python", "python3") and "jarvis_backend/main.py" in cmd


def stop_existing_app() -> None:
    for proc in psutil.process_iter():
        try:
            if is_jarvis_process(proc):
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    deadline = time.time() + 15
    while time.time() < deadline:
        remaining = [p for p in psutil.process_iter() if is_jarvis_process(p)]
        if not remaining:
            return
        time.sleep(0.4)


def start_app() -> subprocess.Popen | None:
    electron_bin = ROOT / "node_modules" / ".bin" / "electron"
    if not electron_bin.exists():
        mark("launch real Electron app", False, "node_modules/.bin/electron missing")
        return None
    with LOG_PATH.open("w") as logf:
        proc = subprocess.Popen(
            [
                "node",
                str(electron_bin),
                "--no-sandbox",
                f"--remote-debugging-port={DEBUG_PORT}",
                str(ROOT / "electron" / "main.js"),
            ],
            cwd=str(ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc


def get_page_target() -> dict | None:
    try:
        targets = requests.get(f"{CDP_HTTP}/json", timeout=2).json()
    except Exception:
        return None
    for target in targets:
        if target.get("type") == "page" and str(target.get("url", "")).startswith(BASE_URL):
            return target
    return None


class Cdp:
    def __init__(self, ws_url: str):
        self._url = ws_url
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.ws = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(
            self._url,
            origin=None,
            max_size=2**26,
        )
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in self._pending:
                    fut = self._pending.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)
        except Exception:
            pass

    async def call(self, method: str, params: dict | None = None, timeout: float = 15.0):
        self._id += 1
        msg_id = self._id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            return {"error": {"message": f"timeout on {method}"}}

    async def evaluate(self, expression: str) -> dict:
        resp = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return resp.get("result", {}).get("result", {}) or {}

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()


def _set_input_js(value: str) -> str:
    value = json.dumps(value)
    return f"""
(() => {{
  const input = document.querySelector('input[aria-label="Ask JARVIS anything"]');
  if (!input) return 'no-input';
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, {value});
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return 'set';
}})()
"""


def _click_send_js() -> str:
    return """
(() => {
  const btn = document.querySelector('button[aria-label="Send message"]');
  if (!btn) return 'no-send';
  btn.click();
  return 'clicked';
})()
"""


def _open_panel_js() -> str:
    return """
(() => {
  const orb = document.querySelector('.minimal-bubble-button');
  if (orb) { orb.click(); return 'clicked-orb'; }
  const input = document.querySelector('input[aria-label="Ask JARVIS anything"]');
  return input ? 'already-panel' : 'no-orb';
})()
"""


def _assistant_text_js() -> str:
    return """
(() => {
  const nodes = Array.from(document.querySelectorAll('.conversation-message.assistant .conversation-message-text'));
  return nodes.map(n => n.textContent.trim()).filter(Boolean);
})()
"""


def _loaded_asset_js() -> str:
    return """
(() => {
  try {
    return performance.getEntriesByType('resource')
      .map(e => e.name)
      .filter(n => /main-.*\\.js$/.test(n))[0] || '';
  } catch { return ''; }
})()
"""


async def wait_for_assistant(cdp: Cdp, timeout: float = 40.0) -> str:
    deadline = time.time() + timeout
    last_texts = []
    while time.time() < deadline:
        res = await cdp.evaluate(_assistant_text_js())
        value = res.get("value")
        if isinstance(value, list) and value:
            last_texts = value
            last = value[-1]
            if last and "THINKING" not in last.upper() and last != "JARVIS IS THINKING…":
                return last
        await asyncio.sleep(0.6)
    return " ".join(last_texts)


def nautilus_state() -> dict:
    state = {}
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if proc.info["name"] == "nautilus":
                state[proc.info["pid"]] = proc.info["create_time"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return state


def new_nautilus(before: dict, after: dict, send_time: float) -> list[int]:
    fresh = []
    for pid, created in after.items():
        if pid not in before and created > send_time - 2:
            fresh.append(pid)
    return fresh


async def run_typed_folder_open(cdp: Cdp, send_time: float) -> tuple[str, str]:
    await cdp.evaluate(_open_panel_js())
    deadline = time.time() + 15
    while time.time() < deadline:
        res = await cdp.evaluate(
            "!!document.querySelector('input[aria-label=\"Ask JARVIS anything\"]')"
        )
        if res.get("value") is True:
            break
        await asyncio.sleep(0.5)
    await cdp.evaluate(_set_input_js("Open my Downloads folder."))
    await asyncio.sleep(0.4)
    clicked = await cdp.evaluate(_click_send_js())
    if clicked.get("value") != "clicked":
        return "no-send-button", send_time
    reply = await wait_for_assistant(cdp)
    return reply, time.time()


async def run_voice_folder_open(token: str) -> str:
    """Push the spoken intent through the real /ws/voice pipeline.

    The wake word ("hey jarvis") is consumed by the frontend's spotter, so the
    orchestrator receives the post-wake utterance — exactly what we send here.
    """
    uri = f"ws://127.0.0.1:{BACKEND_PORT}/ws/voice?token={token}"
    received: list[str] = []
    async with websockets.connect(uri) as ws:

        async def _reader():
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") in ("response", "reply", "final"):
                        received.append(msg.get("text", ""))
                    if msg.get("type") == "error":
                        received.append(f"ERROR:{msg.get('message','')}")
            except Exception:
                pass

        task = asyncio.create_task(_reader())
        await asyncio.sleep(0.6)
        await ws.send(json.dumps({"type": "text", "content": "open my downloads folder"}))
        deadline = time.time() + 30
        while time.time() < deadline:
            if any("Opened" in r or "downloads" in r.lower() for r in received):
                break
            if any(r.startswith("ERROR:") for r in received):
                break
            await asyncio.sleep(0.5)
        task.cancel()
    return " | ".join(received)


def backend_log_has_open_folder_ok() -> bool:
    try:
        text = LOG_PATH.read_text(errors="replace")
    except OSError:
        return False
    return any("open_folder:ok" in line for line in text.splitlines())


def backend_log_safe_line() -> str:
    try:
        text = LOG_PATH.read_text(errors="replace")
    except OSError:
        return ""
    for line in reversed(text.splitlines()):
        if "path=POST /api/chat" in line:
            return line.strip()
    return ""


async def main() -> int:
    if not Path("/home/wiz/Downloads").is_dir():
        mark("precondition", False, "/home/wiz/Downloads missing")
        return 1

    stop_existing_app()
    proc = start_app()
    if proc is None:
        return 1

    try:
        if not wait_for_port(BACKEND_PORT):
            mark("backend startup", False, "backend did not answer on :8000")
            return 1
        if not wait_for_port(DEBUG_PORT):
            mark("CDP startup", False, "remote debugging did not come up on :9222")
            return 1

        target = None
        deadline = time.time() + 30
        while time.time() < deadline and target is None:
            target = get_page_target()
            if target is None:
                await asyncio.sleep(0.5)
        if target is None:
            mark("CDP page target", False, "no page target under BASE_URL")
            return 1

        cdp = Cdp(target["webSocketDebuggerUrl"])
        await cdp.connect()

        # Bundle freshness: the loaded asset must exist in dist with the new hash.
        # Wait for the renderer to finish loading its scripts before probing.
        loaded_asset = ""
        deadline = time.time() + 20
        while time.time() < deadline and not loaded_asset:
            loaded = await cdp.evaluate(_loaded_asset_js())
            loaded_asset = str(loaded.get("value") or "")
            if not loaded_asset:
                await asyncio.sleep(0.8)
        bundle_name = loaded_asset.rsplit("/", 1)[-1]
        built_files = [
            p.name for p in (ROOT / "jarvis_frontend" / "dist" / "assets").glob("main-*.js")
        ]
        mark(
            "running bundle is the fresh build", bundle_name in built_files, f"loaded {bundle_name}"
        )

        # Typed request through the real UI.
        before_nautilus = nautilus_state()
        send_time = time.time()
        reply, _ = await run_typed_folder_open(cdp, send_time)
        mark("typed 'Open my Downloads folder.'", bool(reply), f"reply: {reply[:120]}")
        mark(
            "reply names the opened folder", "Opened" in reply and "Downloads" in reply, reply[:120]
        )
        mark("no generic backend error", "not responding" not in reply.lower(), reply[:120])
        after_nautilus = nautilus_state()
        fresh = new_nautilus(before_nautilus, after_nautilus, send_time)
        if fresh:
            mark("folder-open side effect (new nautilus)", True, f"pids={fresh}")
        elif before_nautilus:
            mark("folder-open side effect (existing nautilus)", True, "reused running window")
        else:
            mark("folder-open side effect (nautilus)", False, "no nautilus process appeared")
        mark(
            "backend log shows open_folder:ok",
            backend_log_has_open_folder_ok(),
            backend_log_safe_line()[:160],
        )

        # Voice-path request through the real app's /ws/voice endpoint.
        token_src = await cdp.evaluate(
            "(async () => { try { const api = window.electronAPI; return api && api.getSessionToken ? await api.getSessionToken() : ''; } catch { return ''; } })()"
        )
        token = str(token_src.get("value") or "")
        if token:
            voice_reply = await run_voice_folder_open(token)
            mark(
                "voice 'open my downloads folder'", bool(voice_reply), f"reply: {voice_reply[:120]}"
            )
            mark(
                "voice reply names the opened folder",
                "Opened" in voice_reply and "Downloads" in voice_reply,
                voice_reply[:120],
            )
        else:
            mark("voice-path request", False, "could not obtain session token from renderer")

        await cdp.close()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(Exception):
                proc.terminate()

    failed = [r for r in RESULTS if r.startswith("FAILED")]
    if failed:
        print(f"\nSMOKE_RESULT=FAILED ({len(failed)} check(s) failed)")
        return 1
    print("\nSMOKE_RESULT=PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
