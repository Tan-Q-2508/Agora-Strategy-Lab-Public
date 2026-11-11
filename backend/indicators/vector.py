"""Indicators over a whole history at once (used by backtests and charts).

Every function returns arrays as long as its input, with NaN where there isn't enough
history yet ("warm-up"). Value ``i`` only ever uses inputs ``0..i``: no look-ahead, which
``tests/golden/test_indicators.py`` proves by recomputing on truncated histories.

Conventions (the same as TA-Lib/TradingView unless noted; golden tests pin each one):
- EMA seeds with the simple average of its first ``n`` values.
- "Wilder" smoothing (RSI, ATR, ADX) seeds with a simple average, then
  ``avg = (avg × (n − 1) + x) / n``.
- True range of the first bar is high − low (there's no previous close).
- Standard deviation is the population one (÷ n), like Bollinger's original.
- Divisions by zero give a neutral value, documented per indicator, never inf/NaN.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from backend.indicators.series import F64, I64

NAN = math.nan
YEAR_MS = 365 * 86_400_000


def _arr(x: F64 | list[float]) -> F64:
    return np.asarray(x, dtype=np.float64)


def _nan(n: int) -> F64:
    return np.full(n, NAN, dtype=np.float64)


def _first_valid(x: F64) -> int:
    """Index of the first non-NaN value (len(x) if none)."""
    valid = np.flatnonzero(~np.isnan(x))
    return int(valid[0]) if len(valid) else len(x)


def _check(n: int, name: str = "period") -> None:
    if n < 1:
        raise ValueError(f"{name} must be at least 1")


# ---------------------------------------------------------------- moving averages


def sma(x: F64, n: int) -> F64:
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) >= n:
        out[n - 1 :] = sliding_window_view(x, n).mean(axis=1)
    return out


def ema(x: F64, n: int) -> F64:
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    f = _first_valid(x)
    if len(x) - f < n:
        return out
    alpha = 2.0 / (n + 1.0)
    e = float(np.mean(x[f : f + n]))
    out[f + n - 1] = e
    for i in range(f + n, len(x)):
        e = alpha * x[i] + (1.0 - alpha) * e
        out[i] = e
    return out


def rma(x: F64, n: int) -> F64:
    """Wilder's moving average."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    f = _first_valid(x)
    if len(x) - f < n:
        return out
    a = float(np.mean(x[f : f + n]))
    out[f + n - 1] = a
    for i in range(f + n, len(x)):
        a = (a * (n - 1) + x[i]) / n
        out[i] = a
    return out


def wma(x: F64, n: int) -> F64:
    """Linearly weighted: the newest value has weight n, the oldest weight 1."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) >= n:
        w = np.arange(1, n + 1, dtype=np.float64)
        out[n - 1 :] = sliding_window_view(x, n) @ w / w.sum()
    return out


# ---------------------------------------------------------------- oscillators


def rsi(x: F64, n: int = 14) -> F64:
    """Wilder's RSI. First value at index n. Flat history (no gains, no losses) → 50;
    gains only → 100."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    f = _first_valid(x)
    if len(x) - f <= n:
        return out
    d = np.diff(x[f:])
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag = float(np.mean(gains[:n]))
    al = float(np.mean(losses[:n]))
    out[f + n] = _rsi_value(ag, al)
    for j in range(n, len(d)):
        ag = (ag * (n - 1) + gains[j]) / n
        al = (al * (n - 1) + losses[j]) / n
        out[f + j + 1] = _rsi_value(ag, al)
    return out


def _rsi_value(ag: float, al: float) -> float:
    if al == 0.0:
        return 50.0 if ag == 0.0 else 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def macd(x: F64, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[F64, F64, F64]:
    """(macd line, signal line, histogram)."""
    line = ema(x, fast) - ema(x, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def stochastic(
    high: F64, low: F64, close: F64, k: int = 14, smooth: int = 3, d: int = 3
) -> tuple[F64, F64]:
    """Slow stochastic (%K smoothed by ``smooth``, %D = SMA of %K over ``d``).
    A flat range (highest == lowest) gives 50."""
    _check(k)
    hh = rolling_max(high, k)
    ll = rolling_min(low, k)
    rng = hh - ll
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(rng > 0, 100.0 * (close - ll) / rng, 50.0)
    raw[np.isnan(hh)] = NAN
    slow_k = sma_nan(raw, smooth)
    return slow_k, sma_nan(slow_k, d)


def sma_nan(x: F64, n: int) -> F64:
    """SMA that starts once ``n`` valid values exist (for chaining after a warm-up)."""
    x = _arr(x)
    out = _nan(len(x))
    f = _first_valid(x)
    out[f:] = sma(x[f:], n)
    return out


def cci(high: F64, low: F64, close: F64, n: int = 20) -> F64:
    """(typical − SMA) / (0.015 × mean deviation). Zero deviation → 0."""
    _check(n)
    tp = (_arr(high) + _arr(low) + _arr(close)) / 3.0
    out = _nan(len(tp))
    if len(tp) < n:
        return out
    win = sliding_window_view(tp, n)
    mean = win.mean(axis=1)
    md = np.abs(win - mean[:, None]).mean(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        val = np.where(md > 0, (tp[n - 1 :] - mean) / (0.015 * md), 0.0)
    out[n - 1 :] = val
    return out


def roc(x: F64, n: int = 12) -> F64:
    """Rate of change in percent versus ``n`` bars ago."""
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) > n:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[n:] = np.where(x[:-n] != 0, 100.0 * (x[n:] / x[:-n] - 1.0), 0.0)
    return out


# ---------------------------------------------------------------- volatility & bands


def true_range(high: F64, low: F64, close: F64) -> F64:
    h, lo, c = _arr(high), _arr(low), _arr(close)
    tr = h - lo
    if len(tr) > 1:
        prev = c[:-1]
        tr[1:] = np.maximum.reduce([h[1:] - lo[1:], np.abs(h[1:] - prev), np.abs(lo[1:] - prev)])
    return tr


def atr(high: F64, low: F64, close: F64, n: int = 14) -> F64:
    """Wilder ATR; the first value (index n − 1) is the average of the first n true ranges."""
    return rma(true_range(high, low, close), n)


def stdev(x: F64, n: int) -> F64:
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) >= n:
        out[n - 1 :] = sliding_window_view(x, n).std(axis=1)
    return out


def bollinger(x: F64, n: int = 20, k: float = 2.0) -> tuple[F64, F64, F64]:
    """(middle, upper, lower) with population standard deviation."""
    mid = sma(x, n)
    sd = stdev(x, n)
    return mid, mid + k * sd, mid - k * sd


def keltner(
    high: F64, low: F64, close: F64, n: int = 20, k: float = 2.0, atr_n: int = 10
) -> tuple[F64, F64, F64]:
    """(middle = EMA(close, n), upper, lower = middle ± k × ATR(atr_n))."""
    mid = ema(close, n)
    a = atr(high, low, close, atr_n)
    return mid, mid + k * a, mid - k * a


def rolling_max(x: F64, n: int) -> F64:
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) >= n:
        out[n - 1 :] = sliding_window_view(x, n).max(axis=1)
    return out


def rolling_min(x: F64, n: int) -> F64:
    _check(n)
    x = _arr(x)
    out = _nan(len(x))
    if len(x) >= n:
        out[n - 1 :] = sliding_window_view(x, n).min(axis=1)
    return out


def donchian(high: F64, low: F64, n: int = 20) -> tuple[F64, F64, F64]:
    """(upper, middle, lower) over the last n bars, including the current one."""
    up = rolling_max(high, n)
    lo = rolling_min(low, n)
    return up, (up + lo) / 2.0, lo


# ---------------------------------------------------------------- trend


def adx(high: F64, low: F64, close: F64, n: int = 14) -> tuple[F64, F64, F64]:
    """(ADX, +DI, −DI), Wilder. DI from index n, ADX from index 2n − 1."""
    _check(n)
    h, lo = _arr(high), _arr(low)
    size = len(h)
    out_adx, out_p, out_m = _nan(size), _nan(size), _nan(size)
    if size <= n:
        return out_adx, out_p, out_m
    up = h[1:] - h[:-1]
    dn = lo[:-1] - lo[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(high, low, close)[1:]
    s_tr, s_p, s_m = rma(tr, n), rma(pdm, n), rma(mdm, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = np.where(s_tr > 0, 100.0 * s_p / s_tr, 0.0)
        mdi = np.where(s_tr > 0, 100.0 * s_m / s_tr, 0.0)
        tot = pdi + mdi
        dx = np.where(tot > 0, 100.0 * np.abs(pdi - mdi) / tot, 0.0)
    pdi[np.isnan(s_tr)] = NAN
    mdi[np.isnan(s_tr)] = NAN
    dx[np.isnan(s_tr)] = NAN
    out_p[1:] = pdi
    out_m[1:] = mdi
    out_adx[1:] = rma(dx, n)
    return out_adx, out_p, out_m


def supertrend(high: F64, low: F64, close: F64, n: int = 10, mult: float = 3.0) -> tuple[F64, F64]:
    """(line, direction): direction +1 = uptrend (line is the lower band, a trailing
    support), −1 = downtrend (line is the upper band). The first bar with an ATR starts
    up if it closed above its mid-point (hl2), else down."""
    h, lo, c = _arr(high), _arr(low), _arr(close)
    size = len(c)
    line, direction = _nan(size), _nan(size)
    a = atr(h, lo, c, n)
    s = _first_valid(a)
    if s >= size:
        return line, direction
    hl2 = (h + lo) / 2.0
    up_b = hl2 + mult * a
    dn_b = hl2 - mult * a
    fu, fd = up_b[s], dn_b[s]
    d = 1.0 if c[s] > hl2[s] else -1.0
    line[s], direction[s] = (fd if d > 0 else fu), d
    for i in range(s + 1, size):
        nfu = up_b[i] if (up_b[i] < fu or c[i - 1] > fu) else fu
        nfd = dn_b[i] if (dn_b[i] > fd or c[i - 1] < fd) else fd
        if d < 0:
            d = 1.0 if c[i] > nfu else -1.0
        else:
            d = -1.0 if c[i] < nfd else 1.0
        fu, fd = nfu, nfd
        line[i], direction[i] = (fd if d > 0 else fu), d
    return line, direction


# ---------------------------------------------------------------- volume


def obv(close: F64, volume: F64) -> F64:
    """On-balance volume, starting at 0 on the first bar."""
    c, v = _arr(close), _arr(volume)
    out = np.zeros(len(c), dtype=np.float64)
    if len(c) > 1:
        step = np.where(c[1:] > c[:-1], v[1:], np.where(c[1:] < c[:-1], -v[1:], 0.0))
        out[1:] = np.cumsum(step)
    return out


def vwap(high: F64, low: F64, close: F64, volume: F64, session: I64) -> F64:
    """Session-anchored VWAP of the typical price; resets each session. While a session
    has no volume yet, it equals the typical price."""
    tp = (_arr(high) + _arr(low) + _arr(close)) / 3.0
    v = _arr(volume)
    out = _nan(len(tp))
    pv = vol = 0.0
    prev = None
    for i in range(len(tp)):
        if session[i] != prev:
            pv = vol = 0.0
            prev = session[i]
        pv += tp[i] * v[i]
        vol += v[i]
        out[i] = pv / vol if vol > 0 else tp[i]
    return out


# ---------------------------------------------------------------- levels


def high_52w(high: F64, ts: I64) -> F64:
    """Highest high over the past 365 days (including today). NaN until a full year
    of history exists, so "near a 52-week high" means what it says."""
    return _time_extreme(_arr(high), ts, YEAR_MS, is_max=True)


def low_52w(low: F64, ts: I64) -> F64:
    return _time_extreme(_arr(low), ts, YEAR_MS, is_max=False)


def _time_extreme(x: F64, ts: I64, window_ms: int, *, is_max: bool) -> F64:
    out = _nan(len(x))
    if not len(x):
        return out
    q: deque[int] = deque()
    t0 = int(ts[0])
    for i in range(len(x)):
        while q and (x[q[-1]] <= x[i] if is_max else x[q[-1]] >= x[i]):
            q.pop()
        q.append(i)
        while int(ts[q[0]]) <= int(ts[i]) - window_ms:
            q.popleft()
        if int(ts[i]) - t0 >= window_ms - 86_400_000:
            out[i] = x[q[0]]
    return out


def previous_day(high: F64, low: F64, close: F64, session: I64) -> tuple[F64, F64, F64]:
    """(high, low, close) of the previous session. NaN during the first session."""
    h, lo, c = _arr(high), _arr(low), _arr(close)
    size = len(c)
    ph, pl, pc = _nan(size), _nan(size), _nan(size)
    cur_h, cur_l, cur_c = -math.inf, math.inf, NAN
    prev: tuple[float, float, float] | None = None
    sid = None
    for i in range(size):
        if session[i] != sid:
            if sid is not None:
                prev = (cur_h, cur_l, cur_c)
            sid = session[i]
            cur_h, cur_l = -math.inf, math.inf
        cur_h = max(cur_h, h[i])
        cur_l = min(cur_l, lo[i])
        cur_c = c[i]
        if prev is not None:
            ph[i], pl[i], pc[i] = prev
    return ph, pl, pc


def opening_range(
    high: F64,
    low: F64,
    ts: I64,
    session: I64,
    session_open: I64,
    bar_minutes: int,
    minutes: int = 15,
) -> tuple[F64, F64]:
    """(high, low) of the first ``minutes`` of each session. Known from the bar that
    completes the range onwards; NaN before that (and on daily bars)."""
    h, lo = _arr(high), _arr(low)
    size = len(h)
    oh, ol = _nan(size), _nan(size)
    if bar_minutes >= 1440:
        return oh, ol  # a daily candle has no "first 15 minutes"
    span = minutes * 60_000
    bar = bar_minutes * 60_000
    sid = None
    hi_v, lo_v = -math.inf, math.inf
    done = False
    for i in range(size):
        if session[i] != sid:
            sid = session[i]
            hi_v, lo_v, done = -math.inf, math.inf, False
        start = int(session_open[i])
        if int(ts[i]) < start + span:
            hi_v = max(hi_v, h[i])
            lo_v = min(lo_v, lo[i])
            if int(ts[i]) + bar >= start + span:
                done = True
        elif not done and hi_v > -math.inf:
            done = True  # the range's last candle was missing; the range ended anyway
        if done:
            oh[i], ol[i] = hi_v, lo_v
    return oh, ol
