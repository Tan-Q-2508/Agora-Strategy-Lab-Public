"""Cache manager: fetch only what's missing, retry politely, fall back, log everything."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import select

from backend.context import AppContext
from backend.core.types import Bar, CorporateAction, Market, Timeframe
from backend.data import store
from backend.data.errors import RateLimited, SourceError
from backend.data.store import InstrumentRef
from backend.db.models import CorporateActionRow, DataFetchLog, SourceStatus
from backend.fakes.data_source import FakeSource
from backend.markets.calendar import sessions_between_ms

DAY_MS = 86_400_000
Y2016 = 1_451_606_400_000  # 2016-01-01 UTC
Y2026 = 1_767_225_600_000


def inst(ctx: AppContext, symbol: str, market: Market = Market.IN) -> InstrumentRef:
    with ctx.db.session() as s:
        r = store.find_instrument(s, market, symbol)
    assert r is not None
    return r


class CountingSource:
    """Wraps the fake source, counting calls and optionally failing."""

    def __init__(self, inner: FakeSource, name: str = "fake", fail_with: Exception | None = None):
        self.inner = inner
        self.name = name
        self.fail_with = fail_with
        self.calls: list[tuple[str, str, int, int]] = []

    def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str | None:
        return self.inner.symbol_for(market, symbol, yahoo_symbol)

    def window_start_ms(self, timeframe: Timeframe) -> int | None:
        return None

    def supports(self, market: Market, timeframe: Timeframe) -> bool:
        return self.inner.supports(market, timeframe)

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        self.calls.append(
            (symbol, timeframe.value, int(start.timestamp() * 1000), int(end.timestamp() * 1000))
        )
        if self.fail_with is not None:
            raise self.fail_with
        bars = self.inner.fetch_bars(symbol, timeframe, start, end)
        return [
            Bar(b.ts, b.open, b.high, b.low, b.close, b.volume, self.name, True, b.split_factor)
            for b in bars
        ]

    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]:
        return self.inner.fetch_corporate_actions(symbol)

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        return {}


def use(ctx: AppContext, *sources: Any) -> None:
    ctx.cache.sources = list(sources)


def test_ensure_fetches_once_then_serves_from_store(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    src = CountingSource(fake_source)
    use(ctx, src)
    rel = inst(ctx, "RELIANCE")
    r1 = ctx.cache.ensure(rel, Timeframe.D1, Y2016, Y2026)
    assert r1.ok and r1.fetched > 2400 and r1.missing_after == 0
    r2 = ctx.cache.ensure(rel, Timeframe.D1, Y2016, Y2026)
    assert r2.fetched == 0 and len(src.calls) == 1
    bars = ctx.cache.bars(rel, Timeframe.D1, Y2016, Y2026)
    assert bars == [b for b in fake_source._all("RELIANCE", Timeframe.D1)]
    with ctx.db.session() as s:
        log = s.scalars(select(DataFetchLog)).all()
    assert [(row.status, row.source) for row in log] == [("ok", "fake")]


def test_real_gap_is_asked_for_once_not_on_every_run(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    src = CountingSource(fake_source)
    use(ctx, src)
    tcs = inst(ctx, "TCS")
    r = ctx.cache.ensure(tcs, Timeframe.D1, Y2016, Y2026)
    assert r.missing_after == 3  # the three sessions missing from the fixture on purpose
    ctx.clock.advance(30 * 86_400_000)
    ctx.cache.ensure(tcs, Timeframe.D1, Y2016, Y2026)
    assert len(src.calls) == 1


def test_only_missing_sessions_are_requested(ctx: AppContext, fake_source: FakeSource) -> None:
    src = CountingSource(fake_source)
    use(ctx, src)
    infy = inst(ctx, "INFY")
    mid = 1_609_459_200_000  # 2021-01-01
    ctx.cache.ensure(infy, Timeframe.D1, Y2016, mid)
    ctx.cache.ensure(infy, Timeframe.D1, Y2016, Y2026)
    assert len(src.calls) == 2
    assert src.calls[1][2] >= mid  # second request starts where the store ended


def test_rate_limits_back_off_then_cool_down_and_fall_back(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    waits: list[float] = []
    ctx.cache._sleep = waits.append
    bad = CountingSource(fake_source, "yahoo", RateLimited("slow down"))
    backup = CountingSource(fake_source, "nse")
    use(ctx, bad, backup)
    rel = inst(ctx, "RELIANCE")
    r = ctx.cache.ensure(rel, Timeframe.D1, Y2016, Y2026)
    assert waits == [2.0, 4.0, 8.0, 16.0]
    assert r.ok and r.sources == {"nse"}
    with ctx.db.session() as s:
        status = s.get(SourceStatus, "yahoo")
        log = [
            (x.source, x.status) for x in s.scalars(select(DataFetchLog).order_by(DataFetchLog.id))
        ]
    assert status is not None and status.state == "cooling_down"
    assert log == [("yahoo", "rate_limited"), ("nse", "fallback")]
    # While cooling down, Yahoo is skipped entirely.
    infy = inst(ctx, "INFY")
    ctx.cache.ensure(infy, Timeframe.D1, Y2016, Y2026)
    assert len(bad.calls) == 5
    # After 15 minutes it is tried again.
    ctx.clock.advance(16 * 60_000)
    bad.fail_with = None
    ctx.cache.ensure(inst(ctx, "TCS"), Timeframe.D1, Y2016, Y2026)
    assert len(bad.calls) == 6


def test_all_sources_failing_reports_plain_problem(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    use(ctx, CountingSource(fake_source, "yahoo", SourceError("broken")))
    r = ctx.cache.ensure(inst(ctx, "ITC"), Timeframe.D1, Y2016, Y2026)
    assert not r.ok
    assert r.problems == ["Couldn't download 1d prices for ITC right now."]


def test_corporate_actions_set_split_factors(ctx: AppContext, fake_source: FakeSource) -> None:
    use(ctx, fake_source)
    rel = inst(ctx, "RELIANCE")
    # Store bars first with no split known: every factor is 1.0 …
    with ctx.db.session() as s:
        store.upsert_bars(
            s,
            rel.id,
            Timeframe.D1,
            [
                Bar(b.ts, b.open, b.high, b.low, b.close, b.volume, "fake")
                for b in fake_source._all("RELIANCE", Timeframe.D1)
            ],
            0,
        )
    ctx.cache._actions_checked.discard(rel.id)
    with ctx.db.session() as s:
        s.execute(CorporateActionRow.__table__.delete())
        store.reapply_split_factors(s, rel.id)
    assert {b.split_factor for b in ctx.cache.bars(rel, Timeframe.D1, Y2016, Y2026)} == {1.0}
    assert ctx.cache.refresh_actions(rel)
    bars = ctx.cache.bars(rel, Timeframe.D1, Y2016, Y2026)
    assert bars == list(fake_source._all("RELIANCE", Timeframe.D1))  # … now 0.5 before the split
    adj = ctx.cache.bars(rel, Timeframe.D1, Y2016, Y2026, adjusted_prices=True)
    split_ts = fake_source.manifest["corporate_actions"]["RELIANCE"][0]["ex_date"]
    before = next(b for b in reversed(adj) if b.ts < split_ts)
    after = next(b for b in adj if b.ts >= split_ts)
    assert abs(after.open / before.close - 1) < 0.1  # no artificial 50% drop


def test_two_downloads_of_one_stocks_actions_take_turns(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    """First start: the Welcome download and the autopilot both save the same stock's
    dividends at once. They used to collide on the unique (stock, date, kind) key."""
    import contextlib
    import threading

    class Slow(CountingSource):
        gate = threading.Barrier(2)

        def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]:
            with contextlib.suppress(threading.BrokenBarrierError):
                self.gate.wait(timeout=0.3)  # both threads here at once, if they are let in
            return [
                CorporateAction(ex_date=1_031_113_500_000 + i * DAY_MS, kind="dividend", amount=2.9)
                for i in range(300)
            ]

    use(ctx, Slow(fake_source))
    rel = inst(ctx, "RELIANCE")
    with ctx.db.session() as s:
        s.execute(CorporateActionRow.__table__.delete())
    errors: list[BaseException] = []

    def run() -> None:
        try:
            ctx.cache.refresh_actions(rel)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with ctx.db.session() as s:
        assert len(list(s.scalars(select(CorporateActionRow)))) == 300


def test_intraday_and_derived_fifteen_minute(ctx: AppContext, fake_source: FakeSource) -> None:
    use(ctx, fake_source)
    spy = inst(ctx, "SPY", Market.US)
    start = Y2026 - 100 * 86_400_000
    r5 = ctx.cache.ensure(spy, Timeframe.M5, start, Y2026)
    assert r5.ok and r5.fetched == 60 * 78 - 2 * 36  # 60 sessions, two 13:00 early closes
    r15 = ctx.cache.ensure(spy, Timeframe.M15, start, Y2026)
    assert r15.sources == {"derived"}
    b15 = ctx.cache.bars(spy, Timeframe.M15, start, Y2026)
    b5 = ctx.cache.bars(spy, Timeframe.M5, start, Y2026)
    first = [b for b in b5 if b15[0].ts <= b.ts < b15[0].ts + 15 * 60_000]
    assert b15[0].open == first[0].open and b15[0].close == first[-1].close
    assert b15[0].high == max(b.high for b in first) and b15[0].volume == sum(
        b.volume for b in first
    )
    sessions = sessions_between_ms(ctx.calendar, Market.US, b15[0].ts, Y2026)
    assert len(b15) == sum(-(-(x.close_ms - x.open_ms) // 900_000) for x in sessions)


def test_recent_daily_bar_is_rechecked_once(ctx: AppContext, fake_source: FakeSource) -> None:
    src = CountingSource(fake_source)
    use(ctx, src)
    spy = inst(ctx, "SPY", Market.US)
    # Pretend it's the evening of 2025-12-31 (fixture's last session closed at 21:00 UTC).
    ctx.clock._now = 1_767_218_400_000 + 3_600_000  # 22:00 UTC
    ctx.cache.ensure(spy, Timeframe.D1, Y2016, Y2026)
    ctx.clock.advance(2 * 3_600_000)  # still within the grace window → re-asked after an hour
    ctx.cache.ensure(spy, Timeframe.D1, Y2016, Y2026)
    assert len(src.calls) == 2
    ctx.clock.advance(12 * 3_600_000)  # fetched again after the grace window: settled
    ctx.cache.ensure(spy, Timeframe.D1, Y2016, Y2026)
    ctx.cache.ensure(spy, Timeframe.D1, Y2016, Y2026)
    assert len(src.calls) == 3


@pytest.mark.parametrize("symbol", ["RELIANCE", "NIFTY50"])
def test_probe(ctx: AppContext, symbol: str) -> None:
    found, _ = ctx.cache.probe(inst(ctx, symbol))
    assert found is True  # the fixtures end 2025-12-31, within 20 days of the clock


def test_one_odd_stock_doesnt_pause_the_source_for_everyone(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    """D-114: a generic failure pauses a source only after 3 different stocks fail in a row."""
    ctx.cache._sleep = lambda s: None
    bad = CountingSource(fake_source, "yahoo", SourceError("didn't answer properly"))
    use(ctx, bad)
    for n, sym in enumerate(("ITC", "TCS", "INFY"), start=1):
        ctx.cache.ensure(inst(ctx, sym), Timeframe.D1, Y2016, Y2026)
        with ctx.db.session() as s:
            st = s.get(SourceStatus, "yahoo")
        paused = st is not None and st.state == "cooling_down"
        assert paused is (n == 3), (sym, n)


def test_a_source_that_refuses_downloads_is_left_alone_for_a_day(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    from backend.data.errors import Blocked

    waits: list[float] = []
    ctx.cache._sleep = waits.append
    use(ctx, CountingSource(fake_source, "stooq", Blocked("browser check")))
    ctx.cache.ensure(inst(ctx, "ITC"), Timeframe.D1, Y2016, Y2026)
    with ctx.db.session() as s:
        st = s.get(SourceStatus, "stooq")
    assert waits == []  # no retries
    assert st is not None and st.until is not None
    assert st.until - ctx.clock.now_ms() >= 23 * 3_600_000


def test_yahoo_saying_no_data_for_the_dates_is_an_empty_answer() -> None:
    from backend.data.errors import EmptyResponse
    from backend.data.yahoo import _translate

    class YFPricesMissingError(Exception):
        pass

    err = _translate(
        YFPricesMissingError("$AAC: Data doesn't exist for startDate = 1, endDate = 2"), "AAC"
    )
    assert isinstance(err, EmptyResponse)


def test_pauses_grow_while_a_source_keeps_failing(ctx: AppContext, fake_source: FakeSource) -> None:
    ctx.cache._sleep = lambda s: None
    bad = CountingSource(fake_source, "stooq", RateLimited("timed out"))
    use(ctx, bad)
    lengths = []
    for sym in ("ITC", "TCS", "INFY"):
        ctx.cache.ensure(inst(ctx, sym), Timeframe.D1, Y2016, Y2026)
        with ctx.db.session() as s:
            st = s.get(SourceStatus, "stooq")
        assert st is not None and st.until is not None
        lengths.append(round((st.until - ctx.clock.now_ms()) / 60_000))
        ctx.clock.advance(st.until - ctx.clock.now_ms() + 1)
    assert lengths == [15, 30, 60]


def test_no_internet_waits_a_minute_and_never_grows_the_pause(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    """D-165: with the Wi-Fi off every request fails, and the doubling pauses left Yahoo
    "cooling down" for 8 hours after the connection came back."""
    ctx.cache._sleep = lambda s: None
    dns = SourceError(
        "Yahoo Finance didn't answer properly.",
        detail="DNSError: curl: (6) Could not resolve host: query2.finance.yahoo.com",
    )
    bad = CountingSource(fake_source, "yahoo", dns)
    use(ctx, bad)
    for sym in ("ITC", "TCS", "INFY", "SBIN"):
        ctx.cache.ensure(inst(ctx, sym), Timeframe.D1, Y2016, Y2026)
        with ctx.db.session() as s:
            st = s.get(SourceStatus, "yahoo")
        assert st is not None and st.until is not None
        assert st.until - ctx.clock.now_ms() == 60_000
        assert "No internet" in (st.last_error or "")
        ctx.clock.advance(60_001)
    assert ctx.cache._pauses.get("yahoo", 0) == 0


def test_a_paused_source_doesnt_count_as_up_to_date(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    """D-182: Yahoo paused for a day on 4 Nov, the only US backup refuses downloads, and the
    autopilot marked ~5,000 stocks "topped up today" without a single download. A download
    skipped because its source is paused now says so (``waited``)."""
    ctx.cache._sleep = lambda _s: None
    only = CountingSource(fake_source, "yahoo", RateLimited("slow down"))
    use(ctx, only)
    r = ctx.cache.ensure(inst(ctx, "RELIANCE"), Timeframe.D1, Y2016, Y2026)
    assert not r.ok  # the first one failed outright
    r2 = ctx.cache.ensure(inst(ctx, "INFY"), Timeframe.D1, Y2016, Y2026)
    assert r2.waited and r2.missing_after > 0  # skipped, not up to date
    only.fail_with = None
    ctx.clock.advance(16 * 60_000)
    r3 = ctx.cache.ensure(inst(ctx, "INFY"), Timeframe.D1, Y2016, Y2026)
    assert not r3.waited and r3.missing_after == 0


def test_a_candles_high_and_low_include_its_open_and_close(ctx: AppContext) -> None:
    """D-182: Yahoo's 5 Nov daily rows had the opening auction above the day's high."""
    rel = inst(ctx, "RELIANCE")
    bad = Bar(1_793_889_000_000, 216.615, 216.43, 203.021, 203.88, 2_933_587, "yahoo")
    with ctx.db.session() as s:
        store.upsert_bars(s, rel.id, Timeframe.D1, [bad], 0)
        got = store.load_bars(s, rel.id, Timeframe.D1, bad.ts, bad.ts + 1)
    assert got[0].high == 216.615 and got[0].low == 203.021
