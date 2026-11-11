"""How much a Sharpe ratio can be trusted (METIS §12, D-82).

- ``sharpe``: mean ÷ standard deviation, annualised (× √periods a year).
- ``psr``: the probabilistic Sharpe ratio (Bailey and López de Prado, 2012): the probability
  that the true Sharpe ratio is above a bar, given how many returns there are and how skewed
  and fat-tailed they are. Uses the per-period Sharpe ratio SR:
  PSR = Φ((SR − SR*) √(n − 1) ÷ √(1 − skew·SR + (kurtosis − 1)/4 · SR²)).
- ``expected_max_sharpe``: the best Sharpe ratio N tries would show by luck alone, when the
  tries' Sharpe ratios vary by ``var``: √var · ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))),
  γ ≈ 0.5772 (the Euler–Mascheroni constant).
- ``dsr``: the deflated Sharpe ratio (Bailey and López de Prado, 2014): PSR against that best
  lucky Sharpe. Under "nothing works" a per-period Sharpe estimate from n returns varies by
  about 1/n, which is the default variance.
- ``min_track_record``: how many returns are needed before PSR reaches ``prob``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.core.clock import ms_to_dt

EULER = 0.5772156649015329
NORMAL = NormalDist()
DAYS = 252


def _arr(x: Sequence[float] | np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[np.isfinite(a)]


def moments(x: Sequence[float] | np.ndarray) -> tuple[float, float, float, float]:
    """(mean, standard deviation (n − 1), skewness, kurtosis (normal = 3))."""
    a = _arr(x)
    n = len(a)
    if n < 2:
        return (float(a.mean()) if n else 0.0, 0.0, 0.0, 3.0)
    mean = float(a.mean())
    sd = float(a.std(ddof=1))
    m2 = float(((a - mean) ** 2).mean())
    if m2 <= 0:
        return mean, sd, 0.0, 3.0
    skew = float(((a - mean) ** 3).mean()) / m2**1.5
    kurt = float(((a - mean) ** 4).mean()) / m2**2
    return mean, sd, skew, kurt


def sharpe_per_period(x: Sequence[float] | np.ndarray) -> float:
    mean, sd, _s, _k = moments(x)
    return mean / sd if sd > 0 else 0.0


def sharpe(x: Sequence[float] | np.ndarray, periods: int = DAYS) -> float:
    """Annualised Sharpe ratio (no risk-free rate: Agora compares strategies with each other)."""
    return sharpe_per_period(x) * math.sqrt(periods)


def _denominator(sr: float, skew: float, kurt: float) -> float:
    return max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr, 1e-12)


def psr(x: Sequence[float] | np.ndarray, sr_star: float = 0.0) -> float:
    """Probability that the true per-period Sharpe ratio exceeds ``sr_star``."""
    a = _arr(x)
    n = len(a)
    if n < 3:
        return 0.5 if sr_star == 0 else 0.0
    _m, sd, skew, kurt = moments(a)
    if sd <= 0:
        return 0.5
    sr = float(a.mean()) / sd
    z = (sr - sr_star) * math.sqrt(n - 1) / math.sqrt(_denominator(sr, skew, kurt))
    return NORMAL.cdf(z)


def expected_max_sharpe(n_trials: int, var: float) -> float:
    """The best per-period Sharpe ratio expected from ``n_trials`` lucky tries."""
    if n_trials <= 1 or var <= 0:
        return 0.0
    a = NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    b = NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var) * ((1.0 - EULER) * a + EULER * b)


def dsr(x: Sequence[float] | np.ndarray, n_trials: int, var: float | None = None) -> float:
    """Deflated Sharpe ratio: PSR against the best Sharpe ratio of ``n_trials`` lucky tries."""
    a = _arr(x)
    if len(a) < 3:
        return 0.0
    v = var if var is not None else 1.0 / len(a)
    return psr(a, expected_max_sharpe(n_trials, v))


def min_track_record(
    x: Sequence[float] | np.ndarray, sr_star: float = 0.0, prob: float = 0.95
) -> float:
    """Returns needed for PSR ≥ ``prob`` at the observed Sharpe ratio (∞ when it isn't above
    the bar)."""
    _m, sd, skew, kurt = moments(x)
    if sd <= 0:
        return math.inf
    sr = _m / sd
    if sr <= sr_star:
        return math.inf
    z = NORMAL.inv_cdf(prob)
    return 1.0 + _denominator(sr, skew, kurt) * (z / (sr - sr_star)) ** 2


def daily_points(
    points: Sequence[Any], tz: str | ZoneInfo, *, lo: int = 0, hi: int = 2**62
) -> list[tuple[str, float]]:
    """(local day, the day's last equity) for points with ``ts`` in [lo, hi), oldest first.
    Accepts EquityPoint-like objects or (ts, equity) pairs."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    by_day: dict[str, float] = {}
    for p in points:
        ts, eq = (p.ts, p.equity) if hasattr(p, "ts") else (p[0], p[1])
        if lo <= ts < hi:
            by_day[ms_to_dt(ts, zone).strftime("%Y-%m-%d")] = float(eq)
    return sorted(by_day.items())


def returns_of(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Period-to-period returns of a value series (0 where the previous value isn't positive)."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return np.array([], dtype=float)
    prev = v[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(prev > 0, v[1:] / prev - 1.0, 0.0)
    return np.asarray(out, dtype=float)


def daily_returns(
    points: Sequence[Any], tz: str | ZoneInfo, *, lo: int = 0, hi: int = 2**62
) -> np.ndarray:
    """Day-to-day returns of an equity curve (the last value of each local day)."""
    return returns_of([v for _d, v in daily_points(points, tz, lo=lo, hi=hi)])


def describe(
    x: Sequence[float] | np.ndarray, n_trials: int = 1, periods: int = DAYS
) -> dict[str, Any]:
    """The numbers a senior quant reads first, rounded for people."""
    a = _arr(x)
    _mean, sd, skew, kurt = moments(a)
    mtr = min_track_record(a)
    return {
        "days": len(a),
        "sharpe": round(sharpe(a, periods), 3),
        "volatility": round(sd * math.sqrt(periods), 4),
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "psr": round(psr(a), 4),
        "dsr": round(dsr(a, n_trials), 4),
        "trials": n_trials,
        "min_track_record_days": None if math.isinf(mtr) else round(mtr),
    }
