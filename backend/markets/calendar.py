"""Market calendars: which days each exchange trades, and from when to when.

The real calendar comes from ``pandas_market_calendars`` (NSE and NYSE holidays, early
closes, NSE's evening Muhurat session), with the ``holiday_overrides`` table layered on
top so a wrong library holiday can be fixed without a code change (DATA_SOURCES §8).

Tests and fixture replays use ``FixtureCalendar``, built from the synthetic data's
manifest, because the fixtures follow a simplified calendar (D-22). Everything else talks
to the ``Calendar`` protocol, so the two are interchangeable.
"""

from __future__ import annotations

import bisect
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market

SESSION_HOURS: dict[Market, tuple[time, time]] = {
    Market.IN: (time(9, 15), time(15, 30)),
    Market.US: (time(9, 30), time(16, 0)),
}
PMC_NAME = {Market.IN: "NSE", Market.US: "NYSE"}


@dataclass(frozen=True, slots=True)
class Session:
    day: date  # the trading date in the market's timezone
    open_ms: int
    close_ms: int


@dataclass(frozen=True)
class Override:
    kind: str  # closed | open | early_close
    close_time: time | None = None


class Calendar(Protocol):
    approximate: bool

    def sessions(self, market: Market, start: date, end: date) -> list[Session]:
        """Trading sessions with ``start <= day <= end``, oldest first."""
        ...


def tz(market: Market) -> ZoneInfo:
    return ZoneInfo(MARKET_TZ[market])


def local_date(market: Market, ts_ms: int) -> date:
    return ms_to_dt(ts_ms, tz(market)).date()


def _ms(day: date, t: time, zone: ZoneInfo) -> int:
    return int(datetime.combine(day, t, zone).timestamp() * 1000)


def regular_session(market: Market, day: date, close: time | None = None) -> Session:
    zone = tz(market)
    open_t, close_t = SESSION_HOURS[market]
    return Session(day, _ms(day, open_t, zone), _ms(day, close or close_t, zone))


class _SessionTable:
    """Sessions of one market keyed by day, with a sorted index for range queries."""

    def __init__(self, by_day: dict[date, Session]) -> None:
        self.by_day = by_day
        self.days = sorted(by_day)

    def between(self, start: date, end: date) -> list[Session]:
        lo = bisect.bisect_left(self.days, start)
        hi = bisect.bisect_right(self.days, end)
        return [self.by_day[d] for d in self.days[lo:hi]]


def _apply_overrides(
    market: Market, table: dict[date, Session], overrides: Mapping[date, Override]
) -> dict[date, Session]:
    out = dict(table)
    for day, o in overrides.items():
        if o.kind == "closed":
            out.pop(day, None)
        elif o.kind == "open":
            out.setdefault(day, regular_session(market, day))
        elif o.kind == "early_close" and o.close_time is not None:
            base = out.get(day) or regular_session(market, day)
            out[day] = Session(day, base.open_ms, _ms(day, o.close_time, tz(market)))
    return out


class ExchangeCalendar:
    """The real NSE/NYSE calendars (2000 → two years ahead) plus local overrides."""

    approximate = False
    FIRST = date(2000, 1, 1)

    def __init__(self, overrides: Mapping[Market, Mapping[date, Override]] | None = None) -> None:
        self._lock = threading.Lock()
        self._base: dict[Market, dict[date, Session]] = {}
        self._tables: dict[Market, _SessionTable] = {}
        self._overrides: dict[Market, dict[date, Override]] = {m: {} for m in Market}
        if overrides:
            self.set_overrides(overrides)

    def set_overrides(self, overrides: Mapping[Market, Mapping[date, Override]]) -> None:
        with self._lock:
            self._overrides = {m: dict(overrides.get(m, {})) for m in Market}
            self._tables.clear()

    def _load_base(self, market: Market) -> dict[date, Session]:
        import pandas_market_calendars as pmc  # slow import; only when first needed

        last = date.today() + timedelta(days=730)
        sched = pmc.get_calendar(PMC_NAME[market]).schedule(
            start_date=self.FIRST.isoformat(), end_date=last.isoformat()
        )
        out: dict[date, Session] = {}
        for idx, row in zip(sched.index, sched.itertuples(index=False), strict=True):
            day = idx.date()
            out[day] = Session(
                day,
                int(row.market_open.timestamp() * 1000),
                int(row.market_close.timestamp() * 1000),
            )
        return out

    def _table(self, market: Market) -> _SessionTable:
        with self._lock:
            table = self._tables.get(market)
            if table is None:
                if market not in self._base:
                    self._base[market] = self._load_base(market)
                merged = _apply_overrides(market, self._base[market], self._overrides[market])
                table = self._tables[market] = _SessionTable(merged)
            return table

    def sessions(self, market: Market, start: date, end: date) -> list[Session]:
        return self._table(market).between(start, end)


class FixtureCalendar:
    """The simplified calendar the synthetic fixtures were generated with (D-22).

    Outside the fixtures' own years it is plain weekdays, so replays and status pills
    keep working on any date."""

    approximate = False

    def __init__(self, manifest: Mapping[str, Any]) -> None:
        self._tables: dict[Market, _SessionTable] = {}
        first, last = date(2000, 1, 1), date(2035, 12, 31)
        for market in Market:
            holidays = {date.fromisoformat(d) for d in manifest["holidays"][market.value]}
            early = {
                date.fromisoformat(d): time.fromisoformat(t)
                for d, t in manifest["early_closes"][market.value].items()
            }
            by_day: dict[date, Session] = {}
            day = first
            while day <= last:
                if day.weekday() < 5 and day not in holidays:
                    by_day[day] = regular_session(market, day, early.get(day))
                day += timedelta(days=1)
            self._tables[market] = _SessionTable(by_day)

    def sessions(self, market: Market, start: date, end: date) -> list[Session]:
        return self._tables[market].between(start, end)


# ---------------------------------------------------------------- queries

_LOOKAHEAD_DAYS = 20  # long weekends + holiday clusters never exceed this


def session_bounds(cal: Calendar, market: Market, day: date) -> Session | None:
    found = cal.sessions(market, day, day)
    return found[0] if found else None


def session_at(cal: Calendar, market: Market, ts_ms: int) -> Session | None:
    """The session that is open at ``ts_ms`` (open inclusive, close exclusive)."""
    s = session_bounds(cal, market, local_date(market, ts_ms))
    if s is not None and s.open_ms <= ts_ms < s.close_ms:
        return s
    return None


def is_open(cal: Calendar, market: Market, at_ms: int) -> bool:
    return session_at(cal, market, at_ms) is not None


def next_session(cal: Calendar, market: Market, after_ms: int) -> Session | None:
    """The first session that has not closed yet at ``after_ms``."""
    day = local_date(market, after_ms)
    for s in cal.sessions(market, day, day + timedelta(days=_LOOKAHEAD_DAYS)):
        if s.close_ms > after_ms:
            return s
    return None


def next_open(cal: Calendar, market: Market, after_ms: int) -> int | None:
    day = local_date(market, after_ms)
    for s in cal.sessions(market, day, day + timedelta(days=_LOOKAHEAD_DAYS)):
        if s.open_ms > after_ms:
            return s.open_ms
    return None


def previous_session(cal: Calendar, market: Market, before_ms: int) -> Session | None:
    """The last session that had fully closed by ``before_ms``."""
    day = local_date(market, before_ms)
    found = cal.sessions(market, day - timedelta(days=_LOOKAHEAD_DAYS), day)
    for s in reversed(found):
        if s.close_ms <= before_ms:
            return s
    return None


def sessions_between_ms(cal: Calendar, market: Market, start_ms: int, end_ms: int) -> list[Session]:
    """Sessions whose open time falls in ``[start_ms, end_ms)``."""
    found = cal.sessions(market, local_date(market, start_ms), local_date(market, end_ms))
    return [s for s in found if start_ms <= s.open_ms < end_ms]


def daily_ts(cal: Calendar, market: Market, day: date) -> int:
    """A daily bar's ``ts``: the session open (D-20), or the regular open if the calendar
    doesn't know the day (the data says it traded, so we trust the data)."""
    s = session_bounds(cal, market, day)
    return s.open_ms if s is not None else regular_session(market, day).open_ms
