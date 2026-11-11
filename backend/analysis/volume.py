"""Volume: is the crowd behind the move? (KAIROS §3)

- **Relative volume** (RVOL): today's volume ÷ the average of the previous 20 candles.
  2× or more is a spike: something happened.
- **Accumulation / distribution days** (last 25 candles): a close up (or down) at least
  0.2% on higher volume than the candle before. Many distribution days warn that big
  holders are selling into strength.
- **OBV divergence**: on-balance volume rising while the price falls (accumulation) or
  the reverse (distribution), over 20 candles.
- **Chaikin money flow** (20): above +0.1 buying pressure, below −0.1 selling pressure.

The score (−1 … +1) leans bullish on accumulation, positive money flow and rising OBV.
Volumes of 0 everywhere (some indices) give a neutral reading.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.analysis.trend import slope
from backend.indicators import vector as vx
from backend.indicators import vector_extra as vxx
from backend.indicators.series import F64


def rvol(volume: F64, n: int = 20) -> F64:
    """Volume ÷ the mean of the previous ``n`` candles (NaN when there's no history)."""
    v = np.asarray(volume, dtype=np.float64)
    out = np.full(len(v), np.nan)
    if len(v) <= n:
        return out
    base = np.lib.stride_tricks.sliding_window_view(v, n)[:-1].mean(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[n:] = np.where(base > 0, v[n:] / np.where(base > 0, base, 1.0), np.nan)
    return out


@dataclass(frozen=True)
class VolumeState:
    has_volume: bool
    rvol: float
    spikes: tuple[int, ...]  # candle indices with RVOL ≥ 2 in the last 20 candles
    accumulation_days: int
    distribution_days: int
    obv_divergence: int  # +1 bullish, −1 bearish, 0 none
    cmf: float
    score: float
    notes: tuple[str, ...]


class VolumeArrays:
    def __init__(self, high: F64, low: F64, close: F64, volume: F64) -> None:
        self.close = np.asarray(close, dtype=np.float64)
        self.volume = np.asarray(volume, dtype=np.float64)
        self.rvol = rvol(self.volume)
        self.obv_slope = slope(vx.obv(close, volume), 20)
        self.price_slope = slope(self.close, 20)
        self.cmf = vxx.cmf(high, low, close, volume, 20)
        prev_c = np.concatenate([[np.nan], self.close[:-1]])
        prev_v = np.concatenate([[np.nan], self.volume[:-1]])
        with np.errstate(invalid="ignore"):
            chg = self.close / prev_c - 1.0
            heavier = self.volume > prev_v
        self.acc = (chg >= 0.002) & heavier
        self.dist = (chg <= -0.002) & heavier

    def state(self, i: int) -> VolumeState:
        lo = max(0, i - 24)
        has = bool(self.volume[max(0, i - 50) : i + 1].sum() > 0)
        if not has:
            return VolumeState(False, float("nan"), (), 0, 0, 0, 0.0, 0.0, ())
        r = float(self.rvol[i]) if np.isfinite(self.rvol[i]) else 1.0
        spikes = tuple(
            int(k)
            for k in range(max(0, i - 19), i + 1)
            if np.isfinite(self.rvol[k]) and self.rvol[k] >= 2
        )
        acc = int(self.acc[lo : i + 1].sum())
        dist = int(self.dist[lo : i + 1].sum())
        div = 0
        ps, os_ = self.price_slope[i], self.obv_slope[i]
        if np.isfinite(ps) and np.isfinite(os_):
            if ps < 0 < os_:
                div = 1
            elif ps > 0 > os_:
                div = -1
        cmf = float(self.cmf[i]) if np.isfinite(self.cmf[i]) else 0.0
        parts = [
            float(np.clip((acc - dist) / 5.0, -1.0, 1.0)),
            float(np.clip(cmf / 0.2, -1.0, 1.0)),
            float(div),
        ]
        notes: list[str] = []
        if r >= 2:
            notes.append(f"Volume is {r:.1f}× its recent average")
        if dist >= 5 and dist > acc:
            notes.append(
                f"{dist} distribution days in the last 25 candles: heavy selling into rises"
            )
        if acc >= 5 and acc > dist:
            notes.append(f"{acc} accumulation days in the last 25 candles: steady buying")
        if div > 0:
            notes.append("On-balance volume is rising while the price falls (quiet accumulation)")
        elif div < 0:
            notes.append("On-balance volume is falling while the price rises (quiet distribution)")
        return VolumeState(
            has_volume=True,
            rvol=round(r, 2),
            spikes=spikes,
            accumulation_days=acc,
            distribution_days=dist,
            obv_divergence=div,
            cmf=round(cmf, 3),
            score=round(float(np.mean(parts)), 3),
            notes=tuple(notes),
        )
