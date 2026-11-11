"""Strategy Definition → something the engine can run.

``compile_definition`` returns a ``Program``: the parameter values in force, an
``on_bar(ctx)`` function, and how much history the rules need before they can fire.

Visual rules are turned into small Python closures once, up front, that call the same
``ctx`` helpers a code strategy uses (``ctx.crosses_above`` …), so the two kinds behave
identically. Code strategies are compiled in the sandbox.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.analysis import mtf
from backend.indicators import catalog
from backend.strategy.definition import (
    AllOf,
    AnyDefinition,
    AnyOf,
    Between,
    CodeDefinition,
    CombinedDefinition,
    Compare,
    Condition,
    IndicatorOperand,
    KairosDefinition,
    NotOf,
    NumberOperand,
    Operand,
    PositionCheck,
    PriceOperand,
    RankingDefinition,
    ScaleOutSpec,
    Sizing,
    StopSpec,
    TimeWindow,
    VisualDefinition,
    resolve_num,
)
from backend.strategy.runtime import (
    ScaleOut,
    SeriesView,
    SizeSpec,
    StopRule,
    StrategyContext,
    make_scale_out,
)
from backend.strategy.validator import iter_operands

OnBar = Callable[[StrategyContext], None]
OperandFn = Callable[[StrategyContext], SeriesView | float]
CondFn = Callable[[StrategyContext], bool]

LABEL_BUY = "Buy rule"
LABEL_SHORT = "Short-sell rule"
LABEL_SELL = "Sell rule"
LABEL_COVER = "Buy-back rule"
LABEL_TIME_LIMIT = "Time limit reached"
LABEL_EXIT_TIME = "Exit time reached"


@dataclass
class Program:
    """A strategy ready to run: ``on_bar`` plus everything the engine needs to know."""

    on_bar: OnBar
    params: dict[str, float]
    default_size: SizeSpec
    warmup: int
    kind: str  # "visual" | "code" | "kairos" | "ranking" | "combined"
    source_code: str | None = None
    brain: Any = None  # the Kairos brain (kind "kairos") or the ranker (kind "ranking")
    # Called by the engine with all its stocks, for rules that compare stocks (ranking, D-91)
    bind: Callable[[list[Any]], None] | None = None


class CompileError(ValueError):
    pass


def parameter_values(
    defn: AnyDefinition, overrides: Mapping[str, float] | None = None
) -> dict[str, float]:
    """Defaults, replaced by any overrides (e.g. from a parameter sweep)."""
    values = {p.name: float(p.default) for p in defn.parameters}
    for k, v in (overrides or {}).items():
        if k not in values:
            raise CompileError(f"The strategy has no parameter called '{k}'.")
        values[k] = float(v)
    return values


def size_spec(sizing: Sizing, params: dict[str, float]) -> SizeSpec:
    return SizeSpec(sizing.kind, resolve_num(sizing.value, params))


def stop_rule(spec: StopSpec | None, params: dict[str, float]) -> StopRule | None:
    if spec is None:
        return None
    return StopRule(spec.kind, resolve_num(spec.value, params), spec.atr_period)


def scale_rule(spec: ScaleOutSpec | None, params: dict[str, float]) -> ScaleOut | None:
    if spec is None:
        return None
    num = resolve_num
    steps = [(s.kind, num(s.value, params), num(s.sell_pct, params)) for s in spec.steps]
    return make_scale_out(steps, spec.breakeven)


def compile_definition(
    defn: AnyDefinition, overrides: Mapping[str, float] | None = None
) -> Program:
    params = parameter_values(defn, overrides)
    size = size_spec(defn.sizing, params)
    if isinstance(defn, KairosDefinition):
        from backend.kairos.brain import compile_brain

        brain, warmup = compile_brain(defn, params)
        return Program(brain.on_bar, params, size, warmup=warmup, kind="kairos", brain=brain)
    if isinstance(defn, RankingDefinition):
        from backend.strategy.ranking import Ranker

        ranker = Ranker(defn.ranking)
        return Program(
            ranker.on_bar,
            params,
            size,
            warmup=ranker.warmup,
            kind="ranking",
            brain=ranker,
            bind=ranker.bind,
        )
    if isinstance(defn, CombinedDefinition):
        from backend.strategy.combined import Combiner
        from backend.strategy.validator import parse_member

        members = [(m.name, compile_definition(parse_member(m.definition))) for m in defn.members]
        combiner = Combiner(members, defn.combine.mode, defn.combine.min_votes, defn.combine.window)
        return Program(combiner.on_bar, params, size, combiner.warmup, "combined")
    if isinstance(defn, CodeDefinition):
        from backend.strategy.sandbox import compile_strategy

        code = compile_strategy(defn.code)
        return Program(code.on_bar, params, size, warmup=250, kind="code", source_code=defn.code)
    return Program(_visual(defn, params), params, size, warmup=_warmup(defn, params), kind="visual")


# ---------------------------------------------------------------- visual


def _operand(o: Operand, params: dict[str, float]) -> OperandFn:
    if isinstance(o, NumberOperand):
        value = resolve_num(o.value, params)
        return lambda ctx: value
    times = resolve_num(o.times, params)
    offset = o.offset
    chart = o.chart
    if isinstance(o, PriceOperand):
        name = o.field

        def price(ctx: StrategyContext) -> SeriesView:
            v = ctx.price(name, chart)
            if offset:
                v = v.shift(offset)
            return v.times(times) if times != 1.0 else v

        return price
    assert isinstance(o, IndicatorOperand)
    ind = catalog.get(o.name)
    p = catalog.resolve_params(ind, {k: resolve_num(v, params) for k, v in o.params.items()})
    source = o.source if ind.uses_source else None
    output = o.output

    def indicator(ctx: StrategyContext) -> SeriesView:
        v = ctx._line(o.name, p, source, output, chart)
        if offset:
            v = v.shift(offset)
        return v.times(times) if times != 1.0 else v

    return indicator


_COMPARE: dict[str, Callable[[StrategyContext, Any, Any], bool]] = {
    "above": lambda ctx, a, b: ctx.above(a, b),
    "below": lambda ctx, a, b: ctx.below(a, b),
    "at_least": lambda ctx, a, b: ctx.at_least(a, b),
    "at_most": lambda ctx, a, b: ctx.at_most(a, b),
    "crosses_above": lambda ctx, a, b: ctx.crosses_above(a, b),
    "crosses_below": lambda ctx, a, b: ctx.crosses_below(a, b),
}


def _condition(c: Condition, params: dict[str, float]) -> CondFn:
    if isinstance(c, Compare):
        left, right, op = _operand(c.left, params), _operand(c.right, params), _COMPARE[c.op]
        return lambda ctx: op(ctx, left(ctx), right(ctx))
    if isinstance(c, Between):
        x, lo, hi = (_operand(o, params) for o in (c.value, c.lower, c.upper))
        return lambda ctx: ctx.between(x(ctx), lo(ctx), hi(ctx))
    if isinstance(c, AllOf):
        parts = [_condition(s, params) for s in c.conditions]
        return lambda ctx: all(f(ctx) for f in parts)
    if isinstance(c, AnyOf):
        parts = [_condition(s, params) for s in c.conditions]
        return lambda ctx: any(f(ctx) for f in parts)
    if isinstance(c, NotOf):
        inner = _condition(c.condition, params)
        return lambda ctx: not inner(ctx)
    if isinstance(c, TimeWindow):
        after, before = c.after, c.before
        return lambda ctx: ctx.time_between(after, before)
    assert isinstance(c, PositionCheck)
    value = resolve_num(c.value, params)
    if c.check == "bars_held_at_least":
        return lambda ctx: ctx.position is not None and ctx.position.bars_held >= value
    if c.check == "profit_pct_at_least":
        return lambda ctx: ctx.position is not None and ctx.position.profit_pct >= value
    return lambda ctx: ctx.position is not None and -ctx.position.profit_pct >= value


def _visual(d: VisualDefinition, params: dict[str, float]) -> OnBar:
    """The evaluation order is part of the contract (codegen.py mirrors it exactly):
    flat → long entry first, then short entry; in a trade → signal exit, then the time
    limit, then the exit time."""
    enter_long = _condition(d.entry.long, params) if d.entry.long else None
    enter_short = _condition(d.entry.short, params) if d.entry.short else None
    exit_long = _condition(d.exit.long, params) if d.exit.long else None
    exit_short = _condition(d.exit.short, params) if d.exit.short else None
    size = size_spec(d.sizing, params)
    sl = stop_rule(d.exit.stop_loss, params)
    tp = stop_rule(d.exit.take_profit, params)
    tr = stop_rule(d.exit.trailing_stop, params)
    so = scale_rule(d.exit.scale_out, params)
    max_bars = int(resolve_num(d.exit.max_bars, params)) if d.exit.max_bars is not None else None
    exit_time = d.exit.exit_time

    def on_bar(ctx: StrategyContext) -> None:
        pos = ctx.position
        if pos is None:
            if enter_long is not None and enter_long(ctx):
                ctx.buy(size, sl, tp, tr, LABEL_BUY, so)
            elif enter_short is not None and enter_short(ctx):
                ctx.short(size, sl, tp, tr, LABEL_SHORT, so)
            return
        rule = exit_long if pos.side == "long" else exit_short
        if rule is not None and rule(ctx):
            ctx.sell_all(LABEL_SELL if pos.side == "long" else LABEL_COVER)
        elif max_bars is not None and pos.bars_held >= max_bars:
            ctx.sell_all(LABEL_TIME_LIMIT, "time")
        elif exit_time is not None and ctx.clock >= exit_time:
            ctx.sell_all(LABEL_EXIT_TIME, "time")

    return on_bar


def _warmup(d: VisualDefinition, params: dict[str, float]) -> int:
    """Candles of history the rules need (longest indicator + largest offset + 1)."""
    best = 2
    conds = [c for c in (d.entry.long, d.entry.short, d.exit.long, d.exit.short) if c]
    for c in conds:
        for o in iter_operands(c):
            chart = getattr(o, "chart", None)
            per = mtf.candles_per(chart, d.timeframe) if chart else 1
            if isinstance(o, IndicatorOperand):
                ind = catalog.get(o.name)
                p = catalog.resolve_params(
                    ind, {k: resolve_num(v, params) for k, v in o.params.items()}
                )
                best = max(best, (ind.warmup(p) + o.offset + 2) * per)
            elif isinstance(o, PriceOperand):
                best = max(best, (o.offset + 3) * per if chart else o.offset + 2)
    for spec in (d.exit.stop_loss, d.exit.take_profit, d.exit.trailing_stop):
        if spec is not None and spec.kind == "atr":
            best = max(best, 3 * spec.atr_period + 1)
    return best
