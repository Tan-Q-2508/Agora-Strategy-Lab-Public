"""When candles close, and so when the live feed should ask for them (DATA_SOURCES §5).

A candle closes ``timeframe`` after it opens, or at the session close if that comes first
(the last candle of a day can be short). Daily candles close at the session close.
"""

from __future__ import annotations

from backend.core.types import Market, Timeframe
from backend.markets.calendar import Calendar, Session, next_session, previous_session, session_at

POLL_DELAY_MS = 5_000  # ask a few seconds after the close (hh:mm:05)
MIN_POLL_MS = 60_000


def poll_interval_ms(timeframe: Timeframe) -> int:
    return max(timeframe.minutes * 60_000, MIN_POLL_MS)


def bar_end_ms(cal: Calendar, market: Market, timeframe: Timeframe, ts: int) -> int:
    s = session_at(cal, market, ts)
    if s is None:  # unknown day: trust the data and assume a full-length candle
        return ts + timeframe.minutes * 60_000 if timeframe.is_intraday else ts
    if timeframe is Timeframe.D1:
        return s.close_ms
    return min(ts + timeframe.minutes * 60_000, s.close_ms)


def _closes(s: Session, timeframe: Timeframe) -> list[int]:
    if timeframe is Timeframe.D1:
        return [s.close_ms]
    step = timeframe.minutes * 60_000
    out = list(range(s.open_ms + step, s.close_ms, step))
    out.append(s.close_ms)
    return out


def next_bar_close(
    cal: Calendar, market: Market, timeframe: Timeframe, after_ms: int
) -> int | None:
    """The first candle close strictly after ``after_ms``."""
    s = next_session(cal, market, after_ms)
    while s is not None:
        for c in _closes(s, timeframe):
            if c > after_ms:
                return c
        s = next_session(cal, market, s.close_ms)
    return None


def last_bar_close(cal: Calendar, market: Market, timeframe: Timeframe, at_ms: int) -> int | None:
    """The most recent candle close at or before ``at_ms``."""
    s = session_at(cal, market, at_ms)
    if s is not None:
        done = [c for c in _closes(s, timeframe) if c <= at_ms]
        if done:
            return done[-1]
    prev = previous_session(cal, market, at_ms)
    return prev.close_ms if prev is not None else None


def bar_open_for_close(cal: Calendar, market: Market, timeframe: Timeframe, close_ms: int) -> int:
    """The open time (``ts``) of the candle that closes at ``close_ms``."""
    s = session_at(cal, market, close_ms - 1)
    if s is None:
        return close_ms - timeframe.minutes * 60_000
    if timeframe is Timeframe.D1:
        return s.open_ms
    step = timeframe.minutes * 60_000
    return s.open_ms + ((close_ms - 1 - s.open_ms) // step) * step
