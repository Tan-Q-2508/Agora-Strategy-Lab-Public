"""D-202: a day still coming in isn't a sector's move."""

from __future__ import annotations

import numpy as np

from backend.sectors import rotation as rot
from backend.world import service as ws


def _m(i: int, closes: list[float]) -> rot.Member:
    return rot.Member(i, f"S{i}", np.array(closes), np.zeros(len(closes)))


def test_the_latest_day_waits_for_most_stocks() -> None:
    """5 minutes after India's close only the desk's stocks had today's price, and one that fell
    hard made "Industrials fell 21.7%"."""
    nan = float("nan")
    dates = np.array([1, 2, 3])
    bench = np.array([100.0, 101.0, 101.3])
    early = {"Industrials": [_m(1, [10, 10, 7.8]), _m(2, [20, 20, nan]), _m(3, [30, 30, nan])]}
    d, b, m = ws.trim_partial_day(dates, bench, early)
    assert len(d) == 2 and len(b) == 2 and all(len(x.close) == 2 for x in m["Industrials"])
    full = {"Industrials": [_m(1, [10, 10, 9.9]), _m(2, [20, 20, 20.2]), _m(3, [30, 30, nan])]}
    d, _, m = ws.trim_partial_day(dates, bench, full)
    assert len(d) == 3 and len(m["Industrials"][0].close) == 3
