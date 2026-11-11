"""The probability of backtest overfitting, by combinatorially symmetric cross-validation (CSCV;
Bailey, Borwein, López de Prado and Zhu, 2017). Task 16.3, D-89 (mlfinlab, LANDSCAPE §4).

The question: when the best of many settings (a sweep's cells, Metis's tries) is picked on
past results, how likely is it that it was just the luckiest? CSCV answers it with the tries'
own returns, no model needed:

1. Put the returns of every try side by side (T days × N tries) and cut the days into S equal
   blocks in time.
2. For every way of choosing half the blocks (C(S, S/2) ways, 12,870 for S = 16): pick the try
   that did best on the chosen half ("in sample") and see where it ranks on the other half
   ("out of sample"): ω = rank ÷ (N + 1), with tied tries sharing their average rank.
3. PBO = the share of ways where the in-sample winner ranked in the bottom half out of sample
   (ω ≤ ½, i.e. logit ln(ω/(1−ω)) ≤ 0).

PBO near 0: choosing the best on past results works. Near ½: the choice is no better than a coin.
Near 1: the in-sample best tends to be among the worst afterwards (pure overfitting). Also
reported: how often the chosen try lost money out of sample, and how much worse it did out of
sample than in sample (the slope of its out-of-sample against its in-sample results).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np

Metric = Literal["sharpe", "mean"]
MAX_COMBOS = 20_000


def _blocks(n_rows: int, s: int) -> list[slice]:
    """S blocks of equal length in time (the last few rows are dropped to make them equal)."""
    size = n_rows // s
    return [slice(k * size, (k + 1) * size) for k in range(s)]


def _avg_rank(row: np.ndarray, j: int) -> float:
    """Rank of entry ``j`` in ``row`` from 1 (worst) to N (best), ties sharing the average."""
    v = row[j]
    below = float((row < v).sum())
    equal = float((row == v).sum())
    return below + (equal + 1.0) / 2.0


def pbo(
    returns: np.ndarray | Sequence[Sequence[float]],
    *,
    s: int = 16,
    metric: Metric = "sharpe",
) -> dict[str, Any]:
    """CSCV on a T × N matrix of per-period returns (rows: days, columns: tries)."""
    m = np.asarray(returns, dtype=float)
    if m.ndim != 2:
        raise ValueError("returns must be a table: one row per day, one column per try")
    t, n = m.shape
    s = int(s) - int(s) % 2
    while s > 2 and t // s < 4:
        s -= 2  # fewer, longer blocks for short histories
    if n < 2 or s < 2 or t // s < 2:
        return {"pbo": None, "tries": n, "days": t, "blocks": s, "combinations": 0}
    m = np.nan_to_num(m, nan=0.0)
    blocks = _blocks(t, s)
    size = t // s
    sums = np.array([m[b].sum(axis=0) for b in blocks])  # S × N
    squares = np.array([(m[b] ** 2).sum(axis=0) for b in blocks])
    combos = list(itertools.islice(itertools.combinations(range(s), s // 2), MAX_COMBOS))
    pick = np.zeros((len(combos), s))
    for k, c in enumerate(combos):
        pick[k, list(c)] = 1.0
    rows = size * (s // 2)

    def perf(sel: np.ndarray) -> np.ndarray:
        total, sq = sel @ sums, sel @ squares
        mean = total / rows
        if metric == "mean":
            return np.asarray(mean)
        var = np.maximum(sq - rows * mean**2, 0.0) / max(rows - 1, 1)
        sd = np.sqrt(var)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(np.where(sd > 0, mean / sd, 0.0))

    is_perf = perf(pick)  # combos × N
    oos_perf = perf(1.0 - pick)
    best = is_perf.argmax(axis=1)
    omegas = np.array([_avg_rank(oos_perf[k], int(best[k])) / (n + 1) for k in range(len(combos))])
    logits = np.log(omegas / (1.0 - omegas))
    chosen_is = is_perf[np.arange(len(combos)), best]
    chosen_oos = oos_perf[np.arange(len(combos)), best]
    slope = _slope(chosen_is, chosen_oos)
    return {
        "pbo": round(float((logits <= 0).mean()), 4),
        "tries": n,
        "days": t,
        "blocks": s,
        "combinations": len(combos),
        "median_logit": round(float(np.median(logits)), 4),
        "oos_loss": round(float((chosen_oos < 0).mean()), 4),
        "degradation": None if slope is None else round(slope, 4),
        "metric": metric,
    }


def _slope(x: np.ndarray, y: np.ndarray) -> float | None:
    """Least-squares slope of y on x (None when x doesn't vary)."""
    if len(x) < 2:
        return None
    dx = x - x.mean()
    den = float((dx * dx).sum())
    if den <= 0 or not math.isfinite(den):
        return None
    return float((dx * (y - y.mean())).sum()) / den


def aligned(series: Sequence[Sequence[tuple[str, float]]]) -> tuple[list[str], np.ndarray]:
    """Line up several (day, return) lists on the days they all have: (days, T × N matrix)."""
    if not series:
        return [], np.zeros((0, 0))
    common = set.intersection(*(set(d for d, _r in x) for x in series))
    days = sorted(common)
    cols = []
    for x in series:
        by_day = dict(x)
        cols.append([by_day[d] for d in days])
    return days, np.array(cols, dtype=float).T if days else np.zeros((0, len(series)))


def words(result: dict[str, Any], what: str = "settings") -> str:
    """One plain sentence for people."""
    p = result.get("pbo")
    if p is None:
        return f"Too few {what} or too short a history to check for overfitting."
    n = result["tries"]
    if p < 0.2:
        verdict = "picking the best on past results has worked well"
    elif p < 0.5:
        verdict = "picking the best on past results worked more often than not"
    elif p < 0.75:
        verdict = "the best on past results was no better than a coin toss afterwards"
    else:
        verdict = "the best on past results usually did badly afterwards: classic overfitting"
    return (
        f"Probability of backtest overfitting: {p * 100:.0f}% over {n} {what}. Cutting the "
        f"history into {result['blocks']} pieces and testing every half against the other, "
        f"{verdict}."
    )
