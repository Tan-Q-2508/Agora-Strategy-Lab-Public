"""Paper-session behaviour on a controllable clock and source: resuming after Agora was
closed (no back-fill, gap shown), data outages, late prices, pausing, strategy errors."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.context import AppContext
from backend.core.types import Bar, Timeframe
from backend.data.errors import SourceError
from backend.db.models import PaperEquity, PaperEvent, PaperOrder, PaperSession, PaperTrade
from backend.fakes.clock import FakeClock
from backend.fakes.data_source import FakeSource
from backend.paper.feed import LiveFeed
from backend.paper.runner import PaperRunner
from backend.paper.service import SessionIn
from backend.strategy import service as strategies
from backend.strategy.definition import CodeDefinition
from backend.strategy.templates import template_definition

START = int(datetime(2025, 9, 1, tzinfo=UTC).timestamp() * 1000)
DAY = 86_400_000

ALWAYS_IN = """
def on_bar(ctx):
    if not ctx.position:
        ctx.buy(size=ctx.size.percent_equity(20))
    elif ctx.position.bars_held >= 2:
        ctx.sell_all("Held two candles")
"""

CRASHES = """
def on_bar(ctx):
    if ctx.close[-1] > 0:
        x = 1 / 0
"""


class FlakySource:
    """The fixture source, but it can be switched off like a failing Yahoo."""

    def __init__(self, inner: FakeSource) -> None:
        self.inner = inner
        self.name = inner.name
        self.down = False

    def __getattr__(self, item: str) -> Any:
        return getattr(self.inner, item)

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        if self.down:
            raise SourceError("Yahoo Finance didn't answer.", detail="test outage")
        return self.inner.latest_bars(symbols, timeframe)


def code_version(ctx: AppContext, code: str, symbols: list[str], timeframe: str = "1d") -> int:
    base = template_definition("ma_crossover", "IN", symbols).model_dump()
    common = {k: base[k] for k in ("schema_version", "market", "universe", "sizing", "limits")}
    d = CodeDefinition.model_validate(
        {
            **common,
            "kind": "code",
            "code": code,
            "timeframe": timeframe,
            "product": "delivery",
            "parameters": [],
        }
    )
    with ctx.db.session() as s:
        _, v = strategies.create(s, name="Code test", description="", definition=d, now=0)
        return v.id


def live_runner(
    ctx: AppContext, version_id: int, clock: FakeClock
) -> tuple[PaperRunner, FlakySource]:
    svc = ctx.paper
    svc.threaded = False
    sid = svc.start_session(SessionIn(strategy_version_id=version_id))
    source = FlakySource(FakeSource(clock))
    runner = PaperRunner(
        ctx,
        sid,
        clock=clock,
        feed=LiveFeed(ctx.db, clock, ctx.calendar, [source]),
        refresh_actions=False,
    )
    return runner, source


def step(runner: PaperRunner, n: int = 1) -> None:
    for _ in range(n):
        assert runner.replay_step()


def events(ctx: AppContext, sid: int) -> list[tuple[str, str]]:
    with ctx.db.session() as s:
        rows = s.scalars(
            select(PaperEvent).where(PaperEvent.session_id == sid).order_by(PaperEvent.id)
        )
        return [(e.kind, e.message_plain) for e in rows]


def test_resume_after_restart_keeps_positions_and_never_backfills(ctx: AppContext) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot()
    assert a.engine is not None
    for _ in range(40):
        step(a)
        if any(st.position for st in a.engine.symbols):
            break
    held = {
        st.inst.symbol: (st.position.qty, st.position.entry_ts)
        for st in a.engine.symbols
        if st.position
    }
    assert held, "the always-in strategy holds something"
    stopped_at = clock.now_ms()
    a.shutdown()

    # Agora is closed for ten days, then started again.
    clock.set(stopped_at + 10 * DAY)
    b = PaperRunner(
        ctx,
        a.id,
        clock=clock,
        feed=LiveFeed(ctx.db, clock, ctx.calendar, [FakeSource(clock)]),
        refresh_actions=False,
    )
    assert b._boot()
    assert b.engine is not None
    restored = {
        st.inst.symbol: (st.position.qty, st.position.entry_ts)
        for st in b.engine.symbols
        if st.position
    }
    # (their exit rule may act on a missed candle, and the last candle may open a new one, D-219)
    assert set(restored) == set(held)
    kinds = [k for k, _ in events(ctx, a.id)]
    assert "gap" in kinds and "resumed" in kinds
    gap_msg = next(m for k, m in events(ctx, a.id) if k == "gap")
    assert "were not simulated" in gap_msg
    # both dates, always (a six-day gap read "from Wed 28 Oct, 11:15 ET to 20:10 ET", D-219)
    assert gap_msg.count(",") >= 2 and "checked on the missed candles" in gap_msg
    step(b, 6)
    with ctx.db.session() as s:
        orders = s.scalars(select(PaperOrder).where(PaperOrder.session_id == a.id)).all()
        eq = s.scalars(select(PaperEquity.ts).where(PaperEquity.session_id == a.id)).all()
        notes = json.loads(s.get(PaperSession, a.id).notes)  # type: ignore[union-attr]
    in_gap = [o for o in orders if stopped_at < o.created_ts < stopped_at + 10 * DAY - DAY]
    opened = [o for o in in_gap if o.status == "filled" and o.side == "buy"]
    assert opened == [], "no new trade may open on the days Agora was closed"
    assert eq, "open trades were followed through the gap"
    assert notes["gaps"] and notes["gaps"][0]["to"] == stopped_at + 10 * DAY
    assert max(o.created_ts for o in orders) > stopped_at + 10 * DAY - DAY, "trading continued"


def test_a_stop_acts_on_the_candles_missed_while_closed(ctx: AppContext) -> None:
    # D-219: a real stop rests at the broker. A stock that falls through its stop while Agora is
    # closed sells at the first missed candle past the stop, not at the price on reopening.
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot()
    step(a, 4)
    assert a.engine is not None
    st = next(x for x in a.engine.symbols if x.position is not None)
    last = st.raw[-1]
    st.position.stop = last.close * 0.999999  # type: ignore[union-attr]
    a._save(clock.now_ms())
    entry_ts = st.position.entry_ts  # type: ignore[union-attr]
    stop = st.position.stop  # type: ignore[union-attr]
    a.shutdown()
    clock.set(clock.now_ms() + 12 * DAY)
    b = PaperRunner(
        ctx,
        a.id,
        clock=clock,
        feed=LiveFeed(ctx.db, clock, ctx.calendar, [FakeSource(clock)]),
        refresh_actions=False,
    )
    assert b._boot()
    with ctx.db.session() as s:
        trades = s.scalars(
            select(PaperTrade).where(PaperTrade.session_id == a.id, PaperTrade.entry_ts == entry_ts)
        ).all()
        bars = ctx.cache.bars(st.inst, Timeframe.D1, last.ts + 1, clock.now_ms())
    assert trades, "the stop should have acted on a missed candle"
    t = trades[0]
    crossed = next((x for x in bars if x.low <= stop), None)
    assert crossed is not None and t.exit_ts == crossed.ts


def test_outage_pauses_entries_then_late_candles_dont_open_trades(ctx: AppContext) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    clock = FakeClock(START)
    r, src = live_runner(ctx, vid, clock)
    assert r._boot()
    step(r, 3)
    src.down = True
    step(r, 2)
    assert r.state == "paused_data"
    assert r.freshness().level == "red"
    assert "outage" in [k for k, _ in events(ctx, r.id)]
    # The source stays down for a week.
    clock.set(clock.now_ms() + 7 * DAY)
    step(r)
    src.down = False
    step(r)
    assert r.state == "running"
    kinds = [k for k, _ in events(ctx, r.id)]
    assert "recovered" in kinds
    with ctx.db.session() as s:
        reasons = [
            o.reason
            for o in s.scalars(
                select(PaperOrder).where(
                    PaperOrder.session_id == r.id, PaperOrder.status == "rejected"
                )
            )
        ]
    assert any("arrived late" in x for x in reasons)


def test_a_desk_moves_to_a_new_list_with_its_trades_and_money(ctx: AppContext) -> None:
    # D-217: no pause, no waiting to be flat. The open trade stays on the list even though the
    # new list drops its stock, and cash and quantity come through unchanged.
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    clock = FakeClock(START)
    r, _ = live_runner(ctx, vid, clock)
    assert r._boot()
    step(r, 4)
    assert r.engine is not None
    st = next(x for x in r.engine.symbols if x.position is not None)
    qty, cash = st.position.qty, r.engine.cash  # type: ignore[union-attr]
    assert r.relist(["TCS"], "The desk now follows 1 stocks (it followed 1).")
    assert r._stop.is_set()
    r2 = PaperRunner(ctx, r.id, clock=clock, feed=r.feed)
    assert r2._boot()
    assert r2.state == "running" and r2.engine is not None
    assert {x.inst.symbol for x in r2.engine.symbols} == {"RELIANCE", "TCS"}
    same = next(x for x in r2.engine.symbols if x.inst.symbol == "RELIANCE")
    assert same.position is not None and same.position.qty == qty
    assert r2.engine.cash == cash
    assert "list_moved" in [k for k, _ in events(ctx, r.id)]
    assert ctx.paper._summary is not None
    with ctx.db.session() as s:
        row = s.get(PaperSession, r.id)
        assert row is not None
        assert ctx.paper._summary(s, row)["symbols"] == ["TCS", "RELIANCE"]


def test_a_busy_database_at_the_start_waits_and_never_stops_a_session(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-225: a 50-second lock during a list update stopped seven sessions for good
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    r, _ = live_runner(ctx, vid, FakeClock(START))
    monkeypatch.setattr("backend.paper.runner.BOOT_WAIT_S", 0.0)
    real = r.load
    calls = {"n": 0}

    def busy_then_fine() -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OperationalError("DELETE", {}, Exception("database is locked"))
        real()

    r.load = busy_then_fine  # type: ignore[method-assign]
    assert r._boot() and r.state == "running" and calls["n"] == 3


def test_a_database_that_stays_busy_leaves_the_session_saved_as_it_was(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    r, _ = live_runner(ctx, vid, FakeClock(START))
    monkeypatch.setattr("backend.paper.runner.BOOT_WAIT_S", 0.0)

    def busy() -> None:
        raise OperationalError("DELETE", {}, Exception("database is locked"))

    r.load = busy  # type: ignore[method-assign]
    assert r._boot() is False
    with ctx.db.session() as s:
        row = s.get(PaperSession, r.id)
        assert row is not None and row.state == "running" and row.stopped_at is None


def test_a_session_still_loading_is_not_moved(ctx: AppContext) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    r, _ = live_runner(ctx, vid, FakeClock(START))
    assert r.relist(["TCS"], "x") is False


def test_pause_blocks_new_trades_but_keeps_exits(ctx: AppContext) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"])
    clock = FakeClock(START)
    r, _ = live_runner(ctx, vid, clock)
    assert r._boot()
    step(r, 4)
    r.pause()
    assert r.state == "paused_user"
    step(r, 12)
    with ctx.db.session() as s:
        rejected = s.scalars(
            select(PaperOrder.reason).where(
                PaperOrder.session_id == r.id, PaperOrder.status == "rejected"
            )
        ).all()
        trades = s.scalars(select(PaperTrade).where(PaperTrade.session_id == r.id)).all()
    assert "Paused by you: no new trades." in rejected
    assert r.engine is not None and not any(st.position for st in r.engine.symbols)
    assert trades, "the open trade was still closed by its exit rule while paused"
    r.resume()
    assert r.state == "running"
    step(r, 4)
    assert any(st.position for st in r.engine.symbols) or any(st.pending for st in r.engine.symbols)


def test_strategy_error_stops_the_session_plainly(ctx: AppContext) -> None:
    vid = code_version(ctx, CRASHES, ["RELIANCE"])
    clock = FakeClock(START)
    r, _ = live_runner(ctx, vid, clock)
    assert r._boot()
    while r.replay_step():
        pass
    assert r.state == "stopped"
    msgs = dict(events(ctx, r.id))
    assert "strategy_error" in msgs
    assert msgs["strategy_error"].startswith("Your strategy code stopped")


def test_status_freshness_and_market_closed(ctx: AppContext) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"], timeframe="5m")
    clock = FakeClock(int(datetime(2025, 11, 3, 4, 0, tzinfo=UTC).timestamp() * 1000))  # 09:30 IST
    r, _ = live_runner(ctx, vid, clock)
    assert r._boot()
    step(r, 3)
    f = r.freshness()
    assert f.level == "green" and f.text.startswith("Up to date")
    clock.set(int(datetime(2025, 11, 3, 14, 0, tzinfo=UTC).timestamp() * 1000))  # 19:30 IST
    r.tick()
    while r.behind_close is not None and r.replay_step():
        pass
    f = r.freshness()
    assert f.level == "closed" and f.text.startswith("Market closed. Next open:")
    payload = r.tick_payload()
    assert payload["session_id"] == r.id and "positions" in payload


def test_live_loop_polls_every_candle_of_the_day(ctx: AppContext) -> None:
    """The live loop sleeps until ``next_due`` and checks again before polling. Counting the
    next candle from "now" moved the due moment on as soon as it arrived, so a desk polled
    once at start and never again (2026-10-26). Walk a whole day the way the loop does."""
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE"], timeframe="5m")
    clock = FakeClock(int(datetime(2025, 11, 3, 3, 0, tzinfo=UTC).timestamp() * 1000))  # 08:30 IST
    r, _ = live_runner(ctx, vid, clock)
    assert r._boot()
    end = int(datetime(2025, 11, 3, 11, 0, tzinfo=UTC).timestamp() * 1000)  # 16:30 IST
    polls = 0
    while clock.now_ms() < end:
        due = r.next_due()
        assert due is not None
        if due > clock.now_ms():
            clock.set(min(due, end))  # the loop wakes at the due moment...
            continue
        r.tick()  # ...finds the poll due, and polls
        polls += 1
    last = max(t for t in r.last_ts.values() if t is not None)
    assert polls >= 75  # 09:15–15:30 IST in 5-minute candles
    assert last >= int(datetime(2025, 11, 3, 9, 55, tzinfo=UTC).timestamp() * 1000)  # 15:25 IST
    with ctx.db.session() as s:
        row = s.get(PaperSession, r.id)
        assert row is not None and row.last_bar_ts == last


def _until_waiting(runner: PaperRunner) -> None:
    """Step until a buy is waiting for the next candle and nothing is held yet."""
    assert runner.engine is not None
    for _ in range(40):
        step(runner)
        sts = runner.engine.symbols
        if any(st.pending for st in sts) and not any(st.position for st in sts):
            return
    raise AssertionError("no order ever waited for the next candle")


def _restart(ctx: AppContext, sid: int, clock: FakeClock) -> PaperRunner:
    b = PaperRunner(
        ctx,
        sid,
        clock=clock,
        feed=LiveFeed(ctx.db, clock, ctx.calendar, [FakeSource(clock)]),
        refresh_actions=False,
    )
    assert b._boot() and b.engine is not None
    return b


def test_an_order_waiting_overnight_survives_a_restart(ctx: AppContext) -> None:
    """D-152: a daily desk decides at the close and buys at the next open. Closing Agora in
    between (no candle closed meanwhile) must not throw the order away; it fills at the open
    it was waiting for, as if Agora had stayed open."""
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot() and a.engine is not None
    _until_waiting(a)
    waiting = {
        st.inst.symbol: [(o.kind, o.qty, o.created_ts) for o in st.pending]
        for st in a.engine.symbols
        if st.pending
    }
    a.shutdown()
    clock.set(clock.now_ms() + 60_000)  # a minute later: the next candle hasn't closed
    b = _restart(ctx, a.id, clock)
    assert b.engine is not None
    again = {
        st.inst.symbol: [(o.kind, o.qty, o.created_ts) for o in st.pending]
        for st in b.engine.symbols
        if st.pending
    }
    assert again == waiting
    msgs = [m for k, m in events(ctx, a.id) if k == "resume"]
    assert any("kept: no candle closed" in m for m in msgs)
    assert not any("cancelled" in m for m in msgs)
    for _ in range(5):
        step(b)
        if any(st.position for st in b.engine.symbols):
            break
    held = [st for st in b.engine.symbols if st.position]
    assert held, "the kept order filled at the next open"
    for st in held:
        assert st.position is not None
        created = waiting[st.inst.symbol][0][2]
        assert st.position.entry_ts > created  # the open after the signal candle


def test_an_order_whose_candle_passed_while_closed_is_cancelled(ctx: AppContext) -> None:
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot() and a.engine is not None
    _until_waiting(a)
    a.shutdown()
    clock.set(clock.now_ms() + 10 * DAY)
    b = _restart(ctx, a.id, clock)
    assert b.engine is not None
    assert not any(st.pending for st in b.engine.symbols)
    msgs = [m for k, m in events(ctx, a.id) if k == "resume"]
    assert any("cancelled because a candle closed" in m for m in msgs)


def test_a_session_stopped_while_it_starts_stays_stopped(ctx: AppContext) -> None:
    """D-170: the autopilot stopped a desk while it was still loading its prices; the start
    then set it running again, and two desks ran for one slot."""
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    a.stop()  # before it has loaded anything
    assert a._boot()
    assert a.state == "stopped"
    with ctx.db.session() as s:
        row = s.get(PaperSession, a.id)
        assert row is not None and row.state == "stopped"
    assert not any(k == "resumed" for k, _ in events(ctx, a.id))


def test_a_candle_that_closed_while_agora_was_closed_is_traded(ctx: AppContext) -> None:
    """D-181: a daily desk decides at the close. India closes at 2 am on the user's laptop, so
    a desk that only decided while Agora was running at the close rarely decided at all. A
    candle that closed while Agora was closed, recently enough (within two candles), is now
    traded on the next start as if Agora had been open: the waiting order fills at its open
    and the session records it."""
    from backend.core.types import Market
    from backend.paper.timing import next_bar_close

    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot() and a.engine is not None
    _until_waiting(a)
    waiting = {st.inst.symbol for st in a.engine.symbols if st.pending}
    a.shutdown()
    close = next_bar_close(ctx.calendar, Market.IN, Timeframe.D1, clock.now_ms())
    assert close is not None
    clock.set(close + 3 * 3_600_000)  # Agora opened three hours after the next close
    b = _restart(ctx, a.id, clock)
    assert b.engine is not None
    kinds = [k for k, _ in events(ctx, a.id)]
    assert "caught_up" in kinds and "gap" not in kinds
    msgs = [m for k, m in events(ctx, a.id) if k == "resume"]
    assert not any("cancelled" in m for m in msgs)
    held = {st.inst.symbol for st in b.engine.symbols if st.position}
    assert held and held <= waiting, "the waiting order filled at the open it waited for"
    with ctx.db.session() as s:
        eq = s.scalars(select(PaperEquity.ts).where(PaperEquity.session_id == a.id)).all()
    assert any(t >= close - DAY for t in eq), "the caught-up candle is on the equity curve"


def test_waiting_buys_are_cancelled_when_news_turns_severe(
    ctx: AppContext, monkeypatch: Any
) -> None:
    """D-190: buys queued at the close on calm news don't fill at the next open once severe
    news has reached this market (down 1%+ today, D-211); exits would still go ahead."""
    from types import SimpleNamespace

    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot() and a.engine is not None
    _until_waiting(a)
    waiting = sum(len(st.pending) for st in a.engine.symbols)
    assert waiting
    # no news guard (not a Kairos desk): nothing happens
    assert a._news_hold() == 0
    monkeypatch.setattr(
        a.engine,
        "program",
        SimpleNamespace(brain=SimpleNamespace(news=SimpleNamespace(mode=lambda: "protective"))),
    )
    monkeypatch.setattr(ctx.news, "risk", lambda _m: {"level": 60.0})
    monkeypatch.setattr(a, "_day_move", lambda: -2.0)
    assert a._news_hold() == 0  # elevated: the buys stand
    # severe news while this market holds up: the buys stand (D-198, D-211)
    monkeypatch.setattr(ctx.news, "risk", lambda _m: {"level": 84.0})
    monkeypatch.setattr(a, "_day_move", lambda: -0.4)
    assert a._news_hold() == 0
    monkeypatch.setattr(a, "_day_move", lambda: -1.5)
    assert a._news_hold() == waiting
    assert not any(st.pending for st in a.engine.symbols)
    a._save(clock.now_ms())  # events are written with the session
    assert any(k == "news_cancel" for k, _ in events(ctx, a.id))


def test_a_desk_that_has_the_latest_candle_waits_for_the_next_close(ctx: AppContext) -> None:
    """D-197: after a restart every desk polled at once, even with its market closed and its
    latest candle already in hand."""
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot() and a.engine is not None
    step(a, 3)
    a.shutdown()
    b = _restart(ctx, a.id, clock)
    due = b.next_due()
    assert due is not None and due > clock.now_ms()  # nothing new: wait for the next close


def test_clearing_stopped_sessions_hides_them_but_keeps_their_trades(
    ctx: AppContext, client: Any
) -> None:
    """D-206: the user found 49 stopped runs on the Paper page confusing. Clearing takes stopped
    sessions off the page; running ones stay, and nothing is deleted."""
    vid = code_version(ctx, ALWAYS_IN, ["RELIANCE", "TCS"])
    clock = FakeClock(START)
    a, _ = live_runner(ctx, vid, clock)
    assert a._boot()
    b, _ = live_runner(ctx, vid, clock)
    assert b._boot()
    ctx.paper.stop(a.id)
    r = client.post("/api/paper/sessions/clear-stopped")
    assert r.status_code == 200 and r.json()["hidden"] == 1
    listed = {s["id"] for s in client.get("/api/paper/sessions").json()["sessions"]}
    assert a.id not in listed and b.id in listed
    assert any(s["id"] == a.id for s in ctx.paper.sessions(include_hidden=True))
    assert client.get(f"/api/paper/sessions/{a.id}").status_code == 200  # still opens
    assert client.post("/api/paper/sessions/clear-stopped").json()["hidden"] == 0
