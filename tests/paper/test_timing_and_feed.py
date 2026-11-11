"""Candle-close timing and the live feed's "is this candle final yet?" rule."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import store
from backend.fakes.clock import FakeClock
from backend.fakes.data_source import FakeSource
from backend.markets.calendar import FixtureCalendar
from backend.paper.feed import LiveFeed
from backend.paper.timing import bar_open_for_close, last_bar_close, next_bar_close


def ist(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> int:
    # IST is UTC+5:30
    return int(datetime(y, mo, d, h, mi, s, tzinfo=UTC).timestamp() * 1000) - 19_800_000


def test_candle_closes_follow_the_session(fixture_calendar: FixtureCalendar) -> None:
    cal = fixture_calendar
    m5 = Timeframe.M5
    # Mon 3 Nov 2025: 09:15–15:30 IST
    assert next_bar_close(cal, Market.IN, m5, ist(2025, 11, 3, 9, 0)) == ist(2025, 11, 3, 9, 20)
    assert next_bar_close(cal, Market.IN, m5, ist(2025, 11, 3, 9, 20)) == ist(2025, 11, 3, 9, 25)
    assert next_bar_close(cal, Market.IN, m5, ist(2025, 11, 3, 15, 29)) == ist(2025, 11, 3, 15, 30)
    # after the close: the next session's first candle
    assert next_bar_close(cal, Market.IN, m5, ist(2025, 11, 3, 15, 30)) == ist(2025, 11, 4, 9, 20)
    assert last_bar_close(cal, Market.IN, m5, ist(2025, 11, 3, 9, 22)) == ist(2025, 11, 3, 9, 20)
    assert last_bar_close(cal, Market.IN, m5, ist(2025, 11, 3, 9, 17)) == ist(2025, 10, 31, 15, 30)
    assert bar_open_for_close(cal, Market.IN, m5, ist(2025, 11, 3, 9, 20)) == ist(
        2025, 11, 3, 9, 15
    )
    # 1h candles: the last one of the day is short (15:15–15:30)
    h1 = Timeframe.H1
    assert next_bar_close(cal, Market.IN, h1, ist(2025, 11, 3, 15, 0)) == ist(2025, 11, 3, 15, 15)
    assert next_bar_close(cal, Market.IN, h1, ist(2025, 11, 3, 15, 15)) == ist(2025, 11, 3, 15, 30)
    assert bar_open_for_close(cal, Market.IN, h1, ist(2025, 11, 3, 15, 30)) == ist(
        2025, 11, 3, 15, 15
    )
    d1 = Timeframe.D1
    assert next_bar_close(cal, Market.IN, d1, ist(2025, 11, 3, 10, 0)) == ist(2025, 11, 3, 15, 30)
    assert bar_open_for_close(cal, Market.IN, d1, ist(2025, 11, 3, 15, 30)) == ist(
        2025, 11, 3, 9, 15
    )


def test_feed_waits_before_trusting_the_newest_candle(ctx: AppContext) -> None:
    clock = FakeClock(ist(2025, 11, 3, 15, 30, 5))
    feed = LiveFeed(ctx.db, clock, ctx.calendar, [FakeSource(clock)])
    with ctx.db.session() as s:
        inst = store.find_instrument(s, Market.IN, "RELIANCE")
    assert inst is not None
    since = {inst.id: ist(2025, 11, 3, 15, 15)}
    # At 15:30:05 the 15:25 candle closed 5 s ago and is the day's last: it must wait a
    # minute (Yahoo may still revise it). 15:20 already has a later candle, so it's final.
    r = feed.poll([inst], Timeframe.M5, since)
    assert r.ok
    got = [b.ts for b in r.bars.get(inst.id, [])]
    assert got == [ist(2025, 11, 3, 15, 20)], "15:20 has a later candle; 15:25 must wait"
    clock.set(ist(2025, 11, 3, 15, 31, 5))
    r = feed.poll([inst], Timeframe.M5, {inst.id: ist(2025, 11, 3, 15, 20)})
    assert [b.ts for b in r.bars[inst.id]] == [ist(2025, 11, 3, 15, 25)]
    # stored for later backtests
    with ctx.db.session() as s:
        stored = store.load_bars(
            s, inst.id, Timeframe.M5, ist(2025, 11, 3, 15, 20), ist(2025, 11, 3, 15, 30)
        )
    assert len(stored) == 2


def test_feed_catches_up_after_a_long_gap(ctx: AppContext) -> None:
    clock = FakeClock(ist(2025, 11, 3, 11, 0, 5))
    feed = LiveFeed(ctx.db, clock, ctx.calendar, [FakeSource(clock)])
    with ctx.db.session() as s:
        inst = store.find_instrument(s, Market.IN, "RELIANCE")
    assert inst is not None
    r = feed.poll([inst], Timeframe.M5, {inst.id: ist(2025, 11, 3, 9, 15)})
    stamps = [b.ts for b in r.bars[inst.id]]
    assert stamps[0] == ist(2025, 11, 3, 9, 20)
    assert stamps[-1] == ist(2025, 11, 3, 10, 55)
    assert len(stamps) == len(set(stamps)) == 20


def test_feed_reports_failure_in_plain_english(ctx: AppContext) -> None:
    class Down:
        name = "yahoo"

        def supports(self, market: Market, timeframe: Timeframe) -> bool:
            return True

        def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str:
            return yahoo_symbol

        def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[object]]:
            raise RuntimeError("boom")

    clock = FakeClock(ist(2025, 11, 3, 11, 0))
    feed = LiveFeed(ctx.db, clock, ctx.calendar, [Down()])  # type: ignore[list-item]
    with ctx.db.session() as s:
        inst = store.find_instrument(s, Market.IN, "RELIANCE")
    assert inst is not None
    r = feed.poll([inst], Timeframe.M5, {})
    assert not r.ok
    assert r.message == "Couldn't get live India prices right now."
    assert "boom" in r.detail
