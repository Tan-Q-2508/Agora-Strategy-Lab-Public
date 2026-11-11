"""Smoke backtest of every template on the fixtures (Phase 3.5 / 4.1), plus a speed check."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select

from backend.backtest.run import RunSpec, run
from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import service, store
from backend.db.models import BrokerageProfile
from backend.strategy.templates import TEMPLATES, template_definition

Y2016 = 1_451_606_400_000
Y2026 = 1_767_225_600_000


def spec_for(ctx: AppContext, key: str, market: str, symbols: list[str]) -> RunSpec:
    d = template_definition(key, market)
    tf = Timeframe(d.timeframe)
    with ctx.db.session() as s:
        insts = [store.find_instrument(s, Market(market), sym) for sym in symbols]
        rules = s.scalar(
            select(BrokerageProfile.rules).where(
                BrokerageProfile.market_code == market, BrokerageProfile.is_default == 1
            )
        )
        bench = store.find_instrument(s, Market(market), service.BENCHMARK[Market(market)])
    targets = [i for i in insts if i is not None]
    start = Y2016 + 400 * 86_400_000 if tf is Timeframe.D1 else Y2026 - 80 * 86_400_000
    service.refresh(
        ctx.cache,
        [*targets, bench],
        [tf] if bench is None else [tf, Timeframe.D1],
        start_ms=Y2016,
        end_ms=Y2026,
    )
    return RunSpec(
        definition=d,
        instruments=targets,
        timeframe=tf,
        start_ms=start,
        end_ms=Y2026,
        capital=1_000_000 if market == "IN" else 100_000,
        brokerage_rules=json.loads(rules or "{}"),
        slippage_bps=5 if market == "IN" else 2,
        benchmark=bench,
    )


@pytest.mark.parametrize("key", sorted(TEMPLATES))
def test_every_template_backtests(ctx: AppContext, key: str) -> None:
    for market, syms in (("IN", ["RELIANCE", "INFY"]), ("US", ["AAPL", "SPY"])):
        out = run(ctx.cache, spec_for(ctx, key, market, syms))
        assert out.metrics["final_equity"] > 0
        assert out.trades, f"{key} ({market}) made no trades"
        assert all(t.charges > 0 for t in out.trades if t.closed) or market == "US"
        assert out.metrics.get("benchmark") is not None


def test_nifty_ten_years_is_fast_enough(ctx: AppContext) -> None:
    syms = [
        "RELIANCE",
        "TCS",
        "HDFCBANK",
        "INFY",
        "ICICIBANK",
        "SBIN",
        "ITC",
        "LT",
        "BHARTIARTL",
        "MARUTI",
    ]
    spec = spec_for(ctx, "rsi_mean_reversion", "IN", syms)
    t0 = time.perf_counter()
    out = run(ctx.cache, spec)
    elapsed = time.perf_counter() - t0
    # SPEC §11: Nifty 50 × 10 years < 30 s on the laptop; 10 symbols here → well under 6 s
    assert elapsed < 6.0, f"{elapsed:.1f}s"
    assert out.metrics["trades"] > 0
