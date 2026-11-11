"""The rest of the world's common indicators, over a whole history (Phase 10.1).

The list follows what traders actually use worldwide: everything in TradingView's
built-in list, TA-Lib and StockCharts' ChartSchool that works on one stock's own candles
(indicators that need a second symbol, order-book data or options are out of scope).
Same rules as ``vector.py`` (D-34): arrays as long as the input, NaN during warm-up, value
``i`` uses inputs ``0..i`` only, and a division by zero gives a documented neutral value
instead of inf/NaN. The one-candle-at-a-time twins are in ``stream_world.py``.

Where platforms disagree on a detail, the choice is written in the docstring and pinned
by ``tests/golden/test_indicators_world.py``.
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
    adx,
    atr,
    bollinger,
    ema,
    macd,
    previous_day,
    rma,
    roc,
    rolling_max,
    rolling_min,
    rsi,
    sma,
    sma_nan,
    stdev,
    true_range,
    wma,
)

NAN = math.nan


def _div(a: F64, b: F64, fill: float) -> F64:
    """a / b, NaN where either is NaN, ``fill`` where b is 0."""
    a, b = _arr(a), _arr(b)
    out = _nan(len(a))
    ok = ~(np.isnan(a) | np.isnan(b))
    aa, bb = a[ok], b[ok]
    out[ok] = np.where(bb != 0, aa / np.where(bb != 0, bb, 1.0), fill)
    return out


def _shift(x: F64, k: int) -> F64:
    """``x`` moved ``k`` candles later (value i is x[i − k])."""
    out = _nan(len(x))
    if k == 0:
        return _arr(x).copy()
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def rolling_sum_nan(x: F64, n: int) -> F64:
    """Sum of the last ``n`` values, starting once ``n`` valid values exist."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    f = _first_valid(x)
    if len(x) - f >= n:
        out[f + n - 1 :] = sliding_window_view(x[f:], n).sum(axis=1)
    return out


# ---------------------------------------------------------------- moving averages


def smma(x: F64, n: int) -> F64:
    """Smoothed moving average (SMMA, Wilder's RMA): seed = SMA of the first n,
    then avg = (avg × (n − 1) + x) / n. Used by the Alligator and Wilder's tools."""
    return rma(x, n)


def zlema(x: F64, n: int) -> F64:
    """Zero-lag EMA (Ehlers): EMA of x + (x − x[lag ago]), lag = (n − 1) // 2."""
    _check(n)
    x = _arr(x)
    lag = (n - 1) // 2
    d = x.copy()
    if lag:
        d[:lag] = NAN
        d[lag:] = 2.0 * x[lag:] - x[:-lag]
    return ema(d, n)


def alma_weights(n: int, offset: float, sigma: float) -> F64:
    """Gaussian weights centred at ``offset × (n − 1)`` (oldest = 0), width n / sigma."""
    m = offset * (n - 1)
    s = n / sigma
    w = np.exp(-((np.arange(n, dtype=np.float64) - m) ** 2) / (2.0 * s * s))
    out: F64 = w / w.sum()
    return out


def alma(x: F64, n: int = 9, offset: float = 0.85, sigma: float = 6.0) -> F64:
    """Arnaud Legoux moving average: a Gaussian-weighted window, smooth with little lag."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) >= n:
        out[n - 1 :] = sliding_window_view(x, n) @ alma_weights(n, offset, sigma)
    return out


def t3_coefficients(v: float) -> tuple[float, float, float, float]:
    a2, a3 = v * v, v * v * v
    return -a3, 3 * a2 + 3 * a3, -6 * a2 - 3 * v - 3 * a3, 1 + 3 * v + a3 + 3 * a2


def t3(x: F64, n: int = 5, v: float = 0.7) -> F64:
    """Tillson T3: six chained EMAs blended with the volume factor ``v``:
    T3 = c1·e6 + c2·e5 + c3·e4 + c4·e3."""
    e1 = ema(x, n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    e4 = ema(e3, n)
    e5 = ema(e4, n)
    e6 = ema(e5, n)
    c1, c2, c3, c4 = t3_coefficients(v)
    out: F64 = c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3
    return out


def mcginley(x: F64, n: int = 14) -> F64:
    """McGinley Dynamic: seeds with the SMA of the first n, then
    MD += (x − MD) / (n × (x / MD)⁴). It speeds up in falls and slows in rises.
    A non-positive price resets it to the price."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) < n:
        return out
    md = float(np.mean(x[:n]))
    out[n - 1] = md
    for i in range(n, len(x)):
        xi = float(x[i])
        md = md + (xi - md) / (n * (xi / md) ** 4) if md > 0 and xi > 0 else xi
        out[i] = md
    return out


def linreg(x: F64, n: int = 25) -> tuple[F64, F64, F64]:
    """Least-squares line through the last n values: (value at the newest candle = LSMA,
    slope per candle, R² 0…1). A flat window has slope 0 and R² 0."""
    if n < 2:
        raise ValueError("period must be at least 2")
    x = _arr(x)
    size = len(x)
    val, slope, r2 = _nan(size), _nan(size), _nan(size)
    if size < n:
        return val, slope, r2
    tc = np.arange(n, dtype=np.float64) - (n - 1) / 2.0
    sxx = float(tc @ tc)
    win = sliding_window_view(x, n)
    ym = win.mean(axis=1)
    yc = win - ym[:, None]
    sxy = yc @ tc
    syy = (yc * yc).sum(axis=1)
    b = sxy / sxx
    val[n - 1 :] = ym + b * tc[-1]
    slope[n - 1 :] = b
    with np.errstate(invalid="ignore", divide="ignore"):
        r2[n - 1 :] = np.where(syy > 0, sxy * sxy / (sxx * np.where(syy > 0, syy, 1.0)), 0.0)
    r2[n - 1 :][np.isnan(syy)] = NAN
    return val, slope, r2


def trima_lengths(n: int) -> tuple[int, int]:
    """TA-Lib's split: odd n → two SMAs of (n + 1) / 2; even n → n/2 then n/2 + 1."""
    return ((n + 1) // 2, (n + 1) // 2) if n % 2 else (n // 2, n // 2 + 1)


def trima(x: F64, n: int = 20) -> F64:
    """Triangular moving average: an SMA of an SMA, weighting the middle of the window."""
    _check(n)
    a, b = trima_lengths(n)
    return sma_nan(sma(x, a), b)


def envelope(x: F64, n: int = 20, pct: float = 2.5) -> tuple[F64, F64, F64]:
    """(middle = SMA, upper = SMA × (1 + pct%), lower = SMA × (1 − pct%))."""
    m = sma(x, n)
    return m, m * (1.0 + pct / 100.0), m * (1.0 - pct / 100.0)


def cmo(x: F64, n: int = 14) -> F64:
    """Chande momentum oscillator: 100 × (gains − losses) / (gains + losses) over n
    changes, −100…+100. No change at all → 0."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) > n:
        d = np.diff(x)
        up = sliding_window_view(np.where(d > 0, d, 0.0), n).sum(axis=1)
        dn = sliding_window_view(np.where(d < 0, -d, 0.0), n).sum(axis=1)
        tot = up + dn
        out[n:] = np.where(tot > 0, 100.0 * (up - dn) / np.where(tot > 0, tot, 1.0), 0.0)
    return out


def vidya(x: F64, n: int = 14, cmo_n: int = 9) -> F64:
    """Chande's variable index dynamic average: an EMA (α = 2/(n+1)) whose speed is
    scaled by |CMO(cmo_n)| / 100. Seeds with the price on the first candle with a CMO."""
    x = _arr(x)
    c = cmo(x, cmo_n)
    out = _nan(len(x))
    f = _first_valid(c)
    if f >= len(x):
        return out
    alpha = 2.0 / (n + 1.0)
    v = float(x[f])
    out[f] = v
    for i in range(f + 1, len(x)):
        k = alpha * abs(float(c[i])) / 100.0
        v = k * float(x[i]) + (1.0 - k) * v
        out[i] = v
    return out


# ---------------------------------------------------------------- momentum


def momentum(x: F64, n: int = 10) -> F64:
    """Price now minus price n candles ago."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) > n:
        out[n:] = x[n:] - x[:-n]
    return out


def trix(x: F64, n: int = 15, signal: int = 9) -> tuple[F64, F64]:
    """(TRIX, signal): one-candle % change of a triple-smoothed EMA, and its EMA."""
    e3 = ema(ema(ema(x, n), n), n)
    t = _nan(len(e3))
    if len(e3) > 1:
        t[1:] = _div(100.0 * (e3[1:] - e3[:-1]), e3[:-1], 0.0)
    return t, ema(t, signal)


def ppo(x: F64, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[F64, F64, F64]:
    """Percentage price oscillator: 100 × (EMA fast − EMA slow) / EMA slow, with its
    signal EMA and histogram. Like MACD, but comparable across price levels."""
    f, s = ema(x, fast), ema(x, slow)
    line = _div(100.0 * (f - s), s, 0.0)
    sig = ema(line, signal)
    return line, sig, line - sig


def dpo(x: F64, n: int = 20) -> F64:
    """Detrended price oscillator, causal form: the price n/2 + 1 candles ago minus
    today's n-candle SMA. Shows cycles with the trend taken out."""
    _check(n)
    k = n // 2 + 1
    return _shift(_arr(x), k) - sma(x, n)


KST_ROC = (10, 15, 20, 30)
KST_SMA = (10, 10, 10, 15)


def kst(x: F64, signal: int = 9) -> tuple[F64, F64]:
    """Know Sure Thing (Pring): 1×R1 + 2×R2 + 3×R3 + 4×R4, where Rk is an SMA (10, 10,
    10, 15) of the ROC (10, 15, 20, 30); signal = SMA(signal) of KST."""
    parts = [sma_nan(roc(x, r), s) for r, s in zip(KST_ROC, KST_SMA, strict=True)]
    k = parts[0] + 2.0 * parts[1] + 3.0 * parts[2] + 4.0 * parts[3]
    return k, sma_nan(k, signal)


def coppock(x: F64, long: int = 14, short: int = 11, n: int = 10) -> F64:
    """Coppock curve: WMA(n) of ROC(long) + ROC(short). Designed on monthly closes as a
    long-term buy signal when it turns up below zero."""
    return wma(roc(x, long) + roc(x, short), n)


def ultimate(high: F64, low: F64, close: F64, a: int = 7, b: int = 14, c: int = 28) -> F64:
    """Ultimate oscillator (Larry Williams): buying pressure / true range averaged over
    three lengths, weighted 4:2:1, 0…100. A window with no range counts 0.5."""
    h, lo, cl = _arr(high), _arr(low), _arr(close)
    size = len(cl)
    out = _nan(size)
    if size < 2:
        return out
    pc = cl[:-1]
    bp = cl[1:] - np.minimum(lo[1:], pc)
    tr = np.maximum(h[1:], pc) - np.minimum(lo[1:], pc)
    total = np.zeros(size - 1)
    m = max(a, b, c)
    if size - 1 < m:
        return out
    for k, w in ((a, 4.0), (b, 2.0), (c, 1.0)):
        sb = sliding_window_view(bp, k).sum(axis=1)[m - k :]
        st = sliding_window_view(tr, k).sum(axis=1)[m - k :]
        avg = np.where(st > 0, sb / np.where(st > 0, st, 1.0), 0.5)
        total[m - 1 :] += w * avg
    out[m:] = 100.0 * total[m - 1 :] / 7.0
    return out


def awesome(high: F64, low: F64, fast: int = 5, slow: int = 34) -> tuple[F64, F64]:
    """(Awesome oscillator, Accelerator oscillator), Bill Williams: AO = SMA(fast) −
    SMA(slow) of the candle mid-point; AC = AO − SMA(fast) of AO."""
    hl2 = (_arr(high) + _arr(low)) / 2.0
    ao = sma(hl2, fast) - sma(hl2, slow)
    return ao, ao - sma_nan(ao, fast)


def tsi(x: F64, long: int = 25, short: int = 13, signal: int = 13) -> tuple[F64, F64]:
    """True strength index (Blau): 100 × double-smoothed change / double-smoothed
    absolute change (−100…+100), with its signal EMA. No change at all → 0."""
    x = _arr(x)
    pc = _nan(len(x))
    if len(x) > 1:
        pc[1:] = np.diff(x)
    num = ema(ema(pc, long), short)
    den = ema(ema(np.abs(pc), long), short)
    t = _div(100.0 * num, den, 0.0)
    return t, ema(t, signal)


def _sym4(x: F64) -> F64:
    """(x + 2·x[1] + 2·x[2] + x[3]) / 6, Ehlers' symmetric weighting."""
    return (x + 2.0 * _shift(x, 1) + 2.0 * _shift(x, 2) + _shift(x, 3)) / 6.0


def rvi(open_: F64, high: F64, low: F64, close: F64, n: int = 10) -> tuple[F64, F64]:
    """Relative vigor index: smoothed (close − open) / smoothed (high − low) over n, with
    a symmetric 4-candle signal. Positive when candles close above their opens."""
    num = sma_nan(_sym4(_arr(close) - _arr(open_)), n)
    den = sma_nan(_sym4(_arr(high) - _arr(low)), n)
    r = _div(num, den, 0.0)
    return r, _sym4(r)


def fisher(high: F64, low: F64, n: int = 9) -> tuple[F64, F64]:
    """Ehlers' Fisher transform of the candle mid-point's place in its n-candle range
    (TradingView's form: value = 0.66 × (pos − 0.5) + 0.67 × previous, clipped to
    ±0.999; fisher = 0.5 × ln((1 + v)/(1 − v)) + 0.5 × previous). (fisher, trigger =
    the previous fisher). A flat range counts as the middle."""
    hl2 = (_arr(high) + _arr(low)) / 2.0
    hh, ll = rolling_max(hl2, n), rolling_min(hl2, n)
    size = len(hl2)
    fish, trig = _nan(size), _nan(size)
    val = f = 0.0
    prev = NAN
    for i in range(n - 1, size):
        rng = float(hh[i] - ll[i])
        pos = (float(hl2[i] - ll[i]) / rng - 0.5) if rng > 0 else 0.0
        val = min(max(0.66 * pos + 0.67 * val, -0.999), 0.999)
        f = 0.5 * math.log((1.0 + val) / (1.0 - val)) + 0.5 * f
        fish[i], trig[i] = f, prev
        prev = f
    return fish, trig


def stc(x: F64, fast: int = 23, slow: int = 50, cycle: int = 10, factor: float = 0.5) -> F64:
    """Schaff trend cycle: a double stochastic of MACD(fast, slow) over ``cycle``
    candles, each pass smoothed by ``factor`` (TradingView's form), 0…100. A flat window
    repeats the previous reading. Shown once ``cycle`` MACD values exist."""
    from backend.indicators.stream_world import STCCore  # one implementation of the loop

    m = ema(x, fast) - ema(x, slow)
    core = STCCore(cycle, factor)
    return np.array([core.update(float(v)) for v in m], dtype=np.float64)


def connors_rsi(close: F64, n: int = 3, streak: int = 2, rank: int = 100) -> F64:
    """Connors RSI: (RSI(n) of the close + RSI(streak) of the up/down streak length +
    percent rank of today's 1-candle % change among the previous ``rank``) / 3."""
    c = _arr(close)
    size = len(c)
    s = np.zeros(size)
    for i in range(1, size):
        if c[i] > c[i - 1]:
            s[i] = s[i - 1] + 1 if s[i - 1] > 0 else 1
        elif c[i] < c[i - 1]:
            s[i] = s[i - 1] - 1 if s[i - 1] < 0 else -1
    r1 = _nan(size)
    if size > 1:
        r1[1:] = _div(100.0 * (c[1:] - c[:-1]), c[:-1], 0.0)
    pr = _nan(size)
    if size > rank + 1:
        w = sliding_window_view(r1[1:], rank + 1)
        pr[rank + 1 :] = 100.0 * (w[:, :-1] < w[:, -1:]).sum(axis=1) / rank
    out: F64 = (rsi(c, n) + rsi(s, streak) + pr) / 3.0
    return out


def elder_ray(high: F64, low: F64, close: F64, n: int = 13) -> tuple[F64, F64]:
    """(bull power = high − EMA, bear power = low − EMA)."""
    e = ema(close, n)
    return _arr(high) - e, _arr(low) - e


def bop(open_: F64, high: F64, low: F64, close: F64, n: int = 14) -> F64:
    """Balance of power: SMA(n) of (close − open) / (high − low), −1…+1."""
    raw = _div(_arr(close) - _arr(open_), _arr(high) - _arr(low), 0.0)
    return sma(raw, n)


def qstick(open_: F64, close: F64, n: int = 8) -> F64:
    """Qstick (Chande): SMA(n) of close − open. Above 0: candles mostly close up."""
    return sma(_arr(close) - _arr(open_), n)


def smi(high: F64, low: F64, close: F64, k: int = 10, d: int = 3) -> tuple[F64, F64]:
    """Stochastic momentum index (Blau): where the close sits against the middle of the
    k-candle range, double-smoothed (EMA d), −100…+100; signal = EMA(d)."""
    hh, ll = rolling_max(high, k), rolling_min(low, k)
    rel = _arr(close) - (hh + ll) / 2.0
    num = ema(ema(rel, d), d)
    den = ema(ema(hh - ll, d), d) / 2.0
    s = _div(100.0 * num, den, 0.0)
    return s, ema(s, d)


def wavetrend(high: F64, low: F64, close: F64, n1: int = 10, n2: int = 21) -> tuple[F64, F64]:
    """WaveTrend (LazyBear): channel index of the typical price, EMA-smoothed (wt1) and
    its 4-candle SMA (wt2). Above +60 stretched up, below −60 stretched down."""
    ap = (_arr(high) + _arr(low) + _arr(close)) / 3.0
    esa = ema(ap, n1)
    dd = ema(np.abs(ap - esa), n1)
    ci = _div(ap - esa, 0.015 * dd, 0.0)
    wt1 = ema(ci, n2)
    return wt1, sma_nan(wt1, 4)


# ---------------------------------------------------------------- trend


def vortex(high: F64, low: F64, close: F64, n: int = 14) -> tuple[F64, F64]:
    """(VI+, VI−): upward vs downward "vortex movement" over n candles, divided by the
    true range. VI+ crossing above VI− marks an uptrend start. No range → 0."""
    _check(n)
    h, lo = _arr(high), _arr(low)
    size = len(h)
    vp, vm = _nan(size), _nan(size)
    if size <= n:
        return vp, vm
    tr = true_range(high, low, close)[1:]
    st = sliding_window_view(tr, n).sum(axis=1)
    sp = sliding_window_view(np.abs(h[1:] - lo[:-1]), n).sum(axis=1)
    sm = sliding_window_view(np.abs(lo[1:] - h[:-1]), n).sum(axis=1)
    safe = np.where(st > 0, st, 1.0)
    vp[n:] = np.where(st > 0, sp / safe, 0.0)
    vm[n:] = np.where(st > 0, sm / safe, 0.0)
    return vp, vm


def adxr(high: F64, low: F64, close: F64, n: int = 14) -> F64:
    """ADX rating: (ADX now + ADX n − 1 candles ago) / 2 (TA-Lib)."""
    a = adx(high, low, close, n)[0]
    return (a + _shift(a, n - 1)) / 2.0


def alligator(
    high: F64, low: F64, jaw: int = 13, teeth: int = 8, lips: int = 5
) -> tuple[F64, F64, F64]:
    """Bill Williams' Alligator: SMMAs of the mid-point, drawn 8, 5 and 3 candles later
    (so today's value is the average as it stood that many candles ago)."""
    hl2 = (_arr(high) + _arr(low)) / 2.0
    return (
        _shift(smma(hl2, jaw), 8),
        _shift(smma(hl2, teeth), 5),
        _shift(smma(hl2, lips), 3),
    )


def elder_impulse(close: F64, n: int = 13, fast: int = 12, slow: int = 26, signal: int = 9) -> F64:
    """Elder impulse: +1 when the EMA and the MACD histogram both rise, −1 when both
    fall, 0 otherwise."""
    e = ema(close, n)
    hist = macd(close, fast, slow, signal)[2]
    de, dh = e - _shift(e, 1), hist - _shift(hist, 1)
    with np.errstate(invalid="ignore"):
        out = np.where((de > 0) & (dh > 0), 1.0, np.where((de < 0) & (dh < 0), -1.0, 0.0))
    out[np.isnan(de) | np.isnan(dh)] = NAN
    return out


def heikin_ashi(open_: F64, high: F64, low: F64, close: F64) -> tuple[F64, F64, F64, F64]:
    """Heikin-Ashi candles (close, open, high, low): close = OHLC average, open = the
    average of the previous HA open and close (first: (open + close)/2)."""
    o, h, lo, c = _arr(open_), _arr(high), _arr(low), _arr(close)
    size = len(c)
    hc = (o + h + lo + c) / 4.0
    ho = _nan(size)
    if size:
        ho[0] = (o[0] + c[0]) / 2.0
    for i in range(1, size):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2.0
    return hc, ho, np.maximum.reduce([h, ho, hc]), np.minimum.reduce([lo, ho, hc])


def fractals(high: F64, low: F64) -> tuple[F64, F64]:
    """Bill Williams' fractals, as known at each candle: (the last up-fractal's high, the
    last down-fractal's low). A fractal is a candle with two lower highs (higher lows) on
    each side, so it is known two candles after it happened."""
    h, lo = _arr(high), _arr(low)
    size = len(h)
    up, dn = _nan(size), _nan(size)
    last_up = last_dn = NAN
    for i in range(size):
        j = i - 2
        if j >= 2:
            if h[j] > max(h[j - 1], h[j - 2], h[j + 1], h[j + 2]):
                last_up = float(h[j])
            if lo[j] < min(lo[j - 1], lo[j - 2], lo[j + 1], lo[j + 2]):
                last_dn = float(lo[j])
        up[i], dn[i] = last_up, last_dn
    return up, dn


# ---------------------------------------------------------------- volatility


def mass_index(high: F64, low: F64, n: int = 9, total: int = 25) -> F64:
    """Mass index (Dorsey): sum over ``total`` candles of EMA(range) / EMA(EMA(range)).
    A "reversal bulge" is a rise above 27 then a fall below 26.5."""
    r = _arr(high) - _arr(low)
    e1 = ema(r, n)
    e2 = ema(e1, n)
    return rolling_sum_nan(_div(e1, e2, 1.0), total)


def chop(high: F64, low: F64, close: F64, n: int = 14) -> F64:
    """Choppiness index: 100 × log10(Σ true range / (highest − lowest)) / log10(n),
    0…100. Above ~61.8 choppy, below ~38.2 trending. No range → 100."""
    if n < 2:
        raise ValueError("period must be at least 2")
    st = rolling_sum_nan(true_range(high, low, close), n)
    rng = rolling_max(high, n) - rolling_min(low, n)
    ratio = _div(st, rng, 0.0)
    out = _nan(len(st))
    ok = ~np.isnan(ratio)
    good = ok & (ratio > 0)
    out[ok] = 100.0
    out[good] = 100.0 * np.log10(ratio[good]) / math.log10(n)
    return out


def ulcer(close: F64, n: int = 14) -> F64:
    """Ulcer index (Martin): root-mean-square of the % drawdown from the n-candle high,
    over n candles. Measures pain, not volatility."""
    c = _arr(close)
    dd = _div(100.0 * (c - rolling_max(c, n)), rolling_max(c, n), 0.0)
    return np.sqrt(sma_nan(dd * dd, n))


def hv(close: F64, n: int = 20, per_year: int = 252) -> F64:
    """Historical volatility: sample standard deviation of n log returns, annualised
    (× √per_year), in %. A non-positive price counts as no change."""
    if n < 2:
        raise ValueError("period must be at least 2")
    c = _arr(close)
    size = len(c)
    out = _nan(size)
    if size <= n:
        return out
    ok = (c[1:] > 0) & (c[:-1] > 0)
    lr = np.zeros(size - 1)
    lr[ok] = np.log(c[1:][ok] / c[:-1][ok])
    out[n:] = sliding_window_view(lr, n).std(axis=1, ddof=1) * math.sqrt(per_year) * 100.0
    return out


def natr(high: F64, low: F64, close: F64, n: int = 14) -> F64:
    """Normalised ATR: ATR as % of the close, comparable across stocks."""
    return _div(100.0 * atr(high, low, close, n), _arr(close), 0.0)


def chandelier(high: F64, low: F64, close: F64, n: int = 22, mult: float = 3.0) -> tuple[F64, F64]:
    """Chandelier exit (Le Beau): (long stop = highest high − mult × ATR,
    short stop = lowest low + mult × ATR), both over n candles."""
    a = atr(high, low, close, n)
    return rolling_max(high, n) - mult * a, rolling_min(low, n) + mult * a


def squeeze(
    high: F64, low: F64, close: F64, n: int = 20, bb: float = 2.0, kc: float = 1.5
) -> tuple[F64, F64]:
    """TTM-style squeeze (Carter; LazyBear's momentum): (momentum = linear-regression
    value over n of close − the average of the range mid-point and the SMA, on = 1 while
    the Bollinger Bands (n, bb) sit inside the Keltner Channel (EMA n ± kc × ATR n))."""
    c = _arr(close)
    mid, up, dn = bollinger(c, n, bb)
    km = ema(c, n)
    a = atr(high, low, close, n)
    on = np.where((up < km + kc * a) & (dn > km - kc * a), 1.0, 0.0)
    on[np.isnan(up) | np.isnan(a) | np.isnan(km)] = NAN
    d = c - ((rolling_max(high, n) + rolling_min(low, n)) / 2.0 + mid) / 2.0
    return linreg(d, max(2, n))[0], on


def zscore(x: F64, n: int = 20) -> F64:
    """How many standard deviations the value is from its n-candle mean."""
    x = _arr(x)
    return _div(x - sma(x, n), stdev(x, n), 0.0)


def bollinger_pct(x: F64, n: int = 20, mult: float = 2.0) -> tuple[F64, F64]:
    """(%B = where the price sits between the bands, 0 = lower, 1 = upper;
    bandwidth = band width as % of the middle). Zero width → %B 0.5."""
    mid, up, dn = bollinger(x, n, mult)
    return _div(_arr(x) - dn, up - dn, 0.5), _div(100.0 * (up - dn), mid, 0.0)


def disparity(x: F64, n: int = 14) -> F64:
    """Disparity index: % distance of the price from its n-candle SMA."""
    m = sma(x, n)
    return _div(100.0 * (_arr(x) - m), m, 0.0)


# ---------------------------------------------------------------- volume


def pvo(volume: F64, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[F64, F64, F64]:
    """Percentage volume oscillator: PPO applied to volume."""
    return ppo(_arr(volume), fast, slow, signal)


def ad_line(high: F64, low: F64, close: F64, volume: F64) -> F64:
    """Accumulation/distribution line: running total of volume × close location value
    ((close − low) − (high − close)) / (high − low). No range → 0."""
    h, lo, c = _arr(high), _arr(low), _arr(close)
    clv = _div((c - lo) - (h - c), h - lo, 0.0)
    out: F64 = np.cumsum(clv * _arr(volume))
    return out


def chaikin_osc(high: F64, low: F64, close: F64, volume: F64, fast: int = 3, slow: int = 10) -> F64:
    """Chaikin oscillator: EMA(fast) − EMA(slow) of the A/D line."""
    ad = ad_line(high, low, close, volume)
    return ema(ad, fast) - ema(ad, slow)


def force_index(close: F64, volume: F64, n: int = 13) -> F64:
    """Elder's force index: EMA(n) of (close − previous close) × volume."""
    c, v = _arr(close), _arr(volume)
    raw = _nan(len(c))
    if len(c) > 1:
        raw[1:] = (c[1:] - c[:-1]) * v[1:]
    return ema(raw, n)


EOM_SCALE = 10_000.0


def eom(high: F64, low: F64, volume: F64, n: int = 14) -> F64:
    """Ease of movement (Arms): SMA(n) of 10,000 × change of the mid-point × range /
    volume. High when price moves easily on light volume. No volume → 0."""
    h, lo, v = _arr(high), _arr(low), _arr(volume)
    size = len(h)
    raw = _nan(size)
    if size > 1:
        hl2 = (h + lo) / 2.0
        raw[1:] = _div(EOM_SCALE * (hl2[1:] - hl2[:-1]) * (h[1:] - lo[1:]), v[1:], 0.0)
    return sma_nan(raw, n)


def klinger(
    high: F64, low: F64, close: F64, volume: F64, fast: int = 34, slow: int = 55, signal: int = 13
) -> tuple[F64, F64]:
    """Klinger volume oscillator, TradingView's form: volume signed by whether the
    typical price rose (or held) or fell; EMA(fast) − EMA(slow), with a signal EMA."""
    tp = (_arr(high) + _arr(low) + _arr(close)) / 3.0
    v = _arr(volume)
    sv = _nan(len(tp))
    if len(tp) > 1:
        sv[1:] = np.where(tp[1:] - tp[:-1] >= 0, v[1:], -v[1:])
    k = ema(sv, fast) - ema(sv, slow)
    return k, ema(k, signal)


def _volume_index(close: F64, volume: F64, *, negative: bool) -> F64:
    c, v = _arr(close), _arr(volume)
    out = _nan(len(c))
    if not len(c):
        return out
    val = 1000.0
    out[0] = val
    for i in range(1, len(c)):
        moved = v[i] < v[i - 1] if negative else v[i] > v[i - 1]
        if moved and c[i - 1] != 0:
            val = val * float(c[i]) / float(c[i - 1])
        out[i] = val
    return out


def nvi(close: F64, volume: F64, signal: int = 255) -> tuple[F64, F64]:
    """Negative volume index (Fosback): starts at 1,000 and follows the price only on
    days volume fell (where "smart money" is said to act); signal = EMA."""
    x = _volume_index(close, volume, negative=True)
    return x, ema(x, signal)


def pvi(close: F64, volume: F64, signal: int = 255) -> tuple[F64, F64]:
    """Positive volume index: follows the price only on days volume rose."""
    x = _volume_index(close, volume, negative=False)
    return x, ema(x, signal)


def pvt(close: F64, volume: F64) -> F64:
    """Price-volume trend: running total of volume × % change of the close."""
    c, v = _arr(close), _arr(volume)
    step = np.zeros(len(c))
    if len(c) > 1:
        step[1:] = _div(v[1:] * (c[1:] - c[:-1]), c[:-1], 0.0)
    out: F64 = np.cumsum(step)
    return out


def rvol(volume: F64, n: int = 20) -> F64:
    """Relative volume: today's volume ÷ the average of the previous n candles' volume.
    No earlier volume → 1 (normal)."""
    v = _arr(volume)
    return _div(v, _shift(sma(v, n), 1), 1.0)


# ---------------------------------------------------------------- pivot variants


def pivots_fib(
    high: F64, low: F64, close: F64, session: I64
) -> tuple[F64, F64, F64, F64, F64, F64, F64]:
    """Fibonacci pivots from the previous session: P = (H+L+C)/3; R/S = P ± 0.382, 0.618
    and 1.0 × (H − L). (P, R1, R2, R3, S1, S2, S3)."""
    ph, pl, pc = previous_day(high, low, close, session)
    p = (ph + pl + pc) / 3.0
    r = ph - pl
    return p, p + 0.382 * r, p + 0.618 * r, p + r, p - 0.382 * r, p - 0.618 * r, p - r


CAMARILLA = (1.1 / 12.0, 1.1 / 6.0, 1.1 / 4.0, 1.1 / 2.0)


def pivots_camarilla(
    high: F64, low: F64, close: F64, session: I64
) -> tuple[F64, F64, F64, F64, F64, F64, F64, F64]:
    """Camarilla pivots: previous close ± (H − L) × 1.1/12, 1.1/6, 1.1/4, 1.1/2.
    (R1, R2, R3, R4, S1, S2, S3, S4). Intraday traders fade R3/S3 and follow R4/S4."""
    ph, pl, pc = previous_day(high, low, close, session)
    r = ph - pl
    ups = tuple(pc + k * r for k in CAMARILLA)
    dns = tuple(pc - k * r for k in CAMARILLA)
    return (*ups, *dns)  # type: ignore[return-value]


def pivots_woodie(
    high: F64, low: F64, close: F64, session: I64
) -> tuple[F64, F64, F64, F64, F64, F64, F64]:
    """Woodie pivots: P = (H + L + 2C)/4 (the close counts double); R1 = 2P − L,
    S1 = 2P − H, R2 = P + (H − L), S2 = P − (H − L), R3 = H + 2(P − L), S3 = L − 2(H − P)."""
    ph, pl, pc = previous_day(high, low, close, session)
    p = (ph + pl + 2.0 * pc) / 4.0
    return (
        p,
        2 * p - pl,
        p + (ph - pl),
        ph + 2 * (p - pl),
        2 * p - ph,
        p - (ph - pl),
        pl - 2 * (ph - p),
    )
