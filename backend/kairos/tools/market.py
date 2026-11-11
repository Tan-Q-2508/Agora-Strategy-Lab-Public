"""Kairos's market-reading tools: charts, forecasts, scans, the market today, news, and its
own playbook. All numbers come from the analyst and the news service, never the model."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

import numpy as np
from pydantic import Field

from backend.analysis.report import Analysis
from backend.analysis.service import VISIBLE_DAYS
from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.data.store import InstrumentRef, find_instrument
from backend.errors import AgoraError
from backend.kairos import knowledge, resolve
from backend.kairos.tools.base import Args, Env, Result, Tool, money
from backend.news import topics
from backend.settings_store import read_setting

DAY_MS = 86_400_000


def chart_link(inst: InstrumentRef, tf: Timeframe) -> str:
    return f"/charts?symbol={quote(inst.symbol)}&market={inst.market.value}&tf={tf.value}&kairos=1"


def _markets(env: Env, market: str | None) -> list[Market]:
    m = resolve.market_of(market)
    if m:
        return [m]
    chosen = read_setting(env.ctx.db, "markets")
    return [Market(x) for x in chosen]


# ---------------------------------------------------------------- analyze_chart


class ChartArgs(Args):
    symbol: str = Field(
        description="Stock ticker or company name, e.g. RELIANCE, TCS, AAPL, Apple."
    )
    timeframe: str = Field("1d", description="Candle size: 1d, 1h, 15m or 5m.")


def analyze_chart(env: Env, a: ChartArgs) -> Result:
    inst = resolve.stock(env.ctx, a.symbol, resolve.market_of(env.state.market))
    tf = resolve.timeframe(a.timeframe)
    reading = env.ctx.analysis.chart(inst, tf)
    rep = reading["report"]
    fc = reading["forecast"]
    env.state.symbols = [inst.symbol]
    env.state.market = inst.market.value
    lines = [
        f"{inst.symbol} ({inst.name}), {tf.value} chart. Close {money(rep['close'], inst.market.value)}.",
        f"Verdict: {rep['bias']}, score {rep['score']:+.0f} of 100, {rep['confidence']} confidence. "
        f"{rep['headline']}.",
        *rep["summary"][:-1],
    ]
    if rep.get("idea"):
        lines.append("Trade idea: " + rep["idea"]["text"])
    if rep.get("invalidation"):
        lines.append(rep["invalidation"])
    mt = reading.get("timeframes")
    if mt:
        frames = ", ".join(
            f"{t['label']} {t['regime']} ({t['trend']:+.0f})" for t in mt["timeframes"]
        )
        lines.append(f"Timeframes: {frames}. {mt['headline']}: {mt['text']}")
    if fc:
        lines += [fc["text"], fc["verdict"]]
    link = chart_link(inst, tf)
    card = {
        "type": "chart",
        "symbol": inst.symbol,
        "name": inst.name,
        "market": inst.market.value,
        "timeframe": tf.value,
        "bias": rep["bias"],
        "score": rep["score"],
        "confidence": rep["confidence"],
        "headline": rep["headline"],
        "lines": rep["summary"][:3],
        "forecast": fc["text"] if fc else None,
        "timeframes": mt["headline"] if mt else None,
        "idea": rep["idea"]["text"]
        if rep.get("idea") and rep["idea"].get("quality") != "poor"
        else None,
        "link": link,
    }
    return Result(
        True,
        "\n".join(lines),
        f"Read {inst.symbol}'s {tf.value} chart",
        f"{rep['bias'].capitalize()} · score {rep['score']:+.0f}",
        card,
        {"navigate": link},
    )


# ---------------------------------------------------------------- forecast


class ForecastArgs(Args):
    symbol: str = Field(description="Stock ticker or company name.")
    timeframe: str = Field("1d", description="Candle size: 1d, 1h, 15m or 5m.")
    horizon: int | None = Field(
        None, description="How many candles ahead (1-30). Default 10 for daily."
    )


def forecast(env: Env, a: ForecastArgs) -> Result:
    inst = resolve.stock(env.ctx, a.symbol, resolve.market_of(env.state.market))
    tf = resolve.timeframe(a.timeframe)
    h = max(1, min(30, a.horizon)) if a.horizon else None
    f = env.ctx.analysis.forecast(inst, tf, h)
    env.state.symbols = [inst.symbol]
    last = f["path"][-1]
    mkt = inst.market.value
    candles = f.get("candles") or []
    ups = sum(1 for c in candles if c.get("direction") == 1)
    downs = sum(1 for c in candles if c.get("direction") == -1)
    shape = (
        f"Predicted candles (drawn on the chart): {ups} rising, {downs} falling, "
        f"{len(candles) - ups - downs} flat."
        if candles
        else ""
    )
    prev = f.get("previous") or {}
    lines = [
        f["text"],
        f"Middle of the range {money(last['median'], mkt)}; 50% range {money(last['p25'], mkt)}–{money(last['p75'], mkt)}.",
        shape,
        f["verdict"],
    ]
    if prev.get("text"):
        how = (
            "re-created with only what was known then"
            if prev.get("kind") == "re-created"
            else "saved"
        )
        lines.append(f"My last prediction for {inst.symbol} ({how}): {prev['text']}")
    cal = f.get("calibration") or {}
    if cal.get("text"):
        lines.append(f"What my misses taught me: {cal['text']}")
    lines.append("Forecasts are ranges, not promises.")
    summary = "\n".join(x for x in lines if x)
    link = chart_link(inst, tf)
    card = {
        "type": "forecast",
        "symbol": inst.symbol,
        "market": mkt,
        "text": f["text"],
        "verdict": f["verdict"],
        "edge": f["edge"],
        "up_probability": f["up_probability"],
        "range": [last["p10"], last["p90"]],
        "median": last["median"],
        "link": link,
    }
    return Result(
        True,
        summary,
        f"Forecast {inst.symbol}",
        f"{f['up_probability'] * 100:.0f}% chance higher",
        card,
        {"navigate": link},
    )


# ---------------------------------------------------------------- scan_market

Focus = Literal[
    "best",
    "bullish",
    "bearish",
    "oversold",
    "overbought",
    "breakouts",
    "patterns",
    "strongest_trend",
]


class ScanArgs(Args):
    market: str | None = Field(
        None, description="IN (India, Nifty 50) or US. Leave out to scan both."
    )
    symbols: list[str] | None = Field(
        None, description="Only these stocks (tickers or names). Leave out for the whole market."
    )
    focus: Focus = Field(
        "best",
        description=(
            "What to look for: best, bullish, bearish, oversold, overbought, breakouts, patterns, "
            "strongest_trend."
        ),
    )
    timeframe: str = Field("1d", description="Candle size: 1d or 1h.")
    limit: int = Field(8, description="How many stocks to list (1-20).")


def scan_market(env: Env, a: ScanArgs) -> Result:
    tf = resolve.timeframe(a.timeframe)
    if a.symbols:
        insts = resolve.stocks(env.ctx, a.symbols, resolve.market_of(a.market))
    else:
        insts = [i for m in _markets(env, a.market) for i in resolve.universe(env.ctx, m)]
    now = env.ctx.clock.now_ms()
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for k, inst in enumerate(insts):
        env.progress(
            100 * k / max(len(insts), 1), f"Reading {inst.symbol} ({k + 1} of {len(insts)})…"
        )
        s = env.ctx.analysis.series(inst, tf, now - VISIBLE_DAYS[tf.value] * DAY_MS)
        if len(s) < 60:
            missing.append(inst.symbol)
            continue
        rep = Analysis(s, inst.market, inst.symbol, inst.name).report()
        rows.append(
            {
                "symbol": inst.symbol,
                "market": inst.market.value,
                "score": rep["score"],
                "bias": rep["bias"],
                "confidence": rep["confidence"],
                "headline": rep["headline"],
                "rsi": rep["momentum"]["rsi"],
                "trend": rep["trend"]["score"],
                "patterns": [p for p in rep["patterns"] if p["status"] in ("forming", "confirmed")],
                "idea": rep["idea"],
                "link": chart_link(inst, tf),
            }
        )
    pick = _focus(rows, a.focus)[: max(1, min(20, a.limit))]
    if not rows:
        raise AgoraError(
            "NO_PRICES",
            "There are no saved prices to scan yet.",
            "Download prices on the Data screen (or ask me to refresh data) and try again.",
        )
    lines = [f"Scanned {len(rows)} stocks ({tf.value}) for '{a.focus}'. Top {len(pick)}:"]
    for r in pick:
        pat = f"; {r['patterns'][0]['name']} {r['patterns'][0]['status']}" if r["patterns"] else ""
        lines.append(
            f"- {r['symbol']}: {r['bias']} {r['score']:+.0f}, RSI {r['rsi']:.0f}, {r['headline']}{pat}"
        )
    if missing:
        lines.append(
            f"No saved prices for: {', '.join(missing[:10])}{'…' if len(missing) > 10 else ''}."
        )
    env.state.symbols = [r["symbol"] for r in pick]
    card = {
        "type": "scan",
        "focus": a.focus,
        "rows": [
            {k: r[k] for k in ("symbol", "market", "score", "bias", "headline", "rsi", "link")}
            for r in pick
        ],
        "scanned": len(rows),
        "missing": missing,
    }
    return Result(
        True, "\n".join(lines), f"Scanned {len(rows)} stocks", f"{len(pick)} stand out", card
    )


def _focus(rows: list[dict[str, Any]], focus: str) -> list[dict[str, Any]]:
    if focus == "bearish":
        return sorted(rows, key=lambda r: r["score"])
    if focus == "oversold":
        return sorted((r for r in rows if r["rsi"] <= 40), key=lambda r: r["rsi"])
    if focus == "overbought":
        return sorted((r for r in rows if r["rsi"] >= 60), key=lambda r: -r["rsi"])
    if focus == "breakouts":
        hits = [r for r in rows if any(p["status"] == "confirmed" for p in r["patterns"])]
        return sorted(hits, key=lambda r: -abs(r["score"]))
    if focus == "patterns":
        return sorted(
            (r for r in rows if r["patterns"]),
            key=lambda r: -max(p["confidence"] for p in r["patterns"]),
        )
    if focus == "strongest_trend":
        return sorted(rows, key=lambda r: -abs(r["trend"]))
    if focus == "bullish":
        return sorted(rows, key=lambda r: -r["score"])

    # "best": strongest readings either way, preferring a usable trade idea
    def best(r: dict[str, Any]) -> float:
        good = r["idea"] is not None and r["idea"].get("quality") in ("good", "fair")
        return (
            abs(float(r["score"])) + (15 if good else 0) + (10 if r["confidence"] == "high" else 0)
        )

    return sorted(rows, key=best, reverse=True)


# ---------------------------------------------------------------- market_overview


class OverviewArgs(Args):
    market: str = Field("IN", description="IN (India) or US.")


def market_overview(env: Env, a: OverviewArgs) -> Result:
    market = resolve.market_of(a.market) or Market.IN
    with env.ctx.db.session() as s:
        bench = find_instrument(s, market, data_service.BENCHMARK[market])
    lines: list[str] = []
    card: dict[str, Any] = {"type": "overview", "market": market.value}
    if bench is not None:
        try:
            rep = env.ctx.analysis.chart(bench, Timeframe.D1, with_forecast=False)["report"]
            lines.append(
                f"{bench.symbol}: {rep['headline']}; score {rep['score']:+.0f}; day change {rep['change_pct']:+.2f}%."
            )
            card["index"] = {
                "symbol": bench.symbol,
                "headline": rep["headline"],
                "score": rep["score"],
                "change_pct": rep["change_pct"],
                "link": chart_link(bench, Timeframe.D1),
            }
        except AgoraError:
            lines.append(f"No saved prices for {bench.symbol} yet.")
    now = env.ctx.clock.now_ms()
    moves: list[tuple[str, float]] = []
    above = total = 0
    for inst in resolve.universe(env.ctx, market):
        s = env.ctx.analysis.series(inst, Timeframe.D1, now - 120 * DAY_MS, warm_bars=60)
        if len(s) < 52:
            continue
        c = s.close
        moves.append((inst.symbol, float(c[-1] / c[-2] - 1.0)))
        total += 1
        above += int(c[-1] > float(np.mean(c[-50:])))
    if total:
        up = sum(1 for _, m in moves if m > 0)
        moves.sort(key=lambda x: x[1])
        lines.append(
            f"Breadth: {up} of {total} stocks rose on the last day; {above} of {total} are above "
            "their 50-day average."
        )
        lines.append(
            "Biggest gainers: " + ", ".join(f"{sym} {m * 100:+.1f}%" for sym, m in moves[-3:][::-1])
        )
        lines.append(
            "Biggest losers: " + ", ".join(f"{sym} {m * 100:+.1f}%" for sym, m in moves[:3])
        )
        card.update(
            {
                "advancers": up,
                "stocks": total,
                "above_50dma": above,
                "gainers": moves[-3:][::-1],
                "losers": moves[:3],
            }
        )
    if env.ctx.news.enabled():
        feeds = env.ctx.news.feeds(market)
        env.ctx.news.refresh(feeds)
        items = env.ctx.news.latest(market, limit=5)
        if items:
            lines.append("Top headlines:")
            lines += [f"- [{i['tone']}] {i['title']}" for i in items]
            card["news"] = [
                {k: i[k] for k in ("title", "link", "tone", "publisher", "published_at")}
                for i in items
            ]
    if not lines:
        raise AgoraError(
            "NO_PRICES",
            "I don't have prices for this market yet.",
            "Download prices on the Data screen first.",
        )
    return Result(
        True, "\n".join(lines), f"Checked the {market.value} market", f"{total} stocks read", card
    )


# ---------------------------------------------------------------- get_news


class NewsArgs(Args):
    symbol: str | None = Field(
        None, description="A stock for company news. Leave out for market news."
    )
    market: str | None = Field(None, description="IN or US, for market news.")
    about: str | None = Field(
        None,
        description="Leave out, or 'world' for geopolitics and the world economy, or a topic: "
        "war, sanctions, tariffs, rates, inflation, oil, banks, elections, currency, disaster.",
    )
    hours: int = Field(72, description="How far back, in hours (1-720).")


ABOUT: dict[str, str] = {
    "war": "conflict", "conflict": "conflict", "military": "conflict", "geopolitics": "conflict",
    "terror": "terror", "sanction": "sanctions", "tariff": "trade", "trade": "trade",
    "rate": "central_bank", "fed": "central_bank", "rbi": "central_bank",
    "central bank": "central_bank", "inflation": "inflation", "cpi": "inflation",
    "jobs": "growth", "gdp": "growth", "recession": "growth", "oil": "energy",
    "crude": "energy", "energy": "energy", "bank": "banking", "debt": "debt",
    "bond": "debt", "currency": "currency", "rupee": "currency", "dollar": "currency",
    "election": "politics", "politic": "politics", "pandemic": "health", "virus": "health",
    "disaster": "disaster", "earthquake": "disaster", "cyclone": "disaster",
    "cyber": "cyber", "crash": "market_stress", "budget": "fiscal", "tax": "fiscal",
}  # fmt: skip


def _topic_of(about: str | None) -> str | None:
    t = (about or "").lower()
    return next((v for k, v in ABOUT.items() if k in t), None)


def get_news(env: Env, a: NewsArgs) -> Result:
    svc = env.ctx.news
    if not svc.enabled():
        return Result(
            False, "Reading news is turned off in Settings.", "Checked the news", "News is off"
        )
    inst = resolve.stock(env.ctx, a.symbol, resolve.market_of(a.market)) if a.symbol else None
    market = inst.market if inst else resolve.market_of(a.market)
    topic = _topic_of(a.about) if not inst else None
    world = bool(a.about) and not inst
    feeds = svc.feeds(market, inst) if not world else []
    if not inst:
        feeds += svc.world_feeds(market)
    env.progress(20, "Reading the latest headlines…")
    r = svc.refresh(feeds)
    hours = max(1, min(720, a.hours))
    if world:
        items = svc.latest(
            None, hours=hours, limit=10, world=None, topic=topic, min_severity=0 if topic else 2
        )
    else:
        items = svc.latest(market, inst.id if inst else None, hours, 10)
    lines = []
    if inst:
        mood = svc.mood(inst.id, a.hours)
        lines.append(
            f"News about {inst.symbol}: {len(items)} headlines; overall tone {mood['tone']} ({mood['score']:+.2f})."
        )
    else:
        what = topics.label(topic) if topic else "world" if world else "market"
        lines.append(f"Latest {what} news ({len(items)} headlines):")
    lines += [
        f"- [{(i.get('topic_labels') or ['business'])[0]}, severity {i.get('severity', 0)}, "
        f"{i['tone']}] {i['title']} ({i['publisher'] or 'news'})"
        for i in items
    ]
    if not inst:
        g = svc.risk(market)
        lines.append(f"News risk now: {g['level']:.0f}/100 ({g['name']}).")
    if r.errors and not items:
        lines.append("Some news sources couldn't be reached: " + "; ".join(r.errors[:2]))
    card = {
        "type": "news",
        "symbol": inst.symbol if inst else None,
        "market": market.value if market else None,
        "items": [
            {k: i[k] for k in ("title", "link", "tone", "publisher", "published_at", "sentiment")}
            for i in items
        ],
    }
    who = inst.symbol if inst else (market.value if market else "the markets")
    return Result(
        True, "\n".join(lines), f"Read the news on {who}", f"{len(items)} headlines", card
    )


# ---------------------------------------------------------------- news_risk


class RiskArgs(Args):
    market: str | None = Field(None, description="IN or US. Leave out for the whole world.")


def news_risk(env: Env, a: RiskArgs) -> Result:
    """How dangerous the news is for a market right now, why, and what the desk does."""
    from backend.kairos import news_guard as ng

    svc = env.ctx.news
    if not svc.enabled():
        return Result(
            False, "Reading news is turned off in Settings.", "Checked news risk", "News is off"
        )
    market = resolve.market_of(a.market)
    env.progress(15, "Reading world and market news…")
    feeds = svc.world_feeds(market) + (svc.feeds(market) if market else [])
    r = svc.refresh(
        [f for f in feeds if f.format != "gdelt"]
    )  # quick: GDELT refreshes in the background
    svc.ensure_fresh(feeds)
    g = svc.risk(market)
    mode = str(read_setting(env.ctx.db, "kairos.news_guard"))
    who = {None: "the world", Market.IN: "Indian stocks", Market.US: "US stocks"}[market]
    lines = [f"News risk for {who}: {g['level']:.0f} of 100 ({g['name']}). {g['text']}"]
    if g["drivers"]:
        lines.append("What is driving it:")
        for d in g["drivers"][:5]:
            src = f"{d['sources']} sources" if d["sources"] > 1 else d["publisher"] or "1 source"
            lines.append(f"- [{d['topic_label']}, severity {d['severity']}] {d['title']} ({src})")
    adv = ng.advise(mode, g, {"state": "quiet"}, long_pnl_pct=-0.1, move_pct=lambda: None)
    if mode == "off":
        lines.append("The desk's news guard is off: it trades on prices only.")
    else:
        rules = []
        if adv.size_factor < 1:
            rules.append("keeps trading, new trades at half size")
        else:
            rules.append("trades normally")
        if mode == "protective" and g["level"] >= ng.ELEVATED:
            rules.append("cuts losing longs once the market's prices fall with the news")
        if mode == "protective" and g["level"] >= ng.SEVERE:
            rules.append("sells longs if the market falls 1%+ on a candle")
        lines.append(f"Kairos's desk ({mode} mode) " + ", ".join(rules) + ".")
        tilt = g.get("sector_tilt") or {}
        up = [k for k, v in sorted(tilt.items(), key=lambda x: -x[1]) if v >= ng.SECTOR_EDGE]
        down = [k for k, v in sorted(tilt.items(), key=lambda x: x[1]) if v <= -ng.SECTOR_EDGE]
        if up:
            lines.append("The news helps: " + ", ".join(up[:5]) + " (the desk is readier to buy).")
        if down:
            lines.append("The news hurts: " + ", ".join(down[:5]) + " (half size, losers cut).")
    if r.errors and not g["drivers"]:
        lines.append("Some news sources couldn't be reached: " + "; ".join(r.errors[:2]))
    card = {
        "type": "news_risk",
        "market": market.value if market else "WORLD",
        "level": g["level"],
        "name": g["name"],
        "text": g["text"],
        "mode": mode,
        "drivers": g["drivers"][:5],
        "link": "/news",
    }
    return Result(
        True,
        "\n".join(lines),
        f"Checked news risk for {who}",
        f"{g['level']:.0f}/100 {g['name']}",
        card,
    )


# ---------------------------------------------------------------- lookup_knowledge


class KnowledgeArgs(Args):
    topic: str = Field(
        description="What to look up, e.g. 'bear flag', 'Sharpe ratio', 'position sizing'."
    )


def lookup_knowledge(env: Env, a: KnowledgeArgs) -> Result:
    from backend.metis import library

    # Kairos's playbook first, then Metis's quant library (D-81): the best of both, by score
    found = knowledge.search(a.topic, k=3)
    titles = {s.title for s in found}
    found += [s for s in library.search(a.topic, k=2) if s.title not in titles]
    found = found[:4]
    if not found:
        return Result(
            True,
            f"My playbook has nothing specific on '{a.topic}'. Answer from general trading knowledge, "
            "briefly, and say so.",
            f"Looked up “{a.topic}”",
            "Nothing specific",
        )
    text = "\n\n".join(f"{s.title}: {s.body}" for s in found)
    return Result(True, text, f"Looked up “{a.topic}”", found[0].title)


TOOLS = [
    Tool(
        "analyze_chart",
        "Read one stock's chart in depth: trend, support/resistance, trendlines, chart and candlestick "
        "patterns, volume, divergences, a trade idea and a forecast range. Opens the chart with "
        "Kairos's drawings.",
        ChartArgs,
        analyze_chart,
        lambda a: f"Reading {a.symbol}'s chart…",
    ),
    Tool(
        "forecast",
        "A likely price range for the next few candles, with its tested track record.",
        ForecastArgs,
        forecast,
        lambda a: f"Forecasting {a.symbol}…",
        group="forecast",
    ),
    Tool(
        "scan_market",
        "Read many stocks at once and rank them: best setups, bullish, bearish, oversold, overbought, "
        "breakouts, chart patterns or strongest trends.",
        ScanArgs,
        scan_market,
        lambda a: "Scanning stocks…",
    ),
    Tool(
        "market_overview",
        "How the market is doing today: index trend, breadth, biggest movers and top headlines.",
        OverviewArgs,
        market_overview,
        lambda a: f"Checking the {a.market} market…",
        group="overview",
    ),
    Tool(
        "get_news",
        "Latest headlines with their tone and topic: for one stock, a market, the world "
        "(about='world') or a topic such as war, tariffs, rates or oil.",
        NewsArgs,
        get_news,
        lambda a: "Reading the news…",
    ),
    Tool(
        "news_risk",
        "How risky the news is for markets right now (wars, sanctions, tariffs, central banks, "
        "crises), what is driving it, and what Kairos's desk does about it (damage control).",
        RiskArgs,
        news_risk,
        lambda a: "Reading the world news…",
    ),
    Tool(
        "lookup_knowledge",
        "Look up how an indicator, chart pattern, candlestick, metric, risk rule or trading concept "
        "works.",
        KnowledgeArgs,
        lookup_knowledge,
        lambda a: f"Looking up {a.topic}…",
    ),
]
