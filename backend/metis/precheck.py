"""Catch ideas that can't work before they cost a backtest, and tell Metis why (D-142).

On the laptop's first full day Metis kept 0 of ~1,180 ideas (PROGRESS 22.4). Many failed for
reasons visible without any backtest: a condition that is never true on these stocks (ADX
"at least 80"), always true (so it changes nothing), or compares things on different scales
(a squeeze's on/off flag against the price). Each such idea used to run a full backtest and
come back as "didn't hold up" with no hint of the real reason, so the model kept making it.

Here each simple condition (one indicator or price against a number or price, on the
strategy's own chart) is evaluated over the **study years only** of a few of the strategy's
stocks. The share of candles where it is true decides: under 1% on every stock means never
true; over 99% on every stock means always true. A cross ("crosses above") is true on few
candles by nature, so it is "never true" only when it didn't happen once on any stock. The
reason carries the indicator's real range (5th to 95th percentile), so the next round's
notebook teaches the scale.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.core.types import Market, Timeframe
from backend.indicators import catalog
from backend.indicators.series import BarSeries, from_bars
from backend.strategy.definition import (
    AllOf,
    Compare,
    Condition,
    IndicatorOperand,
    NumberOperand,
    Operand,
    PriceOperand,
    resolve_num,
)
from backend.strategy.words import condition_text

NEVER = 0.01
ALWAYS = 0.99
MAX_STOCKS = 4
MIN_CANDLES = 30
F64 = np.ndarray


@dataclass
class Reach:
    """How often one condition was true over the study years, per stock."""

    text: str
    shares: list[float]
    low: float | None = None  # the indicator's 5th percentile
    high: float | None = None  # and 95th
    event: bool = False  # a cross: true on few candles by nature

    @property
    def never(self) -> bool:
        if not self.shares:
            return False
        # a cross is rare by design: only "not once on any stock" means it can't work
        return max(self.shares) == 0.0 if self.event else max(self.shares) < NEVER

    @property
    def always(self) -> bool:
        return bool(self.shares) and not self.event and min(self.shares) > ALWAYS

    def problem(self) -> str | None:
        rng = ""
        if self.low is not None and self.high is not None:
            rng = (
                f" On these stocks in the study years it was mostly between {_fmt(self.low)} "
                f"and {_fmt(self.high)}."
            )
        if self.never:
            return f"“{self.text}” was never true, so it would block every trade.{rng}"
        if self.always:
            return f"“{self.text}” was always true, so it changes nothing.{rng}"
        return None


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.3g}"


def leaves(rule: Condition | None) -> Iterator[Compare]:
    """The compares that must all be true: the rule itself or the members of a top-level
    "all of". Compares inside "any of" or "not" can be rare on purpose."""
    if rule is None:
        return
    if isinstance(rule, Compare):
        yield rule
    elif isinstance(rule, AllOf):
        for c in rule.conditions:
            yield from leaves(c)


def _checkable(c: Compare) -> bool:
    ops = (c.left, c.right)
    if any(getattr(o, "chart", None) for o in ops):
        return False  # bigger charts are read by the engine; left to the backtest
    return isinstance(c.left, IndicatorOperand | PriceOperand) and isinstance(
        c.right, NumberOperand | PriceOperand | IndicatorOperand
    )


def _values(o: Operand, s: BarSeries, params: dict[str, float]) -> tuple[F64, bool]:
    """(values, is_an_indicator)."""
    n = len(s.ts)
    if isinstance(o, NumberOperand):
        return np.full(n, resolve_num(o.value, params)), False
    times = resolve_num(o.times, params)
    if isinstance(o, PriceOperand):
        v = s.field(o.field)
        ind = False
    else:
        assert isinstance(o, IndicatorOperand)
        p = {k: resolve_num(x, params) for k, x in o.params.items()}
        out = catalog.compute(o.name, s, p, o.source)
        v = out[o.output] if o.output else next(iter(out.values()))
        ind = True
    v = np.asarray(v, dtype=np.float64)
    if o.offset:
        v = np.concatenate([np.full(o.offset, np.nan), v[: -o.offset]])
    return v * times, ind


def _truth(op: str, a: F64, b: F64) -> F64:
    with np.errstate(invalid="ignore"):
        if op == "above":
            return a > b
        if op == "below":
            return a < b
        if op == "at_least":
            return a >= b
        if op == "at_most":
            return a <= b
        prev_a, prev_b = np.roll(a, 1), np.roll(b, 1)
        if op == "crosses_above":
            t = (a > b) & (prev_a <= prev_b)
        else:
            t = (a < b) & (prev_a >= prev_b)
        t[0] = False
        return t


def reach(
    c: Compare, series: Sequence[tuple[BarSeries, int, int]], params: dict[str, float]
) -> Reach | None:
    """``series``: (bars, study start, study end) per stock. None when it can't be checked."""
    if not _checkable(c):
        return None
    shares: list[float] = []
    seen: list[F64] = []
    for s, lo, hi in series:
        try:
            a, a_ind = _values(c.left, s, params)
            b, _b_ind = _values(c.right, s, params)
        except (KeyError, ValueError, IndexError):
            return None  # unknown names are the validator's job
        window = (s.ts >= lo) & (s.ts < hi) & np.isfinite(a) & np.isfinite(b)
        if int(window.sum()) < MIN_CANDLES:
            continue
        t = _truth(c.op, a, b)[window]
        shares.append(float(np.mean(t)))
        if a_ind:
            seen.append(a[window])
    if not shares:
        return None
    r = Reach(
        text=condition_text(c.model_dump(mode="json")),
        shares=shares,
        event=c.op in ("crosses_above", "crosses_below"),
    )
    if seen:
        allv = np.concatenate(seen)
        r.low, r.high = float(np.percentile(allv, 5)), float(np.percentile(allv, 95))
    return r


def load(
    cache: Any,
    instruments: Sequence[Any],
    timeframe: Timeframe,
    market: Market,
    start_ms: int,
    split_ms: int,
    warm_ms: int,
) -> list[tuple[BarSeries, int, int]]:
    """The study years of up to ``MAX_STOCKS`` stocks (adjusted prices, with warm-up)."""
    out = []
    for inst in list(instruments)[:MAX_STOCKS]:
        bars = cache.bars(inst, timeframe, start_ms - warm_ms, split_ms, adjusted_prices=True)
        if len(bars) >= MIN_CANDLES:
            out.append((from_bars(bars, timeframe, market), start_ms, split_ms))
    return out


def problems(
    compares: Sequence[Compare],
    series: Sequence[tuple[BarSeries, int, int]],
    params: dict[str, float],
) -> list[str]:
    """Plain reasons, one per condition that can't work."""
    out = []
    for c in compares:
        r = reach(c, series, params)
        p = r.problem() if r else None
        if p:
            out.append(p)
    return out
