"""``/ws``: one WebSocket per open tab, pushing live updates (API_CONTRACT → WebSocket).

Messages are ``{type, data}`` JSON from the in-process event bus: job progress, paper
ticks, fills and events, and data-source changes. The page re-fetches full state when it
reconnects, so a dropped message is never a problem.

The hello message carries ``boot_id`` (when this server started): a tab that reconnects to a
*restarted* Agora reloads itself, so the tab already open keeps working after "Start Agora"
(the user's request 2026-10-24, D-111). ``GET /api/tabs`` tells the launcher whether a tab is
connected, so it doesn't open another one.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from backend.context import AppContext

router = APIRouter()
BOOT_ID = time.time_ns() // 1_000_000  # one per server start


def _tabs(app: Any) -> int:
    return int(getattr(app.state, "ws_tabs", 0))


@router.get("/api/tabs")
def tabs(request: Request) -> dict[str, int]:
    """Open Agora tabs connected right now (the launcher asks before opening a new one)."""
    return {"tabs": _tabs(request.app), "boot_id": BOOT_ID}


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    ctx: AppContext = websocket.app.state.ctx
    await websocket.accept()
    queue = ctx.events.subscribe()
    app = websocket.app
    app.state.ws_tabs = _tabs(app) + 1

    async def drain_client() -> None:
        # The page sends nothing we need, but reading is how a disconnect is noticed.
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await websocket.receive_text()

    reader = asyncio.create_task(drain_client())
    try:
        hello = {"server_time": ctx.clock.now_ms(), "boot_id": BOOT_ID}
        await websocket.send_json({"type": "hello", "data": hello})
        while not reader.done():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                await websocket.send_json(getter.result())
            else:
                getter.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        reader.cancel()
        ctx.events.unsubscribe(queue)
        app.state.ws_tabs = max(0, _tabs(app) - 1)
