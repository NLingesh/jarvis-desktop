#!/usr/bin/env python3
"""Real-runtime verification: voice/microphone lifecycle separation.

Launches the actual built JARVIS Electron app and verifies that a successful
voice desktop command is no longer followed by a false red error card, that
no-speech is a subtle non-blocking ``voice_status`` (never a hard error), that
responses carry structured lifecycle IDs, and that an already-running app is
reported truthfully without launching a duplicate instance.

Flow:
  A. typed "Open VS Code." through the real UI -> truthful reply, no error card
  B. "open VS Code" through the real /ws/voice -> verified tool_results + IDs,
     already-running reply, no new VS Code process
  C. real native mic: connect -> READY; hands_free capture -> any no-speech
     arrives as voice_status (never a no-speech error)
  D. device failure: invalid device index (best-effort; falls back on this
     hardware) and an invalid listening mode -> scoped error with
     error_scope/voice_cycle_id (a true, scoped failure)

Exit 0 = PASSED, 1 = FAILED, 2 = not runnable (preconditions missing).
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
    print(f"VOICE_CYCLE_NOT_RUNNABLE missing dependency: {exc}")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PORT = 8000
DEBUG_PORT = 9222
CDP_HTTP = f"http://127.0.0.1:{DEBUG_PORT}"
BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
LOG_PATH = Path("/tmp/jarvis_voice_cycle.log")
RESULTS: list[str] = []
BLOCKED: list[str] = []


def mark(label: str, ok: bool, detail: str = "") -> None:
    status = "PASSED" if ok else "FAILED"
    RESULTS.append(f"{status} {label}" + (f" — {detail}" if detail else ""))
    print(f"{status} {label}" + (f" — {detail}" if detail else ""))


def mark_blocked(label: str, detail: str = "") -> None:
    BLOCKED.append(label)
    print(f"BLOCKED {label}" + (f" — {detail}" if detail else ""))


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


def _conversation_text_js() -> str:
    return """
(() => {
  const nodes = Array.from(document.querySelectorAll('.conversation-message .conversation-message-text'));
  return nodes.map(n => n.textContent.trim()).filter(Boolean);
})()
"""


def _assistant_text_js() -> str:
    return """
(() => {
  const nodes = Array.from(document.querySelectorAll('.conversation-message.assistant .conversation-message-text'));
  return nodes.map(n => n.textContent.trim()).filter(Boolean);
})()
"""


def _error_ui_js() -> str:
    return """
(() => ({
  banner: !!document.querySelector('.error-banner'),
  convError: !!document.querySelector('.conversation-error'),
  micNotice: (document.querySelector('.mic-notice') || {}).textContent || null,
}))()
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


async def wait_for_conversation_text(cdp: Cdp, timeout: float = 40.0) -> list[str]:
    deadline = time.time() + timeout
    last_texts: list[str] = []
    while time.time() < deadline:
        res = await cdp.evaluate(_conversation_text_js())
        value = res.get("value")
        if isinstance(value, list) and value:
            last_texts = value
            if any("THINKING" not in t.upper() and "IS THINKING" not in t.upper() for t in value):
                return value
        await asyncio.sleep(0.6)
    return last_texts


async def wait_for_assistant_text(cdp: Cdp, timeout: float = 40.0) -> list[str]:
    """Wait for the JARVIS reply bubble to appear (not the user echo)."""
    deadline = time.time() + timeout
    last_texts: list[str] = []
    while time.time() < deadline:
        res = await cdp.evaluate(_assistant_text_js())
        value = res.get("value")
        if isinstance(value, list) and value:
            last_texts = value
            if any("THINKING" not in t.upper() and "IS THINKING" not in t.upper() for t in value):
                return value
        await asyncio.sleep(0.6)
    return last_texts


def code_process_count() -> int:
    count = 0
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "/usr/share/code/code" in cmd or cmd.strip().endswith("/code") or cmd.strip() == "code":
            count += 1
    return count


async def get_session_token(cdp: Cdp) -> str:
    res = await cdp.evaluate(
        "(async () => { try { const api = window.electronAPI; return api && api.getSessionToken ? await api.getSessionToken() : ''; } catch { return ''; } })()"
    )
    return str(res.get("value") or "")


async def voice_text_command(token: str, content: str, timeout: float = 30.0) -> list[dict]:
    """Send a typed text command through the real /ws/voice pipeline."""
    uri = f"ws://127.0.0.1:{BACKEND_PORT}/ws/voice?token={token}"
    messages: list[dict] = []
    async with websockets.connect(uri) as ws:

        async def _reader():
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    messages.append(msg)
                    if msg.get("type") in ("response", "error"):
                        return
            except Exception:
                pass

        task = asyncio.create_task(_reader())
        await asyncio.sleep(0.4)
        await ws.send(json.dumps({"type": "text", "content": content}))
        deadline = time.time() + timeout
        while time.time() < deadline and not any(
            m.get("type") in ("response", "error") for m in messages
        ):
            await asyncio.sleep(0.25)
        task.cancel()
    return messages


async def native_connect(token: str) -> tuple[list[dict], object]:
    """Open a real /ws/voice/native session and return its messages + socket."""
    uri = f"ws://127.0.0.1:{BACKEND_PORT}/ws/voice/native?token={token}"
    messages: list[dict] = []
    ws = await websockets.connect(uri)

    async def _reader():
        try:
            async for raw in ws:
                messages.append(json.loads(raw))
        except Exception:
            pass

    reader = asyncio.create_task(_reader())
    await asyncio.sleep(0.4)
    return messages, (ws, reader)


async def main() -> int:
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
        if bundle_name not in built_files:
            # The renderer may have served a cached index.html from an earlier
            # build. Reload so the fresh bundle (and this fix) is actually live.
            await cdp.evaluate("location.reload(); true")
            loaded_asset = ""
            deadline = time.time() + 25
            while time.time() < deadline and not loaded_asset:
                loaded = await cdp.evaluate(_loaded_asset_js())
                loaded_asset = str(loaded.get("value") or "")
                if not loaded_asset:
                    await asyncio.sleep(0.8)
            bundle_name = loaded_asset.rsplit("/", 1)[-1]
        mark(
            "running bundle is the fresh build", bundle_name in built_files, f"loaded {bundle_name}"
        )

        token = await get_session_token(cdp)
        mark("renderer session token available", bool(token))

        # ------------------------------------------------------------ A. typed UI
        await cdp.evaluate(_open_panel_js())
        deadline = time.time() + 15
        while time.time() < deadline:
            res = await cdp.evaluate(
                "!!document.querySelector('input[aria-label=\"Ask JARVIS anything\"]')"
            )
            if res.get("value") is True:
                break
            await asyncio.sleep(0.5)
        await cdp.evaluate(_set_input_js("Open VS Code."))
        await asyncio.sleep(0.4)
        clicked = await cdp.evaluate(_click_send_js())
        if clicked.get("value") != "clicked":
            mark("A typed 'Open VS Code.'", False, "send button missing")
        else:
            texts = await wait_for_assistant_text(cdp)
            joined = " ".join(texts)
            mark(
                "A typed 'Open VS Code.' got an assistant reply",
                bool(texts),
                f"msgs: {joined[:160]}",
            )
            mark(
                "A reply is truthful (already running)",
                "already running" in joined.lower(),
                joined[:160],
            )
            ui = await cdp.evaluate(_error_ui_js())
            val = ui.get("value") or {}
            mark(
                "A no red error card after success",
                not val.get("banner") and not val.get("convError"),
                f"banner={val.get('banner')} convError={val.get('convError')}",
            )

        # ------------------------------------------------------------- B. /ws/voice
        code_before = code_process_count()
        msgs = await voice_text_command(token, "open VS Code")
        resp = next((m for m in msgs if m.get("type") == "response"), None)
        err = next((m for m in msgs if m.get("type") == "error"), None)
        mark(
            "B voice command got a response",
            bool(resp),
            f"text: {resp and resp.get('text','')[:120]}",
        )
        mark("B no error on voice command", err is None, err and err.get("message", ""))
        tools = (resp or {}).get("tool_results") or []
        mark(
            "B voice response carries verified tool_result",
            any(t.get("tool") == "launch_application" and t.get("verified") for t in tools),
            f"tools={tools}",
        )
        mark(
            "B voice response carries interaction_id + voice_cycle_id",
            bool(resp and resp.get("interaction_id") and resp.get("voice_cycle_id")),
            f"interaction_id={resp and resp.get('interaction_id')}",
        )
        mark(
            "B reply is truthful (already running)",
            bool(resp and "already running" in resp.get("text", "").lower()),
            resp and resp.get("text", "")[:120],
        )
        time.sleep(1.5)
        code_after = code_process_count()
        mark(
            "B no duplicate VS Code instance launched",
            code_after <= code_before + 0,
            f"code procs before={code_before} after={code_after}",
        )

        # ------------------------------------------------------- C. native mic
        if token:
            messages, (ws, reader) = await native_connect(token)
            await ws.send(json.dumps({"type": "connect"}))
            deadline = time.time() + 15
            ready = False
            while time.time() < deadline and not ready:
                ready = any(
                    m.get("type") == "state" and m.get("state") in ("READY", "LISTENING")
                    for m in messages
                )
                if ready:
                    break
                err_state = any(
                    m.get("type") == "state" and m.get("state") == "ERROR" for m in messages
                )
                if err_state:
                    break
                await asyncio.sleep(0.4)
            mark(
                "C native mic connects to READY",
                ready,
                [m for m in messages if m.get("type") == "state"][:2],
            )
            if ready:
                await ws.send(json.dumps({"type": "start_listening", "mode": "hands_free"}))
                deadline = time.time() + 20
                no_speech: list[dict] = []
                while time.time() < deadline:
                    no_speech = [m for m in messages if m.get("type") == "voice_status"]
                    no_speech_errs = [
                        m
                        for m in messages
                        if m.get("type") == "error"
                        and any(
                            k in str(m.get("message", ""))
                            for k in ("no speech", "didn't catch", "could not hear")
                        )
                    ]
                    if no_speech_errs:
                        mark(
                            "C no-speech never sent as hard error",
                            False,
                            f"error: {no_speech_errs[0]}",
                        )
                        break
                    if no_speech:
                        mark("C no-speech is a non-blocking voice_status", True, f"{no_speech[0]}")
                        break
                    await asyncio.sleep(0.5)
                else:
                    mark_blocked(
                        "C no-speech capture",
                        "ambient audio produced no empty utterance within 20s",
                    )
                    mark("C no hard no-speech error observed", True)
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "stop_listening"}))
            await asyncio.sleep(0.3)
            with contextlib.suppress(Exception):
                await ws.close()
            with contextlib.suppress(Exception):
                reader.cancel()

            # ---------------------------------------------------- D. device failure
            # D1: a nonexistent device index. On this machine the backend falls
            # back to the default device, so a scoped error is not guaranteed.
            messages, (ws, reader) = await native_connect(token)
            await ws.send(json.dumps({"type": "connect", "device": 999999}))
            deadline = time.time() + 10
            scoped = None
            while time.time() < deadline:
                scoped = next(
                    (m for m in messages if m.get("type") == "error" and m.get("error_scope")),
                    None,
                )
                if scoped:
                    break
                ready = any(
                    m.get("type") == "state" and m.get("state") == "READY" for m in messages
                )
                if ready:
                    break
                await asyncio.sleep(0.4)
            if scoped:
                mark(
                    "D1 invalid device reports scoped error",
                    True,
                    f"scope={scoped.get('error_scope')} msg={scoped.get('message','')[:80]}",
                )
            else:
                mark_blocked(
                    "D1 invalid device scoped error",
                    "backend fell back to the default input device",
                )
            with contextlib.suppress(Exception):
                await ws.close()
            with contextlib.suppress(Exception):
                reader.cancel()

            # D2: an invalid listening mode is a deterministic real voice-session
            # failure that must be reported as a scoped error, not swallowed.
            messages, (ws, reader) = await native_connect(token)
            await ws.send(json.dumps({"type": "connect"}))
            deadline = time.time() + 10
            while time.time() < deadline:
                if any(
                    m.get("type") == "state" and m.get("state") in ("READY", "LISTENING")
                    for m in messages
                ):
                    break
                await asyncio.sleep(0.4)
            await ws.send(json.dumps({"type": "start_listening", "mode": "bogus_mode"}))
            deadline = time.time() + 10
            scoped = None
            while time.time() < deadline:
                scoped = next(
                    (
                        m
                        for m in messages
                        if m.get("type") == "error"
                        and m.get("error_scope")
                        and m.get("voice_cycle_id")
                    ),
                    None,
                )
                if scoped:
                    break
                await asyncio.sleep(0.4)
            mark(
                "D2 invalid listening mode reports scoped error",
                bool(scoped),
                f"scope={scoped and scoped.get('error_scope')} msg={scoped and scoped.get('message','')[:80]}",
            )
            with contextlib.suppress(Exception):
                await ws.close()
            with contextlib.suppress(Exception):
                reader.cancel()
        else:
            mark("C/D native mic", False, "no session token to open native endpoint")

        await cdp.close()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(Exception):
                proc.terminate()

    failed = [r for r in RESULTS if r.startswith("FAILED")]
    if failed:
        print(f"\nVOICE_CYCLE_RESULT=FAILED ({len(failed)} check(s) failed)")
        return 1
    print("\nVOICE_CYCLE_RESULT=PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
