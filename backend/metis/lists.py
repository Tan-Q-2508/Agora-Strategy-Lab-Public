"""Metis makes watchlists when its reading of sectors and the world says a group of stocks is
worth watching (SPEC §18, D-94).

After each research round, in code (no AI needed):

- **a booming sector** (``backend/sectors``: unusually strong month, broad participation,
  beating the market, busy volume) → "Metis · Booming: <sector>" with its leaders;
- **a world event strong enough to matter** (``backend/world``) → "Metis · World: <event>" with
  the stocks the map expects to do better than the market, each with its reason.

Saving a list with the same name updates it; the watchlist service limits new lists to three a
day and twelve kept. These lists feed the opportunity scanner (new stocks for strategies that
work) and the Kairos desk's picks.
"""

from __future__ import annotations

from typing import Any

from backend.logging_setup import get_logger

log = get_logger("metis.lists")
MIN_WORLD_WEIGHT = 0.5  # 1 − e^(−strength/8): a handful of severe stories
MAX_STOCKS = 15


def refresh(ctx: Any, markets: list[str]) -> list[str]:
    """Make or update Metis's lists; returns the names saved."""
    saved: list[str] = []
    lists = ctx.services.get("watchlists")
    if lists is None:
        return saved
    for m in markets:
        try:
            saved += _booms(ctx, lists, m)
            saved += _world(ctx, lists, m)
        except Exception:  # a bonus: never cost Metis its round
            log.exception("Metis couldn't refresh its %s watchlists", m)
    return saved


def _booms(ctx: Any, lists: Any, market: str) -> list[str]:
    out: list[str] = []
    o = ctx.sectors.overview(market)
    for r in [*o["sectors"], *o["industries"]]:
        if r["state"] != "boom":
            continue
        symbols = [x["symbol"] for x in r["leaders"]][:MAX_STOCKS]
        if len(symbols) < 2:
            continue
        notes = {x["symbol"]: f"{x['1m']:+.1f}% this month" for x in r["leaders"]}
        w = lists.save_for_agent(
            "metis", market, f"Booming: {r['name']}", symbols, r["sentence"], notes
        )
        if w is not None:
            out.append(w["name"])
    return out


def _world(ctx: Any, lists: Any, market: str) -> list[str]:
    out: list[str] = []
    v = ctx.world.view(market)
    drivers = [d for d in v["drivers"] if d["weight"] >= MIN_WORLD_WEIGHT]
    if not drivers or not v["helped"]:
        return out
    top = drivers[0]
    picks = v["helped"][:MAX_STOCKS]
    reason = (
        f"{top['title']}{' (calming)' if top['calming'] else ''} is in the news. "
        + top["chain"][0]
        + " These stocks are the ones the world map expects to do better than the market."
    )
    notes = {x["symbol"]: "; ".join(x["why"])[:300] for x in picks}
    w = lists.save_for_agent(
        "metis",
        market,
        f"World: {top['title']}"[:70],
        [x["symbol"] for x in picks],
        reason,
        notes,
    )
    if w is not None:
        out.append(w["name"])
    return out
