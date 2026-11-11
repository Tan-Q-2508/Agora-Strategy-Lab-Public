"""The regime map: what kind of market each candle was in (D-143, Phase 25.4).

Strategies have homes. A pullback-buying strategy earns in calm uptrends and bleeds in
volatile downtrends; a breakout strategy needs volatility. Before this map, Agora judged a
strategy on its average over all years, so a strategy that is excellent in one kind of
market and poor in another looked mediocre, and nothing could say "today suits it".

Two plain axes, each from that candle and the ones before it only (no look-ahead):

- **Trend**: ``up`` when the close is above its 200-candle average *and* the 50-candle average
  rose over the last 20 candles by more than half an ATR(14); ``down`` the mirror image;
  otherwise ``sideways``. Measuring the rise in ATRs makes it work the same on daily and
  minute candles, and keeps a flat, wiggling market from counting as a trend.
- **Volatility**: ``volatile`` when today's ATR(14) as a share of the price is in the top third
  of its own last 250 candles; otherwise ``calm``. Relative to the stock's own past, so a
  naturally jumpy stock isn't always "volatile".

Six regimes: up-calm, up-volatile, sideways-calm, sideways-volatile, down-calm,
down-volatile. Candles before there is enough history are ``None`` (unknown).
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from backend.indicators import vector as vx
from backend.indicators.series import F64, BarSeries

Trend = Literal["up", "sideways", "down"]
Vol = Literal["calm", "volatile"]
REGIMES = (
    "up-calm",
    "up-volatile",
    "sideways-calm",
    "sideways-volatile",
    "down-calm",
    "down-volatile",
)
WORDS = {
    "up-calm": "a calm uptrend",
    "up-volatile": "a jumpy uptrend",
    "sideways-calm": "a calm sideways market",
    "sideways-volatile": "a jumpy sideways market",
    "down-calm": "a calm downtrend",
    "down-volatile": "a jumpy downtrend",
}
LONG, MID, SLOPE_LAG, SLOPE_ATRS = 200, 50, 20, 0.5
ATR_N, VOL_WINDOW, VOL_TOP = 14, 250, 2.0 / 3.0
MIN_VOL_HISTORY = 60


def trend_axis(close: F64, high: F64 | None = None, low: F64 | None = None) -> list[Trend | None]:
    long = vx.sma(close, LONG)
    mid = vx.sma(close, MID)
    hi = close if high is None else high
    lo = close if low is None else low
    atr = vx.atr(hi, lo, close, ATR_N)
    out: list[Trend | None] = []
    for i, c in enumerate(close):
        if i < SLOPE_LAG or not np.isfinite(long[i]) or not np.isfinite(mid[i - SLOPE_LAG]):
            out.append(None)
            continue
        move = mid[i] - mid[i - SLOPE_LAG]
        band = SLOPE_ATRS * atr[i] if np.isfinite(atr[i]) else 0.0
        rising, falling = move > band, move < -band
        if c > long[i] and rising:
            out.append("up")
        elif c < long[i] and falling:
            out.append("down")
        else:
            out.append("sideways")
    return out


def vol_rank(high: F64, low: F64, close: F64) -> F64:
    """Today's ATR% as a share (0–1) of the last ``VOL_WINDOW`` candles' ATR% at or below it."""
    from numpy.lib.stride_tricks import sliding_window_view

    atr_pct = vx.atr(high, low, close, ATR_N) / close
    n = len(close)
    out = np.full(n, np.nan)
    finite = np.isfinite(atr_pct)
    # the short stretch before a full window: one at a time
    for i in range(min(n, VOL_WINDOW - 1)):
        if not finite[i]:
            continue
        window = atr_pct[: i + 1]
        window = window[np.isfinite(window)]
        if len(window) >= MIN_VOL_HISTORY:
            out[i] = float(np.mean(window <= atr_pct[i]))
    if n >= VOL_WINDOW:
        win = sliding_window_view(atr_pct, VOL_WINDOW)  # row k ends at candle k + W − 1
        today = atr_pct[VOL_WINDOW - 1 :]
        with np.errstate(invalid="ignore"):
            valid = np.isfinite(win)
            below = (win <= today[:, None]) & valid
            counts = valid.sum(axis=1)
            share = below.sum(axis=1) / np.maximum(counts, 1)
        ok = np.isfinite(today) & (counts >= MIN_VOL_HISTORY)
        out[VOL_WINDOW - 1 :] = np.where(ok, share, np.nan)
    return out


def vol_axis(high: F64, low: F64, close: F64) -> list[Vol | None]:
    rank = vol_rank(high, low, close)
    return [None if not np.isfinite(r) else ("volatile" if r > VOL_TOP else "calm") for r in rank]


def regimes(s: BarSeries) -> list[str | None]:
    """One regime per candle (``None`` while history is too short)."""
    t = trend_axis(s.close, s.high, s.low)
    v = vol_axis(s.high, s.low, s.close)
    return [None if a is None or b is None else f"{a}-{b}" for a, b in zip(t, v, strict=True)]


def at(s: BarSeries, ts: int) -> str | None:
    """The regime of the last candle that closed at or before ``ts`` (a trade's signal)."""
    idx = int(np.searchsorted(s.ts, ts, side="right")) - 1
    if idx < 0:
        return None
    return regimes(s.upto(idx + 1))[idx]


def lookup(s: BarSeries) -> dict[int, str | None]:
    """ts → regime, for tagging many trades of one stock at once."""
    return dict(zip((int(x) for x in s.ts), regimes(s), strict=True))
