"""Forecasts: hand-checked pieces, honesty on a random walk, determinism, no look-ahead."""

from __future__ import annotations

import numpy as np
import pytest

from backend.analysis import forecast as fc
from backend.analysis.report import price
from backend.core.types import Market
from tests.golden.test_indicators import DAILY


def test_pinball_loss_hand_calculated() -> None:
    # quantiles (0.1 … 0.9) at −2, −1, 0, 1, 2; actual 0:
    # 0.1×2 = 0.2, 0.25×1 = 0.25, 0, (1−0.75)×1 = 0.25, (1−0.9)×2 = 0.2 → mean 0.9/5 = 0.18
    q = np.array([[-2.0], [-1.0], [0.0], [1.0], [2.0]])
    assert fc._pinball(q, 0.0) == pytest.approx(0.18)


def test_earned_weights_hand_calculated() -> None:
    # losses: analogues 1, volatility 2, trend 2 → raw 0.5×1, 0.4×(1/2)², 0.1×(1/2)²
    # = 0.5, 0.1, 0.025 (total 0.625) → 0.8, 0.16, 0.04
    w = fc.earned_weights({"analogues": [1.0] * 10, "volatility": [2.0] * 10, "trend": [2.0] * 10})
    assert w == pytest.approx({"analogues": 0.8, "volatility": 0.16, "trend": 0.04})
    assert fc.earned_weights({"analogues": [1.0] * 3}) == fc.DEFAULT_WEIGHTS


def test_ewma_sigma_of_constant_moves() -> None:
    assert fc.ewma_sigma(np.array([0.01, -0.01] * 100)) == pytest.approx(0.01)


def _random_walk(n: int, sigma: float, seed: int, drift: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(drift, sigma, n)))


def test_ranges_are_calibrated_on_a_random_walk() -> None:
    # On a true random walk the honest answer is "no edge, reliable ranges".
    f = fc.forecast(_random_walk(1500, 0.015, 7), 10)
    assert f.track is not None and f.track.tests >= 40
    assert 0.65 <= f.track.band80 <= 0.95
    assert 0.3 <= f.track.direction_rate <= 0.7
    q = f.quantiles[:, -1]
    assert list(q) == sorted(q)  # p10 ≤ p25 ≤ median ≤ p75 ≤ p90


def test_a_steady_trend_is_projected_forward() -> None:
    f = fc.forecast(_random_walk(600, 0.004, 3, drift=0.004), 10)
    assert f.quantiles[2, -1] > f.origin and f.up_probability > 0.6


def test_same_data_same_forecast() -> None:
    c = DAILY.close[-700:]
    a, b = fc.forecast(c, 10), fc.forecast(c, 10)
    assert np.array_equal(a.quantiles, b.quantiles) and a.track == b.track


def test_analogue_outcomes_must_be_complete_before_the_cutoff() -> None:
    # A huge jump at the very end: windows whose outcome includes it are in the future of
    # any cutoff before it and must never be used.
    r = np.zeros(200)
    r[::2] = 0.001
    r[-1] = 5.0
    lib = fc.AnalogueLibrary([r], horizon=5)
    paths = lib.paths(r[:150], 0.001, cutoff=149, horizon=5)
    assert paths is not None and np.abs(paths).max() < 1.0
    everything = lib.paths(r, 0.001, cutoff=199, horizon=5)
    assert everything is not None


def test_peers_end_on_the_same_candle() -> None:
    own, peer = np.zeros(100), np.zeros(60)
    lib = fc.AnalogueLibrary([own, peer], horizon=5)
    # the peer's last window ends 5 + 1 returns before its end, on the stock's clock
    assert lib.ends.max() == 100 - 5 - 1


def test_needs_enough_history() -> None:
    with pytest.raises(ValueError, match="at least 60 candles"):
        fc.forecast(np.linspace(100, 110, 40), 10)


def test_words_and_json() -> None:
    f = fc.forecast(DAILY.close[-700:], 10)
    words = fc.describe(f, symbol="RELIANCE", money=lambda v: price(v, Market.IN), minutes=1440)
    assert "next 10 trading days" in words["text"] and "8-in-10 range" in words["text"]
    assert words["verdict"].startswith("Tested")
    j = fc.to_json(f, list(range(10)), -1)
    assert len(j["path"]) == 11 and j["path"][0]["median"] == j["origin"]
    assert j["range80_pct"][0] < 0 < j["range80_pct"][1]
    assert "of trading" in fc._span_words(12, 5)


# ---------------------------------------------------------------- learning from misses (§17)


def test_calibration_by_hand() -> None:
    assert fc.calibrate_from([0.5] * 5) == (1.0, 0.0)  # under 8 misses: no correction
    # 20 misses of +2 half-ranges: 80% need 2× → 1 + (2 − 1)·20/40 = 1.5; lean 2·20/50 = 0.8 → 0.5
    assert fc.calibrate_from([2.0] * 20) == pytest.approx((1.5, 0.5))
    # ranges that were far too wide are narrowed (never below 0.6)
    assert fc.calibrate_from([0.0] * 80)[0] == pytest.approx(0.6)
    samples = np.array([[0.0, -1.0], [0.0, 0.0], [0.0, 1.0]])
    wide = fc._apply(samples, 2.0, 0.0)
    assert np.allclose(wide[:, -1], [-2.0, 0.0, 2.0])


def test_the_analyst_only_learns_from_finished_outcomes() -> None:
    rng = np.random.default_rng(5)
    n, h = 600, 5
    scores = rng.uniform(-100, 100, n + 1)
    r = rng.normal(0, 0.01, n)
    for t in range(n - h):  # the score leads the next five moves
        r[t : t + h] += 0.002 * scores[t] / 100
    fit = fc.AnalystFit(r, scores, h)
    assert fit.beta(500) > 0.2
    later = r.copy()
    later[400:] = 0.5  # changing what happens after candle 400 …
    assert fc.AnalystFit(later, scores, h).beta(395) == pytest.approx(fit.beta(395))
    drift, b, x = fit.drift(500)
    assert len(drift) == h and np.sign(drift[0]) == np.sign(b * x)


def test_forecast_with_the_analyst_and_memory() -> None:
    c = DAILY.close[-900:]
    scores = np.linspace(-50, 50, len(c))
    f = fc.forecast(c, 10, scores=scores)
    assert "analyst" in f.weights and f.analyst["score"] == pytest.approx(50.0)
    assert sum(f.weights.values()) == pytest.approx(1.0, abs=0.01)
    # live misses that were all far outside the range widen today's forecast
    wide = fc.forecast(c, 10, scores=scores, memory=fc.Memory(misses=(3.0,) * 40))
    assert wide.calibration.width > f.calibration.width and wide.calibration.live == 40
    assert (wide.quantiles[4, -1] - wide.quantiles[0, -1]) > (
        f.quantiles[4, -1] - f.quantiles[0, -1]
    )
    words = fc.calibration_words(wide.calibration)
    assert "widened them" in words


def test_expected_candles_follow_the_typical_path() -> None:
    s = DAILY.upto(800)
    f = fc.forecast(s.close, 10)
    assert f.typical is not None and len(f.typical) == 10
    cs = fc.expected_candles(f, s.open, s.high, s.low, s.close, list(range(10)))
    assert len(cs) == 10 and cs[0]["open"] == pytest.approx(f.origin, rel=1e-4)
    for k, x in enumerate(cs):
        assert x["close"] == pytest.approx(f.origin * float(np.exp(f.typical[k])), rel=1e-4)
        assert x["high"] >= max(x["open"], x["close"]) and x["low"] <= min(x["open"], x["close"])
        if k:
            assert x["open"] == cs[k - 1]["close"]
    # it ends near the most likely price: inside the middle half of the range
    assert f.quantiles[1, -1] <= cs[-1]["close"] <= f.quantiles[3, -1]
    # and, unlike the bare middle path, its candles have real bodies
    bodies = [abs(x["close"] / x["open"] - 1) for x in cs]
    assert max(bodies) > 0.2 * f.sigma
    # without a typical path the middle path is used
    plain = fc.expected_candles(
        fc.Forecast(
            f.horizon, f.origin, f.quantiles, f.up_probability, f.weights, {}, None, f.sigma
        ),
        s.open,
        s.high,
        s.low,
        s.close,
        list(range(10)),
    )
    assert plain[-1]["close"] == pytest.approx(float(f.quantiles[2, -1]), rel=1e-4)
