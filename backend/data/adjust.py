"""Split adjustment (D-07): signals use split-adjusted prices, fills use raw prices.

Every stored candle keeps its raw (as-traded) prices plus ``split_factor``: multiply raw
prices by it (and divide volume by it) to express the bar in today's share terms. A bar
before a 2-for-1 split has factor 0.5; after the split it is 1.0.

When a new split is ingested, only the factors change, never the raw prices, so saved
backtests stay reproducible.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace

from backend.core.types import Bar, CorporateAction


def split_events(actions: Iterable[CorporateAction]) -> list[tuple[int, float]]:
    """(ex_date, ratio) for every real split, oldest first."""
    return sorted(
        (a.ex_date, float(a.ratio))
        for a in actions
        if a.kind == "split" and a.ratio is not None and a.ratio > 0 and a.ratio != 1.0
    )


def factor_at(ts: int, splits: Sequence[tuple[int, float]]) -> float:
    """Cumulative factor for a bar opening at ``ts``: 1 / product of later split ratios.

    A split whose ex-date is the bar's own session counts as already happened (the bar
    trades in post-split shares), so only ex-dates strictly after ``ts`` are included.
    """
    f = 1.0
    for ex_date, ratio in splits:
        if ex_date > ts:
            f /= ratio
    return f


def with_factors(bars: Iterable[Bar], splits: Sequence[tuple[int, float]]) -> list[Bar]:
    return [replace(b, split_factor=factor_at(b.ts, splits)) for b in bars]


def unadjust(bar: Bar, factor: float, *, digits: int = 4) -> Bar:
    """Turn a split-adjusted bar (as Yahoo and Stooq send it) back into raw prices.
    Also rounds away the float32 noise Yahoo adds (127.58000183 → 127.58)."""
    return replace(
        bar,
        open=round(bar.open / factor, digits),
        high=round(bar.high / factor, digits),
        low=round(bar.low / factor, digits),
        close=round(bar.close / factor, digits),
        volume=round(bar.volume * factor),
        split_factor=factor,
    )


def adjusted(bar: Bar) -> Bar:
    """The bar in today's share terms (what indicators and charts use)."""
    f = bar.split_factor
    if f == 1.0:
        return bar
    return replace(
        bar,
        open=bar.open * f,
        high=bar.high * f,
        low=bar.low * f,
        close=bar.close * f,
        volume=bar.volume / f,
    )
