"""The input every indicator works on: one symbol's closed bars as numpy arrays.

Prices here are split-adjusted (D-07: signals use adjusted prices). ``session`` numbers
each trading session (0, 1, 2, …) so session-anchored indicators (VWAP, opening range,
previous day's levels) know where each day starts; ``session_open`` is that session's
official open time, so an opening range is measured from 09:15 even if the first candle
is missing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backend.core.types import Bar, Market, Timeframe

F64 = NDArray[np.float64]
I64 = NDArray[np.int64]


@dataclass(frozen=True)
class BarSeries:
    ts: I64
    open: F64
    high: F64
    low: F64
    close: F64
    volume: F64
    session: I64
    session_open: I64
    timeframe: Timeframe

    def __len__(self) -> int:
        return len(self.ts)

    def field(self, name: str) -> F64:
        """A price field by name, including the derived ``hl2`` and ``typical``."""
        if name == "hl2":
            return (self.high + self.low) / 2.0
        if name in ("typical", "hlc3"):
            return (self.high + self.low + self.close) / 3.0
        if name in ("open", "high", "low", "close", "volume"):
            arr: F64 = getattr(self, name)
            return arr
        raise KeyError(f"Unknown price field '{name}'")

    def upto(self, n: int) -> BarSeries:
        """The first ``n`` bars (used to prove indicators never look ahead)."""
        return BarSeries(
            self.ts[:n],
            self.open[:n],
            self.high[:n],
            self.low[:n],
            self.close[:n],
            self.volume[:n],
            self.session[:n],
            self.session_open[:n],
            self.timeframe,
        )


def from_bars(
    bars: Sequence[Bar],
    timeframe: Timeframe,
    market: Market,
    session_open_of: dict[int, int] | None = None,
) -> BarSeries:
    """Build a series from (already adjusted) bars. Sessions are split by local date;
    ``session_open_of`` maps a bar's ts → its session's official open (else the session's
    first bar is taken as the open)."""
    from backend.markets.calendar import local_date

    n = len(bars)
    ts = np.fromiter((b.ts for b in bars), dtype=np.int64, count=n)
    session = np.zeros(n, dtype=np.int64)
    sopen = np.zeros(n, dtype=np.int64)
    sid = -1
    last_day = None
    first_ts = 0
    for i, b in enumerate(bars):
        day = local_date(market, b.ts) if timeframe.is_intraday else b.ts
        if day != last_day:
            sid += 1
            last_day = day
            first_ts = b.ts
        session[i] = sid
        if session_open_of is not None and b.ts in session_open_of:
            sopen[i] = session_open_of[b.ts]
        else:
            sopen[i] = first_ts
    return BarSeries(
        ts=ts,
        open=np.fromiter((b.open for b in bars), dtype=np.float64, count=n),
        high=np.fromiter((b.high for b in bars), dtype=np.float64, count=n),
        low=np.fromiter((b.low for b in bars), dtype=np.float64, count=n),
        close=np.fromiter((b.close for b in bars), dtype=np.float64, count=n),
        volume=np.fromiter((b.volume for b in bars), dtype=np.float64, count=n),
        session=session,
        session_open=sopen,
        timeframe=timeframe,
    )


def from_arrays(
    close: Sequence[float],
    *,
    high: Sequence[float] | None = None,
    low: Sequence[float] | None = None,
    open_: Sequence[float] | None = None,
    volume: Sequence[float] | None = None,
    ts: Sequence[int] | None = None,
    session: Sequence[int] | None = None,
    session_open: Sequence[int] | None = None,
    timeframe: Timeframe = Timeframe.D1,
) -> BarSeries:
    """Convenience for tests: missing fields default to the close (or 0 volume)."""
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    t = np.asarray(ts if ts is not None else [i * 86_400_000 for i in range(n)], dtype=np.int64)
    sess = np.asarray(session if session is not None else list(range(n)), dtype=np.int64)
    return BarSeries(
        ts=t,
        open=np.asarray(open_ if open_ is not None else c, dtype=np.float64),
        high=np.asarray(high if high is not None else c, dtype=np.float64),
        low=np.asarray(low if low is not None else c, dtype=np.float64),
        close=c,
        volume=np.asarray(volume if volume is not None else [0.0] * n, dtype=np.float64),
        session=sess,
        session_open=np.asarray(session_open if session_open is not None else t, dtype=np.int64),
        timeframe=timeframe,
    )
