"""Live E2E test for the native voice WebSocket endpoint.

Connects to a running backend, checks device enumeration, runs a mic test
(verifies real level data arrives from the actual microphone), and drives a
PTT-style capture.

Usage:
    python scripts/e2e_native_voice.py [token] [ws_url]
"""

import asyncio
import json
import sys

import websockets


async def drain(ws, timeout=1.0):
    msgs = []
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
            if isinstance(msg, str):
                msg = json.loads(msg)
            msgs.append(msg)
    except TimeoutError:
        pass
    return msgs


async def recv_json(ws, timeout=2.0):
    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(msg) if isinstance(msg, str) else msg


async def main(token, url):
    async with websockets.connect(f"{url}?token={token}") as ws:
        print("== connected ==")

        await ws.send('{"type": "connect"}')
        await asyncio.sleep(0.5)
        msgs = await drain(ws)
        types = [m.get("type") for m in msgs]
        print("connect events:", types)
        assert "devices" in types, "expected devices event"
        assert "READY" in str(types) or "READY" in str(msgs), "expected READY state"
        for m in msgs:
            if m.get("type") == "devices":
                print(f"  devices: {len(m['devices'])} -> {[d['name'] for d in m['devices']]}")

        print("\n== mic test (2s) ==")
        await ws.send('{"type": "mic_test_start"}')
        levels = []
        start = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start < 2.5:
            msg = await recv_json(ws, timeout=2.0)
            if msg.get("type") == "level":
                levels.append(msg)
            elif msg.get("type") == "mic_test":
                print("mic_test:", msg.get("status"))
        await ws.send('{"type": "mic_test_stop"}')
        print(f"  received {len(levels)} level events")
        if levels:
            print(f"  sample level: {levels[-1]}")
            rms_values = [m["rms"] for m in levels]
            print(f"  max rms={max(rms_values):.4f} min rms={min(rms_values):.4f}")
        else:
            print("  NO LEVEL DATA — mic capture broken")
            return 1

        print("\n== get_devices ==")
        await ws.send('{"type": "get_devices"}')
        msgs = await drain(ws, timeout=1.0)
        print("  events:", [m.get("type") for m in msgs])

        print("\n== ping ==")
        await ws.send('{"type": "ping"}')
        msgs = await drain(ws, timeout=1.0)
        assert any(m.get("type") == "pong" for m in msgs), "expected pong"
        print("  pong ok")

        print("\n== PTT record (2s) ==")
        await ws.send('{"type": "start_listening", "mode": "ptt"}')
        await asyncio.sleep(2.0)
        await ws.send('{"type": "stop_listening"}')
        msgs = await drain(ws, timeout=1.5)
        print("  events after PTT:", [m.get("type") for m in msgs])

        print("\nE2E NATIVE VOICE OK")
        return 0


if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else "test-e2e-token-123"
    url = sys.argv[2] if len(sys.argv) > 2 else "ws://127.0.0.1:8000/ws/voice/native"
    sys.exit(asyncio.run(main(token, url)))
