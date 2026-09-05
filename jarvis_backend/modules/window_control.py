"""Backend <-> renderer window-control signaling.

The backend orchestrator runs in its own process and cannot reach the Electron
main process directly.  A ``control_app_window`` tool therefore broadcasts a
``window_action`` message to connected renderers over the WebSocket and waits
(bounded) for a matching ``window_action_ack`` echo before reporting a verified
result.  Without an ack the tool reports an honest failure instead of claiming
the window was opened.
"""

import asyncio
import contextlib
import logging
import threading

logger = logging.getLogger(__name__)

_sockets: set = set()
_lock = threading.Lock()
_ack_waiters: dict[str, asyncio.Event] = {}


def register_socket(ws) -> None:
    with _lock:
        _sockets.add(ws)


def unregister_socket(ws) -> None:
    with _lock:
        _sockets.discard(ws)


def connected() -> int:
    with _lock:
        return len(_sockets)


async def broadcast(payload: dict) -> int:
    with _lock:
        targets = list(_sockets)
    sent = 0
    for ws in targets:
        with contextlib.suppress(Exception):
            await ws.send_json(payload)
            sent += 1
    return sent


def notify_ack(request_id: str) -> None:
    event = _ack_waiters.get(request_id)
    if event is not None:
        event.set()


async def wait_for_ack(request_id: str, timeout: float = 3.0) -> bool:
    event = asyncio.Event()
    _ack_waiters[request_id] = event
    try:
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except TimeoutError:
            return False
    finally:
        _ack_waiters.pop(request_id, None)
