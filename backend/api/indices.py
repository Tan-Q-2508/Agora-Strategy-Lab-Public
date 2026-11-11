"""``/api/indices`` (D-174): every Indian and US index Agora follows, by group.

The user asked (2026-11-05) for one page with all the indices of both markets, sector indices
too. Values come from the saved daily candles the autopilot keeps topped up (D-99, every index
in ``catalog.INDICES``); asking with ``refresh`` tops them up now, in the background.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends

from backend.context import AppContext, get_ctx
from backend.core.types import Market, Timeframe
from backend.data import store
from backend.logging_setup import get_logger
from backend.watchlists import catalog

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]
log = get_logger("api.indices")

DAY_MS = 86_400_000
SPARK_DAYS = 63  # about three months of closes for the little chart
GROUPS = ("broad", "sector", "gauge")
_refreshing = threading.Lock()


def _change(closes: list[float], back: int) -> float | None:
    """Percent change from ``back`` closes ago to the latest."""
    if len(closes) <= back or closes[-1 - back] <= 0:
        return None
    return round(100.0 * (closes[-1] / closes[-1 - back] - 1.0), 2)


def row(ctx: AppContext, market: str, sym: str, name: str, group: str) -> dict[str, Any]:
    """One index: latest value, today's and longer changes, a sparkline (None when unsaved)."""
    out: dict[str, Any] = {"symbol": sym, "name": name, "group": group, "market": market}
    with ctx.db.session() as s:
        inst = store.find_instrument(s, Market(market), sym)
    if inst is None:
        return {**out, "value": None}
    now = ctx.clock.now_ms()
    bars = ctx.cache.bars(inst, Timeframe.D1, now - 400 * DAY_MS, now + 1)
    closes = [b.close * b.split_factor for b in bars if b.close]
    if not closes:
        return {**out, "value": None}
    year = datetime.fromtimestamp(now / 1000, UTC).year
    ytd_base = next(
        (
            b.close * b.split_factor
            for b in reversed(bars)
            if datetime.fromtimestamp(b.ts / 1000, UTC).year < year
        ),
        None,
    )
    return {
        **out,
        "value": round(closes[-1], 2),
        "as_of": bars[-1].ts,
        "change_pct": _change(closes, 1),
        "change_1m_pct": _change(closes, 21),
        "change_1y_pct": _change(closes, 250) if len(closes) > 250 else None,
        "ytd_pct": round(100.0 * (closes[-1] / ytd_base - 1.0), 2) if ytd_base else None,
        "spark": [round(c, 2) for c in closes[-SPARK_DAYS:]],
    }


def _refresh(ctx: AppContext, market: str) -> None:
    """Top up every index's daily candles (one at a time; never overlapping)."""
    if not _refreshing.acquire(blocking=False):
        return
    try:
        now = ctx.clock.now_ms()
        for m, sym, _y, _n, _g in catalog.INDICES:
            if m != market:
                continue
            with ctx.db.session() as s:
                inst = store.find_instrument(s, Market(m), sym)
            if inst is None:
                continue
            try:
                ctx.cache.ensure(inst, Timeframe.D1, now - 400 * DAY_MS, now)
            except Exception as exc:  # one index that can't load doesn't stop the rest
                log.info("Couldn't top up %s: %r", sym, exc)
    finally:
        _refreshing.release()


@router.get("/indices")
def indices(ctx: Ctx, market: Literal["IN", "US"] = "IN", refresh: bool = False) -> dict[str, Any]:
    """Every index of ``market``, grouped: the market by size, its sectors, its gauges."""
    if refresh:
        threading.Thread(target=_refresh, args=(ctx, market), daemon=True).start()
    rows = [row(ctx, m, s, n, g) for m, s, _y, n, g in catalog.INDICES if m == market]
    return {
        "market": market,
        "groups": [{"key": g, "indices": [r for r in rows if r["group"] == g]} for g in GROUPS],
    }
