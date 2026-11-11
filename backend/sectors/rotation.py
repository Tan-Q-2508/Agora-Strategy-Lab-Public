"""Sector strength, rotation, breadth and booms, from member stocks' daily closes (D-98).

Pure functions over numpy arrays, so they are tested by hand. Everything uses closed daily
candles up to the last one.

- **Sector index**: the equal-weight average of its members' daily returns (each member counts
  the same, so one giant can't hide what the rest do), chained into a price line from 100.
- **Relative strength** (RS): the sector line divided by the market's (Nifty 50 / SPY).
- **Rotation** (after Julius de Kempenaer's Relative Rotation Graphs, the tool fund managers use
  to see money moving between sectors): *RS-ratio* = 100 × RS ÷ its 63-day average (above 100:
  beating the market lately); *RS-momentum* = 100 × RS-ratio ÷ RS-ratio 10 days ago (above
  100: getting stronger). Leading (both above 100) → weakening → lagging → improving → leading
  is the usual clockwise cycle.
- **Breadth**: the share of members above their 50-day and 200-day averages and at a 52-week
  high. A rise carried by most members is sturdier than one carried by two or three.
- **Boom** ("the whole sector blooms"): a 1-month return unusually high for this sector (z-score
  ≥ 1.5 against its own 3 years), most members taking part (≥ 60% above their 50-day average),
  beating the market, and trading busier than usual (≥ 1.2× the usual volume). **Slump** is the
  mirror. Booms are when a rising tide lifts most boats: the moment to look at the sector's
  stocks, not only the one in the news.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

F64 = np.ndarray
MONTH, QUARTER, YEAR = 21, 63, 252
BOOM_Z = 1.5
BOOM_BREADTH = 60.0
SLUMP_BREADTH = 30.0
BUSY = 1.2


@dataclass(frozen=True)
class Member:
    instrument_id: int
    symbol: str
    close: F64  # aligned to the common dates, NaN where missing
    volume: F64


def equal_weight(members: Sequence[Member]) -> F64:
    """The sector line (starts at 100): each day, the average return of members that have
    both that day's and the previous day's close."""
    if not members:
        return np.zeros(0)
    c = np.vstack([m.close for m in members])
    with np.errstate(invalid="ignore", divide="ignore"):
        r = c[:, 1:] / c[:, :-1] - 1.0
    r[~np.isfinite(r)] = np.nan
    counts = np.sum(np.isfinite(r), axis=0)
    mean = np.where(counts > 0, np.nansum(r, axis=0) / np.maximum(counts, 1), 0.0)
    out: F64 = np.r_[100.0, 100.0 * np.cumprod(1.0 + mean)]
    return out


def _ret(x: F64, n: int) -> float | None:
    if len(x) <= n or not np.isfinite(x[-1]) or not np.isfinite(x[-n - 1]) or x[-n - 1] <= 0:
        return None
    return float(x[-1] / x[-n - 1] - 1.0) * 100.0


def rotation(line: F64, bench: F64) -> tuple[float | None, float | None, str]:
    """(RS-ratio, RS-momentum, quadrant)."""
    if len(line) < QUARTER + 11 or len(bench) != len(line):
        return None, None, "unknown"
    with np.errstate(invalid="ignore", divide="ignore"):
        rs = line / bench
    if not np.all(np.isfinite(rs[-(QUARTER + 11) :])):
        return None, None, "unknown"

    def ratio_at(end: int) -> float:
        window = rs[end - QUARTER : end]
        return float(100.0 * rs[end - 1] / np.mean(window))

    n = len(rs)
    ratio = ratio_at(n)
    before = ratio_at(n - 10)
    mom = 100.0 * ratio / before
    if ratio >= 100 and mom >= 100:
        quad = "leading"
    elif ratio >= 100:
        quad = "weakening"
    elif mom < 100:
        quad = "lagging"
    else:
        quad = "improving"
    return round(ratio, 2), round(mom, 2), quad


def breadth(members: Sequence[Member]) -> dict[str, float | int]:
    above50 = above200 = highs = counted = 0
    for m in members:
        c = m.close[np.isfinite(m.close)]
        if len(c) < 50:
            continue
        counted += 1
        above50 += int(c[-1] > np.mean(c[-50:]))
        if len(c) >= 200:
            above200 += int(c[-1] > np.mean(c[-200:]))
        if len(c) >= YEAR:
            highs += int(c[-1] >= np.max(c[-YEAR:]) * 0.999)
    if counted == 0:
        return {"members": 0, "above50": 0.0, "above200": 0.0, "new_highs": 0}
    return {
        "members": counted,
        "above50": round(100.0 * above50 / counted, 1),
        "above200": round(100.0 * above200 / counted, 1),
        "new_highs": highs,
    }


def month_z(line: F64, years: int = 3) -> float | None:
    """How unusual the last month's return is for this line: z-score of the latest 21-day
    return against every 21-day return over the last ``years`` years."""
    look = min(len(line), years * YEAR + MONTH + 1)
    x = line[-look:]
    if len(x) < YEAR:
        return None
    rets = x[MONTH:] / x[:-MONTH] - 1.0
    hist = rets[:-1]
    sd = float(np.std(hist, ddof=1))
    if sd <= 0:
        return None
    return round(float((rets[-1] - np.mean(hist)) / sd), 2)


def busy(members: Sequence[Member]) -> float | None:
    """Members' total volume over the last 10 days ÷ their usual (last 60 days) × 10/60."""
    if not members:
        return None
    v = np.vstack([np.nan_to_num(m.volume) for m in members]).sum(axis=0)
    if len(v) < 70 or v[-70:-10].sum() <= 0:
        return None
    return round(float(v[-10:].mean() / v[-70:-10].mean()), 2)


@dataclass
class SectorReading:
    name: str
    members: int
    returns: dict[str, float | None]
    rs_ratio: float | None
    rs_momentum: float | None
    quadrant: str
    breadth: dict[str, float | int]
    month_z: float | None
    volume_ratio: float | None
    state: str  # boom, slump, strong, weak, neutral
    score: float  # for ranking: −100 … +100
    leaders: list[dict[str, Any]] = field(default_factory=list)
    laggards: list[dict[str, Any]] = field(default_factory=list)
    line: list[float] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "members": self.members,
            "returns": self.returns,
            "rs_ratio": self.rs_ratio,
            "rs_momentum": self.rs_momentum,
            "quadrant": self.quadrant,
            "breadth": self.breadth,
            "month_z": self.month_z,
            "volume_ratio": self.volume_ratio,
            "state": self.state,
            "score": self.score,
            "leaders": self.leaders,
            "laggards": self.laggards,
            "sentence": sentence(self),
        }


def read(name: str, members: Sequence[Member], bench: F64) -> SectorReading | None:
    """One sector's reading, or None with fewer than 2 members that have prices."""
    have = [m for m in members if np.sum(np.isfinite(m.close)) >= 60]
    if len(have) < 2:
        return None
    line = equal_weight(have)
    rets = {k: _ret(line, n) for k, n in (("1w", 5), ("1m", MONTH), ("3m", QUARTER), ("6m", 126))}
    ratio, mom, quad = rotation(line, bench)
    br = breadth(have)
    z = month_z(line)
    vol = busy(have)
    b50 = float(br["above50"])
    beat = quad in ("leading", "weakening")
    if z is not None and z >= BOOM_Z and b50 >= BOOM_BREADTH and beat and (vol or 0) >= BUSY:
        state = "boom"
    elif z is not None and z <= -BOOM_Z and b50 <= SLUMP_BREADTH and not beat:
        state = "slump"
    elif quad == "leading" and b50 >= 50:
        state = "strong"
    elif quad == "lagging" and b50 < 50:
        state = "weak"
    else:
        state = "neutral"
    m1 = rets["1m"] or 0.0
    score = float(
        np.clip(
            0.4 * np.tanh(m1 / 8.0) * 100
            + 0.3 * (b50 - 50.0) * 2
            + 0.3 * np.clip(((ratio or 100.0) - 100.0) * 10, -100, 100),
            -100,
            100,
        )
    )
    moves = []
    for m in have:
        r = _ret(m.close[np.isfinite(m.close)], MONTH)
        if r is not None:
            moves.append({"symbol": m.symbol, "instrument_id": m.instrument_id, "1m": round(r, 1)})
    moves.sort(key=lambda x: -float(x["1m"]))  # type: ignore[arg-type]
    return SectorReading(
        name=name,
        members=len(have),
        returns={k: (round(v, 2) if v is not None else None) for k, v in rets.items()},
        rs_ratio=ratio,
        rs_momentum=mom,
        quadrant=quad,
        breadth=br,
        month_z=z,
        volume_ratio=vol,
        state=state,
        score=round(score, 1),
        leaders=moves[:5],
        laggards=list(reversed(moves[-3:])) if len(moves) > 5 else [],
        line=[round(float(x), 2) for x in line[-QUARTER:]],
    )


def sentence(r: SectorReading) -> str:
    m1 = r.returns.get("1m")
    b = r.breadth.get("above50", 0)
    lead = ", ".join(str(x["symbol"]) for x in r.leaders[:3])
    month = f"{m1:+.1f}% this month" if m1 is not None else "too new to measure"
    if r.state == "boom":
        return (
            f"{r.name} is booming: {month}, unusually strong for this sector (z {r.month_z:+.1f}), "
            f"with {b:.0f}% of its stocks above their 50-day average and trading "
            f"{r.volume_ratio:.1f}× the usual volume. Leaders: {lead}."
        )
    if r.state == "slump":
        return (
            f"{r.name} is slumping: {month}, unusually weak (z {r.month_z:+.1f}); only "
            f"{b:.0f}% of its stocks are above their 50-day average."
        )
    quad = {
        "leading": "beating the market and gaining",
        "weakening": "beating the market but fading",
        "lagging": "trailing the market and losing ground",
        "improving": "trailing the market but catching up",
        "unknown": "too new to compare",
    }[r.quadrant]
    return f"{r.name}: {month}, {quad}; {b:.0f}% of its stocks above their 50-day average."


def rank(readings: Mapping[str, SectorReading]) -> list[SectorReading]:
    order = {"boom": 0, "strong": 1, "neutral": 2, "weak": 3, "slump": 4}
    return sorted(readings.values(), key=lambda r: (order.get(r.state, 2), -r.score, r.name))
