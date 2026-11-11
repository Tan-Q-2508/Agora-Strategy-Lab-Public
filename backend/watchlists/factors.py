"""Factor watchlists worked out from saved daily prices (D-94).

The classic price factors quant firms build portfolios from, each a ranking of the stocks of
an index on their closed daily candles (no look-ahead, nothing but prices):

- **momentum (12-1)**: the rise from 12 months ago to 1 month ago (Jegadeesh & Titman 1993;
  the last month is left out because it tends to reverse);
- **low volatility**: the smallest standard deviation of daily returns over a year (the
  low-volatility anomaly: calm stocks have done as well as wild ones, with less risk);
- **near 52-week high**: the close as a share of the year's highest close (George & Hwang 2004);
- **trend**: price above a rising 50-day average above a rising 200-day average (the trend
  template of trend followers), ranked by distance above the 200-day average;
- **reversal**: the biggest fall over the last 5 days among stocks still above their 200-day
  average (the short-term reversal effect, Lehmann 1990);
- **relative strength**: the 3-month return minus the index's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

F64 = np.ndarray
YEAR, MONTH, QUARTER, WEEK = 252, 21, 63, 5
NEEDS = {
    "momentum": YEAR + 1,
    "low_volatility": YEAR + 1,
    "near_high": YEAR,
    "trend": 220,
    "reversal": 201,
    "relative_strength": QUARTER + 1,
}


@dataclass(frozen=True)
class Pick:
    instrument_id: int
    score: float
    note: str


def _sma(c: F64, n: int, back: int = 0) -> float:
    end = len(c) - back
    return float(np.mean(c[end - n : end]))


def score(factor: str, c: F64, bench: F64 | None = None) -> tuple[float, str] | None:
    """One stock's score (higher = better) and a short note, or None when it doesn't qualify."""
    if len(c) < NEEDS[factor] or not np.all(np.isfinite(c[-NEEDS[factor] :])) or c[-1] <= 0:
        return None
    if factor == "momentum":
        r = c[-MONTH - 1] / c[-YEAR - 1] - 1.0
        return float(r), f"{r * 100:+.0f}% from 12 to 1 months ago"
    if factor == "low_volatility":
        rets = np.diff(np.log(c[-YEAR - 1 :]))
        vol = float(np.std(rets, ddof=1) * np.sqrt(YEAR))
        return -vol, f"{vol * 100:.0f}% a year of swings"
    if factor == "near_high":
        hi = float(np.max(c[-YEAR:]))
        share = float(c[-1] / hi)
        return share, f"{(1 - share) * 100:.1f}% below its 52-week high"
    if factor == "trend":
        s50, s200 = _sma(c, 50), _sma(c, 200)
        rising = s50 > _sma(c, 50, back=20) and s200 > _sma(c, 200, back=20)
        if not (c[-1] > s50 > s200 and rising):
            return None
        gap = float(c[-1] / s200 - 1.0)
        return gap, f"{gap * 100:+.0f}% above its 200-day average, both averages rising"
    if factor == "reversal":
        if c[-1] <= _sma(c, 200):
            return None
        r = float(c[-1] / c[-WEEK - 1] - 1.0)
        if r >= 0:
            return None
        return -r, f"fell {abs(r) * 100:.1f}% this week, still above its 200-day average"
    if factor == "relative_strength":
        r = float(c[-1] / c[-QUARTER - 1] - 1.0)
        b = 0.0
        if bench is not None and len(bench) > QUARTER and bench[-QUARTER - 1] > 0:
            b = float(bench[-1] / bench[-QUARTER - 1] - 1.0)
        return r - b, f"{(r - b) * 100:+.0f}% vs the index over 3 months"
    raise ValueError(f"Unknown factor {factor}")


def rank(
    factor: str,
    closes: Mapping[int, F64],
    *,
    bench: F64 | None = None,
    top: int = 30,
) -> list[Pick]:
    """The ``top`` stocks by the factor (ties broken by instrument id, so it's repeatable)."""
    picks: list[Pick] = []
    for iid, c in closes.items():
        got = score(factor, c, bench)
        if got is not None:
            picks.append(Pick(iid, got[0], got[1]))
    picks.sort(key=lambda p: (-p.score, p.instrument_id))
    return picks[:top]
