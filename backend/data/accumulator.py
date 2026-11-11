"""Saves intraday candles every day while Agora is open (SPEC §4).

Yahoo only keeps ~30 days of 1-minute and ~60 days of 5/15-minute candles. By saving
them daily, Agora's own intraday history keeps growing beyond that window.

It runs on a thread inside the app (D-06: nothing runs when Agora is closed). On start it
catches up on anything still inside Yahoo's window; then, a little after each market's
close, it saves that day's candles. It works through one symbol at a time through the
same throttled cache manager as everything else, so it never competes with the user.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date

from backend.core.types import Market, Timeframe
from backend.data import service
from backend.data.cache import CacheManager
from backend.db.engine import Database
from backend.logging_setup import get_logger
from backend.markets.calendar import Calendar, previous_session

log = get_logger("data.accumulator")

TIMEFRAMES = (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1)
AFTER_CLOSE_MS = 20 * 60_000  # give Yahoo time to finalise the last candles
CHECK_EVERY_S = 300.0


class IntradayAccumulator:
    def __init__(
        self,
        db: Database,
        cache: CacheManager,
        calendar: Calendar,
        *,
        enabled: Callable[[], bool] = lambda: True,
        check_every_s: float = CHECK_EVERY_S,
    ) -> None:
        self.db = db
        self.cache = cache
        self.calendar = calendar
        self.enabled = enabled
        self.check_every_s = check_every_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.done_for: dict[Market, date] = {}
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="agora-accumulator", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(30.0)  # let startup and the first screen load finish first
        while not self._stop.is_set():
            try:
                if self.enabled():
                    self.run_once()
            except Exception as exc:  # keep the thread alive; the next round may work
                self.last_error = repr(exc)
                log.exception("Intraday save failed")
            self._stop.wait(self.check_every_s)

    def due(self, market: Market, now_ms: int) -> date | None:
        """The session whose candles should be saved now, if not already done."""
        last = previous_session(self.calendar, market, now_ms - AFTER_CLOSE_MS)
        if last is None or self.done_for.get(market) == last.day:
            return None
        return last.day

    def run_once(self) -> int:
        """Save intraday candles for every market that has a new closed session.
        Returns the number of candles saved."""
        now = self.cache.clock.now_ms()
        saved = 0
        for market in Market:
            day = self.due(market, now)
            if day is None:
                continue
            with self.db.session() as s:
                targets = service.default_symbols(s, market)
            log.info("Saving %s intraday candles for %d symbols (%s)", market, len(targets), day)
            for inst in targets:
                for tf in TIMEFRAMES:
                    if self._stop.is_set():
                        return saved
                    start = service.default_start_ms(tf, now)
                    saved += self.cache.ensure(inst, tf, start, now + 1).fetched
            self.done_for[market] = day
        return saved
