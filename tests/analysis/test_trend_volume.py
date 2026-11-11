"""Trend score, momentum, volume, divergences and Fibonacci."""

from __future__ import annotations

import numpy as np
import pytest

from backend.analysis import divergence as dv
from backend.analysis import fibonacci as fb
from backend.analysis.swings import Swing
from backend.analysis.trend import MomentumArrays, TrendArrays, regime_of, structure
from backend.analysis.volume import VolumeArrays, rvol
from tests.analysis.helpers import path


def test_trend_score_of_a_clean_rise() -> None:
    # Up 1 per candle for 300 candles: every average stacked (+1 × 0.35), slope far above
    # 3 ATR per 20 candles (capped +1 × 0.25), +DI above −DI (+1 × 0.15), no swings
    # (structure 0), ADX ≥ 20 (no shrink): 100 × (0.35 + 0.25 + 0.15) = 75.
    s = path([(0, 100), (300, 400)])
    t = TrendArrays(s.high, s.low, s.close).state(len(s) - 1, [])
    assert t.score == 75.0 and t.regime == "strong uptrend"
    assert t.ma_stack == 1.0 and t.structure == 0


def test_regime_labels() -> None:
    assert [regime_of(x) for x in (80, 30, 0, -30, -80)] == [
        "strong uptrend",
        "uptrend",
        "sideways",
        "downtrend",
        "strong downtrend",
    ]


def test_structure() -> None:
    up = [Swing(0, 10, "L", 1), Swing(5, 20, "H", 6), Swing(9, 12, "L", 10), Swing(14, 25, "H", 15)]
    down = [
        Swing(0, 30, "H", 1),
        Swing(5, 20, "L", 6),
        Swing(9, 28, "H", 10),
        Swing(14, 15, "L", 15),
    ]
    assert structure(up) == 1 and structure(down) == -1 and structure(up[:2]) == 0


def test_momentum_reads_overbought() -> None:
    # A perfectly straight rise: RSI 100 (score +1), but MACD sits exactly on its signal line
    # and %K on %D, which count as neutral (0): (1 + 0 + 0) / 3.
    s = path([(0, 100), (60, 160)])
    m = MomentumArrays(s.high, s.low, s.close).state(len(s) - 1)
    assert m.rsi_state == "overbought" and m.score == pytest.approx(1 / 3, abs=1e-3)


def test_rvol_hand_calculated() -> None:
    # 20 candles of 10, then 30: 30 / mean(10 × 20) = 3
    v = np.array([10.0] * 20 + [30.0])
    r = rvol(v)
    assert np.isnan(r[19]) and r[20] == 3.0


def test_volume_state() -> None:
    s = path([(0, 100), (40, 120)])
    vol = np.full(len(s), 1000.0)
    vol[-1] = 3000.0
    st = VolumeArrays(s.high, s.low, s.close, vol).state(len(s) - 1)
    assert st.has_volume and st.rvol == 3.0 and st.spikes == (len(s) - 1,)
    assert st.notes[0].startswith("Volume is 3.0×")
    flat = VolumeArrays(s.high, s.low, s.close, np.zeros(len(s))).state(len(s) - 1)
    assert not flat.has_volume and flat.score == 0.0


def test_divergences() -> None:
    rsi = np.full(40, 50.0)
    hist = np.zeros(40)
    rsi[10], rsi[30] = 25.0, 35.0  # price lower low, RSI higher low
    hist[10], hist[30] = -2.0, -1.0
    swings = [Swing(10, 100.0, "L", 12), Swing(20, 110.0, "H", 22), Swing(30, 95.0, "L", 33)]
    [d] = dv.find(swings, rsi, hist)
    assert d.kind == "regular_bullish" and d.strong and d.known_at == 33
    rsi[30] = 20.0  # higher price low, lower RSI low → hidden bullish
    swings[2] = Swing(30, 102.0, "L", 33)
    [h] = dv.find(swings, rsi, hist)
    assert h.kind == "hidden_bullish" and not h.strong


def test_fibonacci_levels() -> None:
    # leg 100 → 200: 61.8% retracement = 200 − 61.8 = 138.2; 127.2% extension = 227.2
    f = fb.from_swings([Swing(0, 100.0, "L", 2), Swing(10, 200.0, "H", 12)], 139.0, 2.0)
    assert f is not None and f.up
    by = {lv.label: lv.price for lv in f.levels}
    assert by["61.8%"] == pytest.approx(138.2) and by["127.2%"] == pytest.approx(227.2)
    assert f.nearest is not None and f.nearest.label == "61.8%"
