"""Kairos's tools for the world, sectors and watchlists (SPEC §18, D-94 to D-98).

- ``world_events``: what is happening in the world and what it means for a market, a sector or
  one stock, with the chain of effects and what the map learned from past events;
- ``why_move``: why the market or a sector moved (the investigator, D-96);
- ``sectors``: where money is moving: leading and lagging sectors, booms and slumps;
- ``watchlists``: list, show, make or change watchlists (Kairos's own lists say why it made them).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from backend.core.types import Market
from backend.kairos import resolve
from backend.kairos.tools.base import Args, Env, Result, Tool


def _markets(text: str | None, env: Env) -> list[str]:
    m = resolve.market_of(text) or resolve.market_of(env.state.market)
    if text and text.lower() in ("both", "all", "world", "global"):
        return ["IN", "US"]
    return [m.value] if m else ["IN", "US"]


# ---------------------------------------------------------------- world events


class WorldArgs(Args):
    market: str | None = Field(None, description="India, US or both. Default: both.")
    symbol: str | None = Field(
        None, description="Optional: one stock to explain (e.g. RELIANCE, AAPL)."
    )
    refresh: bool = Field(False, description="Re-read the latest headlines first.")


def world_events(env: Env, a: WorldArgs) -> Result:
    ctx = env.ctx
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    if a.symbol:
        inst = resolve.stock(ctx, a.symbol, resolve.market_of(a.market or env.state.market))
        st = ctx.world.stock(inst.id)
        env.state.symbols = [inst.symbol]
        word = "helps" if st["tilt"] > 0.2 else "hurts" if st["tilt"] < -0.2 else "barely moves"
        lines.append(
            f"{inst.symbol}: today's world events {word} it (score {st['tilt']:+.1f} on −3…+3)."
        )
        if st["why"]:
            lines.append("Why: " + "; ".join(st["why"]) + ".")
        if st["drivers"]:
            lines.append("Events in play: " + ", ".join(st["drivers"]) + ".")
        else:
            lines.append("No world event in the news is big enough to matter right now.")
    for m in _markets(a.market, env):
        v = ctx.world.view(m, refresh=a.refresh)
        name = "India" if m == "IN" else "the US"
        lines.append(f"For {name}: {v['sentence']}")
        for d in v["drivers"][:3]:
            lines.append(
                f"- {d['title']}{' (calming)' if d['calming'] else ''}, "
                f"{len(d['headlines'])} headlines: " + " → ".join(d["chain"][:2])
            )
            for e in d["effects"][:4]:
                meas = e.get("measured")
                learned = (
                    f"; measured on {meas['n']} past events: {meas['mean_pct']:+.1f}% vs the "
                    "market over 5 days"
                    if meas
                    else ""
                )
                lines.append(f"  · {e['label']}: {e['value']:+.1f}{learned}")
            items.append({"label": d["title"], "sub": d["chain"][0][:120], "link": "/world"})
        if v["hurt"]:
            lines.append("Likely hurt most: " + ", ".join(x["symbol"] for x in v["hurt"][:6]))
        if v["helped"]:
            lines.append("Likely helped most: " + ", ".join(x["symbol"] for x in v["helped"][:6]))
    card = {"type": "list", "title": "The world now", "items": items[:5], "link": "/world"}
    return Result(True, "\n".join(lines), "Read the world news", "", card, {"navigate": "/world"})


# ---------------------------------------------------------------- why did it move


class MoveArgs(Args):
    market: str | None = Field(None, description="India or US. Default: the one in the chat.")
    sector: str | None = Field(None, description="Optional: a sector, e.g. IT, banks, energy.")


SECTOR_WORDS = {
    "it": "Information Technology",
    "tech": "Information Technology",
    "technology": "Information Technology",
    "bank": "Financials",
    "banks": "Financials",
    "financial": "Financials",
    "financials": "Financials",
    "energy": "Energy",
    "oil": "Energy",
    "pharma": "Health Care",
    "health": "Health Care",
    "healthcare": "Health Care",
    "auto": "Consumer Discretionary",
    "autos": "Consumer Discretionary",
    "consumer": "Consumer Discretionary",
    "fmcg": "Consumer Staples",
    "staples": "Consumer Staples",
    "industrials": "Industrials",
    "capital goods": "Industrials",
    "metals": "Materials",
    "metal": "Materials",
    "materials": "Materials",
    "cement": "Materials",
    "power": "Utilities",
    "utilities": "Utilities",
    "realty": "Real Estate",
    "real estate": "Real Estate",
    "telecom": "Communication Services",
    "media": "Communication Services",
}


def _sector(text: str | None) -> str | None:
    if not text:
        return None
    low = text.strip().lower()
    from backend.watchlists.taxonomy import SECTORS

    for s in SECTORS:
        if s.lower() == low:
            return s
    return SECTOR_WORDS.get(low) or SECTOR_WORDS.get(low.removesuffix(" sector"))


def why_move(env: Env, a: MoveArgs) -> Result:
    ctx = env.ctx
    market = (resolve.market_of(a.market) or resolve.market_of(env.state.market) or Market.IN).value
    env.progress(20, "Checking for unusual moves and reading the news around them…")
    fresh = ctx.world.investigate(market)
    past = ctx.world.investigations(market, limit=10)
    sector = _sector(a.sector)
    pick = [x for x in [*fresh, *past] if (x["target"] == (sector or "market"))]
    if not pick and not sector:
        pick = [*fresh, *past]
    lines: list[str] = []
    if pick:
        top = pick[0]
        lines.append(top["text"])
        for c in top.get("causes", [])[1:3]:
            hl = (c.get("headline") or {}).get("title", "")
            lines.append(f"- Also considered: {c['title']}" + (f": “{hl}”" if hl else ""))
        lines.append(f"Confidence: {top.get('confidence', 'low')}.")
    else:
        sec = ctx.sectors.overview(market)
        what = sector or ("India" if market == "IN" else "the US market")
        lines.append(
            f"The latest candle for {what} wasn't an unusual move (it stayed within its usual "
            "range), so there is nothing to explain yet."
        )
        lines.append(sec["sentence"])
    card = {
        "type": "list",
        "title": "Why did it move?",
        "items": [
            {"label": x["text"][:140], "sub": x.get("confidence", ""), "link": "/world"}
            for x in pick[:3]
        ],
        "link": "/world",
    }
    return Result(True, "\n".join(lines), "Investigated the move", "", card, {"navigate": "/world"})


# ---------------------------------------------------------------- sectors


class SectorArgs(Args):
    market: str | None = Field(None, description="India or US. Default: both.")


def sectors(env: Env, a: SectorArgs) -> Result:
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    for m in _markets(a.market, env):
        o = env.ctx.sectors.overview(m)
        lines.append(
            f"{'India' if m == 'IN' else 'US'} ({o['stocks']} stocks with prices): {o['sentence']}"
        )
        for r in o["sectors"][:11]:
            lines.append(f"- {r['sentence']}")
        for r in o["industries"][:3]:
            if r["state"] in ("boom", "strong"):
                lines.append(f"- Industry: {r['sentence']}")
        for r in o["sectors"][:3]:
            items.append({"label": r["name"], "sub": r["sentence"][:120], "link": "/watchlists"})
    card = {"type": "list", "title": "Where money is moving", "items": items, "link": "/watchlists"}
    return Result(True, "\n".join(lines), "Read the sectors", "", card, {"navigate": "/watchlists"})


# ---------------------------------------------------------------- watchlists


class WatchlistArgs(Args):
    action: Literal["list", "show", "create", "add", "remove"] = Field(
        "list",
        description="list: the lists; show: one list's stocks; create: make a list; add/remove: "
        "change one of the user's lists.",
    )
    name: str | None = Field(None, description="The list's name, e.g. 'Nifty IT' or 'My banks'.")
    market: str | None = Field(None, description="India or US.")
    symbols: list[str] | None = Field(None, description="Stocks to put in or take out.")
    reason: str | None = Field(None, description="Why the list is worth having.")


def watchlists(env: Env, a: WatchlistArgs) -> Result:
    svc = env.ctx.watchlists
    market = resolve.market_of(a.market) or resolve.market_of(env.state.market)
    m = market.value if market else None
    if a.action == "list":
        rows = svc.lists(m)
        by_cat: dict[str, list[str]] = {}
        for w in rows:
            by_cat.setdefault(w["category"], []).append(f"{w['name']} ({w['count']})")
        lines = [f"{cat}: " + ", ".join(names[:12]) for cat, names in by_cat.items()]
        card = {"type": "list", "title": "Watchlists", "items": [], "link": "/watchlists"}
        return Result(
            True, "\n".join(lines), "Listed the watchlists", "", card, {"navigate": "/watchlists"}
        )
    if a.action == "create":
        if not a.name or not a.symbols:
            return Result(False, "Give the list a name and some stocks.", "Need a name and stocks")
        insts = resolve.stocks(env.ctx, a.symbols, market)
        mk = m or insts[0].market.value
        made = svc.save_for_agent(
            "kairos",
            mk,
            a.name,
            [i.symbol for i in insts if i.market.value == mk],
            a.reason or "Made at your request.",
        )
        if made is None:
            return Result(False, "Kairos has made its three lists for today.", "Limit reached")
        return Result(
            True,
            f"Saved “{made['name']}” with {made['count']} stocks.",
            f"Saved the list {made['name']}",
            "",
            {
                "type": "list",
                "title": made["name"],
                "items": [],
                "link": f"/watchlists/{made['id']}",
            },
            {"navigate": f"/watchlists/{made['id']}"},
        )
    wl = svc.find(a.name or "", m) if a.name else None
    if wl is None:
        return Result(False, f"I couldn't find a list called “{a.name}”.", "List not found")
    if a.action in ("add", "remove"):
        if not wl["editable"]:
            return Result(
                False,
                "That list is kept up to date by Agora; copy it to change it.",
                "Read-only list",
            )
        changed = svc.update(wl["id"], **{a.action: a.symbols or []})
        return Result(
            True,
            f"“{changed['name']}” now has {changed['count']} stocks.",
            f"Updated {changed['name']}",
        )
    d = svc.detail(wl["id"])
    env.state.symbols = [i["symbol"] for i in d["items"][:30]]
    env.state.market = d["market"]
    lines = [f"{d['name']}: {d['count']} stocks. {d['description']}"]
    if d.get("reason"):
        lines.append(f"Why: {d['reason']}")
    for i in d["items"][:20]:
        chg = f" {i['change_pct']:+.1f}%" if i.get("change_pct") is not None else ""
        note = f": {i['note']}" if i.get("note") else ""
        lines.append(f"- {i['symbol']} ({i['sector'] or i['type']}){chg}{note}")
    card = {"type": "list", "title": d["name"], "items": [], "link": f"/watchlists/{d['id']}"}
    return Result(
        True,
        "\n".join(lines),
        f"Opened {d['name']}",
        "",
        card,
        {"navigate": f"/watchlists/{d['id']}"},
    )


TOOLS = [
    Tool(
        "world_events",
        "World and geopolitical events (wars, tariffs, sanctions, oil, central banks, elections, "
        "pandemics) and what they mean for India's and the US's markets, sectors and a given "
        "stock, with the chain of effects and what past events actually did.",
        WorldArgs,
        world_events,
        lambda a: "Reading the world news…",
        group="world",
    ),
    Tool(
        "why_move",
        "Why the market or a sector suddenly rose or fell: finds the news (and world events, "
        "oil, the dollar, the other market) behind an unusual move.",
        MoveArgs,
        why_move,
        lambda a: "Investigating the move…",
        group="world",
    ),
    Tool(
        "sectors",
        "Which sectors and industries are booming, leading or lagging (rotation, breadth, "
        "relative strength) in India or the US.",
        SectorArgs,
        sectors,
        lambda a: "Reading the sectors…",
        group="sectors",
    ),
    Tool(
        "watchlists",
        "The watchlists: ready-made (indices, sectors, large/mid/small caps, factor and theme "
        "lists, ETFs), the user's own, and Kairos's and Metis's. List, show, create, add, remove.",
        WatchlistArgs,
        watchlists,
        lambda a: "Opening the watchlists…",
        group="watchlists",
    ),
]
