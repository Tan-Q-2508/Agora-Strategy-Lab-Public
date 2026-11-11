"""Kairos's tools (KAIROS §7.2): every job Kairos can do in Agora."""

from __future__ import annotations

import re

from backend.kairos.tools import coach, desk, lab, market, metis, options, portfolio, web, world
from backend.kairos.tools.base import Env, Result, ThreadState, Tool

ALL: dict[str, Tool] = {
    t.name: t
    for t in (
        *market.TOOLS,
        *lab.TOOLS,
        *desk.TOOLS,
        *coach.TOOLS,
        *options.TOOLS,
        *metis.TOOLS,
        *portfolio.TOOLS,
        *world.TOOLS,
        *web.TOOLS,
    )
}

# Words that bring in the tools outside the core set (keeps the prompt small for a 4B model).
GROUP_WORDS: dict[str, str] = {
    "forecast": r"forecast|predict|projection|where .* (go|head)|next (week|month|days)|target price|future",
    "overview": r"market (today|overview|mood|now)|how('s| is) the market|nifty today|breadth|movers|gainers|losers",
    "create": r"template|starter|create|build|make|new strategy|draft|idea",
    "optimize": r"optimi[sz]|tune|best setting|parameter|sweep|walk.?forward|robust",
    "compare": r"compare|versus|vs\.?|side by side|which (is|was) better",
    "paper": r"paper|live|session|stop|pause|running|trading status|how are my",
    "data": r"download|refresh|update (the )?(data|prices)|missing prices|history",
    "desk": r"desk|keep an eye|watch|trade (for me|on (your|its) own|automatically)|autonom|monitor",
    "research": r"best strategy|research|which strategy|find (a|the) strategy|suit|fits? (these|this)",
    "learning": r"learn|lesson|experience|mistake|journal|what have you|studied|on your own",
    "options": r"option|call|put|straddle|strangle|condor|butterfly|spread|futures?|f&o|fno|"
    r"expiry|greeks?|theta|delta|hedge|collar|lizard|covered|premium|strike",
    "metis": r"metis|ai researcher|researcher|research(ing)? on (its|your) own|new ideas",
    "portfolio": r"portfolio|allocat|budget|lakh|crore|\$ ?\d|₹ ?\d|rebalanc|opportunit|diversif"
    r"|invest (my|the|a)|spread (my|the) money",
    "world": r"world|geopolit|war|conflict|iran|israel|russia|ukraine|china|taiwan|pakistan"
    r"|tariff|sanction|opec|oil price|crude|fed\b|rbi|rate (cut|hike)|election|news"
    r"|why (did|is|has) .*(fall|fell|drop|crash|sink|rise|rose|jump|rall|move|down|up)"
    r"|what happened|sell.?off|crash|event",
    "sectors": r"sector|industr|rotation|boom|bloom|leading|lagging|breadth|money (is )?moving"
    r"|which (area|part)",
    "watchlists": r"watch ?list|list of stocks|lists?\b|small.?cap|mid.?cap|large.?cap|theme"
    r"|momentum list|factor",
    "web": r"internet|\bweb\b|online|google|search|look (it )?up|find out|research|what do "
    r"(traders|experts|people|funds|institutions) |evidence|studies|study|paper|article|"
    r"institution|fii|dii|fpi|hedge fund|mutual fund|who (is|are|was)|what is|explain|"
    r"does .* (work|make money)|how do (pros|professionals|traders)",
    "coach": r"why .*(lose|lost|los[st]|fail|bad)|losing trades|win ?rate|review (my|the|this|that)"
    r"|costs?|brokerage|charges|tax|improve|bad trades|quality|post.?mortem|what went wrong"
    r"|too many trades|better trades",
}


def register(tools: list[Tool]) -> None:
    """Later phases add their tools (research, desk, learning) here."""
    for t in tools:
        ALL[t.name] = t


def select_tools(text: str) -> list[Tool]:
    """The core tools plus any group the request mentions."""
    low = text.lower()
    groups = {"core"} | {g for g, rx in GROUP_WORDS.items() if re.search(rx, low)}
    return [t for t in ALL.values() if t.group in groups]


__all__ = ["ALL", "Env", "Result", "ThreadState", "Tool", "register", "select_tools"]
