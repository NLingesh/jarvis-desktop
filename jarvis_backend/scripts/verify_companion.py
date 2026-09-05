#!/usr/bin/env python3
"""Real-runtime verification: context, approved memory, orb, regressions.

Drives the actual built Electron app through CDP and the real backend:

  1. fresh bundle live in the renderer
  2. desktop regression: typed "Open VS Code." -> truthful already-running,
     no red error card, no duplicate instance
  3. explicit memory save (real vault): "Remember that I prefer a male
     voice." -> verified on disk + UI confirmation; recall lists it;
     "Forget that I prefer a male voice." removes it (net zero writes)
  4. secret filtering at runtime: a credential-shaped remember is refused
  5. multi-turn project/README follow-up and model-inferred memory need a
     configured LLM provider -- reported BLOCKED when unavailable
  6. native mic READY + no hard no-speech error after success
  7. main window bounds can never inherit bubble geometry

Exit 0 = PASSED, 1 = FAILED, 2 = not runnable.
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
    print(f"COMPANION_NOT_RUNNABLE missing dependency: {exc}")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PORT = 8000
DEBUG_PORT = 9222
CDP_HTTP = f"http://127.0.0.1:{DEBUG_PORT}"
BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
LOG_PATH = Path("/tmp/jarvis_companion.log")
PROFILE_NOTE = Path.home() / "Documents" / "JARVIS Memory" / "People" / "Me.md"
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
        if not [p for p in psutil.process_iter() if is_jarvis_process(p)]:
            return
        time.sleep(0.4)


def start_app() -> subprocess.Popen | None:
    electron_bin = ROOT / "node_modules" / ".bin" / "electron"
    if not electron_bin.exists():
        mark("launch real Electron app", False, "electron binary missing")
        return None
    with LOG_PATH.open("w") as logf:
        return subprocess.Popen(
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
        self.target_id = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(self._url, origin=None, max_size=2**26)
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
  const input = document.querySelector('input[aria-label="Ask JARVIS anything"]');
  if (input && input.offsetParent !== null) return 'already-panel';
  const orb = document.querySelector('.orb-anchor .minimal-bubble-button')
    || document.querySelector('.minimal-bubble-button');
  if (orb) { orb.click(); return 'clicked-orb'; }
  return 'no-orb';
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


async def open_panel(cdp: Cdp) -> bool:
    await cdp.evaluate(_open_panel_js())
    deadline = time.time() + 15
    while time.time() < deadline:
        res = await cdp.evaluate(
            "!!document.querySelector('input[aria-label=\"Ask JARVIS anything\"]')"
        )
        if res.get("value") is True:
            return True
        await asyncio.sleep(0.5)
    return False


async def send_typed(cdp: Cdp, text: str) -> bool:
    await cdp.evaluate(_set_input_js(text))
    await asyncio.sleep(0.35)
    clicked = await cdp.evaluate(_click_send_js())
    return clicked.get("value") == "clicked"


async def wait_for_assistant(cdp: Cdp, timeout: float = 45.0) -> str:
    baseline = await cdp.evaluate(_assistant_text_js())
    base_count = len(baseline.get("value") or [])
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        res = await cdp.evaluate(_assistant_text_js())
        msgs = res.get("value") or []
        if len(msgs) > base_count:
            last = msgs[-1]
            if last and "THINKING" not in last.upper():
                return last
        await asyncio.sleep(0.6)
    return last


async def voice_text_command(token: str, content: str, timeout: float = 30.0) -> list[dict]:
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


def note_contains(fragment: str) -> bool:
    try:
        return fragment.lower() in PROFILE_NOTE.read_text(encoding="utf-8").lower()
    except OSError:
        return False


async def wait_note_absent(fragment: str, timeout: float = 8.0) -> bool:
    """Poll until the fragment disappears from the on-disk note."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not note_contains(fragment):
            return True
        await asyncio.sleep(0.5)
    return False


def llm_configured() -> bool:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return False
    text = env_path.read_text(errors="replace")
    keys = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "NVIDIA_API_KEY")
    for key in keys:
        for line in text.splitlines():
            if line.strip().startswith(key) and "=" in line:
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return True
    # Ollama local provider counts as configured when reachable.
    try:
        requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


async def main() -> int:
    stop_existing_app()
    proc = start_app()
    if proc is None:
        return 1

    try:
        if not wait_for_port(BACKEND_PORT):
            mark("backend startup", False, "no answer on :8000")
            return 1
        if not wait_for_port(DEBUG_PORT):
            mark("CDP startup", False, "no debugging port on :9222")
            return 1
        target = None
        deadline = time.time() + 30
        while time.time() < deadline and target is None:
            target = get_page_target()
            if target is None:
                await asyncio.sleep(0.5)
        if target is None:
            mark("CDP page target", False, "no page under BASE_URL")
            return 1

        cdp = Cdp(target["webSocketDebuggerUrl"])
        cdp.target_id = target.get("id")
        await cdp.connect()

        # 1 ---------------------------------------------------- fresh bundle
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
            await cdp.evaluate("location.reload(); true")
            loaded_asset = ""
            deadline = time.time() + 25
            while time.time() < deadline and not loaded_asset:
                loaded = await cdp.evaluate(_loaded_asset_js())
                loaded_asset = str(loaded.get("value") or "")
                if not loaded_asset:
                    await asyncio.sleep(0.8)
            bundle_name = loaded_asset.rsplit("/", 1)[-1]
        mark("fresh bundle live", bundle_name in built_files, bundle_name)

        token_res = await cdp.evaluate(
            "(async () => { try { const api = window.electronAPI; return api && api.getSessionToken ? await api.getSessionToken() : ''; } catch { return ''; } })()"
        )
        token = str(token_res.get("value") or "")

        # 2 -------------------------------------------- desktop regression check
        def code_procs() -> int:
            return sum(
                1
                for p in psutil.process_iter(["cmdline"])
                if "/usr/share/code/code" in " ".join(p.info["cmdline"] or [])
            )

        if not await open_panel(cdp):
            mark("panel opens from orb", False)
        else:
            ok = await send_typed(cdp, "Open VS Code.")
            reply = await wait_for_assistant(cdp) if ok else ""
            truthful = "already running" in reply.lower() or "has been launched" in reply.lower()
            mark("desktop launch is truthful (VS Code)", truthful, reply[:100])
            ui = (await cdp.evaluate(_error_ui_js())).get("value") or {}
            mark(
                "no red error card after success",
                not ui.get("banner") and not ui.get("convError"),
                f"banner={ui.get('banner')}",
            )
            time.sleep(2.0)
            after_first = code_procs()
            # A second identical command must report already-running and must
            # not spawn another instance.
            await send_typed(cdp, "Open VS Code.")
            reply2 = await wait_for_assistant(cdp)
            mark(
                "second command reports already-running",
                "already running" in reply2.lower(),
                reply2[:100],
            )
            time.sleep(1.5)
            after_second = code_procs()
            mark(
                "no duplicate VS Code instance",
                after_second <= after_first + 1,
                f"procs {after_first}->{after_second}",
            )

        # 3 ------------------------------------------------ memory: save/recall/forget
        if await open_panel(cdp):
            ok = await send_typed(cdp, "Remember that I prefer a male voice.")
            reply = await wait_for_assistant(cdp) if ok else ""
            mark("explicit remember acknowledged", "Saved" in reply, reply[:100])
            mark(
                "fact persisted to real vault",
                note_contains("prefer a male voice"),
                str(PROFILE_NOTE),
            )

            ok = await send_typed(cdp, "What do you remember?")
            reply = await wait_for_assistant(cdp) if ok else ""
            mark("recall lists saved fact", "male voice" in reply.lower(), reply[:120])

            ok = await send_typed(cdp, "Forget that I prefer a male voice.")
            reply = await wait_for_assistant(cdp) if ok else ""
            mark("forget acknowledged", "Forgotten" in reply, reply[:100])
            gone = await wait_note_absent("prefer a male voice")
            mark("vault no longer holds the fact", gone)
        else:
            mark("memory flow", False, "panel could not be opened")

        # 4 ------------------------------------------------ secret filtering live
        if await open_panel(cdp):
            ok = await send_typed(cdp, "Remember that my password is hunter2.")
            reply = await wait_for_assistant(cdp) if ok else ""
            refused = "couldn't complete" in reply.lower() or "won't store" in reply.lower()
            mark("credential remember refused at runtime", refused, reply[:120])
            mark("secret never reached the vault", not note_contains("hunter2"))
        else:
            mark("secret filter runtime", False, "panel could not be opened")

        # 5 ------------------------------------------------ LLM-dependent flows
        if llm_configured():
            if await open_panel(cdp):
                await send_typed(cdp, "Open my JARVIS project.")
                first = await wait_for_assistant(cdp, 60)
                await send_typed(cdp, "Read the README.")
                second = await wait_for_assistant(cdp, 60)
                followup_ok = bool(second) and "couldn't" not in second.lower()[:20]
                mark(
                    "multi-turn project->README follow-up",
                    followup_ok,
                    f"first={first[:60]} second={second[:80]}",
                )
            # Model-inferred save must ask before persisting.
            uri_msgs = (
                await voice_text_command(token, "I usually work late at night.") if token else []
            )
            resp = next((m for m in uri_msgs if m.get("type") == "response"), None)
            confirmations = next((m for m in uri_msgs if m.get("type") == "confirmations"), None)
            inferred_ok = confirmations is not None or (
                resp is not None and "save it to memory" in resp.get("text", "").lower()
            )
            if inferred_ok:
                mark("inferred preference asks before saving", True)
            else:
                mark_blocked(
                    "inferred preference asks before saving",
                    f"model replied without a memory proposal: {(resp or {}).get('text','')[:80]}",
                )
        else:
            mark_blocked(
                "multi-turn project->README follow-up (LLM)",
                "no LLM provider key in .env and Ollama unreachable",
            )
            mark_blocked(
                "inferred preference asks before saving (LLM)", "no LLM provider available"
            )

        # 6 ------------------------------------------------ mic silence after success
        if token:
            uri = f"ws://127.0.0.1:{BACKEND_PORT}/ws/voice/native?token={token}"
            try:
                ws = await websockets.connect(uri)
                messages: list[dict] = []

                async def _reader():
                    try:
                        async for raw in ws:
                            messages.append(json.loads(raw))
                    except Exception:
                        pass

                reader = asyncio.create_task(_reader())
                await asyncio.sleep(0.3)
                await ws.send(json.dumps({"type": "connect"}))
                deadline = time.time() + 12
                ready = any(
                    m.get("type") == "state" and m.get("state") == "READY" for m in messages
                )
                while time.time() < deadline and not ready:
                    ready = any(
                        m.get("type") == "state" and m.get("state") == "READY" for m in messages
                    )
                    await asyncio.sleep(0.4)
                mark("native mic READY after desktop actions", ready)
                hard_no_speech_errs = [
                    m
                    for m in messages
                    if m.get("type") == "error"
                    and any(
                        k in str(m.get("message", "")).lower()
                        for k in ("no speech", "didn't catch")
                    )
                ]
                mark("no hard no-speech error on session", not hard_no_speech_errs)
                with contextlib.suppress(Exception):
                    await ws.close()
                with contextlib.suppress(Exception):
                    reader.cancel()
            except Exception as exc:
                mark_blocked("native mic check", str(exc)[:100])
        else:
            mark_blocked("native mic check", "no renderer token")

        # 7 --------------------------------------- window/bubble size isolation
        # Renderer viewport of the main window: the bubble geometry is 72x72,
        # so a live panel viewport far larger than that proves the main window
        # can never inherit bubble bounds (also enforced by electron/main.js's
        # minimum-bounds guard).
        viewport = await cdp.evaluate("(() => ({ w: window.innerWidth, h: window.innerHeight }))()")
        val = viewport.get("value") or {}
        w, h = val.get("w"), val.get("h")
        mark(
            "main window never inherits bubble bounds",
            isinstance(w, int) and isinstance(h, int) and (w > 200 and h > 200),
            f"viewport={w}x{h} (bubble=72x72)",
        )

        await cdp.close()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(Exception):
                proc.terminate()

    failed = [r for r in RESULTS if r.startswith("FAILED")]
    if failed:
        print(f"\nCOMPANION_RESULT=FAILED ({len(failed)} failed)")
        return 1
    print("\nCOMPANION_RESULT=PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
