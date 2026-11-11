from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.core.types import Market, Timeframe
from backend.fakes.data_source import FakeSource
from backend.markets.calendar import (
    ExchangeCalendar,
    FixtureCalendar,
    is_open,
    next_open,
    previous_session,
    session_bounds,
    sessions_between_ms,
)

IST = ZoneInfo("Asia/Kolkata")
CAL = ExchangeCalendar()


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_nse_muhurat_session_is_an_evening_session() -> None:
    s = session_bounds(CAL, Market.IN, date(2025, 10, 21))
    assert s is not None
    assert datetime.fromtimestamp(s.open_ms / 1000, IST).hour == 13


def test_weekend_and_holiday_queries() -> None:
    sat = ms(datetime(2026, 10, 24, 12, 0, tzinfo=IST))
    assert not is_open(CAL, Market.IN, sat)
    assert next_open(CAL, Market.IN, sat) == ms(datetime(2026, 10, 26, 9, 15, tzinfo=IST))
    prev = previous_session(CAL, Market.IN, sat)
    assert prev is not None and prev.day == date(2026, 10, 23)


def test_every_fixture_daily_bar_opens_a_fixture_session(fake_source: FakeSource) -> None:
    cal = FixtureCalendar(fake_source.manifest)
    for sym in ("RELIANCE", "SPY"):
        market = fake_source.market_of(sym)
        bars = fake_source._all(sym, Timeframe.D1)
        opens = {s.open_ms for s in sessions_between_ms(cal, market, bars[0].ts, bars[-1].ts + 1)}
        assert {b.ts for b in bars} <= opens
