"""A ``DataSource`` that serves the synthetic fixtures, driven by a ``Clock``.

Used by tests, by replay mode (Phase 6.5) and in cloud sessions with no internet. Because
it honours the clock, it never returns a bar that hasn't "happened" yet, which is the same
no-look-ahead guarantee the real sources must give.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import json
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import REPO_ROOT
from backend.core.clock import Clock, ms_to_dt, utc_to_ms
from backend.core.types import MARKET_TZ, Bar, CorporateAction, Market, Timeframe

DEFAULT_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "market"


@lru_cache(maxsize=256)
def _load(path: Path) -> tuple[Bar, ...]:
    with gzip.open(path, "rt", newline="") as fh:
        return tuple(
            Bar(
                ts=int(r["ts"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
                source="fake",
                split_factor=float(r["split_factor"]),
            )
            for r in csv.DictReader(fh)
        )


@lru_cache(maxsize=256)
def _load_stamps(path: Path) -> tuple[int, ...]:
    return tuple(b.ts for b in _load(path))


class FakeSource:
    name = "fake"

    def __init__(self, clock: Clock, fixtures_dir: Path = DEFAULT_FIXTURES) -> None:
        self.clock = clock
        self.dir = fixtures_dir
        self.manifest: dict[str, Any] = json.loads((fixtures_dir / "manifest.json").read_text())
        self._by_alias: dict[str, str] = {}
        for sym, info in self.manifest["symbols"].items():
            self._by_alias[sym] = sym
            self._by_alias[info["yahoo_symbol"]] = sym

    # -- helpers

    def canonical(self, symbol: str) -> str:
        try:
            return self._by_alias[symbol]
        except KeyError:
            raise KeyError(f"The fake source has no data for '{symbol}'.") from None

    def market_of(self, symbol: str) -> Market:
        return Market(self.manifest["symbols"][self.canonical(symbol)]["market"])

    def bar_end_ms(self, symbol: str, timeframe: Timeframe, ts: int) -> int:
        """When a bar closes: its duration, cut short by the session close."""
        market = self.market_of(symbol)
        tz = ZoneInfo(MARKET_TZ[market])
        day = ms_to_dt(ts, tz).date()
        close = self._session_close(market, day)
        close_ms = int(datetime.combine(day, close, tz).timestamp() * 1000)
        if timeframe is Timeframe.D1:
            return close_ms
        return min(ts + timeframe.minutes * 60_000, close_ms)

    def _session_close(self, market: Market, day: date) -> time:
        early = self.manifest["early_closes"][market.value].get(day.isoformat())
        hhmm = early or self.manifest["sessions"][market.value]["close"]
        return time.fromisoformat(hhmm)

    def _path(self, symbol: str, timeframe: Timeframe) -> Path | None:
        sym = self.canonical(symbol)
        if timeframe.value not in self.manifest["symbols"][sym]["timeframes"]:
            return None
        return self.dir / self.market_of(sym).value / f"{sym}_{timeframe.value}.csv.gz"

    def _all(self, symbol: str, timeframe: Timeframe) -> tuple[Bar, ...]:
        path = self._path(symbol, timeframe)
        return () if path is None else _load(path)

    def _visible(self, symbol: str, timeframe: Timeframe, last: int | None = None) -> list[Bar]:
        """Bars that have started by the clock's now; the open one is marked not final.
        With ``last``, only the newest ``last`` of them (cheap: replays call this a lot)."""
        now = self.clock.now_ms()
        path = self._path(symbol, timeframe)
        if path is None:
            return []
        bars = _load(path)
        upto = bisect.bisect_right(_load_stamps(path), now)
        lo = 0 if last is None else max(0, upto - last)
        out = list(bars[lo:upto])
        # Only the newest bar can still be forming (bars don't overlap).
        if out and self.bar_end_ms(symbol, timeframe, out[-1].ts) > now:
            out[-1] = _forming(out[-1])
        return out

    # -- DataSource protocol

    def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str | None:
        return symbol if symbol in self.manifest["symbols"] else None

    def window_start_ms(self, timeframe: Timeframe) -> int | None:
        return None

    def supports(self, market: Market, timeframe: Timeframe) -> bool:
        return any(
            info["market"] == market.value and timeframe.value in info["timeframes"]
            for info in self.manifest["symbols"].values()
        )

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        lo, hi = utc_to_ms(start), utc_to_ms(end)
        return [b for b in self._visible(symbol, timeframe) if lo <= b.ts < hi and b.is_final]

    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]:
        now = self.clock.now_ms()
        raw = self.manifest["corporate_actions"].get(self.canonical(symbol), [])
        return [
            CorporateAction(
                ex_date=a["ex_date"], kind=a["kind"], ratio=a["ratio"], amount=a["amount"]
            )
            for a in raw
            if a["ex_date"] <= now
        ]

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        return {s: self._visible(s, timeframe, last=5) for s in symbols}


def _forming(bar: Bar) -> Bar:
    """A bar still in progress. We don't know its future high/low/close, so we show only
    what was known at its open: this keeps the fake strictly look-ahead free."""
    return Bar(
        ts=bar.ts,
        open=bar.open,
        high=bar.open,
        low=bar.open,
        close=bar.open,
        volume=0.0,
        source=bar.source,
        is_final=False,
        split_factor=bar.split_factor,
    )
