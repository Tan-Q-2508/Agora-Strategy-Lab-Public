"""Keeps requests to a source politely spaced (DATA_SOURCES §2: about one per second).

One ``Throttle`` per source, shared by every thread that talks to it, so the onboarding
download, a backtest's gap fill and paper-trading polls can never burst together.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class Throttle:
    def __init__(
        self,
        min_interval_s: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        """Block until a request is allowed, then claim the slot."""
        with self._lock:
            now = self._monotonic()
            if self._last is not None:
                gap = self._last + self.min_interval_s - now
                if gap > 0:
                    self._sleep(gap)
                    now = self._monotonic()
            self._last = now
