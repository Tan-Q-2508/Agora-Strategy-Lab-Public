"""Golden tests for the Phase 9.1 indicators (D-11): hand-calculated values with the
arithmetic in comments. Streaming == vectorized and no look-ahead are covered for every
catalog indicator by ``test_indicators.py``."""

from __future__ import annotations

import numpy as np

from backend.indicators import vector_extra as vx
from tests.golden.test_indicators import N, same


def test_dema_and_tema() -> None:
    # x = 2,4,6,5,7; EMA(2): alpha 2/3, seed (2+4)/2 = 3 @i1
    # E1: 3, 2/3×6+1/3×3 = 5, 2/3×5+1/3×5 = 5, 2/3×7+1/3×5 = 19/3
    # E2 = EMA(E1): seed (3+5)/2 = 4 @i2; i3: 2/3×5+1/3×4 = 14/3; i4: 2/3×19/3+1/3×14/3 = 52/9
    # E3 = EMA(E2): seed (4+14/3)/2 = 13/3 @i3; i4: 2/3×52/9 + 1/3×13/3 = 143/27
    # DEMA = 2E1 − E2: i2 10−4 = 6; i3 10 − 14/3 = 16/3; i4 38/3 − 52/9 = 62/9
    # TEMA = 3E1 − 3E2 + E3: i3 15 − 14 + 13/3 = 16/3; i4 19 − 52/3 + 143/27 = 188/27
    x = np.array([2.0, 4, 6, 5, 7])
    same(vx.dema(x, 2), [N, N, 6, 16 / 3, 62 / 9])
    same(vx.tema(x, 2), [N, N, N, 16 / 3, 188 / 27])


def test_hma() -> None:
    # n = 4: half 2, root round(√4) = 2. x = 1,2,3,4,6,5
    # WMA2 (1,2)/3: i3 (3+8)/3 = 11/3; i4 (4+12)/3 = 16/3; i5 (6+10)/3 = 16/3
    # WMA4 (1..4)/10: i3 (1+4+9+16)/10 = 3; i4 (2+6+12+24)/10 = 4.4; i5 (3+8+18+20)/10 = 4.9
    # inner = 2×WMA2 − WMA4: i3 13/3; i4 32/3 − 4.4 = 94/15; i5 32/3 − 4.9 = 173/30
    # HMA = WMA2(inner): i4 (13/3 + 2×94/15)/3 = 253/45; i5 (94/15 + 2×173/30)/3 = 89/15
    same(vx.hma(np.array([1.0, 2, 3, 4, 6, 5]), 4), [N, N, N, N, 253 / 45, 89 / 15])


def test_vwma_falls_back_to_sma_without_volume() -> None:
    # i1: (10×1 + 20×3)/4 = 17.5; i2: (20×3 + 30×0)/3 = 20; i3: no volume → (30+40)/2 = 35
    x, v = np.array([10.0, 20, 30, 40]), np.array([1.0, 3, 0, 0])
    same(vx.vwma(x, v, 2), [N, 17.5, 20, 35])


def test_kama() -> None:
    # n 2, fast 2, slow 30: fs = 2/3, ss = 2/31. x = 10, 11, 13, 12. Seed @i1 = 11.
    # i2: ER = |13−10| / (1+2) = 1 → sc = (2/3)² = 4/9 → 11 + 4/9 × 2 = 107/9
    # i3: ER = |12−11| / (2+1) = 1/3 → sc = (1/3×(2/3−2/31) + 2/31)² = (74/279)²
    #     KAMA = 107/9 + sc × (12 − 107/9)
    sc = (74 / 279) ** 2
    same(vx.kama(np.array([10.0, 11, 13, 12]), 2, 2, 30), [N, 11, 107 / 9, 107 / 9 + sc / 9])
    # nothing moves → efficiency 0 → the slowest speed, and the value stays put
    same(vx.kama(np.full(4, 5.0), 2, 2, 30), [N, 5, 5, 5])


def test_ichimoku_cloud_is_shifted_not_looked_ahead() -> None:
    # conversion 2, base 3, span 4, shift 2
    # h = 10,12,11,13,14,12   l = 8,9,9,10,12,11
    # conversion (2): i1 (12+8)/2 = 10; i2 (12+9)/2 = 10.5; i3 11; i4 12; i5 (14+11)/2 = 12.5
    # base (3): i2 (12+8)/2 = 10; i3 (13+9)/2 = 11; i4 (14+9)/2 = 11.5; i5 (14+10)/2 = 12
    # A now = (conv+base)/2: i2 10.25, i3 11 → drawn at i4, i5
    # B now (4): i3 (13+8)/2 = 10.5 → drawn at i5
    h = np.array([10.0, 12, 11, 13, 14, 12])
    lo = np.array([8.0, 9, 9, 10, 12, 11])
    conv, base, a, b = vx.ichimoku(h, lo, 2, 3, 4, 2)
    same(conv, [N, 10, 10.5, 11, 12, 12.5])
    same(base, [N, N, 10, 11, 11.5, 12])
    same(a, [N, N, N, N, 10.25, 11])
    same(b, [N, N, N, N, N, 10.5])


def test_parabolic_sar() -> None:
    # i1: close up → uptrend, SAR = low0 = 9, extreme = high1 = 11, AF .02
    # i2: 9 + .02×2 = 9.04, capped at min(lows i0,i1) = 9; high 12 > 11 → extreme 12, AF .04
    # i3: 9 + .04×3 = 9.12 (lows 11, 10 are higher); high 11.5 → no change
    # i4: 9.12 + .04×(12 − 9.12) = 9.2352; low 8.8 < SAR → flip down: SAR = 12, extreme 8.8
    # i5: 12 + .02×(8.8 − 12) = 11.936, max with highs 10, 11.5 → 11.936
    h = np.array([10.0, 11, 12, 11.5, 10, 9.5])
    lo = np.array([9.0, 10, 11, 10.5, 8.8, 8.5])
    c = np.array([9.5, 10.8, 11.8, 11, 9, 9])
    same(vx.psar(h, lo, c), [N, 9, 9, 9.12, 12, 11.936])


def test_mfi() -> None:
    # typical price (h = l = c) 10, 11, 10.5, 12; volume 100..400 → flow 1000, 2200, 3150, 4800
    # i2 (n=2): positive 2200, negative 3150 → 100 − 100/(1 + 2200/3150) = 100 − 315000/5350
    # i3: positive 4800, negative 3150 → 100 − 315000/7950
    tp = np.array([10.0, 11, 10.5, 12])
    v = np.array([100.0, 200, 300, 400])
    same(vx.mfi(tp, tp, tp, v, 2), [N, N, 100 - 315000 / 5350, 100 - 315000 / 7950])
    rising = np.array([1.0, 2, 3])
    assert vx.mfi(rising, rising, rising, np.ones(3), 2)[-1] == 100  # only buying
    flat = np.full(3, 5.0)
    assert vx.mfi(flat, flat, flat, np.ones(3), 2)[-1] == 50  # nothing moved


def test_williams_r() -> None:
    # i2: HH 12, LL 7, close 8 → −100 × (12−8)/5 = −80
    # i3: HH 13, LL 7, close 12 → −100 × 1/6
    h, lo, c = np.array([10.0, 12, 11, 13]), np.array([8.0, 9, 7, 10]), np.array([9.0, 11, 8, 12])
    same(vx.williams_r(h, lo, c, 3), [N, N, -80, -100 / 6])
    flat = np.full(3, 4.0)
    assert vx.williams_r(flat, flat, flat, 3)[-1] == -50


def test_aroon_counts_the_most_recent_extreme() -> None:
    # n 3, windows of 4 candles. i3 highs (newest first) 12,11,12,10 → the latest 12 is 0
    # candles old → up 100; lows 7.5,9,7,8 → the 7 is 2 old → down 100×1/3
    # i4 highs 9,12,11,12 → 1 old → 200/3; lows 8,7.5,9,7 → 3 old → 0
    h = np.array([10.0, 12, 11, 12, 9])
    lo = np.array([8.0, 7, 9, 7.5, 8])
    up, down, osc = vx.aroon(h, lo, 3)
    same(up, [N, N, N, 100, 200 / 3])
    same(down, [N, N, N, 100 / 3, 0])
    same(osc, [N, N, N, 200 / 3, 200 / 3])


def test_cmf() -> None:
    # multipliers: i0 ((9.5−8) − (10−9.5))/2 = 0.5; i1 flat candle → 0; i2 ((11−9) − 1)/3 = 1/3
    # i1: (0.5×100 + 0×50)/150 = 1/3;  i2: (0×50 + 1/3×200)/250 = 4/15
    h, lo = np.array([10.0, 10, 12]), np.array([8.0, 10, 9])
    c, v = np.array([9.5, 10, 11]), np.array([100.0, 50, 200])
    same(vx.cmf(h, lo, c, v, 2), [N, 1 / 3, 4 / 15])


def test_stoch_rsi() -> None:
    # RSI(3) of 10, 11, 10.5, 11.5, 12, 11 = N, N, N, 80, 84.6154, 50 (see test_rsi_wilder)
    # stochastic over 2 RSI values: i4 (84.6−80)/(84.6−80) = 100; i5 (50−50)/(84.6−50) = 0
    # %K smoothing 1 = raw; %D = SMA2 → i5 (100+0)/2 = 50
    k, d = vx.stoch_rsi(np.array([10.0, 11, 10.5, 11.5, 12, 11]), 3, 2, 1, 2)
    same(k, [N, N, N, N, 100, 0], tol=1e-6)
    same(d, [N, N, N, N, N, 50], tol=1e-6)


def test_pivots() -> None:
    # previous session H 12, L 8, C 10 → P = 10, R1 = 20 − 8 = 12, S1 = 20 − 12 = 8,
    # R2 = 10 + 4 = 14, S2 = 6, R3 = 12 + 2×2 = 16, S3 = 8 − 2×2 = 4
    h, lo, c = np.array([12.0, 13]), np.array([8.0, 9]), np.array([10.0, 12])
    p, r1, r2, r3, s1, s2, s3 = vx.pivots(h, lo, c, np.array([1, 2]))
    for arr, want in ((p, 10), (r1, 12), (r2, 14), (r3, 16), (s1, 8), (s2, 6), (s3, 4)):
        same(arr, [N, want])
