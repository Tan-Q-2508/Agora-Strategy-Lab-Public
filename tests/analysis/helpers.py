"""Hand-built price series for the analyst's tests."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

import numpy as np

from backend.indicators.series import BarSeries, from_arrays


def path(points: Sequence[tuple[int, float]], spread: float = 0.5) -> BarSeries:
    """Closes walking straight between waypoints ``(candle, price)``; each candle's high
    and low are ``spread`` above and below its close, and it opens at the previous close."""
    xs: list[float] = []
    for (x0, y0), (x1, y1) in pairwise(points):
        for x in range(x0, x1):
            xs.append(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    xs.append(points[-1][1])
    c = np.array(xs)
    o = np.concatenate([[c[0]], c[:-1]])
    return from_arrays(
        c,
        open_=o,
        high=np.maximum(o, c) + spread,
        low=np.minimum(o, c) - spread,
        volume=np.full(len(c), 1000.0),
    )


def candles(rows: Sequence[tuple[float, float, float, float]]) -> BarSeries:
    """Explicit (open, high, low, close) rows."""
    o, h, lo, c = (np.array(col, dtype=np.float64) for col in zip(*rows, strict=True))
    return from_arrays(c, open_=o, high=h, low=lo, volume=np.full(len(c), 1000.0))


def falling(n: int = 15, start: float = 120.0) -> list[tuple[float, float, float, float]]:
    """Steady down candles: each opens where the last closed and loses 1 (range 2)."""
    rows = []
    for k in range(n):
        o = start - k
        rows.append((o, o + 0.5, o - 1.5, o - 1))
    return rows


def rising(n: int = 15, start: float = 100.0) -> list[tuple[float, float, float, float]]:
    rows = []
    for k in range(n):
        o = start + k
        rows.append((o, o + 1.5, o - 0.5, o + 1))
    return rows
