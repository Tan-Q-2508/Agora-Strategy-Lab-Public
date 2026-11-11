from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.config import Paths
from backend.context import AppContext
from backend.core.types import Market
from backend.db.engine import Database
from backend.db.models import HolidayOverride
from backend.fakes.clock import FakeClock
from backend.main import create_app
from backend.markets.calendar import ExchangeCalendar, Override
from backend.markets.status import describe, market_status

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")
CAL = ExchangeCalendar()


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_india_open_mid_session() -> None:
    now = ms(datetime(2026, 10, 21, 11, 0, tzinfo=IST))  # Wednesday
    st = market_status(CAL, Market.IN, now)
    assert st.is_open
    assert st.next_change_ms == ms(datetime(2026, 10, 21, 15, 30, tzinfo=IST))
    d = describe(st, now)
    assert d["next_change_display"] == "Closes 15:30 IST"
    assert d["seconds_to_change"] == 4 * 3600 + 30 * 60
    assert d["approximate"] is False


def test_friday_evening_opens_monday() -> None:
    now = ms(datetime(2026, 10, 23, 17, 0, tzinfo=ET))  # Friday after close
    st = market_status(CAL, Market.US, now)
    assert not st.is_open
    assert st.next_change_ms == ms(datetime(2026, 10, 26, 9, 30, tzinfo=ET))
    assert describe(st, now)["next_change_display"] == "Opens Mon 09:30 ET"


def test_before_open_same_day() -> None:
    now = ms(datetime(2026, 10, 21, 8, 0, tzinfo=IST))
    st = market_status(CAL, Market.IN, now)
    assert not st.is_open
    assert describe(st, now)["next_change_display"] == "Opens 09:15 IST"


def test_exchange_holidays_and_early_closes_come_from_the_calendar() -> None:
    # 2026-12-25 is a NYSE holiday; the day after Thanksgiving closes at 13:00 ET.
    xmas = ms(datetime(2026, 12, 25, 11, 0, tzinfo=ET))
    st = market_status(CAL, Market.US, xmas)
    assert not st.is_open
    assert st.next_change_ms == ms(datetime(2026, 12, 28, 9, 30, tzinfo=ET))
    black_friday = ms(datetime(2026, 11, 27, 12, 0, tzinfo=ET))
    assert market_status(CAL, Market.US, black_friday).next_change_ms == ms(
        datetime(2026, 11, 27, 13, 0, tzinfo=ET)
    )


def test_overrides_holiday_and_early_close() -> None:
    cal = ExchangeCalendar(
        {
            Market.IN: {date(2026, 10, 21): Override("closed")},
            Market.US: {date(2026, 11, 25): Override("early_close", time(13, 0))},
        }
    )
    now = ms(datetime(2026, 10, 21, 11, 0, tzinfo=IST))
    st = market_status(cal, Market.IN, now)
    assert not st.is_open
    assert st.next_change_ms == ms(datetime(2026, 10, 22, 9, 15, tzinfo=IST))
    now_us = ms(datetime(2026, 11, 25, 12, 0, tzinfo=ET))
    assert market_status(cal, Market.US, now_us).next_change_ms == ms(
        datetime(2026, 11, 25, 13, 0, tzinfo=ET)
    )


def test_api_uses_holiday_overrides(paths: Paths, db: Database, clock: FakeClock) -> None:
    ctx = AppContext(paths=paths, db=db, clock=clock, calendar=ExchangeCalendar())
    with TestClient(create_app(ctx)) as client:
        with ctx.db.session() as s:
            s.add(HolidayOverride(market_code="IN", date="2026-01-01", kind="closed", note="t"))
        body = client.get("/api/markets/status").json()  # clock: 2026-01-01 00:00 UTC (Thu)
    india = next(m for m in body["markets"] if m["market"] == "IN")
    assert india["is_open"] is False
    assert india["next_change_display"] == "Opens Fri 09:15 IST"
    us = next(m for m in body["markets"] if m["market"] == "US")
    assert us["approximate"] is False


def test_api_status_with_fixture_calendar(client: TestClient) -> None:
    body = client.get("/api/markets/status").json()
    assert {m["market"] for m in body["markets"]} == {"IN", "US"}
