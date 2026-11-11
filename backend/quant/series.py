"""How a price series behaves: does it trend, or come back? (METIS §11)

A senior quant checks this before choosing between a trend-following and a mean-reversion
strategy for a stock:

- ``autocorr``: lag-k autocorrelation of returns (positive: moves continue; negative: they
  reverse).
- ``variance_ratio`` (Lo and MacKinlay, 1988): variance of q-day returns ÷ (q × variance of
  1-day returns), from overlapping q-day sums. About 1 for a random walk, above 1 when moves
  persist (trend), below 1 when they revert. With its z-statistic under the random-walk
  hypothesis (homoskedastic form).
- ``hurst``: the Hurst exponent from how the spread of k-day changes grows with k (it grows like
  k^H): about 0.5 random, above trending, below mean-reverting.
- ``half_life``: how many days a gap from the average takes to halve (Ornstein–Uhlenbeck fit
  of Δy on y), for mean-reverting series; infinite when it doesn't revert.
- ``ewma_vol`` (RiskMetrics, λ = 0.94) and ``parkinson_vol`` (from highs and lows).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from backend.quant.stats import DAYS


def log_returns(close: Sequence[float] | np.ndarray) -> np.ndarray:
    c = np.asarray(close, dtype=float)
    c = c[np.isfinite(c) & (c > 0)]
    return np.diff(np.log(c)) if len(c) > 1 else np.array([], dtype=float)


def autocorr(x: Sequence[float] | np.ndarray, lag: int = 1) -> float:
    a = np.asarray(x, dtype=float)
    if len(a) <= lag + 2:
        return 0.0
    a = a - a.mean()
    den = float((a * a).sum())
    return float((a[lag:] * a[:-lag]).sum()) / den if den > 0 else 0.0


def variance_ratio(returns: Sequence[float] | np.ndarray, q: int = 5) -> tuple[float, float]:
    """(VR(q), z) from overlapping q-period sums of one-period (log) returns."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < q * 4 or q < 2:
        return 1.0, 0.0
    mu = r.mean()
    var1 = float(((r - mu) ** 2).sum()) / (n - 1)
    sums = np.convolve(r, np.ones(q), mode="valid")
    # Lo and MacKinlay's unbiased overlapping estimator; dividing by m (which holds q) already
    # turns the q-period variance into a one-period one
    m = q * (n - q + 1) * (1 - q / n)
    varq = float(((sums - q * mu) ** 2).sum()) / m
    if var1 <= 0:
        return 1.0, 0.0
    vr = varq / var1
    se = math.sqrt(2 * (2 * q - 1) * (q - 1) / (3 * q * n))
    return vr, (vr - 1.0) / se


def hurst(close: Sequence[float] | np.ndarray, max_lag: int = 40) -> float:
    """Hurst exponent: slope of log(spread of k-day log changes) against log(k)."""
    y = np.log(np.asarray(close, dtype=float))
    y = y[np.isfinite(y)]
    lags = [k for k in range(2, max_lag + 1) if len(y) > k * 4]
    if len(lags) < 3:
        return 0.5
    spread = [float(np.std(y[k:] - y[:-k])) for k in lags]
    keep = [(math.log(k), math.log(s)) for k, s in zip(lags, spread, strict=True) if s > 0]
    if len(keep) < 3:
        return 0.5
    xs, ys = np.array([a for a, _ in keep]), np.array([b for _, b in keep])
    slope = float(np.polyfit(xs, ys, 1)[0])
    return slope


def half_life(series: Sequence[float] | np.ndarray) -> float:
    """Candles for a gap from the mean to halve (∞ if the series doesn't revert)."""
    y = np.asarray(series, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 10:
        return math.inf
    dy = np.diff(y)
    lag = y[:-1]
    x = np.vstack([lag, np.ones_like(lag)]).T
    b = float(np.linalg.lstsq(x, dy, rcond=None)[0][0])
    if b > -1e-9:
        return math.inf  # no pull back to the average
    if b <= -1:
        return 0.0
    return -math.log(2) / math.log(1 + b)


def ewma_vol(
    returns: Sequence[float] | np.ndarray, lam: float = 0.94, periods: int = DAYS
) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) == 0:
        return 0.0
    var = float(r[: min(20, len(r))].var()) if len(r) > 1 else float(r[0] ** 2)
    for v in r:
        var = lam * var + (1 - lam) * float(v) ** 2
    return math.sqrt(var * periods)


def parkinson_vol(
    high: Sequence[float] | np.ndarray, low: Sequence[float] | np.ndarray, periods: int = DAYS
) -> float:
    h, lo = np.asarray(high, dtype=float), np.asarray(low, dtype=float)
    ok = (h > 0) & (lo > 0) & np.isfinite(h) & np.isfinite(lo)
    if ok.sum() < 2:
        return 0.0
    hl = np.log(h[ok] / lo[ok])
    return math.sqrt(float((hl**2).mean()) / (4 * math.log(2)) * periods)


def character(close: Sequence[float] | np.ndarray) -> dict[str, Any]:
    """Trending, mean-reverting or random, from the variance ratio and the Hurst exponent."""
    r = log_returns(close)
    vr, z = variance_ratio(r, 5)
    h = hurst(close)
    ac = autocorr(r, 1)
    if vr > 1.05 and h > 0.53 and z > 1.0:
        label = "trending"
    elif vr < 0.95 and h < 0.47 and z < -1.0:
        label = "mean-reverting"
    else:
        label = "close to random"
    return {
        "label": label,
        "variance_ratio": round(vr, 3),
        "vr_z": round(z, 2),
        "hurst": round(h, 3),
        "autocorr": round(ac, 3),
        "volatility": round(float(np.std(r, ddof=1)) * math.sqrt(DAYS), 4) if len(r) > 2 else 0.0,
    }
