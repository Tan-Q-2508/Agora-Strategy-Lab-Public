"""A strategy run as a sleeve of a portfolio (PORTFOLIO §1, D-80, D-84).

A sleeve is one strategy revision on its own stocks (with tuned settings when it has them)
trading a slice of the portfolio's money. Inside a sleeve each trade gets an equal share of
the sleeve's money (95% ÷ its most open trades), so the sleeve's size is its risk budget: sizing
belongs to portfolio construction, as in QuantConnect's LEAN.

``run_sleeve`` backtests one sleeve over Agora's default period and splits it at the 70% point
into study and exam years, giving the allocator daily returns and evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.backtest.manager import BacktestRequest
from backend.backtest.run import RunOutput, RunSpec, run
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import store
from backend.metis.brief import STUDY_SHARE, part
from backend.quant import stats
from backend.strategy import service as strategies
from backend.strategy.definition import RankingDefinition

DAY_MS = 86_400_000
INVESTED = 95.0  # % of a sleeve's money its trades may use together
COST_MARGIN = 1.05


def size_pct_for(max_open: int) -> float:
    """Each trade's share of the sleeve's money."""
    return round(INVESTED / max(1, max_open), 2)


@dataclass
class SleeveSpec:
    strategy_id: int
    version_id: int
    name: str
    market: str
    symbols: list[str]
    overrides: dict[str, float] = field(default_factory=dict)
    max_open: int = 5
    timeframe: str = "1d"
    opportunity_id: int | None = None
    sleeve_id: int | None = None

    @property
    def size_pct(self) -> float:
        return size_pct_for(self.max_open)

    @property
    def key(self) -> str:
        syms = ",".join(sorted(self.symbols))
        return f"{self.version_id}|{syms}|{sorted(self.overrides.items())}"

    def public(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version_id": self.version_id,
            "name": self.name,
            "market": self.market,
            "symbols": self.symbols,
            "overrides": self.overrides,
            "max_open": self.max_open,
            "size_pct": self.size_pct,
            "timeframe": self.timeframe,
            "opportunity_id": self.opportunity_id,
        }


def spec_of(
    ctx: Any,
    version_id: int,
    symbols: list[str],
    overrides: dict[str, float] | None = None,
    *,
    opportunity_id: int | None = None,
    sleeve_id: int | None = None,
) -> SleeveSpec | None:
    with ctx.db.session() as s:
        v = strategies.get_version(s, version_id)
        if v is None:
            return None
        from backend.db.models import Strategy

        row = s.get(Strategy, v.strategy_id)
        name = row.name if row is not None else f"Strategy #{v.strategy_id}"
    d = v.definition
    # a ranking holds ``hold`` stocks (its limit leaves room for a rebalance day, D-91)
    most = d.ranking.hold if isinstance(d, RankingDefinition) else d.limits.max_open_positions
    return SleeveSpec(
        strategy_id=v.strategy_id,
        version_id=v.id,
        name=name,
        market=d.market,
        symbols=list(symbols),
        overrides=dict(overrides or {}),
        max_open=most,
        timeframe=d.timeframe,
        opportunity_id=opportunity_id,
        sleeve_id=sleeve_id,
    )


def request(
    spec: SleeveSpec, capital: float, start: int | None = None, end: int | None = None
) -> BacktestRequest:
    return BacktestRequest(
        strategy_version_id=spec.version_id,
        symbols=spec.symbols,
        overrides=spec.overrides,
        size_pct=spec.size_pct,
        capital=capital,
        start=start,
        end=end,
    )


@dataclass
class SleeveRun:
    spec: SleeveSpec
    run_spec: RunSpec
    out: RunOutput
    split: int
    study: dict[str, Any]
    exam: dict[str, Any]
    days: list[str]  # local days, oldest first
    returns: np.ndarray  # daily returns, one per day after the first
    split_index: int  # returns[:split_index] are study days
    dearest: float  # the highest last price among its stocks

    @property
    def study_returns(self) -> np.ndarray:
        return self.returns[: self.split_index]

    @property
    def exam_returns(self) -> np.ndarray:
        return self.returns[self.split_index :]

    def worst_drop_pct(self) -> float:
        eq = np.array([p.equity for p in self.out.equity], dtype=float)
        if len(eq) == 0:
            return 0.0
        peaks = np.maximum.accumulate(eq)
        return float(((peaks - eq) / np.where(peaks > 0, peaks, 1)).max() * 100.0)

    def min_capital(self) -> float:
        """Enough money for each trade to buy one share of its dearest stock."""
        return self.dearest * 100.0 / self.spec.size_pct * COST_MARGIN


def dearest_price(ctx: Any, market: Market, symbols: list[str], end: int) -> float:
    best = 0.0
    with ctx.db.session() as s:
        insts = [i for x in symbols if (i := store.find_instrument(s, market, x)) is not None]
    for inst in insts:
        bars = ctx.cache.bars(inst, Timeframe.D1, end - 20 * DAY_MS, end + 1)
        if bars:
            best = max(best, float(bars[-1].close))
    return best


def run_sleeve(
    ctx: Any,
    spec: SleeveSpec,
    capital: float,
    *,
    start: int | None = None,
    end: int | None = None,
) -> SleeveRun:
    with ctx.db.session() as s:
        v = strategies.get_version(s, spec.version_id)
    assert v is not None
    run_spec, _extra = ctx.backtests.spec_for(v.definition, request(spec, capital, start, end))
    ctx.backtests.ensure_data_for(run_spec)
    out = run(ctx.cache, run_spec)
    split = run_spec.start_ms + int((run_spec.end_ms - run_spec.start_ms) * STUDY_SHARE)
    market = Market(spec.market)
    pts = stats.daily_points(out.equity, MARKET_TZ[market])
    days = [d for d, _v in pts]
    returns = stats.returns_of([v for _d, v in pts])
    split_day = stats.daily_points([(split, 0.0)], MARKET_TZ[market])[0][0]
    split_index = max(0, sum(1 for d in days[1:] if d < split_day))
    return SleeveRun(
        spec=spec,
        run_spec=run_spec,
        out=out,
        split=split,
        study=part(out.trades, run_spec.start_ms, split),
        exam=part(out.trades, split, run_spec.end_ms + 1),
        days=days,
        returns=returns,
        split_index=split_index,
        dearest=dearest_price(ctx, market, spec.symbols, run_spec.end_ms),
    )


def evidence(r: SleeveRun, tries: int) -> dict[str, Any]:
    """The exam-year evidence the allocator screens on, with the luck check."""
    ex = r.exam_returns
    luck = {
        "dsr": round(stats.dsr(ex, tries), 4) if len(ex) >= 20 else 0.0,
        "psr": round(stats.psr(ex), 4) if len(ex) >= 20 else 0.0,
        "tries": tries,
        "days": len(ex),
    }
    sharpe = stats.sharpe(ex) if len(ex) > 2 else 0.0
    return {
        "exam": r.exam,
        "study": r.study,
        "luck": luck,
        "sharpe": round(sharpe, 3) if math.isfinite(sharpe) else 0.0,
        "volatility": round(float(np.std(r.study_returns, ddof=1)) * math.sqrt(252), 4)
        if len(r.study_returns) > 2
        else 0.0,
    }
