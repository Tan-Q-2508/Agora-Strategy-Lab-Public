"""Check a Strategy Definition and explain every problem in plain English.

Each issue names *where* it is in words the builder shows ("Buy rule › condition 2 ›
right side"), *what* is wrong, and a one-line *hint* to fix it (SPEC §5.2: incomplete
blocks glow amber with a fix hint). Errors block saving and backtesting; warnings don't.

The same validator checks the AI helper's drafts (AI_ASSISTANT §5.4), so its messages are
also what the model gets back when it has to try again.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

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
    Definition,
    ExitRules,
    IndicatorOperand,
    KairosDefinition,
    NotOf,
    NumberOperand,
    Operand,
    PositionCheck,
    PriceOperand,
    RankingDefinition,
    StopSpec,
    TimeWindow,
    VisualDefinition,
    param_ref,
)

Severity = Literal["error", "warning"]
TAGS = {
    "compare",
    "between",
    "all",
    "any",
    "not",
    "time",
    "position",
    "price",
    "indicator",
    "number",
    "visual",
    "code",
    "kairos",
}
SESSION = {"IN": ("09:15", "15:30"), "US": ("09:30", "16:00")}
MAX_CONDITIONS = 60
MAX_DEPTH = 6

_adapter: TypeAdapter[AnyDefinition] = TypeAdapter(Definition)


def parse_member(raw: dict[str, Any]) -> AnyDefinition:
    """A combined strategy's member, saved as plain JSON inside it (D-227)."""
    return _adapter.validate_python(raw)


@dataclass(frozen=True)
class Issue:
    path: tuple[str | int, ...]
    where: str
    message: str
    hint: str
    severity: Severity = "error"

    def public(self) -> dict[str, Any]:
        return {
            "path": list(self.path),
            "where": self.where,
            "message": self.message,
            "hint": self.hint,
            "severity": self.severity,
        }

    def sentence(self) -> str:
        return f"{self.where}: {self.message} {self.hint}".strip()


@dataclass
class Result:
    definition: AnyDefinition | None
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.definition is not None and not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]


# ---------------------------------------------------------------- naming

_NAMES: dict[tuple[str, ...], str] = {
    ("entry", "long"): "Buy rule",
    ("entry", "short"): "Short-sell rule",
    ("exit", "long"): "Sell rule",
    ("exit", "short"): "Buy-back rule",
    ("exit", "stop_loss"): "Stop-loss",
    ("exit", "take_profit"): "Take-profit",
    ("exit", "trailing_stop"): "Trailing stop",
    ("exit", "scale_out"): "Partial exits",
    ("exit", "max_bars"): "Time limit",
    ("exit", "exit_time"): "Exit time",
}
_WORDS = {
    "left": "left side",
    "right": "right side",
    "value": "value",
    "lower": "lower limit",
    "upper": "upper limit",
    "condition": "inner condition",
    "sizing": "Position size",
    "limits": "Limits",
    "universe": "Stocks",
    "timeframe": "Timeframe",
    "product": "Trade type",
    "market": "Market",
    "code": "Code",
    "kairos": "Kairos settings",
    "entry_score": "entry score",
    "exit_score": "exit score",
    "stop_atr": "stop",
    "target_r": "target",
    "trail_atr": "trailing stop",
    "weights": "Signal weights",
    "params": "settings",
    "kind": "kind",
    "steps": "step",
    "sell_pct": "share sold",
}


def describe(path: Iterable[str | int]) -> str:
    parts = [p for p in path if not (isinstance(p, str) and p in TAGS)]
    words: list[str] = []
    i = 0
    while i < len(parts):
        p = parts[i]
        pair = tuple(str(x) for x in parts[i : i + 2])
        if pair in _NAMES:
            words.append(_NAMES[pair])
            i += 2
            continue
        if p == "conditions" and i + 1 < len(parts) and isinstance(parts[i + 1], int):
            words.append(f"condition {int(parts[i + 1]) + 1}")
            i += 2
            continue
        if p == "parameters" and i + 1 < len(parts) and isinstance(parts[i + 1], int):
            words.append(f"parameter {int(parts[i + 1]) + 1}")
            i += 2
            continue
        if isinstance(p, int):
            words.append(f"item {p + 1}")
        else:
            words.append(_WORDS.get(p, p.replace("_", " ")))
        i += 1
    if not words:
        return "Strategy"
    words[0] = words[0][:1].upper() + words[0][1:]
    return " › ".join(words)


def _clean(loc: tuple[Any, ...]) -> tuple[str | int, ...]:
    return tuple(p for p in loc if not (isinstance(p, str) and p in TAGS))


def _from_pydantic(err: dict[str, Any]) -> Issue:
    loc = _clean(tuple(err.get("loc", ())))
    typ = err.get("type", "")
    ctx = err.get("ctx") or {}
    msg, hint = err.get("msg", "is not valid"), "Check this value."
    if typ == "missing":
        msg, hint = "is missing.", "Fill it in."
    elif typ == "extra_forbidden":
        msg, hint = "isn't something Agora understands.", "Remove it."
    elif typ == "literal_error":
        msg, hint = f"must be one of: {ctx.get('expected', '')}.", "Pick one of the listed options."
    elif typ.startswith("union_tag"):
        msg, hint = "has an unknown type.", "Choose a block from the list."
    elif typ == "string_pattern_mismatch":
        pattern = str(ctx.get("pattern", ""))
        if "[0-5]" in pattern:
            msg, hint = "must be a time like 15:15.", "Use 24-hour HH:MM."
        else:
            msg, hint = (
                "uses characters that aren't allowed.",
                "Use lowercase letters, digits and _.",
            )
    elif typ in ("greater_than_equal", "greater_than"):
        msg, hint = f"must be at least {ctx.get('ge', ctx.get('gt'))}.", "Use a larger value."
    elif typ in ("less_than_equal", "less_than"):
        msg, hint = f"must be at most {ctx.get('le', ctx.get('lt'))}.", "Use a smaller value."
    elif typ == "too_short":
        msg, hint = "is empty.", "Add at least one condition."
    elif typ == "too_long":
        msg, hint = "has too many items.", "Remove some."
    elif typ in ("float_parsing", "float_type", "int_parsing", "int_type", "int_from_float"):
        msg, hint = "must be a number.", "Type a number."
    elif typ == "string_too_short":
        msg, hint = "is empty.", "Fill it in."
    elif typ == "model_type":
        msg, hint = "is in the wrong format.", "Rebuild this block."
    return Issue(loc, describe(loc), msg, hint)


# ---------------------------------------------------------------- semantic checks


class _Checker:
    def __init__(self, d: AnyDefinition, known: Callable[[str], bool] | None):
        self.d = d
        self.known = known
        self.issues: list[Issue] = []
        self.params = {p.name: p for p in d.parameters}
        self.count = 0

    def add(
        self, path: tuple[str | int, ...], message: str, hint: str, severity: Severity = "error"
    ) -> None:
        self.issues.append(Issue(path, describe(path), message, hint, severity))

    # -- numbers and parameter references

    def num(
        self,
        value: Any,
        path: tuple[str | int, ...],
        *,
        lo: float | None = None,
        hi: float | None = None,
        integer: bool = False,
        what: str = "This",
    ) -> float | None:
        name = param_ref(value)
        if name is not None:
            p = self.params.get(name)
            if p is None:
                self.add(
                    path,
                    f"uses the parameter '{name}', which doesn't exist.",
                    "Add it under Parameters or type a number.",
                )
                return None
            if integer and p.type != "int":
                self.add(
                    path,
                    f"needs a whole number, but '{name}' is a decimal parameter.",
                    "Make the parameter whole-number.",
                )
            for bound in (p.min, p.max, p.default):
                self._range(bound, path, lo, hi, what, f"parameter '{name}'")
            return float(p.default)
        if isinstance(value, str):
            self.add(path, f"“{value}” isn't a number.", "Type a number, or $name for a parameter.")
            return None
        v = float(value)
        if integer and v != int(v):
            self.add(path, "must be a whole number.", "Remove the decimals.")
        self._range(v, path, lo, hi, what, "it")
        return v

    def _range(
        self,
        v: float,
        path: tuple[str | int, ...],
        lo: float | None,
        hi: float | None,
        what: str,
        subject: str,
    ) -> None:
        if lo is not None and v < lo:
            self.add(
                path,
                f"{what} can't be below {lo:g} ({subject} allows {v:g}).",
                f"Use {lo:g} or more.",
            )
        if hi is not None and v > hi:
            self.add(
                path,
                f"{what} can't be above {hi:g} ({subject} allows {v:g}).",
                f"Use {hi:g} or less.",
            )

    # -- whole definition

    def run(self) -> None:
        d = self.d
        self.settings()
        if isinstance(d, VisualDefinition):
            self.visual(d)
        elif isinstance(d, KairosDefinition):
            self.kairos(d)
        elif isinstance(d, RankingDefinition):
            self.ranking(d)
        elif isinstance(d, CombinedDefinition):
            self.combined(d)
        else:
            self.code(d)

    def settings(self) -> None:
        d = self.d
        names: set[str] = set()
        for i, p in enumerate(d.parameters):
            path: tuple[str | int, ...] = ("parameters", i)
            if p.name in names:
                self.add(
                    path, f"the name '{p.name}' is used twice.", "Give each parameter its own name."
                )
            names.add(p.name)
            if p.min >= p.max:
                self.add(
                    path,
                    "its smallest value must be below its largest.",
                    "Swap or fix min and max.",
                )
            elif not p.min <= p.default <= p.max:
                self.add(
                    path, "its default is outside its range.", "Pick a default between min and max."
                )
            if p.type == "int" and any(v != int(v) for v in (p.min, p.max, p.default)):
                self.add(
                    path,
                    "is whole-number but has decimals.",
                    "Use whole numbers, or switch it to decimal.",
                )
        if d.market == "IN" and d.product == "cash":
            self.add(
                ("product",), "“cash” is for US stocks.", "For India choose Intraday or Delivery."
            )
        if d.market == "US" and d.product != "cash":
            self.add(("product",), "US stocks use the “cash” trade type.", "Choose Cash.")
        if d.universe.kind == "symbols":
            if not d.universe.symbols:
                self.add(
                    ("universe",),
                    "no stocks are chosen.",
                    "Pick at least one stock, or choose all.",
                )
            seen: set[str] = set()
            for i, sym in enumerate(d.universe.symbols):
                if sym.upper() in seen:
                    self.add(
                        ("universe", "symbols", i),
                        f"{sym} is listed twice.",
                        "Remove the duplicate.",
                        "warning",
                    )
                seen.add(sym.upper())
                if self.known is not None and not self.known(sym):
                    self.add(
                        ("universe", "symbols", i),
                        f"Agora doesn't know the stock {sym}.",
                        "Pick it from the list.",
                    )
        s = d.sizing
        if s.kind == "percent_equity":
            self.num(
                s.value,
                ("sizing", "value"),
                lo=0.01,
                hi=100,
                what="The share of your money per trade",
            )
        elif s.kind == "fixed_qty":
            self.num(
                s.value,
                ("sizing", "value"),
                lo=1,
                hi=1e9,
                integer=True,
                what="The number of shares",
            )
        elif s.kind == "fixed_amount":
            self.num(s.value, ("sizing", "value"), lo=1, hi=1e12, what="The amount per trade")
        else:
            self.num(s.value, ("sizing", "value"), lo=0.01, hi=10, what="The risk per trade (%)")

    def combined(self, d: CombinedDefinition) -> None:
        for m in d.members:  # each member was a checked strategy; a damaged one fails here
            parse_member(m.definition)

    def visual(self, d: VisualDefinition) -> None:
        if d.entry.long is None and d.entry.short is None:
            self.add(("entry",), "there's no rule for when to enter a trade.", "Add a Buy rule.")
        if d.entry.short is not None and d.product == "delivery":
            self.add(
                ("entry", "short"),
                "short-selling isn't allowed for India delivery trades.",
                "Switch the trade type to Intraday, or remove the short rule.",
            )
        for side in ("long", "short"):
            cond = getattr(d.entry, side)
            if cond is not None:
                self.condition(cond, ("entry", side), 1, in_exit=False)
            cond = getattr(d.exit, side)
            if cond is not None:
                self.condition(cond, ("exit", side), 1, in_exit=True)
                if getattr(d.entry, side) is None:
                    self.add(
                        ("exit", side),
                        "there's an exit rule but no matching entry rule.",
                        "Remove it, or add the entry.",
                        "warning",
                    )
        ex = d.exit
        for name in ("stop_loss", "take_profit", "trailing_stop"):
            spec = getattr(ex, name)
            if spec is not None:
                self.stop(spec, ("exit", name))
        if ex.scale_out is not None:
            self.scale_out(ex)
        if ex.max_bars is not None:
            self.num(
                ex.max_bars,
                ("exit", "max_bars"),
                lo=1,
                hi=100_000,
                integer=True,
                what="The time limit",
            )
        if ex.exit_time is not None:
            if d.timeframe == "1d":
                self.add(
                    ("exit", "exit_time"),
                    "needs intraday candles.",
                    "Pick a minute or hourly timeframe, or remove it.",
                )
            else:
                self.in_session(ex.exit_time, ("exit", "exit_time"))
        if d.sizing.kind == "risk_percent" and ex.stop_loss is None:
            self.add(
                ("sizing",),
                "risk-based sizing needs a stop-loss to measure the risk.",
                "Add a stop-loss, or pick another sizing.",
            )
        has_exit = any(
            getattr(ex, n) is not None
            for n in (
                "long",
                "short",
                "stop_loss",
                "take_profit",
                "trailing_stop",
                "scale_out",
                "max_bars",
                "exit_time",
            )
        )
        if not has_exit and d.product != "intraday":
            self.add(
                ("exit",),
                "there's no way out of a trade.",
                "Add a sell rule, a stop-loss or a time limit.",
                "warning",
            )
        if self.count > MAX_CONDITIONS:
            self.add(
                (),
                f"has {self.count} conditions; the limit is {MAX_CONDITIONS}.",
                "Simplify the rules.",
            )

    def kairos(self, d: KairosDefinition) -> None:
        k = d.kairos
        path: tuple[str | int, ...] = ("kairos",)
        self.num(k.entry_score, (*path, "entry_score"), lo=10, hi=90, what="The entry score")
        self.num(k.exit_score, (*path, "exit_score"), lo=0, hi=90, what="The exit score")
        self.num(k.stop_atr, (*path, "stop_atr"), lo=0.5, hi=10, what="The stop distance")
        self.num(k.target_r, (*path, "target_r"), lo=0.5, hi=10, what="The target")
        if k.trail_atr is not None:
            self.num(k.trail_atr, (*path, "trail_atr"), lo=0.5, hi=10, what="The trailing stop")
        if k.partial_r is not None:
            self.num(k.partial_r, (*path, "partial_r"), lo=0.3, hi=5, what="The partial exit")
            self.num(k.partial_pct, (*path, "partial_pct"), lo=10, hi=90, what="The share sold")
        if k.max_bars is not None:
            self.num(
                k.max_bars,
                (*path, "max_bars"),
                lo=1,
                hi=100_000,
                integer=True,
                what="The time limit",
            )
        for name, w in d.weights.items():
            if not 0 <= w <= 2:
                self.add(
                    ("weights", name),
                    "signal weights go from 0 to 2.",
                    "Retrain Kairos to refresh them.",
                )
                break

    def ranking(self, d: RankingDefinition) -> None:
        r = d.ranking
        if r.rank_by == "momentum" and r.skip_months >= r.lookback_months:
            self.add(
                ("ranking", "skip_months"),
                "the months left out must be fewer than the months ranked on.",
                f"Use fewer than {r.lookback_months}.",
            )
        if d.universe.kind == "symbols" and 0 < len(d.universe.symbols) <= r.hold:
            self.add(
                ("ranking", "hold"),
                f"it holds {r.hold} stocks but can only choose from "
                f"{len(d.universe.symbols)}, so there is nothing to rank.",
                "Hold fewer stocks or rank more of them (the whole index is best).",
            )
        if d.product == "intraday":
            self.add(
                ("product",),
                "a ranking holds its stocks for a month, so it can't be intraday.",
                "Use delivery (India) or cash (US).",
            )

    def code(self, d: CodeDefinition) -> None:
        from backend.strategy.sandbox import SandboxError, compile_strategy

        try:
            compile_strategy(d.code)
        except SandboxError as exc:
            self.issues.append(
                Issue(
                    ("code", exc.line) if exc.line else ("code",),
                    f"Code, line {exc.line}" if exc.line else "Code",
                    exc.message,
                    exc.hint,
                )
            )

    def stop(self, spec: StopSpec, path: tuple[str | int, ...]) -> None:
        if spec.kind == "percent":
            self.num(spec.value, (*path, "value"), lo=0.01, hi=99, what="The percentage")
        else:
            self.num(spec.value, (*path, "value"), lo=0.1, hi=20, what="The ATR multiple")

    def scale_out(self, ex: ExitRules) -> None:
        """Partial exits (D-125): sensible distances, and something left to run."""
        assert ex.scale_out is not None
        path: tuple[str | int, ...] = ("exit", "scale_out")
        total = 0.0
        for n, step in enumerate(ex.scale_out.steps):
            where = (*path, "steps", n)
            hi = {"r": 10, "percent": 50, "atr": 10}[step.kind]
            self.num(step.value, (*where, "value"), lo=0.1, hi=hi, what="The partial-exit distance")
            self.num(step.sell_pct, (*where, "sell_pct"), lo=1, hi=99, what="The share sold")
            if isinstance(step.sell_pct, int | float):
                total += float(step.sell_pct)
            if step.kind == "r" and ex.stop_loss is None:
                self.add(
                    (*where, "kind"),
                    "is measured in R (the stop distance), but there's no stop-loss.",
                    "Add a stop-loss, or measure it in percent or ATR.",
                )
        if total >= 100:
            self.add(
                path,
                f"sells {total:g}% of the position; something must stay for the rest of the move.",
                "Sell less than 100% in partial exits (for example 50%, or two thirds).",
            )

    def in_session(self, hhmm: str, path: tuple[str | int, ...]) -> None:
        start, end = SESSION[self.d.market]
        if not start < hhmm <= end:
            self.add(
                path,
                f"{hhmm} is outside market hours ({start}–{end}).",
                "Pick a time during the session.",
            )

    # -- conditions

    def condition(
        self, c: Condition, path: tuple[str | int, ...], depth: int, *, in_exit: bool
    ) -> None:
        self.count += 1
        if depth > MAX_DEPTH:
            self.add(path, "is nested too deeply.", "Flatten the AND/OR groups.")
            return
        if isinstance(c, AllOf | AnyOf):
            for i, sub in enumerate(c.conditions):
                self.condition(sub, (*path, "conditions", i), depth + 1, in_exit=in_exit)
            if len(c.conditions) == 1:
                self.add(
                    path,
                    "is a group with a single condition.",
                    "That's fine, but the group isn't needed.",
                    "warning",
                )
        elif isinstance(c, NotOf):
            self.condition(c.condition, (*path, "condition"), depth + 1, in_exit=in_exit)
        elif isinstance(c, Compare):
            left = self.operand(c.left, (*path, "left"))
            right = self.operand(c.right, (*path, "right"))
            if left == "number" and right == "number":
                sev: Severity = "error" if c.op.startswith("crosses") else "warning"
                self.add(
                    path,
                    "compares two fixed numbers, so it never changes.",
                    "Compare a price or an indicator.",
                    sev,
                )
            elif left != "number" and c.left.model_dump() == c.right.model_dump():
                # "%B at least %B" is always true and "above itself" never: a strategy Metis
                # saved bought on 2,641 candles of 2,641 with such a rule (D-161)
                self.add(
                    path,
                    "compares a value with itself, so it is always the same.",
                    "Compare it with a number, the price or another indicator.",
                )
        elif isinstance(c, Between):
            kinds = [
                self.operand(o, (*path, n))
                for o, n in ((c.value, "value"), (c.lower, "lower"), (c.upper, "upper"))
            ]
            if kinds[0] == "number":
                self.add(
                    (*path, "value"),
                    "is a fixed number.",
                    "Use a price or an indicator.",
                    "warning",
                )
        elif isinstance(c, TimeWindow):
            if self.d.timeframe == "1d":
                self.add(
                    path,
                    "time-of-day rules need intraday candles.",
                    "Pick a minute or hourly timeframe.",
                )
            if c.after is None and c.before is None:
                self.add(path, "has no times set.", "Set “after”, “before”, or both.")
            if c.after and c.before and c.after >= c.before:
                self.add(path, "“after” must be earlier than “before”.", "Swap the two times.")
        elif isinstance(c, PositionCheck):
            if not in_exit:
                self.add(
                    path,
                    "checks the open trade, but entry rules run when there is none.",
                    "Move it to an exit rule.",
                )
            if c.check == "bars_held_at_least":
                self.num(
                    c.value,
                    (*path, "value"),
                    lo=1,
                    hi=100_000,
                    integer=True,
                    what="The number of candles",
                )
            else:
                self.num(c.value, (*path, "value"), lo=0.01, hi=1000, what="The percentage")

    def operand(self, o: Operand, path: tuple[str | int, ...]) -> str:
        if isinstance(o, NumberOperand):
            self.num(o.value, (*path, "value"), what="The number")
            return "number"
        self.num(o.times, (*path, "times"), lo=0.0001, hi=1000, what="The multiplier")
        if o.chart is not None and not mtf.allowed(self.d.timeframe, o.chart):
            options = ", ".join(mtf.LABEL[t] for t in mtf.BIGGER.get(self.d.timeframe, ()))
            self.add(
                (*path, "chart"),
                f"A {mtf.LABEL[self.d.timeframe]} strategy can't read the "
                f"{mtf.LABEL[o.chart]} chart.",
                f"Pick a bigger chart: {options}." if options else "Remove the chart choice.",
            )
        if isinstance(o, PriceOperand):
            return "price"
        assert isinstance(o, IndicatorOperand)
        try:
            ind = catalog.get(o.name)
        except catalog.UnknownIndicator:
            self.add(
                (*path, "name"),
                f"“{o.name}” isn't an indicator Agora has.",
                "Pick one from the indicator list.",
            )
            return "indicator"
        resolved: dict[str, float] = {}
        for key, value in o.params.items():
            spec = next((p for p in ind.params if p.name == key), None)
            if spec is None:
                self.add(
                    (*path, "params", key),
                    f"{ind.label} has no setting called “{key}”.",
                    "Remove it.",
                )
                continue
            v = self.num(
                value,
                (*path, "params", key),
                lo=spec.min,
                hi=spec.max,
                integer=spec.integer,
                what=spec.label,
            )
            if v is not None:
                resolved[key] = v
        if o.output is not None and o.output not in {k for k, _ in ind.outputs}:
            names = ", ".join(k for k, _ in ind.outputs)
            self.add(
                (*path, "output"),
                f"{ind.label} has no line called “{o.output}”.",
                f"Use one of: {names}.",
            )
        if o.source is not None and not ind.uses_source:
            self.add(
                (*path, "source"),
                f"{ind.label} always uses the full candle, not one price.",
                "Remove the price choice.",
                "warning",
            )
        if ind.intraday_only and (self.d.timeframe == "1d" or o.chart in ("1d", "1w", "1mo")):
            self.add(
                path,
                f"{ind.label} only works on intraday candles.",
                "Pick a minute or hourly timeframe.",
            )
        return "indicator"


# ---------------------------------------------------------------- entry points


def validate(
    raw: dict[str, Any] | AnyDefinition,
    *,
    known_symbol: Callable[[str], bool] | None = None,
) -> Result:
    """Parse and check a definition. ``known_symbol`` (from the database) checks the
    universe; omit it where the stock list isn't available."""
    if isinstance(raw, AnyDefinition):
        defn = raw
    else:
        try:
            defn = _adapter.validate_python(raw)
        except ValidationError as exc:
            issues = [_from_pydantic(dict(e)) for e in exc.errors()]
            return Result(None, _dedupe(issues))
    checker = _Checker(defn, known_symbol)
    checker.run()
    return Result(defn, _dedupe(checker.issues))


def _dedupe(issues: list[Issue]) -> list[Issue]:
    seen: set[tuple[tuple[str | int, ...], str]] = set()
    out = []
    for i in issues:
        key = (i.path, i.message)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def iter_operands(c: Condition) -> Iterator[Operand]:
    """Every operand in a condition tree (used to collect the indicators a rule needs)."""
    if isinstance(c, AllOf | AnyOf):
        for sub in c.conditions:
            yield from iter_operands(sub)
    elif isinstance(c, NotOf):
        yield from iter_operands(c.condition)
    elif isinstance(c, Compare):
        yield c.left
        yield c.right
    elif isinstance(c, Between):
        yield c.value
        yield c.lower
        yield c.upper
