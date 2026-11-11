"""One background brain at a time (D-113).

Metis's research, Kairos's always-on learner and the world desk each do minutes of number
crunching in their own thread. Agora is one Python process, so when all of them crunched at once
(with the user's own backtests on top) every screen waited its turn for 10–80 seconds on the
laptop. They now take turns through this lock; what the user starts (backtests, checks,
downloads) never waits for it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_turn = threading.Lock()
holder = ""  # who is working now, for the log and the status screens


@contextmanager
def background_turn(who: str) -> Iterator[None]:
    global holder
    with _turn:
        holder = who
        try:
            yield
        finally:
            holder = ""
