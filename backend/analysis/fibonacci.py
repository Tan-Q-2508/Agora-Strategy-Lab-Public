"""Fibonacci retracements and extensions of the last big move (KAIROS §3).

The leg is the last completed swing-to-swing move of the major zig-zag (or, if the price
has since gone beyond it, the move to the current extreme). Retracements 23.6%, 38.2%,
50%, 61.8% and 78.6% are where pullbacks often pause; extensions 127.2% and 161.8% are
common targets once the old extreme breaks.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.analysis.swings import Swing

RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTEND = (1.272, 1.618)


@dataclass(frozen=True)
class FibLevel:
    ratio: float
    price: float
    label: str


@dataclass(frozen=True)
class Fibonacci:
    start: Swing
    end: Swing
    up: bool  # the leg went up (retracements are below its top)
    levels: tuple[FibLevel, ...]
    nearest: FibLevel | None  # the level the price sits closest to (within 0.5 ATR)


def from_swings(swings: list[Swing], close_now: float, atr_now: float) -> Fibonacci | None:
    if len(swings) < 2:
        return None
    a, b = swings[-2], swings[-1]
    leg = b.price - a.price
    if leg == 0:
        return None
    up = leg > 0
    levels = [FibLevel(r, b.price - r * leg, f"{r * 100:.1f}%") for r in RETRACE]
    levels += [FibLevel(r, a.price + r * leg, f"{r * 100:.1f}%") for r in EXTEND]
    near = min(levels, key=lambda lv: abs(lv.price - close_now))
    nearest = near if atr_now > 0 and abs(near.price - close_now) <= 0.5 * atr_now else None
    return Fibonacci(a, b, up, tuple(levels), nearest)
