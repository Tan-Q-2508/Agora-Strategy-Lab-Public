"""The Kairos desk: paper trading on its own, its diary, and learning from it (KAIROS §9)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.backtest.run import RunSpec, run
from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.db.models import (
    KairosJournal,
    KairosMemory,
    KairosSignalStat,
    PaperSession,
    PaperTrade,
)
from backend.kairos import memory
from backend.paper.runner import PaperRunner
from backend.strategy import service as strategies
from tests.kairos.test_brain import load
from tests.paper.test_replay import replay_all, runner_account

STOCKS = ["RELIANCE", "TCS", "INFY", "SBIN", "HDFCBANK", "ICICIBANK"]


def insts(ctx: AppContext, symbols: list[str]) -> list[Any]:
    from backend.kairos import resolve

    return [resolve.stock(ctx, s, Market.IN) for s in symbols]


def start_desk(ctx: AppContext, symbols: list[str] = STOCKS) -> PaperRunner:
    load(ctx, Market.IN, symbols)
    ctx.paper.threaded = False
    desk = ctx.desk.launch(insts(ctx, symbols), Timeframe.D1)
    runner = ctx.paper.runner(desk["id"])
    assert runner is not None and runner._boot()
    return runner


def test_desk_trades_keeps_a_diary_and_learns(ctx: AppContext) -> None:
    runner = start_desk(ctx)
    assert ctx.learning.trained(Market.IN, Timeframe.D1) is not None  # studied first
    replay_all(runner)
    sid = runner.id
    with ctx.db.session() as s:
        trades = s.scalars(select(PaperTrade).where(PaperTrade.session_id == sid)).all()
        journal = s.scalars(select(KairosJournal).where(KairosJournal.session_id == sid)).all()
        paper_stats = s.scalars(
            select(KairosSignalStat).where(KairosSignalStat.source == "paper")
        ).all()
    assert trades, "the desk should trade during the practice replay"
    theses = [j for j in journal if j.kind == "thesis"]
    reviews = [j for j in journal if j.kind == "review"]
    assert len(theses) >= len(trades) and len(reviews) == len(trades)
    for j in theses:
        assert j.text.startswith(("Bought", "Short-sold")) and "Plan:" in j.text
        assert "Stop" in j.text and j.score is not None and abs(j.score) >= 20
        # told as opened, even when a partial sale moved the stop to the entry before the save
        assert "risking 0.0%" not in j.text
        data = json.loads(j.signals)
        assert data["keys"] and data["market"] == "IN"
    for j in reviews:
        assert j.text.startswith("Closed ") and "Net result" in j.text
        assert j.trade_id in {t.id for t in trades}
    # every closed trade taught the signals that were in play at entry
    assert paper_stats and sum(r.n for r in paper_stats) >= len(trades)
    # and every exit plan (D-140): how each would have done on the same trades
    exit_rows = [r for r in paper_stats if r.signal.startswith("exit:paper:")]
    assert exit_rows and max(r.n for r in exit_rows) <= len(trades)
    d = ctx.desk.desk(sid)
    assert d["kind"] == "kairos" and d["journal"] and d["learned"]["trained"]
    assert ctx.desk.desks()[0]["id"] == sid


def test_desk_replay_matches_a_backtest_of_the_brain(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One engine (D-04): with the weights and exits held still, the desk trades exactly like
    a backtest of the same strategy version over the same days."""
    load(ctx, Market.IN, STOCKS[:4])
    ctx.learning.train(Market.IN, Timeframe.D1)
    frozen = ctx.learning.weights(Market.IN, Timeframe.D1)
    monkeypatch.setattr(ctx.learning, "weights", lambda m, tf: frozen)
    monkeypatch.setattr(ctx.learning, "record_trade", lambda *a, **k: None)
    # and the exits held still too: the definition's own (D-140)
    monkeypatch.setattr(ctx.learning, "exit_plan", lambda m, tf: None)
    monkeypatch.setattr(ctx.learning, "record_exits", lambda *a, **k: None)
    runner = start_desk(ctx, STOCKS[:4])
    replay_all(runner)
    with ctx.db.session() as s:
        row = s.get(PaperSession, runner.id)
        assert row is not None
        notes = json.loads(row.notes)
        v = strategies.get_version(s, row.strategy_version_id)
        assert v is not None and v.definition.kind == "kairos"
        live = sorted(
            (t.instrument_id, t.entry_ts, t.exit_ts, round(t.net_pnl, 6))
            for t in s.scalars(select(PaperTrade).where(PaperTrade.session_id == runner.id))
        )
        insts_, _, _ = ctx.backtests._instruments(s, v.definition, None, Market.IN)
    acct = runner_account(ctx, runner)
    first = notes["replay"]["start"]
    out = run(
        ctx.cache,
        RunSpec(
            definition=v.definition,
            instruments=insts_,
            timeframe=Timeframe.D1,
            start_ms=first,
            end_ms=notes["now"] + 1,
            capital=acct["starting_capital"],
            brokerage_rules=acct["rules"],
            slippage_bps=acct["slippage_bps"],
            history_from_ms=notes["history_from"],
        ),
    )
    bt = sorted(
        (t.instrument_id, t.entry_ts, t.exit_ts, round(t.net_pnl, 6))
        for t in out.trades
        if t.closed
    )
    assert live and bt == live


def test_lessons_come_from_a_clear_record(ctx: AppContext) -> None:
    def review(won: bool) -> None:
        data = {
            "market": "IN",
            "side": 1,
            "won": won,
            "keys": [["pattern:bull_flag:up", 1], ["candle:hammer", 1]],
        }
        with ctx.db.session() as s:
            s.add(KairosJournal(kind="review", signals=json.dumps(data), text="x", created_at=0))

    for won in (False, False, False, True):
        review(won)
    written = memory.update_lessons(ctx, Market.IN)
    assert (
        "Bull flag breakout failed 3 of 4 times in my recent paper trades on Indian stocks."
        in written
    )
    review(False)  # the record changes: the same lesson is rewritten, not duplicated
    memory.update_lessons(ctx, Market.IN)
    with ctx.db.session() as s:
        rows = s.scalars(
            select(KairosMemory).where(KairosMemory.tags.like("sig:pattern:bull_flag:up %"))
        ).all()
    assert len(rows) == 1 and "4 of 5" in rows[0].text
    prompt = memory.for_prompt(ctx, "should I trust this bull flag?")
    assert prompt.startswith("- Bull flag breakout failed")


def test_desk_api(client: TestClient, ctx: AppContext) -> None:
    from tests.data.helpers import wait_job

    load(ctx, Market.IN, ["RELIANCE", "TCS"])
    ctx.paper.threaded = False
    r = client.post("/api/kairos/desk", json={"market": "IN", "symbols": ["reliance", "TCS"]})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job
    sid = job["result"]["session_id"]
    desks = client.get("/api/kairos/desk").json()["desks"]
    assert [d["id"] for d in desks] == [sid]
    d = client.get(f"/api/kairos/desk/{sid}").json()
    assert d["symbols"] == ["RELIANCE", "TCS"] and "journal" in d and "learned" in d
    stats = client.get("/api/kairos/stats", params={"market": "IN"}).json()
    assert stats["trained"]["candles"] > 0
    assert client.get("/api/kairos/lessons").json() == {"lessons": []}
    assert client.post(f"/api/kairos/desk/{sid}/stop").json() == {"stopped": sid}
    # a normal strategy's session isn't a desk
    assert client.get("/api/kairos/desk/999").status_code == 404
    jid = client.post("/api/kairos/train", json={"market": "IN"}).json()["job_id"]
    assert wait_job(client, jid)["status"] == "done"


def test_a_restarted_desk_counts_its_return_from_its_first_run(ctx: AppContext) -> None:
    """The user, 2026-11-03: the total return was wrong. A desk the autopilot restarts carries
    on with the money its last run ended with; its return counts from the first run's (D-146)."""
    load(ctx, Market.IN, STOCKS)
    ctx.paper.threaded = False
    d = ctx.desk.launch(insts(ctx, STOCKS), Timeframe.D1, 900_000.0, 1_000_000.0)
    assert d["first_capital"] == 1_000_000.0
    assert d["total_return"] == pytest.approx(-10.0)


def test_upgrade_links_desk_runs_restarted_before_the_fix(ctx: AppContext) -> None:
    """Migration 0014 finds each run's earlier run (same market and timeframe, ending with its
    starting money) and writes the first run's money into its notes."""
    import importlib.util
    from pathlib import Path

    from backend.db.models import PaperEquity

    path = Path("backend/migrations/versions/0014_desk_first_capital.py")
    spec = importlib.util.spec_from_file_location("m0014", path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    load(ctx, Market.IN, STOCKS)
    ctx.paper.threaded = False
    a = ctx.desk.launch(insts(ctx, STOCKS), Timeframe.D1)
    ctx.desk.stop(a["id"])
    with ctx.db.session() as s:
        s.add(PaperEquity(session_id=a["id"], ts=1, equity=1_050_000.0, cash=0, unrealized_pnl=0))
    b = ctx.desk.launch(insts(ctx, STOCKS), Timeframe.D1, 1_050_000.0)
    assert b["total_return"] == pytest.approx(0.0)
    with ctx.db.engine.begin() as conn:
        assert m.link_runs(conn) == 1
        assert m.link_runs(conn) == 0  # already linked
    with ctx.db.session() as s:
        notes = json.loads(s.get(PaperSession, b["id"]).notes or "{}")  # type: ignore[union-attr]
    assert notes["first_capital"] == pytest.approx(1_000_000.0)


def test_a_restarted_desk_shows_its_earlier_runs_money(ctx: AppContext) -> None:
    """D-207: the user saw a desk restarted that morning with only today's flat line under
    'Money over time'. A desk's chart joins the runs it carried its money on from."""
    from backend.db.models import PaperEquity

    load(ctx, Market.IN, STOCKS)
    ctx.paper.threaded = False
    other = ctx.desk.launch(insts(ctx, STOCKS), Timeframe.D1, 500_000.0)
    ctx.desk.stop(other["id"])
    a = ctx.desk.launch(insts(ctx, STOCKS), Timeframe.D1)
    ctx.desk.stop(a["id"])
    with ctx.db.session() as s:
        s.add(PaperEquity(session_id=other["id"], ts=2, equity=480_000.0, cash=0, unrealized_pnl=0))
        s.add(PaperEquity(session_id=a["id"], ts=5, equity=1_000_000.0, cash=0, unrealized_pnl=0))
        s.add(PaperEquity(session_id=a["id"], ts=6, equity=1_050_000.0, cash=0, unrealized_pnl=0))
    b = ctx.desk.launch(insts(ctx, STOCKS), Timeframe.D1, 1_050_000.0, 1_000_000.0)
    curve = ctx.paper.detail(b["id"])["equity_curve"]
    assert [p["ts"] for p in curve][:2] == [5, 6]  # run a, not the unrelated run
    assert all(p["equity"] != 480_000.0 for p in curve)
    assert [p["ts"] for p in ctx.paper.detail(a["id"])["equity_curve"]] == [5, 6]
    # D-209: and its completed trades and their numbers
    from backend.db.models import Instrument, PaperTrade

    with ctx.db.session() as s:
        inst = s.scalars(select(Instrument).where(Instrument.symbol == STOCKS[0])).first()
        assert inst is not None
        for k, pnl in enumerate([500.0, -200.0]):
            s.add(
                PaperTrade(
                    session_id=a["id"],
                    instrument_id=inst.id,
                    side="long",
                    qty=1,
                    entry_ts=k,
                    entry_price=100.0,
                    exit_ts=k + 1,
                    exit_price=101.0,
                    gross_pnl=pnl,
                    charges=5.0,
                    net_pnl=pnl,
                    return_pct=pnl / 100,
                    bars_held=1,
                    entry_reason="",
                    exit_reason="target" if pnl > 0 else "stop",
                )
            )
    d = ctx.paper.detail(b["id"])
    assert d["runs"] == 2 and d["stats"]["trades"] == 2 and d["stats"]["win_rate"] == 50.0
    assert [t["symbol"] for t in d["closed_trades"]] == [STOCKS[0]] * 2
    assert d["trades"] == 2  # the card on the Paper page counts them too


def test_a_desk_follows_all_the_stocks_it_is_given() -> None:
    """D-191: D-177 widened the desks to 250 stocks, but the desk kept only the first 30 and a
    strategy's list allowed 100; the log said 250."""
    from backend.kairos import brain, picks
    from backend.kairos import desk as dk
    from backend.strategy.validator import validate

    assert dk.MAX_SYMBOLS >= picks.N_PICKS
    syms = [f"S{k}" for k in range(picks.N_PICKS)]
    d = brain.definition("US", syms)
    res = validate(d.model_dump())
    assert res.ok and len(res.definition.universe.symbols) == picks.N_PICKS  # type: ignore[union-attr]
