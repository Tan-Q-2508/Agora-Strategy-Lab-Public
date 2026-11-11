"""Resampling: how different could the result have been? (METIS §11, LANDSCAPE §2)

- ``bootstrap_sharpe``: a stationary block bootstrap (Politis and Romano, 1994) of daily
  returns, which keeps runs of good and bad days together, giving a range for the Sharpe ratio.
- ``trade_order``: Monte Carlo of the order of the trades: the same trades in a random order
  give the same profit but other drawdowns; the 95th percentile is a fairer "worst drop to
  expect" than the one order history happened to take.

Seeded, so results repeat exactly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from backend.quant.stats import DAYS, sharpe


def stationary_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Indices of one stationary-bootstrap resample of length ``n``."""
    out = np.empty(n, dtype=int)
    p = 1.0 / max(mean_block, 1.0)
    i = int(rng.integers(n))
    for k in range(n):
        if k > 0 and rng.random() < p:
            i = int(rng.integers(n))
        out[k] = i
        i = (i + 1) % n
    return out


def bootstrap_sharpe(
    x: Sequence[float] | np.ndarray,
    *,
    n_boot: int = 500,
    mean_block: float = 10.0,
    seed: int = 7,
    periods: int = DAYS,
) -> dict[str, float]:
    """5th, 50th and 95th percentiles of the annualised Sharpe ratio over resamples."""
    a = np.asarray(x, dtype=float)
    if len(a) < 10:
        s = sharpe(a, periods) if len(a) > 1 else 0.0
        return {"p5": s, "p50": s, "p95": s}
    rng = np.random.default_rng(seed)
    vals = np.array(
        [sharpe(a[stationary_indices(len(a), mean_block, rng)], periods) for _ in range(n_boot)]
    )
    p5, p50, p95 = np.percentile(vals, [5, 50, 95])
    return {"p5": float(p5), "p50": float(p50), "p95": float(p95)}


def max_drawdown_pct(path: np.ndarray) -> float:
    """Largest fall from a peak, as a % of the peak."""
    if len(path) == 0:
        return 0.0
    peaks = np.maximum.accumulate(path)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peaks > 0, (peaks - path) / peaks, 0.0)
    return float(dd.max() * 100.0)


def trade_order(
    pnls: Sequence[float], capital: float, *, n: int = 1000, seed: int = 7
) -> dict[str, Any]:
    """Drawdowns of the same trades in random orders (money after costs per trade)."""
    a = np.asarray(pnls, dtype=float)
    if len(a) == 0 or capital <= 0:
        return {"trades": 0, "history": 0.0, "p50": 0.0, "p95": 0.0, "worst": 0.0}
    rng = np.random.default_rng(seed)
    history = max_drawdown_pct(capital + np.concatenate([[0.0], np.cumsum(a)]))
    sims = np.empty(n)
    for k in range(n):
        order = rng.permutation(a)
        sims[k] = max_drawdown_pct(capital + np.concatenate([[0.0], np.cumsum(order)]))
    p50, p95 = np.percentile(sims, [50, 95])
    return {
        "trades": len(a),
        "history": round(history, 3),
        "p50": round(float(p50), 3),
        "p95": round(float(p95), 3),
        "worst": round(float(sims.max()), 3),
        "losing_streak_p95": _streak_p95(a, rng, n),
    }


def _streak_p95(a: np.ndarray, rng: np.random.Generator, n: int) -> int:
    streaks = []
    for _ in range(min(n, 300)):
        longest = run = 0
        for v in rng.permutation(a):
            run = run + 1 if v <= 0 else 0
            longest = max(longest, run)
        streaks.append(longest)
    return math.ceil(float(np.percentile(streaks, 95)))
