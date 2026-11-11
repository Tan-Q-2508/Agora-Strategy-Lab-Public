"""Robustness tools (SPEC §6.4): in/out-of-sample split, parameter sweep, walk-forward.

They all reuse the single-run engine; this module only slices results and builds grids.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from backend.engine.types import EquityPoint, Trade
from backend.metrics import performance

MAX_CELLS = 100
DAY_MS = 86_400_000


def split_metrics(
    equity: Sequence[EquityPoint],
    trades: Sequence[Trade],
    capital: float,
    split_ts: int,
    tz: ZoneInfo,
) -> dict[str, Any]:
    """Metrics for the in-sample part (before ``split_ts``) and the out-of-sample part,
    each starting from the equity it inherited."""
    before = [p for p in equity if p.ts < split_ts]
    after = [p for p in equity if p.ts >= split_ts]
    start_after = before[-1].equity if before else capital

    def part(points: list[EquityPoint], start: float, ts: list[Trade]) -> dict[str, Any]:
        if not points:
            return {"empty": True}
        charges = sum(t.charges for t in ts)
        notional = sum(t.entry_price * t.qty * (2 if t.closed else 1) for t in ts)
        return performance.compute(
            points, ts, start, tz, charges_total=charges, traded_notional=notional
        )

    return {
        "split_ts": split_ts,
        "in_sample": part(before, capital, [t for t in trades if t.entry_ts < split_ts]),
        "out_of_sample": part(after, start_after, [t for t in trades if t.entry_ts >= split_ts]),
    }


@dataclass(frozen=True)
class SweepParam:
    name: str
    values: list[float]


def grid(params: Sequence[SweepParam]) -> list[dict[str, float]]:
    if not 1 <= len(params) <= 2:
        raise ValueError("A sweep varies one or two parameters.")
    cells = [
        dict(zip([p.name for p in params], combo, strict=True))
        for combo in itertools.product(*[p.values for p in params])
    ]
    if len(cells) > MAX_CELLS:
        raise ValueError(f"That's {len(cells)} combinations; the limit is {MAX_CELLS}.")
    return cells


def frange(lo: float, hi: float, step: float) -> list[float]:
    if step <= 0 or hi < lo:
        raise ValueError("The range needs a positive step and an end after its start.")
    n = math.floor((hi - lo) / step + 1e-9) + 1
    return [round(lo + k * step, 10) for k in range(n)]


def score(metrics: dict[str, Any], metric: str) -> float:
    v = metrics.get(metric)
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return -math.inf
    return float(v)


def isolated_peak(
    cells: Sequence[dict[str, Any]], metric: str, params: Sequence[SweepParam]
) -> bool:
    """True when the best cell stands far above its neighbours: a sign of overfitting.

    "Far above" = the best score beats the average of its grid neighbours by more than
    one standard deviation of all cells (and by at least half its own size)."""
    scored = [(score(c["metrics"], metric), c) for c in cells]
    finite = [s for s, _ in scored if math.isfinite(s)]
    if len(finite) < 4:
        return False
    best_score, best = max(scored, key=lambda x: x[0])
    idx = {p.name: {v: i for i, v in enumerate(p.values)} for p in params}
    pos = {name: idx[name][best["overrides"][name]] for name in idx}
    neighbours = []
    for s, c in scored:
        if c is best or not math.isfinite(s):
            continue
        d = [abs(idx[n][c["overrides"][n]] - pos[n]) for n in idx]
        if max(d) == 1:
            neighbours.append(s)
    if not neighbours:
        return False
    gap = best_score - statistics.fmean(neighbours)
    spread = statistics.pstdev(finite)
    return spread > 0 and gap > spread and gap > abs(best_score) * 0.5


@dataclass(frozen=True)
class Window:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


def windows(start: int, end: int, train_days: int, test_days: int) -> list[Window]:
    if train_days < 30 or test_days < 5:
        raise ValueError("Use at least 30 days to tune and 5 days to test.")
    out = []
    t = start
    while True:
        test_start = t + train_days * DAY_MS
        test_end = min(test_start + test_days * DAY_MS, end)
        if test_start >= end or test_end - test_start < 5 * DAY_MS:
            break
        out.append(Window(t, test_start, test_start, test_end))
        t += test_days * DAY_MS
    if not out:
        raise ValueError("The date range is too short for those window sizes.")
    if len(out) > 40:
        raise ValueError("That makes more than 40 windows; use longer test windows.")
    return out


def stitch(parts: Sequence[Sequence[EquityPoint]], capital: float) -> list[EquityPoint]:
    """Chain test-window equity curves: each window continues from the last one's money."""
    out: list[EquityPoint] = []
    level = capital
    for pts in parts:
        if not pts:
            continue
        scale = level / capital  # every window's run starts with ``capital``
        for p in pts:
            out.append(EquityPoint(p.ts, p.equity * scale, p.cash * scale, p.exposure))
        level = out[-1].equity
    return out
