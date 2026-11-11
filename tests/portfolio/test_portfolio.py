"""Opportunities, portfolio backtests and paper portfolios on practice data (PORTFOLIO §3–§7,
D-80, D-84 to D-86)."""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.db.models import Opportunity, PaperSession, PortfolioSleeve
from backend.engine.types import Trade
from backend.kairos import router
from backend.kairos.tools import ALL
from backend.kairos.tools.base import Env, ThreadState
from backend.portfolio import allocate, live, scan, sleeves
from backend.portfolio import service as svc
from backend.portfolio.backtest import _engine, run_portfolio
from tests.data.helpers import wait_job
from tests.strategy.test_backtest_api import Y2018, Y2026, make_strategy

FIVE = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"]


def _version(client: TestClient, key: str = "ma_crossover") -> int:
    created = make_strategy(client, key, "IN")
    vid: int = created["version"]["id"]
    return vid


def _plan_item(
    ctx: AppContext, vid: int, symbols: list[str], capital: float, weight: float
) -> dict[str, Any]:
    sp = sleeves.spec_of(ctx, vid, symbols)
    assert sp is not None
    return {
        "name": sp.name,
        "strategy_id": sp.strategy_id,
        "version_id": vid,
        "symbols": symbols,
        "overrides": {},
        "size_pct": sp.size_pct,
        "capital": capital,
        "weight": weight,
        "worst_drop_pct": 10.0,
        "reasons": ["Held up on unseen years (test)."],
        "opportunity_id": None,
    }


# ---------------------------------------------------------------- the engine and the backtest


def test_transfers_only_move_free_cash(client: TestClient, ctx: AppContext) -> None:
    vid = _version(client)
    sp = sleeves.spec_of(ctx, vid, FIVE[:2])
    assert sp is not None
    from backend.strategy import service as strategies

    with ctx.db.session() as s:
        v = strategies.get_version(s, vid)
    assert v is not None
    spec, _x = ctx.backtests.spec_for(v.definition, sleeves.request(sp, 50_000.0, Y2018, Y2026))
    ctx.backtests.ensure_data_for(spec)
    eng = _engine(ctx, spec)
    assert eng.transfer(1_000.0, 0) == 1_000.0 and eng.cash == 51_000.0
    assert eng.transfer(-99_999.0, 0) == -51_000.0 and eng.cash == 0.0  # no more than it has
    assert eng.transfer(0.0, 0) == 0.0


def test_a_one_sleeve_portfolio_is_a_plain_backtest(client: TestClient, ctx: AppContext) -> None:
    vid = _version(client)
    sp = sleeves.spec_of(ctx, vid, FIVE)
    assert sp is not None
    plain = sleeves.run_sleeve(ctx, sp, 100_000.0, start=Y2018, end=Y2026)
    plan = {
        "market": "IN",
        "budget": 100_000.0,
        "sleeves": [_plan_item(ctx, vid, FIVE, 100_000.0, 1.0)],
    }
    out = run_portfolio(ctx, plan, start=Y2018, end=Y2026)
    assert out["rebalances"] == 0 and out["moved"] == 0
    assert out["final"] == pytest.approx(plain.out.equity[-1].equity, abs=0.01)
    assert out["sleeves"][0]["trades"] == sum(1 for t in plain.out.trades if t.closed)


def test_rebalancing_conserves_money(client: TestClient, ctx: AppContext) -> None:
    a, b = _version(client, "ma_crossover"), _version(client, "rsi_mean_reversion")
    plan = {
        "market": "IN",
        "budget": 200_000.0,
        "sleeves": [
            _plan_item(ctx, a, FIVE[:3], 90_000.0, 0.45),
            _plan_item(ctx, b, FIVE[2:], 90_000.0, 0.45),
        ],
    }
    out = run_portfolio(ctx, plan, start=Y2018, end=Y2026)
    assert out["rebalances"] > 0 and out["moved"] > 0
    made = sum(s["made"] for s in out["sleeves"])
    assert out["final"] - out["budget"] == pytest.approx(made, abs=0.05)
    moved_net = sum(s["moved"] for s in out["sleeves"])
    assert out["reserve_end"] == pytest.approx(20_000.0 - moved_net, abs=0.05)
    assert out["metrics"]["start_equity"] == 200_000.0 and "flatters" in out["honesty"]


# ---------------------------------------------------------------- the scanner


def _trade(sym: str, entry: int, net: float) -> Trade:
    return Trade(sym, 1, "long", 1, entry, 1, entry + 1, 1, net, 0.0, net, net, 1, "", "signal")


def test_stocks_are_chosen_on_the_study_years_only() -> None:
    trades = [_trade("GOOD", 10 + k, 5.0) for k in range(6)]
    trades += [_trade("GOOD", 20, -2.0), _trade("FEW", 30, 9.0), _trade("BAD", 40, -1.0)]
    trades += [_trade("BAD", 41, -1.0), _trade("BAD", 42, -1.0), _trade("BAD", 43, 0.5)]
    trades += [_trade("LATE", 200 + k, 50.0) for k in range(9)]  # all after the split
    study = scan.per_stock(trades, 0, 100)
    assert scan.choose(study) == ["GOOD"]
    ok, st = scan.exam_ok([t for t in trades if t.entry_ts >= 100])
    assert ok and st["trades"] == 9


def test_the_scanner_records_and_refreshes_opportunities(
    client: TestClient, ctx: AppContext
) -> None:
    vid = _version(client)
    out = scan.scan(ctx, "IN")
    assert out["strategies"] == 1 and out["note"].startswith("Tried 1 strategy on ")
    sp = sleeves.spec_of(ctx, vid, ["TCS", "INFY"])
    assert sp is not None
    ev = {
        "exam": {"trades": 12, "wins": 8, "net": 4200.0, "profit_factor": 1.8},
        "study": {"trades": 30},
        "luck": {"dsr": 0.81, "psr": 0.9, "tries": 3, "days": 500},
        "sharpe": 1.2,
        "volatility": 0.1,
    }
    oid = scan.record(ctx, sp, ev, "scanner")
    assert scan.record(ctx, sp, ev, "scanner") == oid  # the same pairing is one opportunity
    got = svc.opportunities(ctx, "IN")
    mine = next(o for o in got if o["id"] == oid)
    assert (
        mine["score"] == pytest.approx(1.2 * 0.81)
        and "81% chance it isn't luck" in mine["evidence"]
    )
    assert (
        client.post(f"/api/opportunities/{oid}/dismiss").json()["opportunity"]["status"]
        == "dismissed"
    )
    r = client.post(f"/api/opportunities/{oid}/backtest")
    assert r.status_code == 202 and r.json()["run_id"] > 0


def test_an_archived_strategys_opportunities_go_stale(client: TestClient, ctx: AppContext) -> None:
    """A retired strategy is never scanned again, so its offers stayed open (2026-11-05)."""
    from backend.db.models import Opportunity

    vid = _version(client)
    sp = sleeves.spec_of(ctx, vid, ["TCS", "INFY"])
    assert sp is not None
    ev = {
        "exam": {"trades": 12, "wins": 8, "net": 4200.0, "profit_factor": 1.8},
        "study": {"trades": 30},
        "luck": {"dsr": 0.81, "psr": 0.9, "tries": 3, "days": 500},
        "sharpe": 1.2,
        "volatility": 0.1,
    }
    oid = scan.record(ctx, sp, ev, "scanner")
    with ctx.db.session() as s:
        sid = s.get(Opportunity, oid).strategy_id  # type: ignore[union-attr]
    assert client.delete(f"/api/strategies/{sid}").status_code == 200
    scan.scan(ctx, "IN")
    with ctx.db.session() as s:
        assert s.get(Opportunity, oid).status == "stale"  # type: ignore[union-attr]


# ---------------------------------------------------------------- plans, paper and the manager


def _fake_candidates(ctx: AppContext, vids: list[tuple[int, list[str]]]) -> Any:
    """Real strategy versions with made-up evidence, so the flow can be tested on random data."""
    pats = [[1, -1, 1, -1], [1, 1, -1, -1], [1, -1, -1, 1]]

    def fake(_ctx: Any, market: str, pid: int | None = None) -> list[allocate.Candidate]:
        out = []
        for k, (vid, syms) in enumerate(vids):
            sp = sleeves.spec_of(ctx, vid, syms)
            assert sp is not None
            r = np.array(pats[k % 3] * 125, dtype=float) * 0.002
            out.append(
                allocate.Candidate(
                    key=sp.key,
                    name=sp.name,
                    strategy_id=sp.strategy_id,
                    version_id=vid,
                    symbols=syms,
                    size_pct=sp.size_pct,
                    max_open=sp.max_open,
                    dearest=500.0,
                    days=[f"d{i:04d}" for i in range(len(r) + 1)],
                    returns=r,
                    split_index=400,
                    exam={"trades": 15, "wins": 9, "net": 3000.0, "profit_factor": 1.6},
                    sharpe=1.0 + k * 0.1,
                    dsr=0.8,
                    worst_drop_pct=8.0,
                )
            )
        return out

    return fake


def _wait_runners(ctx: AppContext, pid: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = live._sleeves(ctx, pid)
        if rows and all(
            (r := ctx.paper.runner(x.session_id)) is not None and r.engine is not None for x in rows
        ):
            return
        time.sleep(0.05)
    raise AssertionError("sleeve sessions did not start")


def test_portfolio_end_to_end(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = _version(client, "ma_crossover"), _version(client, "rsi_mean_reversion")
    monkeypatch.setattr(svc, "candidates", _fake_candidates(ctx, [(a, FIVE[:3]), (b, FIVE[2:])]))
    r = client.post("/api/portfolios", json={"market": "IN", "budget": 100_000, "risk": "balanced"})
    assert r.status_code == 201, r.json()
    pid = r.json()["portfolio"]["id"]
    assert wait_job(client, r.json()["job_id"], 120)["status"] == "done"
    p = client.get(f"/api/portfolios/{pid}").json()["portfolio"]
    plan = p["plan"]
    assert len(plan["sleeves"]) == 2 and plan["cash"] >= 10_000 - 1e-6
    assert sum(s["capital"] for s in plan["sleeves"]) + plan["cash"] == pytest.approx(100_000)
    assert p["moves"][0]["kind"] == "plan" and "Planned 2 sleeves" in p["moves"][0]["text"]
    # backtest it
    job = client.post(f"/api/portfolios/{pid}/backtest").json()["job_id"]
    assert wait_job(client, job, 180)["status"] == "done"
    bt = client.get(f"/api/portfolios/{pid}").json()["portfolio"]["backtest"]
    assert bt["budget"] == 100_000 and len(bt["sleeves"]) == 2 and bt["curve"]
    # paper trade it: one session per sleeve, with its own stocks and trade size (D-80)
    d = client.post(f"/api/portfolios/{pid}/paper/start").json()["portfolio"]
    assert d["status"] == "paper" and len(d["sleeves"]) == 2
    _wait_runners(ctx, pid)
    with ctx.db.session() as s:
        rows = s.query(PortfolioSleeve).filter_by(portfolio_id=pid).all()
        notes = [json.loads(s.get(PaperSession, r.session_id).notes) for r in rows]
    assert all(n["portfolio_id"] == pid and n["size_pct"] == 19.0 for n in notes)
    assert {tuple(n["symbols"]) for n in notes} == {tuple(FIVE[:3]), tuple(FIVE[2:])}
    v = live.value(ctx, pid)
    assert v["equity"] == pytest.approx(100_000, rel=0.05)
    # take money out of a sleeve by hand: its P&L doesn't change, the cash grows
    sleeve = live._sleeves(ctx, pid)[0]
    runner = ctx.paper.runner(sleeve.session_id)
    assert runner is not None
    before = ctx.paper.detail(sleeve.session_id)["total_return"]
    moved = runner.transfer(-1_000.0, "test")
    assert moved == -1_000.0
    assert ctx.paper.detail(sleeve.session_id)["total_return"] == pytest.approx(before, abs=1e-6)
    pv = client.get(f"/api/portfolios/{pid}/rebalance").json()
    assert any(abs(x["move"]) > 0 for x in pv["moves"])
    out = client.post(f"/api/portfolios/{pid}/rebalance").json()
    assert out["moved"] > 0
    assert (
        "Rebalance you asked for"
        in client.get(f"/api/portfolios/{pid}").json()["portfolio"]["moves"][0]["text"]
    )
    # the kill switch winds a sleeve down; once flat it retires and its money returns
    with ctx.db.session() as s:
        row = s.get(PortfolioSleeve, sleeve.id)
        assert row is not None
        row.worst_drop_pct = 0.0001
    monkeypatch.setattr(live, "_peak_drop_pct", lambda _c, _s: 5.0)
    res = live.review(ctx, pid)
    assert res["wound_down"] >= 1
    live.settle(ctx, pid)
    stopped = client.post(f"/api/portfolios/{pid}/paper/stop").json()["portfolio"]
    assert stopped["status"] == "stopped"
    kinds = [m["kind"] for m in stopped["moves"]]
    assert {"start", "rebalance", "retire", "stop"} <= set(kinds)


def test_kairos_builds_a_portfolio_from_a_budget(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _version(client, "ma_crossover")
    monkeypatch.setattr(svc, "candidates", _fake_candidates(ctx, [(a, FIVE)]))
    calls = router.plan(ctx, "Build me a portfolio with 1 lakh rupees", ThreadState(), {})
    assert calls[0].name == "portfolio"
    assert dict(calls[0].arguments) == {"action": "build", "budget": 100000.0}
    assert dict(router.plan(ctx, "how is my portfolio doing?", ThreadState(), {})[0].arguments) == {
        "action": "status"
    }
    assert (
        dict(router.plan(ctx, "find new opportunities", ThreadState(), {})[0].arguments)["action"]
        == "scan"
    )
    tool = ALL["portfolio"]
    res = tool.run(Env(ctx, ThreadState()), tool.args(action="build", budget=100_000, market="IN"))
    assert res.ok and "The allocator (tested code) split it" in res.summary
    assert res.ui is not None and res.ui["navigate"].startswith("/portfolio/")
    status = tool.run(Env(ctx, ThreadState()), tool.args(action="status"))
    assert status.ok and "budget ₹1.00 lakh" in status.summary


def test_api_validation(client: TestClient) -> None:
    assert client.post("/api/portfolios", json={"market": "XX"}).status_code == 422
    assert client.get("/api/portfolios/999").status_code == 404
    assert client.get("/api/portfolios").json() == {"portfolios": []}
    opp = client.get("/api/opportunities").json()
    assert opp == {"opportunities": []}
    with pytest.raises(AssertionError):
        assert client.post("/api/portfolios/999/paper/start").status_code == 200
    _ = Opportunity  # the table is part of the model (migration 0009)
