"""Golden tests for the quant toolkit (METIS §11–12, PORTFOLIO §4, D-81, D-82): values worked out
by hand in the comments, plus independent checks (simulation, a second implementation)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.quant import portfolio as pf
from backend.quant import resample, series, sizing, stats

# x: mean 0.01; deviations 0.01, −0.02, 0.02, −0.01, 0 → Σd² = 0.001, sd = √(0.001/4) = 0.0158114
# SR = 0.632456; m2 = 0.0002, m3 = 0 → skew 0; m4 = 3.4e-7/5 = 6.8e-8 → kurtosis 1.7
X = [0.02, -0.01, 0.03, 0.0, 0.01]


def test_moments_by_hand() -> None:
    mean, sd, skew, kurt = stats.moments([1, 2, 3, 4])
    assert mean == 2.5 and sd == pytest.approx(math.sqrt(5 / 3))
    assert skew == pytest.approx(0.0) and kurt == pytest.approx(2.5625 / 1.5625)
    mean, sd, skew, kurt = stats.moments(X)
    assert sd == pytest.approx(0.0158114, abs=1e-7) and kurt == pytest.approx(1.7)
    assert stats.sharpe_per_period(X) == pytest.approx(0.632456, abs=1e-6)
    assert stats.sharpe(X, 252) == pytest.approx(0.632456 * math.sqrt(252), abs=1e-5)


def test_probabilistic_sharpe_by_hand() -> None:
    # denominator = 1 − 0·SR + (1.7 − 1)/4 · SR² = 1 + 0.175 · 0.4 = 1.07
    # z = 0.632456 · √4 / √1.07 = 1.222835 → Φ(z) = 0.889297
    assert stats.psr(X) == pytest.approx(0.889297, abs=1e-5)
    assert stats.psr(X, stats.sharpe_per_period(X)) == pytest.approx(0.5)
    assert stats.psr(X, 0.1) < stats.psr(X)  # a higher bar is harder to clear
    # deflating for one try changes nothing
    assert stats.dsr(X, 1) == pytest.approx(stats.psr(X))


def test_expected_best_of_many_lucky_tries() -> None:
    # N = 1000, var 1: Φ⁻¹(0.999) = 3.090232, Φ⁻¹(1 − 1/(1000e)) = 3.375683
    # 0.4227843 · 3.090232 + 0.5772157 · 3.375683 = 1.306510 + 1.948496 = 3.255006
    assert stats.expected_max_sharpe(1000, 1.0) == pytest.approx(3.2550, abs=1e-3)
    assert stats.expected_max_sharpe(1, 1.0) == 0.0
    assert stats.expected_max_sharpe(20, 1.0) < stats.expected_max_sharpe(200, 1.0)
    # an independent check: the mean of the largest of 1000 standard normals (≈ 3.24)
    rng = np.random.default_rng(1)
    sim = float(rng.standard_normal((2000, 1000)).max(axis=1).mean())
    assert abs(sim - stats.expected_max_sharpe(1000, 1.0)) < 0.05


def test_deflated_sharpe_needs_more_with_more_tries() -> None:
    rng = np.random.default_rng(3)
    good = rng.normal(0.001, 0.01, 750)  # a modest edge over three years
    assert stats.dsr(good, 1) > stats.dsr(good, 10) > stats.dsr(good, 500)
    # luck alone: the best of 50 random strategies looks good but deflates to a coin flip or less
    tries = rng.normal(0.0, 0.01, (50, 750))
    best = tries[np.argmax(tries.mean(axis=1) / tries.std(axis=1))]
    assert stats.psr(best) > 0.9 and stats.dsr(best, 50) < 0.75


def test_minimum_track_record_by_hand() -> None:
    # 1 + 1.07 · (1.644854 / 0.632456)² = 1 + 1.07 · 6.763921 = 8.237395
    assert stats.min_track_record(X) == pytest.approx(8.2374, abs=1e-3)
    assert math.isinf(stats.min_track_record([0.01, -0.02, 0.0, -0.01]))


def test_daily_returns_take_each_days_last_value() -> None:
    day = 86_400_000
    pts = [(0, 100.0), (3_600_000, 104.0), (day, 110.0), (2 * day, 99.0)]
    out = stats.daily_returns(pts, "UTC")
    assert out == pytest.approx([110 / 104 - 1, 99 / 110 - 1])
    assert len(stats.daily_returns(pts, "UTC", lo=day)) == 1


def test_trade_order_monte_carlo_by_hand() -> None:
    # +10, −5, −5 on 100: history 100 → 110 → 105 → 100 falls 9.09% from its peak.
    # The orders: (−5, −5, +10) falls 10%; (−5, +10, −5) 5%; (+10, −5, −5) 9.09%; each 1/3.
    out = resample.trade_order([10, -5, -5], 100.0, n=3000, seed=2)
    assert out["history"] == pytest.approx(9.091, abs=1e-3)
    assert out["worst"] == pytest.approx(10.0) and out["p95"] == pytest.approx(10.0)
    assert out["p50"] == pytest.approx(9.091, abs=1e-3)
    assert out["losing_streak_p95"] == 2


def test_bootstrap_is_repeatable_and_ordered() -> None:
    rng = np.random.default_rng(4)
    x = rng.normal(0.0005, 0.01, 500)
    a = resample.bootstrap_sharpe(x, n_boot=200, seed=9)
    b = resample.bootstrap_sharpe(x, n_boot=200, seed=9)
    assert a == b and a["p5"] <= a["p50"] <= a["p95"]
    assert a["p5"] < stats.sharpe(x) < a["p95"]


# ---------------------------------------------------------------- how series behave


def _ar(phi: float, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    e = rng.normal(0, 0.01, n)
    r = np.zeros(n)
    for t in range(1, n):
        r[t] = phi * r[t - 1] + e[t]
    return r


def test_variance_ratio_and_autocorrelation() -> None:
    # for q = 2, VR ≈ 1 + ρ₁; an AR(1) with φ = −0.5 has ρ₁ = −0.5
    r = _ar(-0.5, 20_000, 5)
    vr, z = series.variance_ratio(r, 2)
    assert vr == pytest.approx(0.5, abs=0.05) and z < -10
    assert series.autocorr(r, 1) == pytest.approx(-0.5, abs=0.05)
    rw = np.random.default_rng(6).normal(0, 0.01, 20_000)
    assert series.variance_ratio(rw, 5)[0] == pytest.approx(1.0, abs=0.05)


def test_hurst_and_character() -> None:
    walk = 100 * np.exp(np.cumsum(np.random.default_rng(7).normal(0, 0.01, 5000)))
    trend = 100 * np.exp(np.cumsum(_ar(0.5, 5000, 8)))
    rng = np.random.default_rng(9)
    y = np.zeros(5000)
    for t in range(1, 5000):
        y[t] = 0.9 * y[t - 1] + rng.normal(0, 0.01)
    revert = 100 * np.exp(y)
    assert series.hurst(walk) == pytest.approx(0.5, abs=0.06)
    assert series.hurst(trend) > 0.55 and series.hurst(revert) < 0.45
    assert series.character(trend)["label"] == "trending"
    assert series.character(revert)["label"] == "mean-reverting"
    # half-life of y_t = 0.9 y_{t−1} + e: −ln 2 / ln 0.9 = 6.579 candles
    assert series.half_life(y) == pytest.approx(6.579, rel=0.2)
    assert math.isinf(series.half_life(np.cumsum(np.ones(50))))


def test_volatility_estimators() -> None:
    r = np.full(500, 0.01)
    assert series.ewma_vol(r) == pytest.approx(0.01 * math.sqrt(252), rel=1e-6)
    # Parkinson: ln(H/L)² / (4 ln 2), here ln(1.02)² / 2.7726 per day
    hl = math.log(1.02) ** 2 / (4 * math.log(2))
    assert series.parkinson_vol([102] * 10, [100] * 10) == pytest.approx(math.sqrt(hl * 252))


# ---------------------------------------------------------------- portfolio maths


def test_ledoit_wolf_against_a_second_implementation() -> None:
    rng = np.random.default_rng(10)
    x = rng.normal(0, 0.01, (60, 4)) + rng.normal(0, 0.01, (60, 1))
    cov, delta = pf.ledoit_wolf(x)
    t, n = x.shape
    xc = x - x.mean(axis=0)
    s = sum(np.outer(r, r) for r in xc) / t
    mu = np.trace(s) / n
    d2 = np.linalg.norm(s - mu * np.eye(n), "fro") ** 2 / n
    b2 = min(sum(np.linalg.norm(np.outer(r, r) - s, "fro") ** 2 / n for r in xc) / t**2, d2)
    assert delta == pytest.approx(b2 / d2) and 0 <= delta <= 1
    assert cov == pytest.approx(delta * mu * np.eye(n) + (1 - delta) * s)


def test_inverse_vol_and_risk_parity_by_hand() -> None:
    cov = np.diag([0.01, 0.04])  # volatilities 0.1 and 0.2, uncorrelated
    assert pf.inverse_vol(cov) == pytest.approx([2 / 3, 1 / 3])
    assert pf.erc(cov) == pytest.approx([2 / 3, 1 / 3], abs=1e-9)
    c3 = np.array([[0.04, 0.006, 0.0], [0.006, 0.01, 0.002], [0.0, 0.002, 0.0225]])
    w = pf.erc(c3)
    assert pf.risk_contributions(w, c3) == pytest.approx([1 / 3] * 3, abs=1e-8)


def test_hierarchical_risk_parity_by_hand() -> None:
    # Two pairs, correlation 0.8 inside each and 0 across; volatilities 0.1, 0.1, 0.2, 0.2.
    # Variance of each half with its inverse-volatility weights (½, ½):
    #   left ¼(0.01 + 0.01 + 2·0.8·0.01) = 0.009; right ¼(0.04 + 0.04 + 2·0.8·0.04) = 0.036
    # α = 1 − 0.009 / 0.045 = 0.8 → [0.4, 0.4, 0.1, 0.1]
    vols = np.array([0.1, 0.1, 0.2, 0.2])
    corr = np.array([[1, 0.8, 0, 0], [0.8, 1, 0, 0], [0, 0, 1, 0.8], [0, 0, 0.8, 1]])
    cov = corr * np.outer(vols, vols)
    assert pf.hrp(cov) == pytest.approx([0.4, 0.4, 0.1, 0.1])
    # shuffled inputs give the same weights per asset (clustering finds the pairs)
    order = [2, 0, 3, 1]
    assert pf.hrp(cov[np.ix_(order, order)]) == pytest.approx([0.1, 0.4, 0.1, 0.4])


def test_caps_hand_the_excess_on() -> None:
    # 0.6 → 0.4 gives 0.2 to (0.3, 0.1) as 0.15 / 0.05; 0.45 → 0.4 gives 0.05 to the last
    assert pf.cap(np.array([0.6, 0.3, 0.1]), 0.4) == pytest.approx([0.4, 0.4, 0.2])
    assert pf.cap(np.array([0.5, 0.5]), 0.3) == pytest.approx([0.3, 0.3])  # the rest is cash


def test_volatility_and_diversification() -> None:
    cov = np.diag([0.0001, 0.0001])
    w = np.array([0.5, 0.5])
    assert pf.volatility(w, cov) == pytest.approx(math.sqrt(0.00005 * 252))
    assert pf.diversification_ratio(w, cov) == pytest.approx(math.sqrt(2))


def test_sizing_by_hand() -> None:
    assert sizing.kelly(0.01, 0.04) == pytest.approx(0.25)
    assert sizing.kelly_from_trades(0.55, 1.0) == pytest.approx(0.10)
    assert sizing.vol_target(0.30, 0.15) == pytest.approx(0.5)
    assert sizing.vol_target(0.05, 0.15) == 1.0
