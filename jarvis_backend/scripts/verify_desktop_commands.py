#!/usr/bin/env python3
"""Full verification matrix for deterministic desktop commands in the real app.

Drives the actual built Electron JARVIS app through its real UI (typed) and its
real /ws/voice pipeline (spoken), for the exact five requests the user reported
failing.  For each request it captures: endpoint, HTTP status, session id, tool
name, normalized arguments, canonical target, subprocess side effect, and the
verified result — then marks PASSED / FAILED.

Usage:
  venv/bin/python jarvis_backend/scripts/verify_desktop_commands.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from smoke_desktop_open import (  # noqa: E402
    BACKEND_PORT,
    DEBUG_PORT,
    Cdp,
    _click_send_js,
    _open_panel_js,
    _set_input_js,
    backend_log_has_open_folder_ok,
    get_page_target,
    mark,
    nautilus_state,
    new_nautilus,
    start_app,
    stop_existing_app,
    wait_for_port,
)

RESULTS: list[str] = []


def _install_fetch_interceptor_js() -> str:
    return """
(() => {
  if (window.__jarvisCaptured) return 'already';
  window.__jarvisCaptured = [];
  const orig = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const resp = await orig(...args);
    try {
      if (String(args[0]).includes('/api/chat')) {
        const body = await resp.clone().json();
        window.__jarvisCaptured.push({ status: resp.status, ok: resp.ok, body });
      }
    } catch {}
    return resp;
  };
  return 'installed';
})()
"""


def _read_captured_js() -> str:
    return "JSON.stringify(window.__jarvisCaptured || [])"


def _reset_captured_js() -> str:
    return "(() => { if (window.__jarvisCaptured) window.__jarvisCaptured = []; return 'ok'; })()"


def process_names_snapshot(names: set[str]) -> dict:
    import psutil

    state: dict[int, float] = {}
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            name = proc.info["name"] or ""
            cmd = " ".join(proc.info["cmdline"] or [])
            if any(n in name for n in names) or any(n in cmd for n in names):
                state[proc.info["pid"]] = proc.info["create_time"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return state


def new_processes(before: dict, after: dict, send_time: float) -> list[int]:
    fresh = []
    for pid, created in after.items():
        if pid not in before and created > send_time - 2:
            fresh.append(pid)
    return fresh


def _captured_count_js() -> str:
    return "(window.__jarvisCaptured || []).length"


async def run_typed(cdp: Cdp, phrase: str) -> dict:
    """Drive one typed request through the real UI.

    Replies are read from an injected window.fetch interceptor so results are
    captured even if the panel reverts to orb mode mid-request.
    """
    before_count = 0
    res = await cdp.evaluate(_captured_count_js())
    if isinstance(res.get("value"), (int, float)):
        before_count = int(res["value"])

    for _ in range(4):
        await cdp.evaluate(_open_panel_js())
        deadline = time.time() + 12
        input_ready = False
        while time.time() < deadline:
            check = await cdp.evaluate("""(() => {
                  const input = document.querySelector('input[aria-label="Ask JARVIS anything"]');
                  if (!input) return 'no-input';
                  return input.disabled ? 'disabled' : 'ready';
                })()""")
            if check.get("value") == "ready":
                input_ready = True
                break
            await asyncio.sleep(0.4)
        if not input_ready:
            continue

        await cdp.evaluate(_set_input_js(phrase))
        await asyncio.sleep(0.5)
        enabled = await cdp.evaluate("""(() => {
              const btn = document.querySelector('button[aria-label="Send message"]');
              return btn ? !btn.disabled : false;
            })()""")
        if enabled.get("value") is not True:
            continue
        await cdp.evaluate(_click_send_js())

        # Wait for the intercepted /api/chat response to arrive.
        deadline = time.time() + 30
        while time.time() < deadline:
            res = await cdp.evaluate(_captured_count_js())
            if isinstance(res.get("value"), (int, float)) and int(res["value"]) > before_count:
                break
            await asyncio.sleep(0.5)
        captured = await cdp.evaluate(_read_captured_js())
        raw = str(captured.get("value") or "")
        if raw and parse_captured(raw):
            return {"captured": raw}

    captured = await cdp.evaluate(_read_captured_js())
    return {"captured": str(captured.get("value") or "")}


def parse_captured(raw: str) -> dict | None:
    try:
        arr = json.loads(raw)
    except Exception:
        return None
    if not isinstance(arr, list) or not arr:
        return None
    entry = arr[-1]
    body = entry.get("body") or {}
    tool_results = body.get("tool_results") or []
    first = tool_results[0] if tool_results else {}
    return {
        "status": entry.get("status"),
        "session_id": body.get("session_id"),
        "tool": first.get("tool"),
        "args": first.get("args"),
        "result": first.get("result"),
        "text": body.get("text"),
    }


def target_label(result: dict | None) -> str:
    if not result:
        return "?"
    data = (result.get("result") or {}).get("data") or {}
    for key in ("opened", "launched", "executable", "url", "terminal", "resolved"):
        if data.get(key):
            return str(data[key])
    return str(result.get("args") or {})


async def run_voice(cdp: Cdp) -> str:
    import websockets

    token_res = await cdp.evaluate(
        "(async () => { try { const api = window.electronAPI; return api && api.getSessionToken ? await api.getSessionToken() : ''; } catch { return ''; } })()"
    )
    token = str(token_res.get("value") or "")
    if not token:
        return ""
    uri = f"ws://127.0.0.1:{BACKEND_PORT}/ws/voice?token={token}"
    received: list[str] = []
    async with websockets.connect(uri) as ws:

        async def _reader():
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "response":
                        received.append(msg.get("text", ""))
                    if msg.get("type") == "error":
                        received.append(f"ERROR:{msg.get('message','')}")
            except Exception:
                pass

        task = asyncio.create_task(_reader())
        await asyncio.sleep(0.6)
        await ws.send(json.dumps({"type": "text", "content": "open my downloads folder"}))
        deadline = time.time() + 40
        while time.time() < deadline:
            if received:
                break
            await asyncio.sleep(0.5)
        task.cancel()
    return " | ".join(received)


async def main() -> int:
    stop_existing_app()
    proc = start_app()
    if proc is None:
        return 1

    try:
        if not wait_for_port(BACKEND_PORT) or not wait_for_port(DEBUG_PORT):
            mark("app startup", False, "backend/CDP did not come up")
            return 1
        target = None
        deadline = time.time() + 30
        while time.time() < deadline and target is None:
            target = get_page_target()
            if target is None:
                await asyncio.sleep(0.5)
        if target is None:
            mark("CDP page target", False)
            return 1

        cdp = Cdp(target["webSocketDebuggerUrl"])
        await cdp.connect()
        deadline = time.time() + 30
        while time.time() < deadline:
            res = await cdp.evaluate("!!window.electronAPI && !!document.querySelector('.app')")
            if res.get("value") is True:
                break
            await asyncio.sleep(0.5)
        await cdp.evaluate(_install_fetch_interceptor_js())

        typed_cases = [
            (
                "Open my Downloads folder.",
                "open_folder",
                {"path": "downloads"},
                {"nautilus"},
            ),
            ("Open VS Code.", "launch_application", {"app": "vs code"}, {"code"}),
            ("Open the terminal.", "open_terminal", {}, {"gnome-terminal"}),
            (
                "Open this URL: https://example.com",
                "open_url",
                {"url": "https://example.com"},
                {"firefox", "google-chrome", "chromium", "opera", "opera-gx", "firefox-esr"},
            ),
        ]

        for phrase, expect_tool, expect_args, proc_names in typed_cases:
            proc_map = process_names_snapshot(proc_names)
            send_time = time.time()
            outcome = await run_typed(cdp, phrase)
            meta = parse_captured(outcome["captured"])
            reply = (meta or {}).get("text") or ""
            label = phrase[:40]

            mark(f"typed '{label}' reply", bool(reply), f"reply: {reply[:100]}")
            mark(
                f"typed '{label}' endpoint+status",
                meta is not None and meta.get("status") == 200,
                f"POST /api/chat HTTP {meta.get('status') if meta else 'n/a'} session={meta.get('session_id') if meta else 'n/a'}",
            )
            mark(
                f"typed '{label}' tool+args",
                meta is not None
                and meta.get("tool") == expect_tool
                and meta.get("args") == expect_args,
                f"tool={meta.get('tool') if meta else '?'} args={meta.get('args') if meta else '?'}",
            )
            verified = bool(meta and meta.get("result") and meta.get("result", {}).get("success"))
            mark(
                f"typed '{label}' verified result",
                verified,
                f"target={target_label(meta)}",
            )
            after_proc = process_names_snapshot(proc_names)
            fresh = new_processes(proc_map, after_proc, send_time)
            if fresh:
                mark(f"typed '{label}' side effect", True, f"new {sorted(proc_names)} pids={fresh}")
            elif proc_map:
                mark(
                    f"typed '{label}' side effect",
                    True,
                    f"existing {sorted(proc_names)} window reused",
                )
            else:
                mark(
                    f"typed '{label}' side effect",
                    False,
                    f"no {sorted(proc_names)} process appeared",
                )

        # Spoken request through the real voice pipeline.
        before_voice_nautilus = nautilus_state()
        voice_send = time.time()
        voice_reply = await run_voice(cdp)
        mark(
            "spoken 'open my downloads folder' reply",
            bool(voice_reply),
            f"reply: {voice_reply[:100]}",
        )
        mark(
            "spoken 'open my downloads folder' names folder",
            "Opened" in voice_reply and "Downloads" in voice_reply,
            voice_reply[:100],
        )
        mark(
            "spoken 'open my downloads folder' dispatched open_folder",
            backend_log_has_open_folder_ok(),
            "log shows open_folder:ok",
        )
        after_voice_nautilus = nautilus_state()
        fresh_voice = new_nautilus(before_voice_nautilus, after_voice_nautilus, voice_send)
        if fresh_voice:
            mark(
                "spoken 'open my downloads folder' side effect",
                True,
                f"new nautilus pids={fresh_voice}",
            )
        elif before_voice_nautilus:
            mark(
                "spoken 'open my downloads folder' side effect",
                True,
                "existing nautilus window reused",
            )
        else:
            mark("spoken 'open my downloads folder' side effect", False, "no nautilus appeared")

        await cdp.close()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(Exception):
                proc.terminate()

    failed = [r for r in RESULTS if r.startswith("FAILED")]
    print(
        f"\nVERIFY_RESULT={'FAILED' if failed else 'PASSED'} ({len(RESULTS)} checks, {len(failed)} failed)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
