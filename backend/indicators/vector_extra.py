"""More indicators over a whole history (Phase 9.1, KAIROS §4).

Same rules as ``vector.py`` (D-34): arrays as long as the input, NaN during warm-up, value
``i`` uses inputs ``0..i`` only, divisions by zero give a documented neutral value. Their
one-bar-at-a-time twins are in ``stream_extra.py``; golden tests pin both.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from backend.indicators.series import F64, I64
from backend.indicators.vector import (
    _arr,
    _check,
    _first_valid,
    _nan,
    ema,
    previous_day,
    rolling_max,
    rolling_min,
    rsi,
    sma_nan,
    wma,
)

NAN = math.nan


# ---------------------------------------------------------------- moving averages


def dema(x: F64, n: int) -> F64:
    """Double EMA: 2 × EMA − EMA(EMA). Less lag than a plain EMA."""
    e1 = ema(x, n)
    return 2.0 * e1 - ema(e1, n)


def tema(x: F64, n: int) -> F64:
    """Triple EMA: 3 × E1 − 3 × E2 + E3, where each E is the EMA of the one before."""
    e1 = ema(x, n)
    e2 = ema(e1, n)
    return 3.0 * e1 - 3.0 * e2 + ema(e2, n)


def hma_lengths(n: int) -> tuple[int, int]:
    """Hull's half length (rounded down) and smoothing length (√n rounded)."""
    return n // 2, max(1, round(math.sqrt(n)))


def hma(x: F64, n: int) -> F64:
    """Hull moving average: WMA(2 × WMA(n/2) − WMA(n), √n). Very little lag."""
    if n < 2:
        raise ValueError("period must be at least 2")
    half, root = hma_lengths(n)
    inner = 2.0 * wma(x, half) - wma(x, n)
    return wma(inner, root)


def vwma(x: F64, volume: F64, n: int) -> F64:
    """Volume-weighted moving average. A window with no volume falls back to the SMA."""
    _check(n)
    x, v = _arr(x), _arr(volume)
    out = _nan(len(x))
    if len(x) >= n:
        xv = sliding_window_view(x * v, n).sum(axis=1)
        vs = sliding_window_view(v, n).sum(axis=1)
        plain = sliding_window_view(x, n).mean(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[n - 1 :] = np.where(vs > 0, xv / np.where(vs > 0, vs, 1.0), plain)
    return out


def kama(x: F64, n: int = 10, fast: int = 2, slow: int = 30) -> F64:
    """Kaufman's adaptive MA. Seeds with the price at index n − 1; from index n:
    ER = |x_i − x_{i−n}| / Σ|x_j − x_{j−1}| (0 when nothing moved),
    sc = (ER × (2/(fast+1) − 2/(slow+1)) + 2/(slow+1))², KAMA += sc × (x − KAMA)."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) < n:
        return out
    fs, ss = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
    k = float(x[n - 1])
    out[n - 1] = k
    diffs = np.abs(np.diff(x))
    for i in range(n, len(x)):
        vol = float(diffs[i - n : i].sum())
        er = abs(float(x[i] - x[i - n])) / vol if vol > 0 else 0.0
        sc = (er * (fs - ss) + ss) ** 2
        k = k + sc * (float(x[i]) - k)
        out[i] = k
    return out


# ---------------------------------------------------------------- trend systems


def ichimoku(
    high: F64, low: F64, conv: int = 9, base: int = 26, span: int = 52, shift: int = 26
) -> tuple[F64, F64, F64, F64]:
    """(conversion, base, span A, span B). The cloud lines are the values *drawn* at each
    candle: span A at i = (conversion + base)/2 of candle i − shift, span B at i = the
    52-candle midpoint of candle i − shift, so they never look ahead. The lagging span
    (close drawn 26 candles back) is left out: on any candle it would need future closes."""
    h, lo = _arr(high), _arr(low)
    tenkan = (rolling_max(h, conv) + rolling_min(lo, conv)) / 2.0
    kijun = (rolling_max(h, base) + rolling_min(lo, base)) / 2.0
    a_now = (tenkan + kijun) / 2.0
    b_now = (rolling_max(h, span) + rolling_min(lo, span)) / 2.0
    a, b = _nan(len(h)), _nan(len(h))
    if shift == 0:
        return tenkan, kijun, a_now, b_now
    if len(h) > shift:
        a[shift:] = a_now[:-shift]
        b[shift:] = b_now[:-shift]
    return tenkan, kijun, a, b


def psar(
    high: F64, low: F64, close: F64, start: float = 0.02, step: float = 0.02, maximum: float = 0.2
) -> F64:
    """Wilder's parabolic SAR, the stop level for candle i.

    Candle 0 has none. At candle 1 the trend is up if close₁ ≥ close₀ (SAR = low₀,
    extreme = high₁) else down (SAR = high₀, extreme = low₁). Then each candle:
    SAR += AF × (extreme − SAR), kept beyond the previous two candles' lows (uptrend) or
    highs (downtrend); if the candle crosses it the trend flips, SAR = the old extreme,
    extreme = this candle's low/high, AF = start; otherwise a new extreme raises AF by
    ``step`` up to ``maximum``."""
    h, lo, c = _arr(high), _arr(low), _arr(close)
    size = len(c)
    out = _nan(size)
    if size < 2:
        return out
    up = bool(c[1] >= c[0])
    sar = float(lo[0] if up else h[0])
    ep = float(h[1] if up else lo[1])
    af = start
    out[1] = sar
    for i in range(2, size):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, float(lo[i - 1]), float(lo[i - 2]))
            if lo[i] < sar:
                up, sar, ep, af = False, ep, float(lo[i]), start
            elif h[i] > ep:
                ep, af = float(h[i]), min(af + step, maximum)
        else:
            sar = max(sar, float(h[i - 1]), float(h[i - 2]))
            if h[i] > sar:
                up, sar, ep, af = True, ep, float(h[i]), start
            elif lo[i] < ep:
                ep, af = float(lo[i]), min(af + step, maximum)
        out[i] = sar
    return out


def aroon(high: F64, low: F64, n: int = 25) -> tuple[F64, F64, F64]:
    """(up, down, oscillator). Up = 100 × (n − candles since the highest high of the last
    n + 1 candles) / n; ties count the most recent candle. Oscillator = up − down."""
    _check(n)
    h, lo = _arr(high), _arr(low)
    up, dn = _nan(len(h)), _nan(len(h))
    if len(h) > n:
        wh = sliding_window_view(h, n + 1)[:, ::-1]  # newest first, so argmax = most recent
        wl = sliding_window_view(lo, n + 1)[:, ::-1]
        up[n:] = 100.0 * (n - wh.argmax(axis=1)) / n
        dn[n:] = 100.0 * (n - wl.argmin(axis=1)) / n
    return up, dn, up - dn


# ---------------------------------------------------------------- oscillators


def williams_r(high: F64, low: F64, close: F64, n: int = 14) -> F64:
    """(highest high − close) / (highest high − lowest low) × −100; a flat range gives −50."""
    hh, ll = rolling_max(high, n), rolling_min(low, n)
    c = _arr(close)
    rng = hh - ll
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isnan(rng), NAN, np.where(rng > 0, -100.0 * (hh - c) / rng, -50.0))


def mfi(high: F64, low: F64, close: F64, volume: F64, n: int = 14) -> F64:
    """Money flow index (volume-weighted RSI) over n price changes, starting at index n.
    Typical price up → positive flow, down → negative, unchanged → neither.
    No negative flow → 100 (or 50 if there's no flow at all)."""
    _check(n)
    tp = (_arr(high) + _arr(low) + _arr(close)) / 3.0
    flow = tp * _arr(volume)
    out = _nan(len(tp))
    if len(tp) <= n:
        return out
    d = np.diff(tp)
    pos = np.where(d > 0, flow[1:], 0.0)
    neg = np.where(d < 0, flow[1:], 0.0)
    ps = sliding_window_view(pos, n).sum(axis=1)
    ns = sliding_window_view(neg, n).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        val = np.where(
            ns > 0,
            100.0 - 100.0 / (1.0 + ps / np.where(ns > 0, ns, 1.0)),
            np.where(ps > 0, 100.0, 50.0),
        )
    out[n:] = val
    return out


def cmf(high: F64, low: F64, close: F64, volume: F64, n: int = 20) -> F64:
    """Chaikin money flow: Σ(multiplier × volume) / Σvolume over n candles, where
    multiplier = ((close − low) − (high − close)) / (high − low), 0 for a flat candle.
    No volume in the window → 0."""
    _check(n)
    h, lo, c, v = _arr(high), _arr(low), _arr(close), _arr(volume)
    rng = h - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        mult = np.where(rng > 0, ((c - lo) - (h - c)) / np.where(rng > 0, rng, 1.0), 0.0)
    out = _nan(len(c))
    if len(c) >= n:
        mv = sliding_window_view(mult * v, n).sum(axis=1)
        vs = sliding_window_view(v, n).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[n - 1 :] = np.where(vs > 0, mv / np.where(vs > 0, vs, 1.0), 0.0)
    return out


def stoch_rsi(
    x: F64, rsi_n: int = 14, stoch_n: int = 14, k: int = 3, d: int = 3
) -> tuple[F64, F64]:
    """(%K, %D): the stochastic of RSI over ``stoch_n`` RSI values (50 when they're all
    equal), smoothed by SMA(k), and %D = SMA(%K, d)."""
    _check(stoch_n)
    r = rsi(x, rsi_n)
    raw = _nan(len(r))
    f = _first_valid(r)
    if len(r) - f >= stoch_n:
        win = sliding_window_view(r[f:], stoch_n)
        hh, ll = win.max(axis=1), win.min(axis=1)
        cur = r[f + stoch_n - 1 :]
        with np.errstate(invalid="ignore", divide="ignore"):
            raw[f + stoch_n - 1 :] = np.where(
                hh - ll > 0, 100.0 * (cur - ll) / np.where(hh - ll > 0, hh - ll, 1.0), 50.0
            )
    kk = sma_nan(raw, k)
    return kk, sma_nan(kk, d)


# ---------------------------------------------------------------- levels


def pivots(
    high: F64, low: F64, close: F64, session: I64
) -> tuple[F64, F64, F64, F64, F64, F64, F64]:
    """Classic floor-trader pivots from the previous session's high H, low L, close C:
    P = (H + L + C)/3, R1 = 2P − L, S1 = 2P − H, R2 = P + (H − L), S2 = P − (H − L),
    R3 = H + 2(P − L), S3 = L − 2(H − P). Returned as (P, R1, R2, R3, S1, S2, S3).
    On daily candles "the previous session" is the previous candle."""
    ph, pl, pc = previous_day(high, low, close, session)
    p = (ph + pl + pc) / 3.0
    return (
        p,
        2 * p - pl,
        p + (ph - pl),
        ph + 2 * (p - pl),
        2 * p - ph,
        p - (ph - pl),
        pl - 2 * (ph - p),
    )
