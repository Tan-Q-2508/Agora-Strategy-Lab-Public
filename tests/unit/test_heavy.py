"""Background brains take turns (D-113): never two inside at once."""

from __future__ import annotations

import threading
import time

from backend.core import heavy


def test_background_work_takes_turns() -> None:
    inside: list[int] = []
    most = [0]

    def work(n: int) -> None:
        with heavy.background_turn(f"worker {n}"):
            inside.append(n)
            most[0] = max(most[0], len(inside))
            assert heavy.holder == f"worker {n}"
            time.sleep(0.02)
            inside.remove(n)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1 and heavy.holder == ""
