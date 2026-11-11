"""Portfolio maths for the allocator (docs/PORTFOLIO.md §4, D-84).

- ``ledoit_wolf``: shrink the sample covariance towards a scaled identity (Ledoit and Wolf,
  2004, "A well-conditioned estimator for large-dimensional covariance matrices"). Sample
  covariances from a few years of returns are noisy; shrinking makes weights steadier.
- ``inverse_vol``: weights ∝ 1 ÷ volatility.
- ``erc``: equal risk contribution (risk parity; Maillard, Roncalli and Teïletche, 2010),
  solved by cyclical coordinate descent (Griveau-Billion, Richard and Roncalli, 2013).
- ``hrp``: hierarchical risk parity (López de Prado, 2016): cluster by correlation distance
  √(½(1 − ρ)) with single linkage, order the assets so similar ones sit together, then split
  the money top-down between halves in inverse proportion to each half's variance.
- ``cap``: limit each weight, handing the excess to the others in proportion.
"""

from __future__ import annotations

import math

import numpy as np

from backend.quant.stats import DAYS


def ledoit_wolf(x: np.ndarray) -> tuple[np.ndarray, float]:
    """(shrunk covariance, shrinkage intensity δ in [0, 1]) of a T × N matrix of returns."""
    x = np.asarray(x, dtype=float)
    t, n = x.shape
    xc = x - x.mean(axis=0)
    s = xc.T @ xc / t
    mu = float(np.trace(s)) / n
    target = mu * np.eye(n)
    d2 = float(((s - target) ** 2).sum()) / n
    b_bar = 0.0
    for row in xc:
        outer = np.outer(row, row)
        b_bar += float(((outer - s) ** 2).sum()) / n
    b_bar /= t * t
    b2 = min(b_bar, d2)
    delta = b2 / d2 if d2 > 0 else 1.0
    return delta * target + (1 - delta) * s, delta


def correlation(cov: np.ndarray) -> np.ndarray:
    sd = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    c: np.ndarray = np.clip(cov / np.outer(sd, sd), -1.0, 1.0)
    return c


def inverse_vol(cov: np.ndarray) -> np.ndarray:
    v = 1.0 / np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    return v / v.sum()


def risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Each weight's share of the portfolio's variance (they add up to 1)."""
    total = float(w @ cov @ w)
    return (w * (cov @ w)) / total if total > 0 else np.zeros_like(w)


def erc(cov: np.ndarray, iters: int = 500, tol: float = 1e-12) -> np.ndarray:
    n = cov.shape[0]
    b = np.full(n, 1.0 / n)
    x = inverse_vol(cov).copy()
    for _ in range(iters):
        old = x.copy()
        for i in range(n):
            c = float(cov[i] @ x - cov[i, i] * x[i])
            a = float(cov[i, i])
            x[i] = (-c + math.sqrt(c * c + 4 * a * b[i])) / (2 * a)
        if float(np.abs(x - old).max()) < tol:
            break
    out: np.ndarray = x / x.sum()
    return out


def _single_linkage_order(dist: np.ndarray) -> list[int]:
    """Leaves in dendrogram order: clusters merged closest first, each kept contiguous."""
    clusters: list[list[int]] = [[i] for i in range(dist.shape[0])]
    while len(clusters) > 1:
        best = (math.inf, 0, 1)
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                d = min(dist[i, j] for i in clusters[a] for j in clusters[b])
                if d < best[0] - 1e-15:
                    best = (d, a, b)
        _d, a, b = best
        merged = clusters[a] + clusters[b]
        clusters = [c for k, c in enumerate(clusters) if k not in (a, b)]
        clusters.insert(min(a, b), merged)
    return clusters[0]


def _cluster_var(cov: np.ndarray, items: list[int]) -> float:
    sub = cov[np.ix_(items, items)]
    w = inverse_vol(sub)
    return float(w @ sub @ w)


def hrp(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    dist = np.sqrt(np.clip(0.5 * (1.0 - correlation(cov)), 0.0, None))
    order = _single_linkage_order(dist)
    w = np.ones(n)
    stack = [order]
    while stack:
        items = stack.pop()
        if len(items) < 2:
            continue
        half = len(items) // 2
        left, right = items[:half], items[half:]
        vl, vr = _cluster_var(cov, left), _cluster_var(cov, right)
        alpha = 1.0 - vl / (vl + vr) if vl + vr > 0 else 0.5
        w[left] *= alpha
        w[right] *= 1.0 - alpha
        stack += [left, right]
    return w / w.sum()


def cap(w: np.ndarray, limit: float) -> np.ndarray:
    """Weights no larger than ``limit``; the excess goes to the others in proportion. When
    every weight is capped the total is below 1 (the rest stays in cash)."""
    out = np.asarray(w, dtype=float).copy()
    for _ in range(len(out) + 1):
        over = out > limit + 1e-12
        if not over.any():
            break
        excess = float((out[over] - limit).sum())
        out[over] = limit
        free = ~over & (out < limit - 1e-12)
        if not free.any():
            break
        out[free] += excess * out[free] / out[free].sum()
    return out


def volatility(w: np.ndarray, cov: np.ndarray, periods: int = DAYS) -> float:
    return math.sqrt(max(float(w @ cov @ w), 0.0) * periods)


def diversification_ratio(w: np.ndarray, cov: np.ndarray) -> float:
    """Weighted average volatility ÷ portfolio volatility (1 = no diversification)."""
    port = math.sqrt(max(float(w @ cov @ w), 0.0))
    return float(w @ np.sqrt(np.diag(cov))) / port if port > 0 else 1.0
