"""Trendlines and channels (KAIROS §3).

A support trendline joins two or more swing lows with no candle *closing* clearly below it
in between (wicks may poke through: 0.3 × ATR of slack). A resistance line joins swing
highs. More touches, a longer span and a recent last touch make a line more reliable. A
line the price has just closed through is reported as *broken*: one of the classic signals
that a trend is ending.

Lines are straight in candle-index space, which is how traders draw them on a chart with
gaps for weekends and holidays.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Literal

import numpy as np

from backend.analysis.swings import Swing
from backend.indicators.series import F64

LineKind = Literal["support", "resistance"]
SLACK = 0.3  # × ATR a close may stray beyond the line before it counts as a break
TOUCH = 0.35  # × ATR: a swing this close to the line touches it
CANDIDATES = 8  # most recent swings tried on each side
RECENT_BREAK = 10  # candles: a break this recent is still worth showing


@dataclass(frozen=True)
class TrendLine:
    kind: LineKind
    i1: int
    p1: float
    i2: int
    p2: float
    slope: float  # price per candle
    touches: int
    score: float
    broken_at: int | None  # candle whose close broke the line (after i2)

    def value_at(self, i: float) -> float:
        return self.p1 + self.slope * (i - self.i1)

    @property
    def direction(self) -> Literal["rising", "falling", "flat"]:
        return "rising" if self.slope > 0 else "falling" if self.slope < 0 else "flat"


def _fit(
    kind: LineKind, a: Swing, b: Swing, close: F64, atr: F64, last: int, pts: list[Swing]
) -> TrendLine | None:
    slope = (b.price - a.price) / (b.index - a.index)
    idx = np.arange(a.index, last + 1)
    line = a.price + slope * (idx - a.index)
    tol = SLACK * atr[a.index : last + 1]
    seg = close[a.index : last + 1]
    bad = seg < line - tol if kind == "support" else seg > line + tol
    broken_at: int | None = None
    if bad.any():
        first = int(a.index + np.argmax(bad))
        if first <= b.index:
            return None  # broken before it was even drawn
        broken_at = first
    touches = 0
    for s in pts:
        if s.index < a.index or (broken_at is not None and s.index >= broken_at):
            continue
        if abs(s.price - (a.price + slope * (s.index - a.index))) <= TOUCH * atr[s.index]:
            touches += 1
    touches = max(touches, 2)
    span = b.index - a.index
    recency = 1.0 - min(1.0, (last - b.index) / 120.0)
    score = 30.0 * touches + 20.0 * min(1.0, span / 60.0) + 20.0 * recency
    if broken_at is not None:
        score -= 25.0
    return TrendLine(kind, a.index, a.price, b.index, b.price, slope, touches, score, broken_at)


def find_lines(
    swings: list[Swing], close: F64, atr: F64, last: int, min_gap: int = 5
) -> list[TrendLine]:
    """The best support and resistance lines (active ones, plus one recently broken line
    per side), strongest first."""
    out: list[TrendLine] = []
    kinds: tuple[LineKind, ...] = ("support", "resistance")
    for kind in kinds:
        pts = [s for s in swings if (s.kind == "L") == (kind == "support") and s.index <= last]
        recent = pts[-CANDIDATES:]
        lines: list[TrendLine] = []
        for a, b in combinations(recent, 2):
            if b.index - a.index < min_gap:
                continue
            ln = _fit(kind, a, b, close, atr, last, pts)
            if ln is not None:
                lines.append(ln)
        active = sorted((ln for ln in lines if ln.broken_at is None), key=lambda x: -x.score)
        broken = sorted(
            (
                ln
                for ln in lines
                if ln.broken_at is not None and last - ln.broken_at <= RECENT_BREAK
            ),
            key=lambda x: -x.score,
        )
        out += _distinct(active, atr, last)[:2] + broken[:1]
    return sorted(out, key=lambda x: -x.score)


def _distinct(lines: list[TrendLine], atr: F64, last: int) -> list[TrendLine]:
    """Drop near-copies: lines ending within 0.5 × ATR of a better line today."""
    keep: list[TrendLine] = []
    a = float(atr[last])
    for ln in lines:
        if all(abs(ln.value_at(last) - k.value_at(last)) > 0.5 * a for k in keep):
            keep.append(ln)
    return keep


@dataclass(frozen=True)
class Channel:
    kind: Literal["rising", "falling", "sideways"]
    support: TrendLine
    resistance: TrendLine


def find_channel(lines: list[TrendLine], atr_now: float) -> Channel | None:
    """Two active lines that run roughly parallel form a channel."""
    sup = next((ln for ln in lines if ln.kind == "support" and ln.broken_at is None), None)
    res = next((ln for ln in lines if ln.kind == "resistance" and ln.broken_at is None), None)
    if sup is None or res is None or atr_now <= 0:
        return None
    span = max(sup.i2, res.i2) - min(sup.i1, res.i1)
    if span <= 0 or abs(sup.slope - res.slope) * span > 1.0 * atr_now:
        return None
    mean = (sup.slope + res.slope) / 2.0
    if abs(mean) * span < 1.0 * atr_now:
        kind: Literal["rising", "falling", "sideways"] = "sideways"
    else:
        kind = "rising" if mean > 0 else "falling"
    return Channel(kind, sup, res)
