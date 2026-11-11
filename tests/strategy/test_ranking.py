"""Ranking strategies and ranking portfolios (D-91): scores worked by hand, the monthly pick,
the shared engine holding the top few, templates, rules, sameness, and the portfolio method."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.core.types import Bar
from backend.kairos import router
from backend.kairos.tools.base import ThreadState
from backend.portfolio import service as portfolios
from backend.strategy import diff, lineage
from backend.strategy.definition import RankingDefinition, RankingSettings
from backend.strategy.ranking import RANKING_TEMPLATES, Ranker, describe, ranking_definition
from backend.strategy.validator import validate
from tests.data.helpers import wait_job
from tests.strategy.test_backtest_api import Y2018, Y2026, wait_run

DAY = 86_400_000


def test_momentum_score_by_hand() -> None:
    # 12-1 momentum: look = 252 days, skip = 21. Closes 100 … 352 (one a day, +1 each): the
    # close 252 days ago (index 0) is 100, the close 21 days ago (index 231) is 331, so the
    # score is 331 / 100 − 1 = 2.31.
    r = Ranker(RankingSettings(rank_by="momentum", lookback_months=12, skip_months=1, hold=3))
    close = np.arange(100.0, 353.0)
    assert len(close) == 253
    assert r.score(close) == pytest.approx(2.31)
    assert r.score(close[:252]) is None  # one candle short of the lookback
    # with the trend filter a faller doesn't qualify; without it, it ranks low: reversed,
    # index 0 is 352 and index 231 is 352 − 231 = 121, so 121 / 352 − 1 = −0.65625
    assert r.score(close[::-1].copy()) is None
    r2 = Ranker(RankingSettings(rank_by="momentum", trend_filter=False))
    assert r2.score(close[::-1].copy()) == pytest.approx(-0.65625)


def test_low_volatility_score_by_hand() -> None:
    # daily log moves alternate +a, −a: their spread (n − 1) over 126 moves is
    # a × √(126/125); the score is minus that × √252 (calmer ranks higher).
    a = 0.01
    moves = np.array([a if k % 2 == 0 else -a for k in range(240)])
    close = 100 * np.exp(np.concatenate([[0.0], np.cumsum(moves)]))
    r = Ranker(RankingSettings(rank_by="low_volatility", lookback_months=6, skip_months=0))
    flat_trend = r.score(close)
    # close ends on 100 (an even number of moves), equal to its 200-day average's rounding:
    # not above it, so the trend filter rejects it
    assert flat_trend is None
    r2 = Ranker(RankingSettings(rank_by="low_volatility", lookback_months=6, trend_filter=False))
    assert r2.score(close) == pytest.approx(-a * math.sqrt(126 / 125) * math.sqrt(252))
    rising = close * np.linspace(1.0, 1.5, len(close))
    assert r.score(rising) is not None


@dataclass
class _Inst:
    symbol: str


@dataclass
class _St:
    inst: _Inst
    raw: list[Bar]
    member: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def _stock(symbol: str, daily: float, n: int = 300, t0: int = 1_600_000_000_000) -> _St:
    raw = [
        Bar(t0 + k * DAY, 0, 0, 0, 100 * (1 + daily) ** k, 1000, "test", split_factor=1.0)
        for k in range(n)
    ]
    return _St(_Inst(symbol), raw)


def test_the_monthly_pick() -> None:
    r = Ranker(RankingSettings(rank_by="momentum", hold=2))
    stocks = [
        _stock("SLOW", 0.0005),
        _stock("FAST", 0.003),
        _stock("MID", 0.0015),
        _stock("DOWN", -0.001),
        _stock("SHORT", 0.01, n=100),  # too little history to rank
    ]
    stocks[2].member = lambda ts: False  # not in the index: never ranked
    r.bind(stocks)
    now = stocks[0].raw[-1].ts
    chosen = r.select(now)
    assert list(chosen) == ["FAST", "SLOW"] and chosen["FAST"][0] == 1
    # a stock whose prices stopped (no candle for weeks) isn't ranked either
    late = r.select(now + 30 * DAY)
    assert late == {}


def test_describe_and_templates() -> None:
    assert describe(RankingSettings()) == (
        "Each month, rank the stocks by 12-month rise (leaving out the latest 1 month) and hold "
        "the top 10 that actually rose, in equal shares."
    )
    d = ranking_definition("low_volatility", "US")
    assert d.product == "cash" and d.universe.kind == "all" and d.ranking.hold == 10
    # sizing and the open-trade limit follow from what it holds
    assert d.sizing.value == 9.5 and d.limits.max_open_positions == 20 and d.parameters == []
    assert set(RANKING_TEMPLATES) == {"momentum_top", "momentum_fast", "low_volatility"}


def test_rules_are_checked() -> None:
    bad = validate(
        {
            "kind": "ranking",
            "market": "IN",
            "product": "delivery",
            "universe": {"kind": "symbols", "symbols": ["RELIANCE", "TCS"]},
            "ranking": {"lookback_months": 3, "skip_months": 3, "hold": 5},
        }
    )
    where = {i.message for i in bad.issues}
    assert any("fewer than the months ranked on" in m for m in where)
    assert any("nothing to rank" in m for m in where)
    ok = validate(ranking_definition("momentum_top", "IN").model_dump(mode="json"))
    assert ok.ok, ok.issues


def test_sameness_and_plain_differences() -> None:
    a = ranking_definition("momentum_top", "IN")
    b = ranking_definition("momentum_fast", "IN")
    c = ranking_definition("low_volatility", "IN")
    same, sim, why = lineage.same(lineage.signature(a), lineage.signature(b))
    assert same and sim == 1.0 and why == "the same ranking with different numbers"
    assert not lineage.same(lineage.signature(a), lineage.signature(c))[0]
    lines = diff.changes(a, b)
    assert "Months ranked on: 12 → 6." in lines and "Stocks held: 10 → 5." in lines
    assert not any(line.startswith("Trade size") for line in lines)


def _concurrent(trades: list[dict[str, Any]]) -> int:
    events = []
    for t in trades:
        events.append((t["entry_ts"], 1))
        if t["exit_ts"] is not None and t["exit_reason"] != "end_of_test":
            events.append((t["exit_ts"], -1))
    most = held = 0
    for _ts, d in sorted(events, key=lambda e: (e[0], e[1])):  # exits first at the same open
        held += d
        most = max(most, held)
    return most


def test_a_ranking_backtest_holds_the_top_few(client: TestClient) -> None:
    tpl = client.get("/api/templates").json()["templates"]
    assert {"momentum_top", "low_volatility"} <= {t["key"] for t in tpl if t["kind"] == "ranking"}
    one = client.get("/api/templates/momentum_fast", params={"market": "US"}).json()
    assert one["definition"]["kind"] == "ranking" and one["definition"]["ranking"]["hold"] == 5
    r = client.post(
        "/api/strategies", json={"name": "Mom", "market": "IN", "template_key": "momentum_fast"}
    )
    assert r.status_code == 201 and r.json()["strategy"]["kind"] == "ranking"
    vid = r.json()["version"]["id"]
    run_id = client.post(
        "/api/backtests",
        json={"strategy_version_id": vid, "start": Y2018 + 365 * DAY, "end": Y2026},
    ).json()["run_id"]
    body = wait_run(client, run_id, timeout=300)
    assert body["status"] == "done", body
    trades = client.get(f"/api/backtests/{run_id}/trades", params={"limit": 5000}).json()["trades"]
    assert len(trades) > 10
    assert _concurrent(trades) <= 5
    assert all(t["entry_reason"].startswith("Rank ") for t in trades)
    sells = [t for t in trades if t["exit_reason"] == "signal"]
    # sells happen on the first trading day of a month (when it drops out of the top 5)
    assert sells and all(datetime.fromtimestamp(t["exit_ts"] / 1000, UTC).day <= 7 for t in sells)


def test_a_momentum_portfolio(client: TestClient, ctx: AppContext) -> None:
    r = client.post(
        "/api/portfolios", json={"market": "IN", "budget": 500_000, "method": "momentum"}
    )
    assert r.status_code in (200, 201), r.json()
    pid = r.json()["portfolio"]["id"]
    j = wait_job(client, r.json()["job_id"], timeout=300)
    assert j["status"] == "done", j
    d = client.get(f"/api/portfolios/{pid}").json()["portfolio"]
    assert d["method"] == "momentum"
    (sleeve,) = d["plan"]["sleeves"]
    assert sleeve["symbols"] == [] and sleeve["name"] == "Momentum: the 10 strongest risers"
    assert sleeve["size_pct"] == 9.5 and sleeve["reasons"][0].startswith("Momentum ranking:")
    assert 0 < sleeve["capital"] <= 450_000  # balanced keeps 10% in cash
    # a second ranking portfolio reuses the same strategy (D-79)
    again = portfolios.create(ctx, market="IN", budget=100_000, method="momentum")
    plan = portfolios.make_plan(ctx, again["id"])
    assert plan["sleeves"][0]["strategy_id"] == sleeve["strategy_id"]
    bt = portfolios.backtest(ctx, pid)
    assert bt["final"] > 0 and bt["metrics"]["trades"] > 0
    assert (
        client.post("/api/portfolios", json={"market": "IN", "method": "magic"}).status_code == 422
    )


def test_kairos_hears_a_momentum_portfolio(ctx: AppContext) -> None:
    calls = router.plan(ctx, "build me a momentum portfolio with 1 lakh", ThreadState(), {})
    call = next(c for c in calls if c.name == "portfolio")
    assert call.arguments["action"] == "build" and call.arguments["method"] == "momentum"
    calm = router.plan(ctx, "make a calm low volatility portfolio of 50000", ThreadState(), {})
    assert next(c for c in calm if c.name == "portfolio").arguments["method"] == "low_volatility"


def test_settings_are_plain_numbers() -> None:
    with pytest.raises(ValueError):
        RankingDefinition(market="IN", product="delivery", ranking={"hold": "$n"})  # type: ignore[arg-type]


def test_the_scanner_judges_rankings_as_a_whole(client: TestClient, ctx: AppContext) -> None:
    import json

    from backend.db.models import Opportunity
    from backend.portfolio import scan

    r = client.post(
        "/api/strategies", json={"name": "Calm", "market": "IN", "template_key": "low_volatility"}
    )
    sid = r.json()["strategy"]["id"]
    out = scan.scan(ctx, "IN")
    assert out["market"] == "IN"
    rankings = [f for f in out["found"] if f["strategy_id"] == sid]
    for f in rankings:
        assert f["symbols"] == [] and f["which"].startswith("the whole index")
    with ctx.db.session() as s:
        rows = s.query(Opportunity).filter(Opportunity.strategy_id == sid).all()
        assert all(json.loads(o.symbols) == [] for o in rows)
        assert len(rows) == len(rankings)
