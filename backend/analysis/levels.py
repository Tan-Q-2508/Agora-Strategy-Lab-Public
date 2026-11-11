"""Support and resistance zones (KAIROS §3).

Prices where the market turned more than once tend to matter again: buyers who missed the
last low wait there, sellers who were trapped at the last high want out there. So a level
is a *cluster of swing turning points* within a small band (0.6 × ATR). Its strength grows
with the number of turns, big (major) turns, recent turns and heavy volume at the turns.
A level that used to be resistance and later held as support has "flipped", which traders
treat as extra confirmation.

Zones above the latest close are resistance, below it support; a close inside a zone means
the price is testing it right now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from backend.analysis.swings import Swing
from backend.indicators.series import F64

Role = Literal["support", "resistance", "testing"]
CLUSTER_TOL = 0.6  # × ATR: turns this close together are one level
MIN_HALF_WIDTH = 0.15  # × ATR: a single-point zone is drawn this thick on each side


@dataclass(frozen=True)
class Touch:
    index: int
    price: float
    kind: str  # "H" or "L"
    major: bool


@dataclass(frozen=True)
class Zone:
    low: float
    high: float
    center: float
    touches: tuple[Touch, ...]
    strength: int  # 0-100
    role: Role
    flipped: bool  # has acted as both support and resistance
    first_index: int
    last_index: int
    distance_atr: float  # from the latest close to the nearest edge (0 when inside)
    tags: tuple[str, ...] = field(default=())

    @property
    def count(self) -> int:
        return len(self.touches)


def _rvol_at(volume: F64, i: int) -> float:
    lo = max(0, i - 20)
    base = float(np.mean(volume[lo:i])) if i > lo else 0.0
    return float(volume[i]) / base if base > 0 else 1.0


def find_zones(
    minor: list[Swing],
    major: list[Swing],
    close_now: float,
    atr_now: float,
    last_index: int,
    volume: F64 | None = None,
    lookback: int = 400,
) -> list[Zone]:
    """All zones from swings in the last ``lookback`` candles, strongest first."""
    if atr_now <= 0 or not np.isfinite(atr_now):
        return []
    start = last_index - lookback
    major_keys = {(s.index, s.kind) for s in major}
    pts = [
        Touch(s.index, s.price, s.kind, (s.index, s.kind) in major_keys)
        for s in minor
        if s.index >= start
    ]
    # Major swings the minor zig-zag merged away still count.
    seen = {(t.index, t.kind) for t in pts}
    pts += [
        Touch(s.index, s.price, s.kind, True)
        for s in major
        if s.index >= start and (s.index, s.kind) not in seen
    ]
    if not pts:
        return []
    pts.sort(key=lambda t: t.price)
    tol = CLUSTER_TOL * atr_now
    clusters: list[list[Touch]] = [[pts[0]]]
    for t in pts[1:]:
        cur = clusters[-1]
        if t.price - cur[-1].price <= tol and t.price - cur[0].price <= 2 * tol:
            cur.append(t)
        else:
            clusters.append([t])
    zones = [_zone(c, close_now, atr_now, last_index, lookback, volume) for c in clusters]
    return sorted(zones, key=lambda z: -z.strength)


def _zone(
    c: list[Touch],
    close_now: float,
    atr_now: float,
    last_index: int,
    lookback: int,
    volume: F64 | None,
) -> Zone:
    prices = [t.price for t in c]
    # Recent turns pull the zone's centre towards them.
    weights = [1.0 + (t.index - (last_index - lookback)) / max(lookback, 1) for t in c]
    center = float(np.average(prices, weights=weights))
    half = MIN_HALF_WIDTH * atr_now
    low, high = min(min(prices), center - half), max(max(prices), center + half)
    kinds = {t.kind for t in c}
    majors = sum(t.major for t in c)
    last = max(t.index for t in c)
    recency = 1.0 - min(1.0, (last_index - last) / max(lookback, 1))
    vol_bonus = 0.0
    if volume is not None and len(volume):
        heavy = sum(_rvol_at(volume, t.index) >= 1.5 for t in c)
        vol_bonus = min(15.0, 7.5 * heavy)
    # Each extra touch adds less (the 5th matters less than the 2nd); max ≈ 100.
    strength = (
        45.0 * (1.0 - 0.6 ** len(c))
        + 15.0 * (1.0 - 0.5**majors)
        + 20.0 * recency
        + vol_bonus * (10.0 / 15.0)
    )
    flipped = len(kinds) == 2
    if flipped:
        strength += 10.0
    if close_now > high:
        role: Role = "support"
        dist = (close_now - high) / atr_now
    elif close_now < low:
        role = "resistance"
        dist = (low - close_now) / atr_now
    else:
        role, dist = "testing", 0.0
    tags: list[str] = []
    if flipped:
        tags.append("flipped")
    if majors:
        tags.append("major")
    return Zone(
        low=low,
        high=high,
        center=center,
        touches=tuple(sorted(c, key=lambda t: t.index)),
        strength=int(min(100.0, round(strength))),
        role=role,
        flipped=flipped,
        first_index=min(t.index for t in c),
        last_index=last,
        distance_atr=round(dist, 3),
        tags=tuple(tags),
    )


def key_zones(zones: list[Zone], per_side: int = 2, min_strength: int = 40) -> list[Zone]:
    """The zones worth drawing: the price's current test plus the nearest strong zones on
    each side (nearest first), so the chart shows what matters without clutter."""
    testing = [z for z in zones if z.role == "testing" and z.strength >= min_strength]
    sup = sorted(
        (z for z in zones if z.role == "support" and z.strength >= min_strength),
        key=lambda z: z.distance_atr,
    )[:per_side]
    res = sorted(
        (z for z in zones if z.role == "resistance" and z.strength >= min_strength),
        key=lambda z: z.distance_atr,
    )[:per_side]
    return testing[:1] + sup + res
