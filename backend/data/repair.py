"""Candles Yahoo served half-adjusted around a split (D-228).

Yahoo's history of a stock that split recently can mix rows already adjusted for the split with
rows that aren't, so undoing the adjustment over-corrects some of them: AMTD, before its 60-for-1
reverse split, read 0.77 for a few days and 0.0126 for others, a false −98% day each time. Such a
row is wrong by exactly the split's ratio, which is what finds it.

Within a run of candles that share a split factor, a jump of the factor (or its inverse) moves
into or out of the wrong level. The first candle after the split says which level is right: the
last candle before it, adjusted, must land near it. Only big splits are touched (3-for-1 or more,
either way): a real 50% day could otherwise pass for a 2-for-1.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from backend.core.types import Bar

MIN_RATIO = 3.0
TOLERANCE = 0.3  # how close, in log terms, a jump must be to the factor
LANDING = math.log(3.0)  # how far the adjusted price may land from the next run's first close


def fixed(bars: list[Bar]) -> list[Bar]:
    """Bars as a download should have delivered them."""
    fixes = find([b.close for b in bars], [b.split_factor for b in bars])
    if not fixes:
        return bars
    out = list(bars)
    for f in fixes:
        b, m = out[f.index], f.multiply
        out[f.index] = replace(
            b, open=b.open * m, high=b.high * m, low=b.low * m, close=b.close * m, volume=b.volume / m
        )
    return out


@dataclass(frozen=True)
class Fix:
    index: int
    multiply: float


def find(closes: Sequence[float], factors: Sequence[float]) -> list[Fix]:
    """Rows to rescale, given raw closes and split factors in time order."""
    out: list[Fix] = []
    n = len(closes)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and factors[j + 1] == factors[i]:
            j += 1
        f = factors[i]
        big = f >= MIN_RATIO or (f > 0 and f <= 1 / MIN_RATIO)
        if big and j + 1 < n and closes[j + 1] > 0 and factors[j + 1] > 0:
            out += _in_run(closes, i, j, f, closes[j + 1], factors[j + 1])
        i = j + 1
    return out


def _in_run(
    closes: Sequence[float], lo: int, hi: int, f: float, next_close: float, next_factor: float
) -> list[Fix]:
    jump = math.log(f)
    levels = [0]
    for k in range(lo + 1, hi + 1):
        if closes[k] <= 0 or closes[k - 1] <= 0:
            levels.append(levels[-1])
            continue
        step = math.log(closes[k] / closes[k - 1])
        here = levels[-1]
        if abs(step + jump) < TOLERANCE:
            here -= 1  # fell by the factor: into the over-corrected level
        elif abs(step - jump) < TOLERANCE:
            here += 1
        levels.append(here)
    if len(set(levels)) < 2:
        return []
    target = math.log(next_close * next_factor)
    last = math.log(closes[hi] * f) if closes[hi] > 0 else None
    if last is None:
        return []
    # which level, if the last candle were on it, would land on the next run's first close?
    best = min(set(levels), key=lambda v: abs(last + (v - levels[-1]) * -jump - target))
    if abs(last + (best - levels[-1]) * -jump - target) > LANDING:
        return []  # nothing lands: leave it for a person to look at
    return [
        Fix(lo + k, f ** (best - lv))
        for k, lv in enumerate(levels)
        if lv != best
    ]
