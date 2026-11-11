"""Swing highs and lows: the skeleton every chart reading is built on (KAIROS §3).

A zig-zag: a swing high is confirmed once the price has fallen ``mult`` × ATR below the
highest high since the last swing low (and the mirror for swing lows). Each swing records
the candle of the extreme *and* the candle where it was confirmed, because nobody can
know a top is a top until the price has turned. Anything that uses swings as "known at
candle i" must only use swings with ``confirmed <= i`` (no look-ahead).

Two degrees are used: ``MINOR`` (1.5 × ATR reversals, the small waves patterns are made
of) and ``MAJOR`` (3 × ATR, the big turns that make strong levels).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from backend.indicators import vector as vx
from backend.indicators.series import F64

Kind = Literal["H", "L"]
MINOR = 1.5
MAJOR = 3.0


@dataclass(frozen=True)
class Swing:
    index: int  # candle of the extreme
    price: float  # its high (H) or low (L)
    kind: Kind
    confirmed: int  # candle on which the reversal proved it; ``index`` <= ``confirmed``

    @property
    def is_high(self) -> bool:
        return self.kind == "H"


@dataclass(frozen=True)
class SwingSet:
    swings: tuple[Swing, ...]  # confirmed, alternating H/L, oldest first
    pending: Swing | None  # the current unconfirmed extreme (``confirmed`` = -1)
    mult: float

    def known_at(self, i: int) -> list[Swing]:
        """Swings confirmed on or before candle ``i``."""
        return [s for s in self.swings if s.confirmed <= i]

    def highs(self) -> list[Swing]:
        return [s for s in self.swings if s.is_high]

    def lows(self) -> list[Swing]:
        return [s for s in self.swings if not s.is_high]

    def with_pending(self) -> list[Swing]:
        return [*self.swings, self.pending] if self.pending else list(self.swings)


def reversal_size(high: F64, low: F64, close: F64, period: int = 14) -> F64:
    """ATR, with the running average true range standing in during ATR's warm-up so the
    first candles still get a sensible threshold (and no future value is ever used)."""
    tr = vx.true_range(high, low, close)
    a = vx.atr(high, low, close, period)
    early = np.cumsum(tr) / np.arange(1, len(tr) + 1)
    return np.where(np.isnan(a), early, a)


def find_swings(
    high: F64, low: F64, close: F64, mult: float = MINOR, atr: F64 | None = None
) -> SwingSet:
    """The zig-zag over the whole history. ``atr`` may be passed in to share work."""
    h = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    n = len(h)
    if n == 0:
        return SwingSet((), None, mult)
    size = reversal_size(h, lo, np.asarray(close, dtype=np.float64)) if atr is None else atr
    out: list[Swing] = []
    hi_i, lo_i = 0, 0  # candidate extremes
    direction = 0  # +1 looking for a high, -1 looking for a low, 0 undecided
    for i in range(1, n):
        thr = mult * float(size[i])
        if direction >= 0 and h[i] > h[hi_i]:
            hi_i = i
        if direction <= 0 and lo[i] < lo[lo_i]:
            lo_i = i
        if direction == 0:
            if h[i] - lo[lo_i] >= thr and lo_i < i:
                out.append(Swing(lo_i, float(lo[lo_i]), "L", i))
                direction, hi_i = 1, i
            elif h[hi_i] - lo[i] >= thr and hi_i < i:
                out.append(Swing(hi_i, float(h[hi_i]), "H", i))
                direction, lo_i = -1, i
        elif direction == 1:
            if hi_i != i and h[hi_i] - lo[i] >= thr:
                out.append(Swing(hi_i, float(h[hi_i]), "H", i))
                direction, lo_i = -1, i
        elif lo_i != i and h[i] - lo[lo_i] >= thr:
            out.append(Swing(lo_i, float(lo[lo_i]), "L", i))
            direction, hi_i = 1, i
    pending: Swing | None = None
    if direction == 1:
        pending = Swing(hi_i, float(h[hi_i]), "H", -1)
    elif direction == -1:
        pending = Swing(lo_i, float(lo[lo_i]), "L", -1)
    return SwingSet(tuple(out), pending, mult)
