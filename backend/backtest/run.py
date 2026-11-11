"""Run one backtest: load data (with indicator warm-up), drive the engine through the
historical steps, and compute metrics. Persistence and job handling live in manager.py.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.data import store
from backend.data.adjust import adjusted
from backend.data.cache import CacheManager
from backend.data.store import InstrumentRef
from backend.engine.core import Engine, EngineConfig, SymbolState
from backend.engine.types import ChargeTotals, EquityPoint, OrderEvent, Trade
from backend.markets.calendar import sessions_between_ms
from backend.metrics import performance
from backend.strategy.compiler import Program, compile_definition
from backend.strategy.definition import AnyDefinition

DAY_MS = 86_400_000
ENGINE_VERSION = "1"
Progress = Callable[[float, str], None]


class NoData(Exception):
    """Plain-English: nothing to backtest on."""


@dataclass
class RunSpec:
    definition: AnyDefinition
    instruments: list[InstrumentRef]
    timeframe: Timeframe
    start_ms: int
    end_ms: int
    capital: float
    brokerage_rules: dict[str, Any]
    slippage_bps: float
    volume_cap_pct: float = 5.0
    square_off: str = "15:20"
    overrides: dict[str, float] = field(default_factory=dict)
    benchmark: InstrumentRef | None = None
    # instrument_id → [(from, to)] index membership; set once history has been imported
    membership: dict[int, list[tuple[int, int | None]]] = field(default_factory=dict)
    # load indicator history from here instead of the usual warm-up (backtest-vs-live uses
    # the paper session's own history start so both see identical indicator values)
    history_from_ms: int | None = None
    # Kairos's trade check (KAIROS §16): off, learn, balanced or strict, and what it already
    # knows (results that were complete before this run's start, D-71)
    trade_check: str = "off"
    trade_check_seed: list[Any] = field(default_factory=list)

    @property
    def market(self) -> Market:
        return Market(self.definition.market)


@dataclass
class RunOutput:
    trades: list[Trade]
    equity: list[EquityPoint]
    orders: list[OrderEvent]
    logs: list[str]
    charges: ChargeTotals
    metrics: dict[str, Any]
    per_symbol: list[dict[str, Any]]
    benchmark: list[tuple[int, float]]
    data: dict[str, dict[str, Any]]
    program: Program
    traded_notional: float
    trade_check: dict[str, Any] | None = None
    check_samples: list[Any] = field(default_factory=list)


def warmup_ms(timeframe: Timeframe, bars: int) -> int:
    """Calendar time that holds ``bars`` candles, with room for weekends and holidays."""
    if timeframe is Timeframe.D1:
        return int((bars * 1.6 + 10) * DAY_MS)
    per_day = max(1.0, 375.0 / timeframe.minutes)
    return int((bars / per_day * 1.6 + 5) * DAY_MS)


def load_states(
    cache: CacheManager, spec: RunSpec, program: Program
) -> tuple[list[SymbolState], dict[str, dict[str, Any]]]:
    """Each symbol's raw candles from warm-up start to the end, plus a data report for the
    honesty panel (first/last candle, gaps, sources)."""
    load_from = spec.start_ms - warmup_ms(spec.timeframe, program.warmup)
    if spec.history_from_ms is not None:
        load_from = min(spec.history_from_ms, spec.start_ms)
    tz = ZoneInfo(MARKET_TZ[spec.market])
    states: list[SymbolState] = []
    report: dict[str, dict[str, Any]] = {}
    for inst in spec.instruments:
        raw = cache.bars(inst, spec.timeframe, load_from, spec.end_ms)
        in_range = [b for b in raw if b.ts >= spec.start_ms]
        with cache.db.session() as s:
            sources = store.sources_used(s, inst.id, spec.timeframe, spec.start_ms, spec.end_ms)
            actions = store.load_actions(s, inst.id)
        expected = [
            x
            for x in sessions_between_ms(cache.calendar, inst.market, spec.start_ms, spec.end_ms)
            if x.close_ms <= cache.clock.now_ms()
        ]
        have_days = {ms_to_dt(b.ts, tz).date() for b in in_range}
        missing = [x for x in expected if x.day not in have_days]
        if in_range:
            first_day = ms_to_dt(in_range[0].ts, tz).date()
            missing = [x for x in missing if x.day >= first_day]  # before listing isn't a gap
        else:
            missing = []  # reported as "left out" instead
        report[inst.symbol] = {
            "instrument_id": inst.id,
            "bars": len(in_range),
            "first": in_range[0].ts if in_range else None,
            "last": in_range[-1].ts if in_range else None,
            "warmup_bars": len(raw) - len(in_range),
            "missing_sessions": len(missing),
            "trading_days": len(have_days),
            "sources": sources,
        }
        if not in_range:
            continue
        dividends = {
            ms_to_dt(a.ex_date, tz).strftime("%Y-%m-%d"): float(a.amount or 0.0)
            for a in actions
            if a.kind == "dividend" and a.amount
        }
        st = SymbolState(inst=inst, raw=raw, dividends=dividends)
        ranges = spec.membership.get(inst.id)
        if ranges is not None:
            st.member = _member_check(ranges)
        states.append(st)
    if spec.definition.limits.max_per_group is not None:
        with cache.db.session() as s:
            named = store.groups(s, [x.inst.id for x in states])
        for x in states:
            x.group = named.get(x.inst.id, "")
    return states, report


def _member_check(ranges: list[tuple[int, int | None]]) -> Callable[[int], bool]:
    def member(ts: int) -> bool:
        return any(a <= ts and (b is None or ts < b) for a, b in ranges)

    return member


def benchmark_curve(
    cache: CacheManager, spec: RunSpec, start_value: float
) -> list[tuple[int, float]]:
    """Buy-and-hold of the benchmark (Nifty 50 / SPY), price only, scaled to the capital."""
    if spec.benchmark is None:
        return []
    bars = cache.bars(spec.benchmark, Timeframe.D1, spec.start_ms - 5 * DAY_MS, spec.end_ms)
    bars = [adjusted(b) for b in bars if b.ts >= spec.start_ms - DAY_MS]
    if not bars:
        return []
    first = bars[0].close
    return [(b.ts, start_value * b.close / first) for b in bars]


def execute(
    states: Sequence[SymbolState],
    spec: RunSpec,
    program: Program,
    costs: CostModel,
    *,
    progress: Progress | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> Engine:
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
        max_per_group=spec.definition.limits.max_per_group,
        start_ms=spec.start_ms,
    )
    engine = Engine(cfg, program, costs, states)
    if spec.trade_check != "off":
        from backend.kairos.quality import TradeCheck, score_reader

        engine.check = TradeCheck(
            spec.trade_check,  # type: ignore[arg-type]
            spec.trade_check_seed,
            score_for=score_reader(),
        )
    steps: dict[int, list[tuple[SymbolState, int]]] = {}
    for st in engine.symbols:
        for i, b in enumerate(st.raw):
            if spec.start_ms <= b.ts < spec.end_ms:
                steps.setdefault(b.ts, []).append((st, i))
    ordered = sorted(steps)
    total = len(ordered)
    every = max(1, total // 100)
    for n, ts in enumerate(ordered):
        if n % every == 0:
            if check_cancel:
                check_cancel()
            if progress:
                progress(5 + 90 * n / max(total, 1), "Running the strategy…")
        engine.step(ts, steps[ts])
    engine.finish()
    return engine


def run(
    cache: CacheManager,
    spec: RunSpec,
    *,
    progress: Progress | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> RunOutput:
    program = compile_definition(spec.definition, spec.overrides)
    if progress:
        progress(2, "Loading prices…")
    states, report = load_states(cache, spec, program)
    if not states:
        names = ", ".join(i.symbol for i in spec.instruments[:5])
        raise NoData(f"No saved prices for {names} in that period.")
    with cache.db.session() as s:
        table = ChargeTable.load(s, spec.market.value)
    costs = CostModel(spec.market.value, spec.definition.product, spec.brokerage_rules, table)
    engine = execute(states, spec, program, costs, progress=progress, check_cancel=check_cancel)
    if progress:
        progress(96, "Calculating results…")
    tz = ZoneInfo(MARKET_TZ[spec.market])
    bench = benchmark_curve(cache, spec, spec.capital)
    notional = sum((o.price or 0.0) * o.qty for o in engine.orders if o.status == "filled")
    metrics = performance.compute(
        engine.equity,
        engine.trades,
        spec.capital,
        tz,
        charges_total=float(engine.charges.total),
        traded_notional=notional,
        benchmark=bench,
    )
    metrics["charges_by_type"] = {k: float(v) for k, v in engine.charges.by_type.items() if v}
    check = engine.check.summary() if engine.check is not None else None
    if check is not None:
        metrics["trade_check"] = check
    return RunOutput(
        trades=engine.trades,
        equity=engine.equity,
        orders=engine.orders,
        logs=engine.logs,
        charges=engine.charges,
        metrics=_clean(metrics),
        per_symbol=performance.per_symbol(engine.trades),
        benchmark=bench,
        data=report,
        program=program,
        traded_notional=notional,
        trade_check=check,
        check_samples=list(engine.check.new_samples) if engine.check is not None else [],
    )


def _clean(x: Any) -> Any:
    """JSON-safe: NaN/inf become None."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x
