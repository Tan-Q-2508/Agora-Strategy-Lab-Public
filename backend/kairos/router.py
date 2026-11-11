"""The rule-based fallback (D-62): understands common requests without the AI model.

Used when Ollama isn't installed or running, when the model fails, and in practice mode.
It turns a request into an ordered list of tool calls ("backtest the RSI strategy on TCS
and Infosys over 5 years, then paper trade it" → create, backtest, paper trade). It is
deliberately simple and predictable; the model handles everything subtler.
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.ai_provider import ToolCall
from backend.kairos import resolve
from backend.kairos.tools import ALL
from backend.kairos.tools.base import ThreadState


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


def _years(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", text)
    return float(m.group(1)) if m else None


def _budget(text: str) -> float | None:
    """A money amount in the request: "1 lakh", "₹2,00,000", "$1000", "50k", "1.5 crore"."""
    m = re.search(
        r"(?:₹|rs\.?|inr|\$|usd)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|k|thousand|million|m)?\b",
        text,
    )
    while m:
        raw, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        has_money = bool(re.search(r"₹|rs|inr|\$|usd", m.group(0))) or unit
        if has_money:
            value = float(raw)
            scale = {
                "lakh": 1e5,
                "lakhs": 1e5,
                "lac": 1e5,
                "lacs": 1e5,
                "crore": 1e7,
                "crores": 1e7,
                "cr": 1e7,
                "k": 1e3,
                "thousand": 1e3,
                "million": 1e6,
                "m": 1e6,
            }
            return value * scale.get(unit, 1.0)
        m = re.search(
            r"(?:₹|rs\.?|inr|\$|usd)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|k|thousand|million|m)?\b",
            text[m.end() :],
        )
        if m is None:
            break
    return None


def _market(text: str) -> str | None:
    if _has(text, r"\b(india|indian|nifty|nse|sensex)\b"):
        return "IN"
    if _has(text, r"\b(us|usa|american|nasdaq|s&p|wall street|nyse)\b"):
        return "US"
    return None


def _tf(text: str) -> str:
    if _has(text, r"\b(hourly|1h|1 hour|60 ?min)\b"):
        return "1h"
    if _has(text, r"\b15 ?(m|min|minutes?)\b"):
        return "15m"
    if _has(text, r"\b5 ?(m|min|minutes?)\b"):
        return "5m"
    return "1d"


def plan(ctx: Any, text: str, state: ThreadState, page: dict[str, Any]) -> list[ToolCall]:
    """Tool calls for a request, in order (empty when nothing matched)."""
    t = " " + text.lower() + " "
    found = resolve.find_in_text(ctx, text)
    symbols = [i.symbol for i in found if not i.is_index]
    here = page.get("symbol")
    if not symbols and here and _has(t, r"\b(this|it|the chart|here)\b"):
        symbols = [str(here)]
    market = _market(t)
    years = _years(t)
    tf = _tf(t)
    calls: list[ToolCall] = []

    def add(name: str, **args: Any) -> None:
        if name in ALL:
            calls.append(ToolCall(name, {k: v for k, v in args.items() if v not in (None, [], "")}))

    # Phase 18: why did it move, the world, sectors, watchlists (D-94 to D-98)
    if (
        _has(
            t,
            r"why (did|is|has|are)\b.*\b(fall|fell|drop|crash|sink|sank|tank|down|rise|rose|"
            r"jump|rall|up|move|slump|surge)",
        )
        and not symbols
        and not _has(t, r"\b(trades?|strateg\w*|backtests?|sessions?|portfolio|desk)\b")
    ):
        sector = None
        m = re.search(
            r"\b(it|tech|banks?|financials?|energy|oil|pharma|health ?care|autos?|fmcg|"
            r"metals?|realty|real estate|power|utilities|telecom|media|cement)\b"
            r"(?: stocks| sector| shares)?",
            t,
        )
        if m and (m.group(1) != "it" or _has(t, r"\bit (stocks|sector|shares)")):
            sector = m.group(1)
        add("why_move", market=market, sector=sector)
        return calls
    if _has(
        t,
        r"geopolitic\w* (events?|situation|picture)|world events|what('s| is) happening in the world"
        r"|world now"
        r"|\b(war|tariffs?|sanctions?|opec)\b.*\b(mean|affect|impact|do to)\b",
    ):
        add("world_events", market=market, symbol=symbols[0] if symbols else None)
        return calls
    if _has(t, r"\bsectors?\b|rotation|booming|\bbloom|where (is )?money (is )?moving"):
        add("sectors", market=market)
        return calls
    if _has(t, r"watch ?lists?"):
        if _has(t, r"\b(show|open)\b") and not _has(t, r"\blists\b"):
            wanted = (
                re.sub(r".*\b(show|open)( me)?( the)?\s+", "", t).replace("watchlist", "").strip()
            )
            args = {"action": "show", "name": wanted or None, "market": market}
            calls.append(ToolCall("watchlists", {k: v for k, v in args.items() if v}))
        else:
            add("watchlists", action="list", market=market)
        return calls
    if _has(t, r"portfolio|allocat|rebalanc|opportunit|\blakh\b|\bcrore\b") and "portfolio" in ALL:
        budget = _budget(t)
        if _has(t, r"rebalanc"):
            add("portfolio", action="rebalance")
        elif _has(t, r"(find|look for|search|scan|hunt).*opportunit|new opportunit"):
            add("portfolio", action="scan", market=market)
        elif _has(t, r"opportunit"):
            add("portfolio", action="opportunities", market=market)
        elif _has(t, r"\bstop\b"):
            add("portfolio", action="stop")
        elif _has(t, r"paper|start trading|go live"):
            add("portfolio", action="start")
        elif _has(t, r"backtest|test it|how would it have"):
            add("portfolio", action="backtest")
        elif budget is not None or _has(t, r"build|make|create|new|allocat|invest|split|spread"):
            risk = (
                "careful"
                if _has(t, r"careful|safe|conservative|low risk")
                else ("bold" if _has(t, r"bold|aggressive|high risk") else None)
            )
            method = (
                "momentum"
                if _has(t, r"momentum|strongest|top risers|winners")
                else ("low_volatility" if _has(t, r"low.?vol|calm|steady|defensive") else None)
            )
            add(
                "portfolio",
                action="build",
                market=market,
                budget=budget,
                risk=risk,
                method=method,
            )
        else:
            add("portfolio", action="status")
        return calls
    if _has(t, r"\bmetis\b|ai researcher") and "metis" in ALL:
        if _has(t, r"turn (it |metis )?off|switch (it |metis )?off|stop|pause|disable"):
            add("metis", action="off")
        elif _has(t, r"research now|right now|look into|look at|go research|new round"):
            asked = re.search(r"look (?:into|at) (.+)", text, re.IGNORECASE)
            add("metis", action="now", focus=asked.group(1).strip(" .?!") if asked else None)
        elif _has(t, r"turn (it |metis )?on|switch (it |metis )?on|start|enable|wake"):
            add("metis", action="on")
        else:
            add("metis", action="status")
        return calls
    if _has(t, r"\bstop\b") and _has(t, r"paper|trading|session|desk|all"):
        add(
            "stop_desk" if _has(t, r"\bdesk\b") and "stop_desk" in ALL else "stop_paper_trading",
            session="all",
        )
        return calls
    if _has(t, r"\bdesk\b") and _has(t, r"how|status|doing|show|open") and "desk_status" in ALL:
        # the desk the question names (a market, a candle size), else every desk
        where: dict[str, str] = {}
        if _has(t, r"\b(india|indian|nse|nifty)\b"):
            where["market"] = "IN"
        elif _has(t, r"\b(us|usa|american|s&p|nasdaq)\b"):
            where["market"] = "US"
        for pattern, tf in (
            (r"\b(daily|1d|day)\b", "1d"),
            (r"\b(hourly|1h|1-hour|one hour)\b", "1h"),
            (r"\b(15m|15-minute|15 minute|fifteen)\b", "15m"),
            (r"\b(5m|5-minute|5 minute|five)\b", "5m"),
            (r"\b(1m|1-minute|1 minute|one minute)\b", "1m"),
        ):
            if _has(t, pattern):
                where["timeframe"] = tf
                break
        add("desk_status", **where)
        return calls
    if _has(t, r"how are my|paper status|my (paper )?sessions|how is (my )?paper"):
        add("paper_status")
        return calls
    if (
        _has(t, r"\b(re-?train|study the history|train (yourself|on|again))\b")
        and "train_kairos" in ALL
    ):
        add("train_kairos", market=market, timeframe=tf)
        return calls
    if (
        _has(
            t,
            r"keep an eye|watch (these|them|it)|watch .{1,80}\b(trade|buy)|trade (it |them |these )?"
            r"(for me|on your own|by yourself|automatically)|trade these|run (the|your|a) desk|"
            r"start (the|your|a) desk|autonom",
        )
        and "start_desk" in ALL
    ):
        add("start_desk", symbols=symbols or None, market=market)
        return calls
    if (
        _has(
            t,
            r"best strategy|which strategy|research|find (a|the) (good |best )?strategy|build (the|a) (best )?strategy",
        )
        and "research_strategy" in ALL
    ):
        add("research_strategy", symbols=symbols or None, market=market, timeframe=tf)
        return calls
    if (
        _has(
            t,
            r"why (did|do|are|were) .{0,60}(lose|lost|losing|fail|bad)|losing trades|"
            r"what went wrong|post.?mortem|review (my|the|this|that) (trades|backtest|results)|"
            r"costs? (eat|ate|kill)|win ?rate (is |so )?(low|bad|poor)",
        )
        and "review_trades" in ALL
    ):
        add("review_trades", strategy=None)
        return calls
    if (
        _has(t, r"improve (my |the |this |that )?strateg|fewer bad trades|better (quality )?trades")
        and "improve_strategy" in ALL
    ):
        add("improve_strategy")
        return calls
    if (
        _has(
            t,
            r"what (have you|did you) (been )?(stud|learn).{0,30}(own|today|lately)|"
            r"what did you study",
        )
        and "learning_status" in ALL
    ):
        add("learning_status")
        return calls
    if _has(t, r"what (have you|did you) learn|lessons?") and "get_lessons" in ALL:
        add("get_lessons")
        return calls

    from backend.analysis.options import find_strategy

    opt = find_strategy(text)
    if (
        opt is not None
        and "option_strategy" in ALL
        and not _has(t, r"what is|what's|explain|meaning|define|how does")
    ):
        name = (
            "nifty" if _has(t, r"\bnifty\b") and not symbols else (symbols[0] if symbols else None)
        )
        days = re.search(r"(\d+)\s*(?:days?|d)\b", t)
        add(
            "option_strategy",
            strategy=opt.name,
            symbol=name,
            days=int(days.group(1)) if days else None,
        )
        return calls

    key = resolve.template_key(text)
    wants_backtest = _has(t, r"backtest|back-test|test (it|this|the strategy|on)")
    if resolve.means_kairos(text) and (
        wants_backtest or _has(t, r"would (you|kairos) have (traded|done)")
    ):
        add("create_strategy", template="kairos", symbols=symbols or None, market=market)
        add("run_backtest", years=years)
        return calls
    wants_paper = _has(
        t, r"paper.?trad|live test|go live|start (live )?trading|live trad|paper (it|this)"
    )
    if key and (wants_backtest or wants_paper or _has(t, r"\b(create|build|make|set up|start)\b")):
        add("create_strategy", template=key, symbols=symbols or None, market=market)
    if wants_backtest:
        add("run_backtest", symbols=None if key else symbols or None, years=years)
    if wants_paper:
        add("start_paper_trading", symbols=None if key else symbols or None)
    if calls:
        return calls

    if _has(t, r"optimi[sz]|tune|best settings?|walk.?forward|parameter sweep"):
        add(
            "optimize_strategy",
            method="sweep" if "sweep" in t else "walk_forward",
            symbols=symbols or None,
            years=years,
        )
        return calls
    if _has(t, r"\bcompare\b"):
        add("compare_backtests")
        return calls
    if _has(t, r"download|refresh (the )?(data|prices)|update (the )?prices"):
        add("refresh_data", symbols=symbols or None, market=market, timeframe=tf)
        return calls
    if symbols and _has(
        t, r"forecast|predict|where .* (go|head)|next (week|month|few days)|target price"
    ):
        add("forecast", symbol=symbols[0], timeframe=tf)
        return calls
    if (
        _has(
            t,
            r"news risk|risk (in|from) the news|geopolit|\bwar\b|is it safe|safe to (buy|trade|invest)|"
            r"damage control|pull out|get out of the market|crisis|sanction|tariff",
        )
        and not symbols
    ):
        add("news_risk", market=market)
        return calls
    if _has(t, r"\bnews\b|headline"):
        about = "world" if _has(t, r"world|global|international") else None
        add("get_news", symbol=symbols[0] if symbols else None, market=market, about=about)
        return calls
    if _has(t, r"market (today|overview|mood|now)|how('s| is) the market|nifty today|market doing"):
        add("market_overview", market=market or "IN")
        return calls
    if not symbols and _has(
        t,
        r"scan|screen|which stocks|best stocks|top stocks|find stocks|setups|opportunit|oversold|overbought|breakouts?",
    ):
        focus = "best"
        for word, f in (
            ("oversold", "oversold"),
            ("overbought", "overbought"),
            ("breakout", "breakouts"),
            ("bearish", "bearish"),
            ("bullish", "bullish"),
            ("pattern", "patterns"),
            ("trend", "strongest_trend"),
        ):
            if word in t:
                focus = f
                break
        add("scan_market", market=market, focus=focus, timeframe=tf)
        return calls
    if symbols:
        for sym in symbols[:3]:
            add("analyze_chart", symbol=sym, timeframe=tf)
        return calls
    if _has(t, r"what is|what's|what are|explain|meaning|how does|define|tell me about|why do"):
        add("lookup_knowledge", topic=text.strip()[:120])
        return calls
    if _has(t, r"my strategies|list (my )?strategies|saved strategies"):
        add("list_strategies")
    elif _has(t, r"templates?|starter"):
        add("list_templates")
    return calls


HELP = (
    'I can read any chart ("analyse RELIANCE"), scan the market ("which Nifty stocks look '
    'oversold?"), read business and world news and say how risky it is for markets, forecast a range, explain any indicator or pattern, build and '
    'backtest strategies ("backtest RSI mean reversion on TCS and Infosys over 5 years"), '
    "start or stop paper trading, and run my own paper-trading desk."
)
