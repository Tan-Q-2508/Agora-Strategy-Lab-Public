"""Backtesting a whole portfolio (PORTFOLIO §5, D-85).

Every sleeve is its own ``Engine`` (the shared engine, D-04) with its own cash, and all of them
step together over the union of their candle times: one budget, many strategies. On the first
candle of each month, and when a sleeve drifts more than 25% from its target, the portfolio
rebalances: each sleeve's target is its weight × the portfolio's value; sleeves above target
hand **free** cash to the reserve (open trades are never cut), sleeves below target receive from
it, and the reserve keeps its own share.

The honesty note travels with every result: the sleeves were chosen because they held up in
these years, so the backtest flatters the portfolio; the paper portfolio is the real test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from backend.backtest.run import RunSpec, _clean, benchmark_curve, load_states
from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market
from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.engine.core import Engine, EngineConfig
from backend.engine.types import EquityPoint, Trade
from backend.metis.brief import STUDY_SHARE
from backend.metrics import performance
from backend.portfolio import sleeves as sl
from backend.quant import stats
from backend.strategy import service as strategies
from backend.strategy.compiler import compile_definition

DRIFT = 0.25
CURVE_POINTS = 400
HONESTY = (
    "These sleeves were chosen because they held up in these years, so this backtest flatters "
    "the portfolio. The paper portfolio is the real test."
)
Progress = Callable[[float, str], None]


@dataclass
class Sleeve:
    name: str
    weight: float  # share of the portfolio's value
    capital: float
    spec: RunSpec
    engine: Engine
    moved: float = 0.0  # money moved in (+) and out (−) by rebalancing
    trades: list[Trade] = field(default_factory=list)


def _engine(ctx: Any, spec: RunSpec) -> Engine:
    program = compile_definition(spec.definition, spec.overrides)
    states, _report = load_states(ctx.cache, spec, program)
    with ctx.db.session() as s:
        table = ChargeTable.load(s, spec.market.value)
    costs = CostModel(spec.market.value, spec.definition.product, spec.brokerage_rules, table)
    cfg = EngineConfig(
        market=spec.market,
        product=spec.definition.product,
        timeframe=spec.timeframe,
        capital=spec.capital,
        slippage_bps=spec.slippage_bps,
        volume_cap_pct=spec.volume_cap_pct,
        square_off=spec.square_off,
        max_open_positions=spec.definition.limits.max_open_positions,
        max_daily_loss_pct=spec.definition.limits.max_daily_loss_pct,
        max_position_pct=spec.definition.limits.max_position_pct,
        start_ms=spec.start_ms,
    )
    return Engine(cfg, program, costs, states)


def rebalance(
    books: list[Sleeve], reserve: float, reserve_share: float, ts: int
) -> tuple[float, float]:
    """Move free cash towards each sleeve's target. Returns (new reserve, money moved)."""
    total = reserve + sum(b.engine.last_equity for b in books)
    moved = 0.0
    for b in books:
        target = b.weight * total
        extra = b.engine.last_equity - target
        if extra > 0:
            got = -b.engine.transfer(-extra, ts, "Rebalance: money to the reserve")
            reserve += got
            b.moved -= got
            moved += got
    spare = max(0.0, reserve - reserve_share * total)
    gaps = [(b, b.weight * total - b.engine.last_equity) for b in books]
    need = sum(g for _b, g in gaps if g > 0)
    if need > 0 and spare > 0:
        share = min(1.0, spare / need)
        for b, gap in gaps:
            if gap > 0:
                amount = b.engine.transfer(gap * share, ts, "Rebalance: money from the reserve")
                reserve -= amount
                b.moved += amount
                moved += amount
    return reserve, moved


def run_portfolio(
    ctx: Any,
    plan: dict[str, Any],
    *,
    start: int | None = None,
    end: int | None = None,
    progress: Progress | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> dict[str, Any]:
    say = progress or (lambda _p, _m: None)
    market = Market(plan["market"])
    tz = ZoneInfo(MARKET_TZ[market])
    budget = float(plan["budget"])
    books: list[Sleeve] = []
    for n, item in enumerate(plan["sleeves"]):
        say(2 + 18 * n / max(len(plan["sleeves"]), 1), f"Loading {item['name']}…")
        spec_ = sl.spec_of(
            ctx, int(item["version_id"]), list(item["symbols"]), item.get("overrides")
        )
        if spec_ is None:
            continue
        with ctx.db.session() as s:
            v = strategies.get_version(s, spec_.version_id)
        assert v is not None
        run_spec, _x = ctx.backtests.spec_for(
            v.definition, sl.request(spec_, float(item["capital"]), start, end)
        )
        start, end = run_spec.start_ms, run_spec.end_ms  # every sleeve shares the period
        ctx.backtests.ensure_data_for(run_spec)
        books.append(
            Sleeve(
                item["name"],
                float(item["weight"]),
                float(item["capital"]),
                run_spec,
                _engine(ctx, run_spec),
            )
        )
    if not books:
        return {"empty": True, "note": "The plan has no sleeves to backtest."}
    reserve = budget - sum(b.capital for b in books)
    reserve_share = max(0.0, reserve / budget)
    steps: dict[int, list[tuple[int, Any, int]]] = {}
    for k, b in enumerate(books):
        for st in b.engine.symbols:
            for i, bar in enumerate(st.raw):
                if b.spec.start_ms <= bar.ts < b.spec.end_ms:
                    steps.setdefault(bar.ts, []).append((k, st, i))
    order = sorted(steps)
    points: list[EquityPoint] = []
    moved_total, rebalances = 0.0, 0
    last_month = last_day = None
    every = max(1, len(order) // 100)
    for n, ts in enumerate(order):
        if n % every == 0:
            if check_cancel:
                check_cancel()
            say(20 + 75 * n / max(len(order), 1), "Running the portfolio…")
        local = ms_to_dt(ts, tz)
        month, day = local.strftime("%Y-%m"), local.strftime("%Y-%m-%d")
        if last_day is not None and day != last_day:
            total = reserve + sum(b.engine.last_equity for b in books)
            drift = any(
                b.weight > 0 and abs(b.engine.last_equity / (b.weight * total) - 1) > DRIFT
                for b in books
            )
            if month != last_month or drift:
                reserve, moved = rebalance(books, reserve, reserve_share, ts)
                if moved > 0:
                    rebalances += 1
                    moved_total += moved
        last_month, last_day = month, day
        by_book: dict[int, list[tuple[Any, int]]] = {}
        for k, st, i in steps[ts]:
            by_book.setdefault(k, []).append((st, i))
        for k, items in by_book.items():
            books[k].engine.step(ts, items)
        equity = reserve + sum(b.engine.last_equity for b in books)
        gross = sum(b.engine.position_value()[1] for b in books)
        cash = reserve + sum(b.engine.cash for b in books)
        points.append(EquityPoint(ts, equity, cash, gross / equity if equity > 0 else 0.0))
    for b in books:
        b.engine.finish()
    say(96, "Calculating results…")
    trades = [t for b in books for t in b.engine.trades]
    charges = sum(float(b.engine.charges.total) for b in books)
    notional = sum(
        (o.price or 0.0) * o.qty for b in books for o in b.engine.orders if o.status == "filled"
    )
    bench_spec = books[0].spec
    bench = benchmark_curve(ctx.cache, bench_spec, budget)
    metrics = performance.compute(
        points, trades, budget, tz, charges_total=charges, traded_notional=notional, benchmark=bench
    )
    split = int(start + (end - start) * STUDY_SHARE) if start is not None and end is not None else 0
    study_r = stats.daily_returns(points, tz, hi=split)
    exam_r = stats.daily_returns(points, tz, lo=split)
    parts = {
        "split": split,
        "study": {
            "days": len(study_r),
            "sharpe": round(stats.sharpe(study_r), 3) if len(study_r) > 2 else None,
        },
        "exam": {
            "days": len(exam_r),
            "sharpe": round(stats.sharpe(exam_r), 3) if len(exam_r) > 2 else None,
        },
    }
    contributions = []
    for b in books:
        final = b.engine.last_equity
        contributions.append(
            {
                "name": b.name,
                "capital": round(b.capital, 2),
                "final": round(final, 2),
                "moved": round(b.moved, 2),
                "made": round(final - b.capital - b.moved, 2),
                "trades": sum(1 for t in b.engine.trades if t.closed),
            }
        )
    step = max(1, len(points) // CURVE_POINTS)
    curve = [(p.ts, round(p.equity, 2)) for p in points[::step]]
    if points and curve[-1][0] != points[-1].ts:
        curve.append((points[-1].ts, round(points[-1].equity, 2)))
    bstep = max(1, len(bench) // CURVE_POINTS)
    say(100, "Done.")
    result: dict[str, Any] = _clean(
        {
            "start": start,
            "end": end,
            "budget": budget,
            "final": round(points[-1].equity, 2) if points else budget,
            "metrics": metrics,
            "curve": curve,
            "benchmark": [(t, round(v, 2)) for t, v in bench[::bstep]],
            "sleeves": contributions,
            "rebalances": rebalances,
            "moved": round(moved_total, 2),
            "reserve_end": round(reserve, 2),
            "parts": parts,
            "honesty": HONESTY,
        }
    )
    return result
