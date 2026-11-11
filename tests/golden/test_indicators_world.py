"""Golden tests for the Phase 10.1 indicators (D-11): hand-calculated values with the
arithmetic in comments. Where an indicator is a long chain (KST, Connors RSI, Schaff,
squeeze), it is checked against a brute-force reference written straight from the
definition, recomputing every candle from scratch. Streaming == vectorized, no look-ahead
and warm-up are covered for every catalog indicator by ``test_indicators.py``."""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.indicators import vector as vx
from backend.indicators import vector_world as vw
from tests.golden.test_indicators import DAILY, N, same

A = np.array


def test_smma_is_wilder() -> None:
    # n 2: seed (1+2)/2 = 1.5; (1.5+3)/2 = 2.25; (2.25+4)/2 = 3.125; (3.125+5)/2 = 4.0625
    same(vw.smma(A([1.0, 2, 3, 4, 5]), 2), [N, 1.5, 2.25, 3.125, 4.0625])


def test_zlema() -> None:
    # n 3 → lag 1: d = 2x − x[1] = N, 3, 6, 10, 15; EMA(3) α ½ seeds (3+6+10)/3 = 19/3 @i3
    # i4: ½×15 + ½×19/3 = 32/3
    same(vw.zlema(A([1.0, 2, 4, 7, 11]), 3), [N, N, N, 19 / 3, 32 / 3])


def test_alma() -> None:
    # n 3, offset ½ → centre m = 1; sigma 3 → s = 1; weights e^-½, 1, e^-½
    w = math.exp(-0.5)
    same(vw.alma(A([1.0, 2, 6]), 3, 0.5, 3.0), [N, N, (w * 1 + 2 + w * 6) / (1 + 2 * w)])


def test_t3() -> None:
    # The coefficients add up to 1, so a length-1 T3 (every EMA = the price) is the price.
    x = A([3.0, 5, 4, 8, 7, 9])
    same(vw.t3(x, 1, 0.7), list(x))
    # Volume factor 0 → c4 = 1, the rest 0: T3 = the triple EMA, once all six EMAs exist
    # (the sixth EMA of length 2 starts at candle 6 × (2 − 1) = 6).
    y = A([3.0, 5, 4, 8, 7, 9, 6, 10, 11])
    e3 = vx.ema(vx.ema(vx.ema(y, 2), 2), 2)
    got = vw.t3(y, 2, 0.0)
    assert np.isnan(got[5]) and not np.isnan(got[6])
    np.testing.assert_allclose(got[6:], e3[6:])


def test_mcginley() -> None:
    # n 2: seed (10+12)/2 = 11 @i1; i2: 11 + (15−11) / (2 × (15/11)⁴)
    same(vw.mcginley(A([10.0, 12, 15]), 2), [N, 11, 11 + 4 / (2 * (15 / 11) ** 4)])


def test_linreg() -> None:
    # x = 1, 2, 4 over t = −1, 0, 1: mean 7/3, deviations −4/3, −1/3, 5/3
    # Σt·y = 4/3 + 5/3 = 3, Σt² = 2 → slope 3/2; value at t = 1: 7/3 + 3/2 = 23/6
    # Σy² dev = 42/9 → R² = 3² / (2 × 42/9) = 27/28
    val, slope, r2 = vw.linreg(A([1.0, 2, 4]), 3)
    same(val, [N, N, 23 / 6])
    same(slope, [N, N, 1.5])
    same(r2, [N, N, 27 / 28])
    # a flat window: slope 0, fit 0 (not "perfect")
    same(vw.linreg(A([5.0, 5, 5]), 3)[2], [N, N, 0])


def test_cmo_and_vidya() -> None:
    # changes 2, −1, 3. CMO(2) i2: (2−1)/(2+1) = 1/3 → 33.3; i3: (3−1)/(3+1) = 50
    x = A([1.0, 3, 2, 5])
    same(vw.cmo(x, 2), [N, N, 100 / 3, 50])
    # VIDYA α = 2/(3+1) = ½, seeded with the price (2) on the first CMO candle;
    # i3: k = ½ × 50/100 = ¼ → ¼ × 5 + ¾ × 2 = 2.75
    same(vw.vidya(x, 3, 2), [N, N, 2, 2.75])


def test_trima() -> None:
    # n 4 → SMA 2 then SMA 3. SMA2 = N, 1.5, 2.5, 3.5, 6
    # i3: (1.5+2.5+3.5)/3 = 2.5; i4: (2.5+3.5+6)/3 = 4
    same(vw.trima(A([1.0, 2, 3, 4, 8]), 4), [N, N, N, 2.5, 4])


def test_envelope() -> None:
    mid, up, lo = vw.envelope(A([10.0, 20]), 2, 10.0)
    same(mid, [N, 15])
    same(up, [N, 16.5])
    same(lo, [N, 13.5])


def test_momentum_and_trix() -> None:
    same(vw.momentum(A([1.0, 4, 9, 16]), 2), [N, N, 8, 12])
    # length 1: the triple EMA is the price → TRIX = % change: +10%, −10%
    t, sig = vw.trix(A([100.0, 110, 99]), 1, 1)
    same(t, [N, 10, -10])
    same(sig, [N, 10, -10])


def test_ppo_and_pvo() -> None:
    # EMA1 = x; EMA2 seeds 15 @i1, i2: ⅔×30 + ⅓×15 = 25
    # PPO i1: 100 × 5/15; i2: 100 × 5/25 = 20
    line, sig, hist = vw.ppo(A([10.0, 20, 30]), 1, 2, 1)
    same(sig, [N, 100 / 3, 20])  # signal length 1 = the line itself
    same(line, [N, 100 / 3, 20])
    same(hist, [N, 0, 0])
    same(vw.pvo(A([10.0, 20, 30]), 1, 2, 1)[0], [N, 100 / 3, 20])
    same(vw.ppo(A([0.0, 0, 0]), 1, 2, 1)[0], [N, 0, 0])  # no price → 0, not a crash


def test_dpo() -> None:
    # n 4 → the price 3 candles ago minus SMA4: i3 1 − 2.5; i4 2 − 3.5; i5 3 − 4.5
    same(vw.dpo(A([1.0, 2, 3, 4, 5, 6]), 4), [N, N, N, -1.5, -1.5, -1.5])


def _roc_at(x: np.ndarray, i: int, n: int) -> float:
    return 100.0 * (x[i] / x[i - n] - 1.0) if i >= n else math.nan


def test_kst_against_its_definition() -> None:
    x = DAILY.close[:200]
    k, sig = vw.kst(x, 9)
    for i in (60, 120, 199):
        parts = []
        for r, s in zip(vw.KST_ROC, vw.KST_SMA, strict=True):
            parts.append(sum(_roc_at(x, j, r) for j in range(i - s + 1, i + 1)) / s)
        expect = parts[0] + 2 * parts[1] + 3 * parts[2] + 4 * parts[3]
        assert k[i] == pytest.approx(expect, rel=1e-9)
    assert sig[199] == pytest.approx(float(np.mean(k[191:200])), rel=1e-9)


def test_coppock() -> None:
    # ROC1 + ROC1 = N, 20, 20, 0 → WMA2 (weights 1, 2): i2 (20+40)/3 = 20; i3 (20+0)/3
    same(vw.coppock(A([100.0, 110, 121, 121]), 1, 1, 2), [N, N, 20, 20 / 3])


def test_ultimate() -> None:
    # bar 1: prev close 10, h 12 l 9 c 11 → BP 11 − 9 = 2, TR 12 − 9 = 3
    # bar 2: prev close 11, h 13 l 12 c 12.5 → BP 12.5 − 11 = 1.5, TR 13 − 11 = 2
    # lengths 1, 1, 2: 0.75, 0.75, (2+1.5)/(3+2) = 0.7 → 100 × (3 + 1.5 + 0.7)/7
    h, lo, c = A([10.0, 12, 13]), A([9.0, 9, 12]), A([10.0, 11, 12.5])
    same(vw.ultimate(h, lo, c, 1, 1, 2), [N, N, 520 / 7])


def test_awesome_and_accelerator() -> None:
    # mid 1, 2, 4, 7: SMA2 N, 1.5, 3, 5.5; SMA3 N, N, 7/3, 13/3 → AO i2 2/3, i3 7/6
    # AC i3: 7/6 − (2/3 + 7/6)/2 = 1/4
    m = A([1.0, 2, 4, 7])
    ao, ac = vw.awesome(m, m, 2, 3)
    same(ao, [N, N, 2 / 3, 7 / 6])
    same(ac, [N, N, N, 0.25])


def test_tsi() -> None:
    # length 1 everywhere: TSI = 100 × change / |change|
    t, _ = vw.tsi(A([1.0, 3, 2, 2]), 1, 1, 1)
    same(t, [N, 100, -100, 0])


def test_rvi() -> None:
    # close − open 1, 1, 1, 2 → (2 + 2 + 2 + 1)/6 = 7/6; range 3 → 7/18
    o, c = A([1.0, 1, 1, 1]), A([2.0, 2, 2, 3])
    r, sig = vw.rvi(o, A([3.0, 3, 3, 3]), A([0.0, 0, 0, 0]), c, 1)
    same(r, [N, N, N, 7 / 18])
    same(sig, [N, N, N, N])


def test_fisher() -> None:
    # n 2, mid 1, 3, 2. i1: range 1..3, pos (3−1)/2 − ½ = ½ → v = 0.33,
    #   F = ½ ln(1.33/0.67); trigger none yet
    # i2: range 2..3, pos 0 − ½ → v = 0.66 × −½ + 0.67 × 0.33 = −0.1089,
    #   F = ½ ln(0.8911/1.1089) + ½ F1; trigger = F1
    m = A([1.0, 3, 2])
    f, trig = vw.fisher(m, m, 2)
    f1 = 0.5 * math.log(1.33 / 0.67)
    f2 = 0.5 * math.log(0.8911 / 1.1089) + 0.5 * f1
    same(f, [N, f1, f2])
    same(trig, [N, N, f1])


def test_stc_matches_a_list_based_reference() -> None:
    x = DAILY.close[:300]
    m = vx.ema(x, 23) - vx.ema(x, 50)
    ms: list[float] = []
    pfs: list[float] = []
    f1 = f2 = 0.0
    pf = pff = math.nan
    expect = []
    for v in m:
        if math.isnan(v):
            expect.append(math.nan)
            continue
        ms.append(float(v))
        w = ms[-10:]
        if max(w) > min(w):
            f1 = (v - min(w)) / (max(w) - min(w)) * 100
        pf = f1 if math.isnan(pf) else pf + 0.5 * (f1 - pf)
        pfs.append(pf)
        w2 = pfs[-10:]
        if max(w2) > min(w2):
            f2 = (pf - min(w2)) / (max(w2) - min(w2)) * 100
        pff = f2 if math.isnan(pff) else pff + 0.5 * (f2 - pff)
        expect.append(pff if len(ms) >= 10 else math.nan)
    np.testing.assert_allclose(vw.stc(x), expect, equal_nan=True)
    valid = vw.stc(DAILY.close)
    assert np.nanmin(valid) >= 0 and np.nanmax(valid) <= 100


def test_connors_rsi_against_its_definition() -> None:
    x = DAILY.close[:260]
    got = vw.connors_rsi(x, 3, 2, 100)
    streak = [0.0]
    for i in range(1, len(x)):
        p = streak[-1]
        streak.append(
            (p + 1 if p > 0 else 1)
            if x[i] > x[i - 1]
            else (p - 1 if p < 0 else -1)
            if x[i] < x[i - 1]
            else 0
        )
    r_close = vx.rsi(x, 3)
    r_streak = vx.rsi(np.array(streak), 2)
    for i in (101, 150, 259):
        today = _roc_at(x, i, 1)
        before = [_roc_at(x, j, 1) for j in range(i - 100, i)]
        rank = 100 * sum(1 for v in before if v < today) / 100
        assert got[i] == pytest.approx((r_close[i] + r_streak[i] + rank) / 3, rel=1e-9)
    assert math.isnan(got[100])


def test_elder_ray_bop_qstick_smi() -> None:
    h, lo, c, o = A([4.0, 5]), A([0.0, 5]), A([3.0, 5]), A([1.0, 5])
    bull, bear = vw.elder_ray(h, lo, c, 1)  # EMA1 = close
    same(bull, [1, 0])
    same(bear, [-3, 0])
    same(vw.bop(o, h, lo, c, 1), [0.5, 0])  # (3−1)/(4−0); a flat candle → 0
    same(vw.qstick(A([1.0, 5]), A([2.0, 2]), 2), [N, (1 - 3) / 2])
    # SMI with k = d = 1: 100 × (close − range middle) / (half the range) = 100 × 1/2
    same(vw.smi(h[:1], lo[:1], c[:1], 1, 1)[0], [50])


def test_wavetrend_is_zero_without_deviation() -> None:
    # channel length 1: the average is the price itself, so the channel index is 0
    wt1, _ = vw.wavetrend(A([3.0, 4, 5]), A([1.0, 2, 3]), A([2.0, 3, 4]), 1, 1)
    same(wt1, [0, 0, 0])


def test_elder_impulse() -> None:
    # EMA1 = x rises; MACD(1, 2, 2): EMA2 N, 1.5, 19/6, 115/18; line N, .5, 5/6, 29/18
    # signal EMA2 of the line seeds (.5 + 5/6)/2 = 2/3 @i2, i3 ⅔×29/18 + ⅓×2/3 = 35/27
    # histogram i2 1/6, i3 29/18 − 35/27 = 17/54 → rising with the EMA → +1
    same(vw.elder_impulse(A([1.0, 2, 4, 8]), 1, 1, 2, 2), [N, N, N, 1])


def test_vortex() -> None:
    # bar 1: VM+ |12 − 9| = 3, VM− |10 − 11| = 1, TR max(2, 2, 0) = 2 → 1.5 and 0.5
    vp, vm = vw.vortex(A([11.0, 12]), A([9.0, 10]), A([10.0, 11]), 1)
    same(vp, [N, 1.5])
    same(vm, [N, 0.5])


def test_adxr_averages_today_and_a_window_ago() -> None:
    h, lo, c = DAILY.high[:120], DAILY.low[:120], DAILY.close[:120]
    a = vx.adx(h, lo, c, 14)[0]
    np.testing.assert_allclose(vw.adxr(h, lo, c, 14)[60:], (a[60:] + a[47:107]) / 2)


def test_chop() -> None:
    # TR 1 (first candle: high − low), then max(2, |12 − 9.5|, |10 − 9.5|) = 2.5
    # Σ 3.5 over a 12 − 9 = 3 range → 100 × log10(3.5/3) / log10(2)
    v = vw.chop(A([10.0, 12]), A([9.0, 10]), A([9.5, 11]), 2)
    same(v, [N, 100 * math.log10(3.5 / 3) / math.log10(2)])
    same(vw.chop(A([5.0, 5]), A([5.0, 5]), A([5.0, 5]), 2), [N, 100])  # no range


def test_fractals_are_known_two_candles_later() -> None:
    h = A([1.0, 2, 5, 2, 1, 3])
    up, dn = vw.fractals(h, h - 0.5)
    same(up, [N, N, N, N, 5, 5])
    same(dn, [N] * 6)


def test_alligator_lines_are_drawn_ahead() -> None:
    h, lo = DAILY.high[:80], DAILY.low[:80]
    jaw, teeth, lips = vw.alligator(h, lo)
    m = (h + lo) / 2
    np.testing.assert_allclose(jaw[30:], vx.rma(m, 13)[22:72])
    np.testing.assert_allclose(teeth[30:], vx.rma(m, 8)[25:75])
    np.testing.assert_allclose(lips[30:], vx.rma(m, 5)[27:77])


def test_heikin_ashi() -> None:
    # bar 0: close (10+12+9+11)/4 = 10.5, open (10+11)/2 = 10.5, high 12, low 9
    # bar 1: close 46/4 = 11.5, open (10.5+10.5)/2 = 10.5, high 13, low 10
    hc, ho, hh, hl = vw.heikin_ashi(A([10.0, 11]), A([12.0, 13]), A([9.0, 10]), A([11.0, 12]))
    same(hc, [10.5, 11.5])
    same(ho, [10.5, 10.5])
    same(hh, [12, 13])
    same(hl, [9, 10])


def test_mass_index_ulcer_hv_natr() -> None:
    # length 1 EMAs: the ratio is 1 on every candle → a 3-candle sum is 3
    same(vw.mass_index(A([2.0, 3, 4]), A([1.0, 1, 1]), 1, 3), [N, N, 3])
    # highest of 2: N, 10, 9 → drawdowns N, −20%, 0 → √((400 + 0)/2)
    same(vw.ulcer(A([10.0, 8, 9]), 2), [N, N, math.sqrt(200)])
    # two log returns a, b: sample std = |a − b| / √2; per year 1, in %
    a, b = math.log(1.1), math.log(0.9)
    same(vw.hv(A([100.0, 110, 99]), 2, 1), [N, N, 100 * abs(a - b) / math.sqrt(2)])
    # ATR1 = true range: 2 / 10, then max(2, 2, 0) = 2 / 11
    same(vw.natr(A([11.0, 12]), A([9.0, 10]), A([10.0, 11]), 1), [20, 200 / 11])


def test_chandelier() -> None:
    # length 1, 1 ATR: long = high − TR, short = low + TR (TR 2, then 2)
    long, short = vw.chandelier(A([11.0, 12]), A([9.0, 10]), A([10.0, 11]), 1, 1.0)
    same(long, [9, 10])
    same(short, [11, 12])


def test_squeeze_against_its_parts() -> None:
    h, lo, c = DAILY.high[:200], DAILY.low[:200], DAILY.close[:200]
    mom, on = vw.squeeze(h, lo, c, 20, 2.0, 1.5)
    mid, up, dn = vx.bollinger(c, 20, 2.0)
    km, a = vx.ema(c, 20), vx.atr(h, lo, c, 20)
    for i in (19, 60, 199):
        assert on[i] == (
            1.0 if (up[i] < km[i] + 1.5 * a[i] and dn[i] > km[i] - 1.5 * a[i]) else 0.0
        )
    d = c - ((vx.rolling_max(h, 20) + vx.rolling_min(lo, 20)) / 2 + mid) / 2
    np.testing.assert_allclose(mom[38:], vw.linreg(d, 20)[0][38:])
    assert math.isnan(on[18])


def test_zscore_pct_b_disparity() -> None:
    same(vw.zscore(A([1.0, 3]), 2), [N, 1])  # mean 2, population sd 1
    pct_b, width = vw.bollinger_pct(A([1.0, 3]), 2, 1.0)  # bands 1 … 3
    same(pct_b, [N, 1])
    same(width, [N, 100])
    same(vw.bollinger_pct(A([2.0, 2]), 2, 1.0)[0], [N, 0.5])  # zero width
    same(vw.disparity(A([10.0, 12]), 2), [N, 100 / 11])


def test_rvol_compares_with_previous_candles() -> None:
    # average of the previous two: i2 (10+20)/2 = 15 → 30/15 = 2; i3 25 → 60/25 = 2.4
    same(vw.rvol(A([10.0, 20, 30, 60]), 2), [N, N, 2, 2.4])


def test_ad_line_and_chaikin() -> None:
    # CLV ((8 − 0) − (10 − 8)) / 10 = 0.6 × 100 = 60; then a mid close adds 0
    h, lo, c, v = A([10.0, 10, 10]), A([0.0, 0, 0]), A([8.0, 5, 10]), A([100.0, 50, 100])
    same(vw.ad_line(h, lo, c, v), [60, 60, 160])
    # EMA1 − EMA2: EMA2 seeds (60+60)/2 = 60 @i1; i2: ⅔×160 + ⅓×60 = 380/3
    same(vw.chaikin_osc(h, lo, c, v, 1, 2), [N, 0, 160 - 380 / 3])


def test_force_eom_klinger() -> None:
    same(vw.force_index(A([10.0, 12]), A([1.0, 5]), 1), [N, 10])
    # mid 9 → 11 (+2), range 2, volume 20,000: 10,000 × 2 × 2 / 20,000 = 2
    same(vw.eom(A([10.0, 12]), A([8.0, 10]), A([1.0, 20000]), 1), [N, 2])
    # typical 10, 11, 10.5: signed volume N, +200, −300; EMA1 − EMA2 (seed −50 @i2)
    tp = A([10.0, 11, 10.5])
    k, _ = vw.klinger(tp, tp, tp, A([100.0, 200, 300]), 1, 2, 1)
    same(k, [N, N, -250])


def test_volume_indexes_and_pvt() -> None:
    c, v = A([10.0, 11, 12, 12.6]), A([100.0, 90, 120, 80])
    # NVI follows the price on quieter days: ×1.1 (i1), hold (i2), ×1.05 (i3)
    same(vw.nvi(c, v, 1)[0], [1000, 1100, 1100, 1155])
    # PVI on busier days: hold, hold, ×12/11, hold
    same(vw.pvi(c, v, 1)[0], [1000, 1000, 12000 / 11, 12000 / 11])
    # PVT: 100 × +10% = +10, then 200 × −10% = −20
    same(vw.pvt(A([10.0, 11, 9.9]), A([0.0, 100, 200])), [0, 10, -10])


def test_pivot_variants() -> None:
    # previous session H 12, L 8, C 10 (range 4)
    h, lo, c, sess = A([12.0, 11]), A([8.0, 10]), A([10.0, 10.5]), np.array([1, 2])
    p, r1, r2, r3, s1, s2, s3 = (x[1] for x in vw.pivots_fib(h, lo, c, sess))
    assert (p, r1, r2, r3) == pytest.approx((10, 11.528, 12.472, 14))
    assert (s1, s2, s3) == pytest.approx((8.472, 7.528, 6))
    cam = [x[1] for x in vw.pivots_camarilla(h, lo, c, sess)]
    assert cam == pytest.approx(
        [10 + 4 * 1.1 / k for k in (12, 6, 4, 2)] + [10 - 4 * 1.1 / k for k in (12, 6, 4, 2)]
    )
    # Woodie P = (12 + 8 + 2×10)/4 = 10; R1 = 2P − L = 12; S1 = 2P − H = 8
    wp, wr1, *_rest = (x[1] for x in vw.pivots_woodie(h, lo, c, sess))
    assert (wp, wr1) == pytest.approx((10, 12))
    assert math.isnan(vw.pivots_fib(h, lo, c, sess)[0][0])
