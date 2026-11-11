"""Golden tests for every indicator (D-11): hand-calculated values, with the arithmetic in
comments, plus three properties checked on the fixtures and on random data:
streaming == vectorized, no look-ahead, and warm-up length."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as hs

from backend.core.types import Timeframe
from backend.data.adjust import adjusted
from backend.fakes.data_source import FakeSource
from backend.indicators import vector as vx
from backend.indicators.catalog import INDICATORS, StreamIndicator, bar_inputs, compute
from backend.indicators.series import BarSeries, from_arrays, from_bars

N = math.nan


def same(actual: np.ndarray, expected: list[float], tol: float = 1e-9) -> None:
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected, strict=True):
        if math.isnan(e):
            assert math.isnan(a), f"expected NaN, got {a}"
        else:
            assert a == pytest.approx(e, rel=tol, abs=tol), f"{actual} != {expected}"


# ---------------------------------------------------------------- hand-calculated


def test_sma() -> None:
    # (1+2+3)/3 = 2, (2+3+4)/3 = 3, (3+4+5)/3 = 4
    same(vx.sma(np.array([1.0, 2, 3, 4, 5]), 3), [N, N, 2, 3, 4])


def test_ema_seeds_with_sma() -> None:
    # alpha = 2/(3+1) = 0.5; seed (10+11+12)/3 = 11
    # i3: 0.5×13 + 0.5×11 = 12;  i4: 0.5×12 + 0.5×12 = 12;  i5: 0.5×11 + 0.5×12 = 11.5
    same(vx.ema(np.array([10.0, 11, 12, 13, 12, 11]), 3), [N, N, 11, 12, 12, 11.5])


def test_wma() -> None:
    # i2: (1×1 + 2×2 + 3×3)/6 = 14/6;  i3: (1×2 + 2×3 + 3×4)/6 = 20/6
    same(vx.wma(np.array([1.0, 2, 3, 4]), 3), [N, N, 14 / 6, 20 / 6])


def test_rsi_wilder() -> None:
    # changes: +1, −0.5, +1, +0.5, −1
    # i3: avg gain (1+0+1)/3 = 2/3, avg loss (0+0.5+0)/3 = 1/6, RS = 4 → 100 − 100/5 = 80
    # i4: gain (2/3×2 + 0.5)/3 = 0.61111, loss (1/6×2 + 0)/3 = 0.11111, RS = 5.5 → 84.6154
    # i5: gain 0.61111×2/3 = 0.407407, loss (0.11111×2 + 1)/3 = 0.407407, RS = 1 → 50
    same(
        vx.rsi(np.array([10.0, 11, 10.5, 11.5, 12, 11]), 3),
        [N, N, N, 80, 100 - 100 / 6.5, 50],
        tol=1e-6,
    )


def test_rsi_edge_cases() -> None:
    assert vx.rsi(np.full(10, 5.0), 3)[-1] == 50  # no movement at all
    assert vx.rsi(np.arange(10, dtype=float), 3)[-1] == 100  # only gains


def test_macd() -> None:
    # data 1,3,2,5,4; fast EMA(2) alpha 2/3, slow EMA(3) alpha 1/2
    # fast: seed (1+3)/2 = 2 @i1; i2: 2/3×2 + 1/3×2 = 2; i3: 2/3×5 + 1/3×2 = 4;
    #       i4: 2/3×4 + 1/3×4 = 4
    # slow: seed (1+3+2)/3 = 2 @i2; i3: .5×5 + .5×2 = 3.5; i4: .5×4 + .5×3.5 = 3.75
    # macd: i2 0, i3 0.5, i4 0.25
    # signal EMA(2): seed (0+0.5)/2 = 0.25 @i3; i4: 2/3×.25 + 1/3×.25 = .25
    line, sig, hist = vx.macd(np.array([1.0, 3, 2, 5, 4]), 2, 3, 2)
    same(line, [N, N, 0, 0.5, 0.25])
    same(sig, [N, N, N, 0.25, 0.25])
    same(hist, [N, N, N, 0.25, 0.0])


def test_bollinger_uses_population_stdev() -> None:
    # window 1,2,3: mean 2, std = sqrt((1+0+1)/3) = 0.816497 → bands 2 ± 1.632993
    mid, up, lo = vx.bollinger(np.array([1.0, 2, 3]), 3, 2.0)
    same(mid, [N, N, 2])
    same(up, [N, N, 2 + 2 * math.sqrt(2 / 3)])
    same(lo, [N, N, 2 - 2 * math.sqrt(2 / 3)])


H = np.array([10.0, 12, 11, 15])
L = np.array([8.0, 9, 10, 12])
C = np.array([9.0, 11, 10.5, 14])


def test_true_range_and_atr() -> None:
    # TR0 = 10−8 = 2 (no previous close); TR1 = max(3, |12−9|, |9−9|) = 3
    # TR2 = max(1, |11−11|, |10−11|) = 1;    TR3 = max(3, |15−10.5|, |12−10.5|) = 4.5
    same(vx.true_range(H, L, C), [2, 3, 1, 4.5])
    # ATR(3): (2+3+1)/3 = 2 @i2; then (2×2 + 4.5)/3 = 2.8333
    same(vx.atr(H, L, C, 3), [N, N, 2, 8.5 / 3])


def test_stochastic() -> None:
    # k=3: i2 range 8..12, (10−8)/4 = 50%; i3 range 9..13, (12−9)/4 = 75%; %D(2) = 62.5
    k, d = vx.stochastic(
        np.array([10.0, 12, 11, 13]),
        np.array([8.0, 9, 9, 10]),
        np.array([9.0, 11, 10, 12]),
        3,
        1,
        2,
    )
    same(k, [N, N, 50, 75])
    same(d, [N, N, N, 62.5])


def test_cci() -> None:
    # typical = close here. i2: mean 2, mean deviation (1+0+1)/3 = 2/3 → (3−2)/(0.015×2/3) = 100
    # i3: window 2,3,6: mean 11/3, md = (5/3 + 2/3 + 7/3)/3 = 14/9 → (6 − 11/3)/(0.015×14/9) = 100
    x = np.array([1.0, 2, 3, 6])
    same(vx.cci(x, x, x, 3), [N, N, 100, 100], tol=1e-9)


def test_roc() -> None:
    # 100 × (121/100 − 1) = 21
    same(vx.roc(np.array([100.0, 110, 121]), 2), [N, N, 21])


def test_donchian_and_rolling() -> None:
    up, mid, lo = vx.donchian(np.array([1.0, 5, 3, 2]), np.array([0.0, 4, 1, 1]), 2)
    same(up, [N, 5, 5, 3])
    same(lo, [N, 0, 1, 1])
    same(mid, [N, 2.5, 3, 2])


def test_obv() -> None:
    # up +200, down −300, flat 0, up +500
    same(
        vx.obv(np.array([10.0, 11, 10, 10, 12]), np.array([100.0, 200, 300, 400, 500])),
        [0, 200, -100, -100, 400],
    )


def test_vwap_resets_each_session() -> None:
    # session 0: tp 10 × 100 and tp 12 × 300 → (1000 + 3600)/400 = 11.5
    # session 1: first bar has no volume → its typical price 20; then 21×100/100 = 21
    out = vx.vwap(
        np.array([11.0, 13, 21, 22]),
        np.array([9.0, 11, 19, 20]),
        np.array([10.0, 12, 20, 21]),
        np.array([100.0, 300, 0, 100]),
        np.array([0, 0, 1, 1]),
    )
    same(out, [10, 11.5, 20, 21])


def test_adx() -> None:
    # +DM/−DM/TR from i1: (1,0,1.5) (1,0,1.5) (0,0.5,1.5) (2,0,2.5)
    # Wilder(2): TR 1.5,1.5,2.0  +DM 1,0.5,1.25  −DM 0,0.25,0.125   (at i2, i3, i4)
    # +DI 66.667, 33.333, 62.5   −DI 0, 16.667, 6.25
    # DX 100, 33.333, 81.818 → ADX seed (100+33.333)/2 = 66.667 @i3; i4 (66.667+81.818)/2
    h = np.array([10.0, 11, 12, 11, 13])
    lo = np.array([9.0, 9.5, 10.5, 10, 11])
    c = np.array([9.5, 10.5, 11.5, 10.5, 12.5])
    a, p, m = vx.adx(h, lo, c, 2)
    same(p, [N, N, 200 / 3, 100 / 3, 62.5])
    same(m, [N, N, 0, 50 / 3, 6.25])
    same(a, [N, N, N, 200 / 3, (200 / 3 + 900 / 11) / 2])


def test_supertrend() -> None:
    # ATR(2): 1.25, 1.225, 1.5125, 1.85625 (i1..i4); hl2: 10.5, 11.5, 10.5, 8.5
    # i1: bands 11.75 / 9.25, close 10.8 > hl2 → up, line 9.25
    # i2: lower band rises to 10.275, still up
    # i3: close 10.2 < 10.275 → flips down; line = upper band 12.0125
    # i4: upper band 10.35625 (lower than 12.0125), close 8.5 stays below → down
    line, d = vx.supertrend(
        np.array([10.0, 11, 12, 11, 9]),
        np.array([9.0, 10, 11, 10, 8]),
        np.array([9.5, 10.8, 11.8, 10.2, 8.5]),
        2,
        1.0,
    )
    same(line, [N, 9.25, 10.275, 12.0125, 10.35625])
    same(d, [N, 1, 1, -1, -1])


def test_previous_day() -> None:
    ph, pl, pc = vx.previous_day(
        np.array([5.0, 6, 7, 8, 9]),
        np.array([1.0, 2, 3, 4, 5]),
        np.array([2.0, 3, 4, 5, 6]),
        np.array([0, 0, 1, 1, 2]),
    )
    same(ph, [N, N, 6, 6, 8])
    same(pl, [N, N, 1, 1, 3])
    same(pc, [N, N, 3, 3, 5])


def test_opening_range_is_known_once_the_range_closes() -> None:
    # 5-minute bars from the 0-ms session open; 15-minute range ends with the 10-min bar
    m5 = 300_000
    oh, ol = vx.opening_range(
        np.array([10.0, 12, 11, 20]),
        np.array([9.0, 8, 10, 15]),
        np.array([0, m5, 2 * m5, 3 * m5]),
        np.array([0, 0, 0, 0]),
        np.array([0, 0, 0, 0]),
        5,
        15,
    )
    same(oh, [N, N, 12, 12])
    same(ol, [N, N, 8, 8])


def test_52_week_high_needs_a_year_and_rolls_off() -> None:
    day = 86_400_000
    ts = np.arange(400, dtype=np.int64) * day
    high = np.ones(400)
    high[0] = 1000.0
    out = vx.high_52w(high, ts)
    assert math.isnan(out[362])  # less than a year of history
    assert out[364] == 1000.0  # bar 0 is still inside the 365-day window
    assert out[365] == 1.0  # …and gone one day later


# ---------------------------------------------------------------- properties on fixtures


def _fixture_series(symbol: str, tf: Timeframe) -> BarSeries:
    src = FakeSource(_Forever())
    bars = [adjusted(b) for b in src._all(symbol, tf)]
    return from_bars(bars, tf, src.market_of(symbol))


class _Forever:
    def now_ms(self) -> int:
        return 2**62


DAILY = _fixture_series("RELIANCE", Timeframe.D1)
INTRA = _fixture_series("INFY", Timeframe.M5)
PARAMS: dict[str, dict[str, float]] = {
    "sma": {"period": 50},
    "ema": {"period": 30},
    "macd": {"fast": 5, "slow": 13, "signal": 4},
    "bollinger": {"period": 10, "mult": 1.5},
    "keltner": {"period": 15, "mult": 1.5, "atr_period": 7},
    "supertrend": {"period": 7, "mult": 2.0},
}


@pytest.mark.parametrize("key", sorted(INDICATORS))
@pytest.mark.parametrize("series", [DAILY, INTRA], ids=["daily", "5m"])
def test_streaming_matches_vectorized(key: str, series: BarSeries) -> None:
    params = PARAMS.get(key, {})
    vec = compute(key, series, params)
    stream = StreamIndicator(key, params)
    got: dict[str, list[float]] = {k: [] for k in vec}
    for b in bar_inputs(series):
        for k, v in stream.update(b).items():
            got[k].append(v)
    for k, arr in vec.items():
        np.testing.assert_allclose(np.array(got[k]), arr, rtol=1e-9, atol=1e-9, equal_nan=True)


@pytest.mark.parametrize("key", sorted(INDICATORS))
def test_no_look_ahead(key: str) -> None:
    series = INTRA if INDICATORS[key].intraday_only else DAILY
    full = compute(key, series, PARAMS.get(key, {}))
    for cut in (30, 400, len(series) // 2, len(series) - 1):
        part = compute(key, series.upto(cut), PARAMS.get(key, {}))
        for k in full:
            a, b = full[k][cut - 1], part[k][cut - 1]
            assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b, rel=1e-12), (
                key,
                k,
                cut,
            )


@pytest.mark.parametrize("key", sorted(INDICATORS))
def test_values_settle_after_warmup(key: str) -> None:
    ind = INDICATORS[key]
    series = INTRA if ind.intraday_only else DAILY
    out = compute(key, series, {})
    first = next(iter(out.values()))
    w = ind.warmup({p.name: p.default for p in ind.params})
    if key not in ("opening_range", "prev_day", "vwap"):
        assert not np.isnan(first[w:]).any(), key


@settings(max_examples=60, deadline=None)
@given(
    hs.lists(hs.floats(min_value=1, max_value=1000, allow_nan=False), min_size=1, max_size=80),
    hs.integers(min_value=1, max_value=12),
)
def test_streaming_matches_on_random_data(prices: list[float], n: int) -> None:
    series = from_arrays(
        prices,
        high=[p * 1.01 for p in prices],
        low=[p * 0.99 for p in prices],
        volume=[100.0 + i for i in range(len(prices))],
    )
    for key in ("sma", "ema", "rsi", "atr", "adx", "cci", "stochastic", "supertrend", "roc"):
        params = {p.name: n for p in INDICATORS[key].params if p.integer and p.min <= n <= p.max}
        vec = compute(key, series, params)
        stream = StreamIndicator(key, params)
        rows = [stream.update(b) for b in bar_inputs(series)]
        for k, arr in vec.items():
            np.testing.assert_allclose(
                np.array([r[k] for r in rows]), arr, rtol=1e-8, atol=1e-8, equal_nan=True
            )


def test_param_validation() -> None:
    from backend.indicators.catalog import resolve_params

    ind = INDICATORS["rsi"]
    with pytest.raises(ValueError, match="between 1 and 500"):
        resolve_params(ind, {"period": 0})
    with pytest.raises(ValueError, match="whole number"):
        resolve_params(ind, {"period": 2.5})
    with pytest.raises(ValueError, match="no setting called 'length'"):
        resolve_params(ind, {"length": 3})
