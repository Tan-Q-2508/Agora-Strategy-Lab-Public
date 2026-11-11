"""Visual strategy → readable Python for the code editor ("Open as code", SPEC §5.2).

The generated ``on_bar`` uses the same ``ctx`` helpers in the same order as the compiled
visual strategy (compiler.py ``_visual``), so the two produce identical signals; a test
checks this for every template.
"""

from __future__ import annotations

import json
import re

from backend.indicators import catalog
from backend.strategy.compiler import (
    LABEL_BUY,
    LABEL_COVER,
    LABEL_EXIT_TIME,
    LABEL_SELL,
    LABEL_SHORT,
    LABEL_TIME_LIMIT,
)
from backend.strategy.definition import (
    AllOf,
    AnyOf,
    Between,
    Compare,
    Condition,
    IndicatorOperand,
    NotOf,
    Num,
    NumberOperand,
    Operand,
    PositionCheck,
    PriceOperand,
    ScaleOutSpec,
    StopSpec,
    TimeWindow,
    VisualDefinition,
    param_ref,
)

_PRICE_ATTR = {"open", "high", "low", "close", "volume", "hl2", "typical"}


def _num(v: Num) -> str:
    name = param_ref(v)
    if name is not None:
        return f'p["{name}"]'
    f = float(v)
    return repr(int(f)) if f == int(f) and abs(f) < 1e15 else repr(f)


class _Gen:
    def __init__(self) -> None:
        self.vars: dict[str, str] = {}  # expression → variable name
        self.lines: list[str] = []

    def _var(self, expr: str, base: str) -> str:
        if expr not in self.vars:
            name = re.sub(r"[^a-z0-9_]", "_", base.lower())
            taken = set(self.vars.values())
            n, cand = 1, name
            while cand in taken:
                n += 1
                cand = f"{name}_{n}"
            self.vars[expr] = cand
            self.lines.append(f"    {cand} = {expr}")
        return self.vars[expr]

    def operand(self, o: Operand) -> str:
        if isinstance(o, NumberOperand):
            return _num(o.value)
        if isinstance(o, PriceOperand):
            base = f"ctx.{o.field}" if o.field in _PRICE_ATTR else f'ctx.price("{o.field}")'
            if o.chart:
                base = self._var(
                    f'ctx.chart("{o.chart}").price("{o.field}")', f"{o.field}_{o.chart}"
                )
        else:
            assert isinstance(o, IndicatorOperand)
            base = self._indicator(o)
        if o.offset:
            base = f"{base}.shift({o.offset})"
        if param_ref(o.times) is not None or float(o.times) != 1.0:
            base = f"{base}.times({_num(o.times)})"
        return base

    def _indicator(self, o: IndicatorOperand) -> str:
        ind = catalog.get(o.name)
        args: list[str] = []
        if ind.uses_source:
            src = o.source or ind.default_source
            args.append(f'"{src}"' if o.chart else f"ctx.{src}")
        for p in ind.params:
            if p.name in o.params:
                args.append(f"{p.name}={_num(o.params[p.name])}")
        on = f'ctx.chart("{o.chart}").ind' if o.chart else "ctx.ind"
        call = f"{on}.{o.name}({', '.join(args)})"
        if len(ind.outputs) > 1:
            call = f"{call}.{o.output or ind.outputs[0][0]}"
        label = o.name
        nums = [str(_num(o.params[p.name])) for p in ind.params if p.name in o.params]
        if nums and all(n.replace(".", "").isdigit() for n in nums):
            label += "_" + "_".join(n.replace(".", "_") for n in nums)
        if len(ind.outputs) > 1:
            label += f"_{o.output or ind.outputs[0][0]}"
        if o.chart:
            label += f"_{o.chart}"
        return self._var(call, label)

    def cond(self, c: Condition) -> str:
        if isinstance(c, Compare):
            return f"ctx.{c.op}({self.operand(c.left)}, {self.operand(c.right)})"
        if isinstance(c, Between):
            x, lo, hi = (self.operand(o) for o in (c.value, c.lower, c.upper))
            return f"ctx.between({x}, {lo}, {hi})"
        if isinstance(c, AllOf):
            return "(" + " and ".join(self.cond(s) for s in c.conditions) + ")"
        if isinstance(c, AnyOf):
            return "(" + " or ".join(self.cond(s) for s in c.conditions) + ")"
        if isinstance(c, NotOf):
            return f"(not {self.cond(c.condition)})"
        if isinstance(c, TimeWindow):
            return f"ctx.time_between({json.dumps(c.after)}, {json.dumps(c.before)})".replace(
                "null", "None"
            )
        assert isinstance(c, PositionCheck)
        v = _num(c.value)
        if c.check == "bars_held_at_least":
            return f"(position is not None and position.bars_held >= {v})"
        if c.check == "profit_pct_at_least":
            return f"(position is not None and position.profit_pct >= {v})"
        return f"(position is not None and -position.profit_pct >= {v})"


def _stop(spec: StopSpec | None) -> str:
    if spec is None:
        return "None"
    if spec.kind == "percent":
        return f"ctx.stop.percent({_num(spec.value)})"
    return f"ctx.stop.atr({_num(spec.value)}, {spec.atr_period})"


def _scale(spec: ScaleOutSpec | None) -> str:
    if spec is None:
        return "None"
    steps = ", ".join(f'("{s.kind}", {_num(s.value)}, {_num(s.sell_pct)})' for s in spec.steps)
    return f"ctx.scale_out([{steps}], breakeven={spec.breakeven})"


def to_code(d: VisualDefinition, title: str = "Strategy") -> str:
    g = _Gen()
    entry_long = g.cond(d.entry.long) if d.entry.long else None
    entry_short = g.cond(d.entry.short) if d.entry.short else None
    exit_long = g.cond(d.exit.long) if d.exit.long else None
    exit_short = g.cond(d.exit.short) if d.exit.short else None
    size = {
        "percent_equity": "ctx.size.percent_equity",
        "fixed_qty": "ctx.size.fixed_qty",
        "fixed_amount": "ctx.size.fixed_amount",
        "risk_percent": "ctx.size.risk_percent",
    }[d.sizing.kind] + f"({_num(d.sizing.value)})"
    out = [
        f'"""{title}: converted from a visual strategy.',
        "",
        "Edit freely: the visual version is kept unchanged. on_bar(ctx) runs once per",
        'closed candle for each stock. See the Agora API panel for everything ctx offers."""',
        "",
        "",
        "def on_bar(ctx):",
        "    p = ctx.params",
        "    position = ctx.position",
    ]
    out += g.lines
    out += [
        f"    size = {size}",
        f"    stop_loss = {_stop(d.exit.stop_loss)}",
        f"    take_profit = {_stop(d.exit.take_profit)}",
        f"    trailing_stop = {_stop(d.exit.trailing_stop)}",
        f"    scale_out = {_scale(d.exit.scale_out)}",
        "",
        "    if position is None:",
    ]
    branch = "if"
    if entry_long:
        out += [
            f"        {branch} {entry_long}:",
            "            ctx.buy(size, stop_loss, take_profit, trailing_stop, "
            f'"{LABEL_BUY}", scale_out)',
        ]
        branch = "elif"
    if entry_short:
        out += [
            f"        {branch} {entry_short}:",
            "            ctx.short(size, stop_loss, take_profit, trailing_stop, "
            f'"{LABEL_SHORT}", scale_out)',
        ]
    out.append("        return")
    out.append("")
    # Signal exit first, then the time limit, then the exit time (same order as compiler.py).
    long_rule, short_rule = exit_long or "False", exit_short or "False"
    out.append(f'    signal_exit = {long_rule} if position.side == "long" else {short_rule}')
    out += [
        "    if signal_exit:",
        f'        ctx.sell_all("{LABEL_SELL}" if position.side == "long" else "{LABEL_COVER}")',
    ]
    if d.exit.max_bars is not None:
        out += [
            f"    elif position.bars_held >= {_num(d.exit.max_bars)}:",
            f'        ctx.sell_all("{LABEL_TIME_LIMIT}", "time")',
        ]
    if d.exit.exit_time is not None:
        out += [
            f'    elif ctx.clock >= "{d.exit.exit_time}":',
            f'        ctx.sell_all("{LABEL_EXIT_TIME}", "time")',
        ]
    return "\n".join(out) + "\n"
