"""Trend regime and momentum (KAIROS §3).

The trend score (−100 … +100) blends four things a trader checks at a glance:

- **Moving-average stack** (35%): close vs EMA 20, EMA 20 vs SMA 50, SMA 50 vs SMA 200,
  close vs SMA 200: each +1 or −1, averaged.
- **Swing structure** (25%): the last two swing highs and lows: higher highs and higher
  lows = +1, lower highs and lower lows = −1, mixed = 0.
- **Slope** (25%): the regression slope of the last 50 closes over 20 candles, in ATRs,
  capped at ±3 ATR → ±1.
- **Direction lines** (15%): +DI above −DI = +1, below = −1.

When ADX is under 20 (no real trend) the score is shrunk by 30%. Labels: ≥ 60 strong
uptrend, ≥ 25 uptrend, > −25 sideways, > −60 downtrend, else strong downtrend.

Momentum (−1 … +1) reads RSI, MACD and the stochastic the usual way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from backend.analysis.swings import Swing
from backend.indicators import vector as vx
from backend.indicators.series import F64

Regime = Literal["strong uptrend", "uptrend", "sideways", "downtrend", "strong downtrend"]


def regime_of(score: float) -> Regime:
    if score >= 60:
        return "strong uptrend"
    if score >= 25:
        return "uptrend"
    if score > -25:
        return "sideways"
    if score > -60:
        return "downtrend"
    return "strong downtrend"


def structure(swings: list[Swing]) -> int:
    """+1 higher highs and higher lows, −1 lower highs and lower lows, else 0."""
    highs = [s.price for s in swings if s.kind == "H"][-2:]
    lows = [s.price for s in swings if s.kind == "L"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return 0
    if highs[1] > highs[0] and lows[1] > lows[0]:
        return 1
    if highs[1] < highs[0] and lows[1] < lows[0]:
        return -1
    return 0


def slope(close: F64, n: int = 50) -> F64:
    """Least-squares slope of the last ``n`` closes at every candle (price per candle)."""
    c = np.asarray(close, dtype=np.float64)
    out = np.full(len(c), np.nan)
    if len(c) < n:
        return out
    x = np.arange(n, dtype=np.float64)
    xm = x - x.mean()
    denom = float((xm**2).sum())
    win = np.lib.stride_tricks.sliding_window_view(c, n)
    out[n - 1 :] = (win - win.mean(axis=1, keepdims=True)) @ xm / denom
    return out


@dataclass(frozen=True)
class TrendState:
    score: float
    regime: Regime
    ma_stack: float
    structure: int
    slope_atr: float
    adx: float
    plus_di: float
    minus_di: float
    ema20: float
    sma50: float
    sma200: float
    atr: float
    atr_pct: float
    volatility: Literal["calm", "normal", "wild"]


class TrendArrays:
    """Every input of the trend score as whole-history arrays (computed once)."""

    def __init__(self, high: F64, low: F64, close: F64) -> None:
        self.close = np.asarray(close, dtype=np.float64)
        self.ema20 = vx.ema(self.close, 20)
        self.sma50 = vx.sma(self.close, 50)
        self.sma200 = vx.sma(self.close, 200)
        self.adx, self.pdi, self.mdi = vx.adx(high, low, close, 14)
        self.atr = vx.atr(high, low, close, 14)
        self.slope = slope(self.close, 50)

    def ma_stack(self, i: int) -> float:
        c = self.close[i]
        votes = [
            (c, self.ema20[i]),
            (self.ema20[i], self.sma50[i]),
            (self.sma50[i], self.sma200[i]),
            (c, self.sma200[i]),
        ]
        vals = [1.0 if a > b else -1.0 for a, b in votes if np.isfinite(a) and np.isfinite(b)]
        return float(np.mean(vals)) if vals else 0.0

    def score(self, i: int, struct: int) -> float:
        a = self.atr[i]
        sl = 0.0
        if np.isfinite(self.slope[i]) and np.isfinite(a) and a > 0:
            sl = float(np.clip(self.slope[i] * 20 / a / 3.0, -1.0, 1.0))
        di = 0.0
        if np.isfinite(self.pdi[i]) and np.isfinite(self.mdi[i]):
            di = 1.0 if self.pdi[i] > self.mdi[i] else -1.0 if self.pdi[i] < self.mdi[i] else 0.0
        raw = 0.35 * self.ma_stack(i) + 0.25 * struct + 0.25 * sl + 0.15 * di
        if np.isfinite(self.adx[i]) and self.adx[i] < 20:
            raw *= 0.7
        return float(round(100.0 * raw, 1))

    def state(self, i: int, swings: list[Swing]) -> TrendState:
        st = structure(swings)
        score = self.score(i, st)
        a = float(self.atr[i]) if np.isfinite(self.atr[i]) else 0.0
        c = float(self.close[i])
        pct = 100.0 * a / c if c else 0.0
        hist = 100.0 * self.atr[max(0, i - 250) : i + 1] / self.close[max(0, i - 250) : i + 1]
        hist = hist[np.isfinite(hist)]
        rank = float((hist < pct).mean()) if len(hist) > 20 else 0.5
        vol: Literal["calm", "normal", "wild"] = (
            "calm" if rank < 0.25 else "wild" if rank > 0.8 else "normal"
        )
        sl = float(self.slope[i] * 20 / a) if a > 0 and np.isfinite(self.slope[i]) else 0.0
        return TrendState(
            score=score,
            regime=regime_of(score),
            ma_stack=self.ma_stack(i),
            structure=st,
            slope_atr=round(sl, 2),
            adx=_f(self.adx[i]),
            plus_di=_f(self.pdi[i]),
            minus_di=_f(self.mdi[i]),
            ema20=_f(self.ema20[i]),
            sma50=_f(self.sma50[i]),
            sma200=_f(self.sma200[i]),
            atr=round(a, 4),
            atr_pct=round(pct, 2),
            volatility=vol,
        )


def _sign(x: float, eps: float = 1e-9) -> float:
    """−1, 0 or +1, treating floating-point dust as zero (NaN → 0)."""
    if not np.isfinite(x) or abs(x) <= eps:
        return 0.0
    return 1.0 if x > 0 else -1.0


def _f(x: float) -> float:
    return round(float(x), 4) if np.isfinite(x) else float("nan")


@dataclass(frozen=True)
class Momentum:
    score: float  # −1 … +1
    rsi: float
    rsi_state: Literal["overbought", "oversold", "strong", "weak", "neutral"]
    macd_above_signal: bool
    macd_hist_rising: bool
    stoch_k: float
    notes: tuple[str, ...]


class MomentumArrays:
    def __init__(self, high: F64, low: F64, close: F64) -> None:
        self.rsi = vx.rsi(close, 14)
        self.macd, self.signal, self.hist = vx.macd(close, 12, 26, 9)
        self.k, self.d = vx.stochastic(high, low, close, 14, 3, 3)

    def score(self, i: int) -> float:
        parts: list[float] = []
        r = self.rsi[i]
        if np.isfinite(r):
            parts.append(float(np.clip((r - 50.0) / 25.0, -1.0, 1.0)))
        if np.isfinite(self.hist[i]):
            # Equal lines (a perfectly steady move) are neutral, not bearish.
            change = self.hist[i] - self.hist[i - 1] if i > 0 else 0.0
            parts.append(0.6 * _sign(self.hist[i]) + 0.4 * _sign(change))
        if np.isfinite(self.k[i]) and np.isfinite(self.d[i]):
            parts.append(0.5 * _sign(self.k[i] - self.d[i]))
        return float(np.mean(parts)) if parts else 0.0

    def state(self, i: int) -> Momentum:
        r = float(self.rsi[i]) if np.isfinite(self.rsi[i]) else 50.0
        if r >= 70:
            rs: Literal["overbought", "oversold", "strong", "weak", "neutral"] = "overbought"
        elif r <= 30:
            rs = "oversold"
        elif r >= 55:
            rs = "strong"
        elif r <= 45:
            rs = "weak"
        else:
            rs = "neutral"
        above = bool(np.isfinite(self.macd[i]) and self.macd[i] > self.signal[i])
        rising = bool(i > 0 and np.isfinite(self.hist[i - 1]) and self.hist[i] > self.hist[i - 1])
        notes: list[str] = []
        if i > 0 and np.isfinite(self.signal[i - 1]):
            was = self.macd[i - 1] > self.signal[i - 1]
            if above and not was:
                notes.append("MACD just crossed above its signal line")
            elif was and not above:
                notes.append("MACD just crossed below its signal line")
        return Momentum(
            score=round(self.score(i), 3),
            rsi=round(r, 1),
            rsi_state=rs,
            macd_above_signal=above,
            macd_hist_rising=rising,
            stoch_k=round(float(self.k[i]), 1) if np.isfinite(self.k[i]) else 50.0,
            notes=tuple(notes),
        )
