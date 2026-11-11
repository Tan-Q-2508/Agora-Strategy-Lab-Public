"""Swings, support/resistance zones and trendlines on hand-built series."""

from __future__ import annotations

import pytest

from backend.analysis import levels as lv
from backend.analysis import trendlines as tl
from backend.analysis.swings import MINOR, Swing, find_swings, reversal_size
from tests.analysis.helpers import path
from tests.golden.test_indicators import DAILY, INTRA


def test_zigzag_hand_calculated() -> None:
    # Up 2 per candle to 120 (candle 10), down to 100 (20), up to 120 (30). Rising candles:
    # high = close + 0.5, low = open − 0.5 → true range 3, so ATR → 3 and a reversal needs
    # 1.5 × ATR ≈ 4.3–4.5.
    # • Candle 1: high 102.5 − low₀ 99.5 = 3 ≥ 1.5 × mean(TR 1, 3) = 3 → swing low 0 known at 1.
    # • The top is candle 10 (high 120.5). Candle 11's low 117.5 is only 3 below; candle 12's
    #   115.5 is 5 below ≥ 1.5 × 37/13 = 4.27 → swing high 10 known at 12.
    # • The bottom is candle 20 (low 99.5); candle 22's high 104.5 is 5 above → known at 22.
    s = path([(0, 100), (10, 120), (20, 100), (30, 120)])
    sw = find_swings(s.high, s.low, s.close, MINOR)
    assert sw.swings == (
        Swing(0, 99.5, "L", 1),
        Swing(10, 120.5, "H", 12),
        Swing(20, 99.5, "L", 22),
    )
    assert sw.pending is not None and sw.pending.kind == "H" and sw.pending.index == 30


@pytest.mark.parametrize("series", [DAILY, INTRA], ids=["daily", "5m"])
def test_swings_never_look_ahead(series: object) -> None:
    from backend.indicators.series import BarSeries

    assert isinstance(series, BarSeries)
    full = find_swings(series.high, series.low, series.close)
    for cut in (60, 300, len(series) // 2, len(series) - 7):
        part = find_swings(*(a[:cut] for a in (series.high, series.low, series.close)))
        assert list(part.swings) == full.known_at(cut - 1)


def test_reversal_size_has_no_gaps() -> None:
    s = path([(0, 100), (5, 110)])
    a = reversal_size(s.high, s.low, s.close)
    assert all(x > 0 for x in a)


def test_zone_from_three_equal_lows() -> None:
    minor = [
        Swing(10, 100.0, "L", 12),
        Swing(20, 110.0, "H", 22),
        Swing(30, 100.3, "L", 32),
        Swing(40, 110.2, "H", 42),
        Swing(50, 100.1, "L", 52),
    ]
    zones = lv.find_zones(minor, [], close_now=105.0, atr_now=2.0, last_index=60)
    sup = next(z for z in zones if z.role == "support")
    res = next(z for z in zones if z.role == "resistance")
    assert sup.count == 3 and res.count == 2
    # centre: recency-weighted mean of 100, 100.3, 100.1 with weights 1.875, 1.925, 1.975
    assert sup.center == pytest.approx(578.275 / 5.775)
    # strength: 45 × (1 − 0.6³) + 20 × (1 − 10/400) = 35.28 + 19.5 = 54.78
    assert sup.strength == 55
    assert sup.high == pytest.approx(sup.center + 0.3)  # half-width 0.15 × ATR
    assert sup.distance_atr == pytest.approx((105.0 - sup.high) / 2.0, abs=1e-3)
    assert not sup.flipped


def test_flipped_zone_and_testing_role() -> None:
    minor = [Swing(10, 100.0, "H", 12), Swing(20, 95.0, "L", 22), Swing(30, 100.2, "L", 32)]
    z = lv.find_zones(minor, [], close_now=100.1, atr_now=2.0, last_index=40)
    top = next(x for x in z if x.count == 2)
    assert top.flipped and top.role == "testing" and "flipped" in top.tags


def test_key_zones_keep_the_nearest_strong_ones() -> None:
    minor = [
        Swing(i * 10, 100.0 + 10 * (i % 5), "L" if i % 2 else "H", i * 10 + 2) for i in range(20)
    ]
    zones = lv.find_zones(minor, [], close_now=120.5, atr_now=1.0, last_index=200)
    chosen = lv.key_zones(zones)
    assert len(chosen) <= 5
    assert all(z.strength >= 40 for z in chosen)


def test_rising_support_line_with_three_touches_then_broken() -> None:
    pts = [(0, 105), (10, 100), (20, 112), (30, 110), (40, 122), (50, 120), (60, 128)]
    s = path(pts)
    sw = find_swings(s.high, s.low, s.close)
    atr = reversal_size(s.high, s.low, s.close)
    lines = tl.find_lines(list(sw.swings), s.close, atr, len(s) - 1)
    sup = next(ln for ln in lines if ln.kind == "support" and ln.broken_at is None)
    assert sup.direction == "rising" and sup.touches == 3
    assert sup.slope == pytest.approx(0.5)  # lows 99.5 → 109.5 → 119.5, 10 per 20 candles
    broken = path([*pts, (70, 110)])
    sw2 = find_swings(broken.high, broken.low, broken.close)
    atr2 = reversal_size(broken.high, broken.low, broken.close)
    lines2 = tl.find_lines(list(sw2.swings), broken.close, atr2, len(broken) - 1)
    assert any(ln.kind == "support" and ln.broken_at is not None for ln in lines2)


def test_channel_from_parallel_lines() -> None:
    s = path(
        [(0, 100), (10, 110), (20, 105), (30, 115), (40, 110), (50, 120), (60, 115), (70, 125)]
    )
    sw = find_swings(s.high, s.low, s.close)
    atr = reversal_size(s.high, s.low, s.close)
    lines = tl.find_lines(list(sw.swings), s.close, atr, len(s) - 1)
    ch = tl.find_channel(lines, float(atr[-1]))
    assert ch is not None and ch.kind == "rising"
