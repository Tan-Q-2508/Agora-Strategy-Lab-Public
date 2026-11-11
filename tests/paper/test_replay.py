"""Replay mode (task 6.5): a paper session runs on a fast fake clock through fixture
prices, and must trade exactly like a backtest of the same days (D-04)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

from backend.backtest.run import RunSpec, run
from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.db.models import (
    PaperEquity,
    PaperEvent,
    PaperOrder,
    PaperSession,
    PaperTrade,
)
from backend.paper.runner import PaperRunner
from backend.paper.service import SessionIn
from backend.paper.timing import bar_end_ms
from backend.strategy import service as strategies
from backend.strategy.templates import template_definition


def make_version(ctx: AppContext, key: str, market: str, symbols: list[str], **changes: Any) -> int:
    d = template_definition(key, market, symbols)
    if changes:
        d = d.model_copy(update=changes)
    with ctx.db.session() as s:
        _, v = strategies.create(
            s, name=f"Test {key}", description="", definition=d, now=ctx.clock.now_ms()
        )
        return v.id


def start(ctx: AppContext, version_id: int, **kw: Any) -> PaperRunner:
    svc = ctx.paper
    svc.threaded = False
    sid = svc.start_session(SessionIn(strategy_version_id=version_id, **kw))
    runner = svc.runner(sid)
    assert runner is not None
    assert runner._boot()
    return runner


def replay_all(runner: PaperRunner, limit: int = 100_000) -> int:
    n = 0
    while runner.replay_step():
        n += 1
        assert n < limit, "replay did not finish"
    return n


def test_daily_replay_matches_a_backtest_exactly(ctx: AppContext) -> None:
    vid = make_version(ctx, "bollinger_reversion", "IN", ["RELIANCE", "TCS", "INFY", "SBIN"])
    runner = start(ctx, vid)
    replay_all(runner)
    assert runner.state == "stopped"
    with ctx.db.session() as s:
        row = s.get(PaperSession, runner.id)
        assert row is not None and row.state == "stopped"
        notes = json.loads(row.notes)
        live = s.scalars(select(PaperTrade).where(PaperTrade.session_id == runner.id)).all()
        live_trades = sorted(
            (t.instrument_id, t.entry_ts, t.exit_ts, round(t.net_pnl, 6)) for t in live
        )
        equity = s.scalars(
            select(PaperEquity).where(PaperEquity.session_id == runner.id).order_by(PaperEquity.ts)
        ).all()
        events = [
            e.kind for e in s.scalars(select(PaperEvent).where(PaperEvent.session_id == runner.id))
        ]
    assert "started" in events and "stopped" in events
    assert len(live_trades) >= 2, "the fixture period should produce some trades"
    assert len(equity) > 100

    # The same strategy, account and days as a backtest.
    first_live = equity[0].ts
    last = equity[-1].ts
    with ctx.db.session() as s:
        v = strategies.get_version(s, vid)
        assert v is not None
        insts, _, _ = ctx.backtests._instruments(s, v.definition, None, Market.IN)
    acct = runner_account(ctx, runner)
    spec = RunSpec(
        definition=v.definition,
        instruments=insts,
        timeframe=Timeframe.D1,
        start_ms=first_live,
        end_ms=last + 1,
        capital=acct["starting_capital"],
        brokerage_rules=acct["rules"],
        slippage_bps=acct["slippage_bps"],
        history_from_ms=notes["history_from"],
    )
    out = run(ctx.cache, spec)
    bt = sorted(
        (t.instrument_id, t.entry_ts, t.exit_ts, round(t.net_pnl, 6))
        for t in out.trades
        if t.closed
    )
    assert bt == live_trades
    assert out.equity[-1].equity == pytest.approx(equity[-1].equity, abs=1e-6)


def runner_account(ctx: AppContext, runner: PaperRunner) -> dict[str, Any]:
    from backend.db.models import BrokerageProfile, PaperAccount

    with ctx.db.session() as s:
        row = s.get(PaperSession, runner.id)
        assert row is not None
        a = s.get(PaperAccount, row.account_id)
        assert a is not None
        p = s.get(BrokerageProfile, a.brokerage_profile_id)
        assert p is not None
        return {
            "starting_capital": a.starting_capital,
            "slippage_bps": a.slippage_bps,
            "rules": json.loads(p.rules),
        }


def test_intraday_replay_trades_and_squares_off(ctx: AppContext) -> None:
    vid = make_version(ctx, "opening_range_breakout", "IN", ["RELIANCE", "INFY"])
    runner = start(ctx, vid)
    for _ in range(800):  # about ten days of 5-minute candles
        assert runner.replay_step()
    runner.stop()
    with ctx.db.session() as s:
        orders = s.scalars(select(PaperOrder).where(PaperOrder.session_id == runner.id)).all()
        trades = s.scalars(select(PaperTrade).where(PaperTrade.session_id == runner.id)).all()
    assert orders, "the breakout should fire at least once in ten days"
    assert all(t.exit_reason is not None for t in trades)
    # India intraday: nothing is held overnight
    for t in trades:
        assert t.exit_ts is not None
        assert (
            bar_end_ms(ctx.calendar, Market.IN, Timeframe.M5, t.exit_ts) - t.entry_ts < 86_400_000
        )


def test_a_ranking_paper_trades_like_its_backtest(ctx: AppContext) -> None:
    """A ranking (D-91) compares stocks inside the engine; paper trading must still match the
    backtest of the same days trade for trade (D-04)."""
    from backend.strategy.ranking import ranking_definition

    d = ranking_definition("momentum_fast", "IN", ["RELIANCE", "TCS", "INFY", "SBIN", "ITC", "LT"])
    d = d.model_copy(update={"ranking": d.ranking.model_copy(update={"hold": 2})})
    d = type(d).model_validate(d.model_dump())  # re-derive sizing and limits from hold
    with ctx.db.session() as s:
        _, v = strategies.create(
            s, name="Rank", description="", definition=d, now=ctx.clock.now_ms()
        )
        vid = v.id
    runner = start(ctx, vid)
    replay_all(runner)
    with ctx.db.session() as s:
        row = s.get(PaperSession, runner.id)
        assert row is not None
        notes = json.loads(row.notes)
        live = s.scalars(select(PaperTrade).where(PaperTrade.session_id == runner.id)).all()
        live_trades = sorted(
            (t.instrument_id, t.entry_ts, t.exit_ts, round(t.net_pnl, 6)) for t in live
        )
        equity = s.scalars(
            select(PaperEquity).where(PaperEquity.session_id == runner.id).order_by(PaperEquity.ts)
        ).all()
        insts, _, _ = ctx.backtests._instruments(s, d, None, Market.IN)
    assert len(live_trades) >= 2
    acct = runner_account(ctx, runner)
    spec = RunSpec(
        definition=d,
        instruments=insts,
        timeframe=Timeframe.D1,
        start_ms=equity[0].ts,
        end_ms=equity[-1].ts + 1,
        capital=acct["starting_capital"],
        brokerage_rules=acct["rules"],
        slippage_bps=acct["slippage_bps"],
        history_from_ms=notes["history_from"],
    )
    out = run(ctx.cache, spec)
    bt = sorted(
        (t.instrument_id, t.entry_ts, t.exit_ts, round(t.net_pnl, 6))
        for t in out.trades
        if t.closed
    )
    assert bt == live_trades
