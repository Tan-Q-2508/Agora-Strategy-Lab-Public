"""In-process publish/subscribe for live updates (job progress, paper ticks, source status).

Worker threads publish; each WebSocket connection subscribes with its own asyncio queue.
Publishing never blocks a worker: if a browser tab stops reading, its oldest messages are
dropped (the UI re-fetches state on reconnect anyway).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Any

MAX_QUEUE = 1000


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MAX_QUEUE)
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subs = [(loop, sq) for loop, sq in self._subs if sq is not q]

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, type_: str, data: dict[str, Any]) -> None:
        msg = {"type": type_, "data": data}
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put, q, msg)
            except RuntimeError:  # loop closed: the connection is gone
                self.unsubscribe(q)


def _put(q: asyncio.Queue[dict[str, Any]], msg: dict[str, Any]) -> None:
    if q.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()
    q.put_nowait(msg)
