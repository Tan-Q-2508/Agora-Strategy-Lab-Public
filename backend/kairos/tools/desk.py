"""Kairos's desk and learning tools: trade on its own (paper money), report, and say what it
has learned (KAIROS §7.2, §8, §9)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from backend.core.types import Market, Timeframe
from backend.errors import AgoraError
from backend.kairos import memory, resolve
from backend.kairos.tools.base import Args, Env, Result, Tool, money
from backend.kairos.tools.lab import wait_job


class DeskArgs(Args):
    symbols: list[str] | None = Field(
        None, description="Stocks for Kairos to watch and trade (tickers or names)."
    )
    market: str | None = Field(None, description="IN or US (default: from the stocks).")
    timeframe: str = Field("1d", description="Candle size: 1d (default), 1h, 15m, 5m.")
    capital: float | None = Field(None, description="Paper money for the desk (default: Settings).")


def start_desk(env: Env, a: DeskArgs) -> Result:
    market = resolve.market_of(a.market) or resolve.market_of(env.state.market)
    names = a.symbols or env.state.symbols
    if not names:
        raise AgoraError(
            "NO_STOCKS",
            "Which stocks should I watch?",
            "Name a few, e.g. “watch TCS, Infosys and HDFC Bank and trade them for me”.",
        )
    insts = [i for i in resolve.stocks(env.ctx, names, market) if not i.is_index]
    if not insts:
        raise AgoraError("NO_STOCKS", "I couldn't find those stocks.", "Check the names.")
    market = insts[0].market
    insts = [i for i in insts if i.market is market]
    tf = resolve.timeframe(a.timeframe)
    learning = env.ctx.learning
    if learning.trained(market, tf) is None:
        env.progress(5, "Studying this market's history first…")
        jid = learning.ensure_trained(market, tf)
        if jid:
            wait_job(env, jid, "study of the history")
    env.progress(80, "Opening the desk…")
    desk = env.ctx.desk.launch(insts, tf, a.capital)
    sid = desk["id"]
    env.state.session_id = sid
    env.state.symbols = [i.symbol for i in insts]
    env.state.market = market.value
    learned = desk.get("learned") or {}
    best = (learned.get("best") or [{}])[0].get("text", "")
    who = ", ".join(i.symbol for i in insts)
    m = market.value
    risk = desk.get("account", {})
    capital = money(risk.get("starting_capital", 0), m)
    mode = "a practice replay" if desk.get("mode") == "replay" else "live prices"
    summary = (
        f"Kairos desk #{sid} is running on {who} with {capital} of paper money ({mode}). "
        "The Kairos brain decides every trade from the chart signals, weighted by what has "
        "worked; each trade gets a written thesis and, when it closes, a review that updates "
        f"what Kairos has learned. It runs until stopped or Agora is closed. {best}"
    )
    link = f"/paper/desk/{sid}"
    card = {
        "type": "desk",
        "id": sid,
        "market": m,
        "symbols": [i.symbol for i in insts],
        "capital": risk.get("starting_capital"),
        "mode": desk.get("mode"),
        "link": link,
    }
    return Result(
        True,
        summary,
        f"Started the Kairos desk on {len(insts)} stocks",
        f"Desk #{sid}",
        card,
        {"navigate": link},
    )


class DeskStopArgs(Args):
    desk: str | None = Field("all", description="A desk id, or 'all'.")


def stop_desk(env: Env, a: DeskStopArgs) -> Result:
    running = [d for d in env.ctx.desk.desks() if d["state"] != "stopped"]
    target = (a.desk or "all").strip().lower()
    if target != "all" and target.isdigit():
        running = [d for d in running if d["id"] == int(target)]
    if not running:
        return Result(
            True, "No Kairos desk is running.", "Checked the Kairos desk", "Nothing running"
        )
    for d in running:
        env.ctx.desk.stop(d["id"])
    ids = ", ".join(f"#{d['id']}" for d in running)
    return Result(
        True,
        f"Stopped Kairos desk {ids}. Its journal and what it learned are kept.",
        "Stopped the Kairos desk",
        f"{len(running)} stopped",
        {"type": "link", "label": "Open paper trading", "link": "/paper"},
    )


class NoArgs(Args):
    pass


class DeskStatusArgs(Args):
    market: str | None = Field(None, description="IN or US (default: every desk).")
    timeframe: str | None = Field(
        None, description="Candle size, e.g. 1d, 1h, 15m, 5m, 1m (default: every desk)."
    )


TF_NAME = {"1d": "daily", "1h": "1-hour", "15m": "15-minute", "5m": "5-minute", "1m": "1-minute"}


def _desk_line(d: dict[str, Any]) -> str:
    """One desk in a sentence, with what its trade judge is doing (D-145, D-147)."""
    m = d["market"]
    where = "India" if m == "IN" else "US"
    tf = TF_NAME.get(d.get("timeframe", "1d"), d.get("timeframe", "1d"))
    judge = ((d.get("learned") or {}).get("judge") or {}).get("text")
    return (
        f"#{d['id']} {where} {tf} desk ({d['state']}): equity {money(d['equity'], m)}, "
        f"return {d['total_return']:+.2f}% since it began, today {money(d['day_pnl'], m)}, "
        f"{d['open_positions']} open, {d['trades']} trades closed since it started."
        + (f" Trade judge: {judge}" if judge else "")
    )


def desk_status(env: Env, a: DeskStatusArgs) -> Result:
    """Every running desk, or the ones asked about: Kairos runs a desk per market and candle
    size, so describing only the newest one told the user other desks didn't exist."""
    desks = [d for d in env.ctx.desk.desks() if d["state"] != "stopped"]
    if not desks:
        return Result(
            True,
            "There is no Kairos desk running. Ask me to watch some stocks and trade them.",
            "Checked the Kairos desk",
            "No desk",
        )
    market = (a.market or "").strip().upper()
    tf = (a.timeframe or "").strip().lower()
    tf = {v: k for k, v in TF_NAME.items()}.get(tf, tf)
    picked = [
        d
        for d in desks
        if (not market or d["market"] == market) and (not tf or d.get("timeframe", "1d") == tf)
    ]
    if not picked:
        names = ", ".join(f"{d['market']} {TF_NAME.get(d.get('timeframe', '1d'))}" for d in desks)
        return Result(
            True,
            f"No such desk is running. Running desks: {names}.",
            "Checked the Kairos desk",
            "Not found",
        )
    full = [env.ctx.desk.desk(d["id"]) for d in picked]
    lines = [f"{len(full)} Kairos desk{'s' if len(full) != 1 else ''} running:"]
    lines += ["- " + _desk_line(d) for d in full]
    if len(full) == 1:
        d = full[0]
        for p in d.get("positions", [])[:5]:
            pnl = p.get("unrealized_pct")
            lines.append(
                f"- Holding {p['symbol']} ({p['side']}) since {p['entry_price']:.2f}"
                + (f", {pnl:+.2f}%" if pnl is not None else "")
                + (f". Thesis: {p['thesis'][:220]}" if p.get("thesis") else "")
            )
        for j in [x for x in d.get("journal", []) if x["kind"] == "review"][:3]:
            lines.append(f"- Review: {j['text'][:220]}")
    d = full[0]
    m = d["market"]
    card = {
        "type": "desk",
        "id": d["id"],
        "market": m,
        "symbols": d.get("symbols") or [],
        "capital": d["account"]["starting_capital"],
        "equity": d["equity"],
        "total_return": d["total_return"],
        "mode": d.get("mode"),
        "link": f"/paper/desk/{d['id']}",
    }
    detail = f"{d['total_return']:+.2f}%" if len(full) == 1 else f"{len(full)} desks"
    return Result(True, "\n".join(lines), "Checked the Kairos desk", detail, card)


class LessonsArgs(Args):
    market: str | None = Field(None, description="IN or US (default: both).")
    timeframe: str = Field("1d", description="Candle size the lessons are for.")


def get_lessons(env: Env, a: LessonsArgs) -> Result:
    markets = [resolve.market_of(a.market)] if a.market else [Market.IN, Market.US]
    tf = resolve.timeframe(a.timeframe)
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    for m in markets:
        if m is None:
            continue
        learned = env.ctx.learning.learned(m, tf)
        info = learned.get("trained")
        if info:
            lines.append(
                f"{m.value}: studied {info['candles']:,} candles; a move up {info['horizon']} candles "
                f"later happened {round(100 * (info['base_rate'] or 0))}% of the time on any candle."
            )
        for x in learned["best"][:3]:
            lines.append(f"- Works: {x['text']}")
            items.append({"label": x["label"], "sub": x["text"], "link": None})
        for x in learned["worst"][:2]:
            lines.append(f"- Doesn't: {x['text']}")
        for lesson in memory.lessons(env.ctx, m, limit=4):
            lines.append(f"- Lesson: {lesson['text']}")
    if not lines:
        return Result(
            True,
            "I haven't studied any history yet. Open a chart with Kairos switched on, or ask me "
            "to start a desk, and I'll study the market first.",
            "Checked what Kairos learned",
            "Nothing yet",
        )
    card = {"type": "list", "title": "What Kairos learned", "items": items[:6]}
    return Result(
        True, "\n".join(lines), "Checked what Kairos learned", f"{len(lines)} findings", card
    )


class TrainArgs(Args):
    market: str | None = Field(None, description="IN or US.")
    timeframe: str = Field("1d", description="Candle size to study.")


def train_kairos(env: Env, a: TrainArgs) -> Result:
    market = resolve.market_of(a.market) or resolve.market_of(env.state.market) or Market.IN
    tf = resolve.timeframe(a.timeframe, Timeframe.D1)
    jid = env.ctx.learning.start_training(market, tf)
    out = wait_job(env, jid, "study of the history")
    learned = env.ctx.learning.learned(market, tf)
    best = "; ".join(x["text"] for x in learned["best"][:2])
    summary = (
        f"Studied {out['stocks']} stocks ({out['candles']:,} {tf.value} candles) and measured "
        f"{out['signals']} kinds of signal over {out['horizon']} candles. {best}"
    )
    return Result(
        True,
        summary,
        "Studied the history",
        f"{out['signals']} signals measured",
        {"type": "link", "label": "See what Kairos learned", "link": "/paper/desk"},
    )


TOOLS = [
    Tool(
        "start_desk",
        "Kairos trades chosen stocks on its own with paper money: watches them, opens and closes "
        "trades by its own rules, and keeps a journal. Use for 'keep an eye on X and trade it'.",
        DeskArgs,
        start_desk,
        lambda a: "Starting the Kairos desk…",
        group="desk",
    ),
    Tool(
        "stop_desk",
        "Stop the Kairos desk.",
        DeskStopArgs,
        stop_desk,
        lambda a: "Stopping the Kairos desk…",
        group="desk",
    ),
    Tool(
        "desk_status",
        "How Kairos's desks are doing (one per market and candle size): results, open trades, "
        "whether each trades or stands aside; with a market and candle size, that desk's "
        "positions, theses and reviews.",
        DeskStatusArgs,
        desk_status,
        lambda a: "Checking the Kairos desk…",
        group="desk",
    ),
    Tool(
        "get_lessons",
        "What Kairos has learned: which signals worked on this market's history and in its own "
        "paper trades, and its lessons.",
        LessonsArgs,
        get_lessons,
        lambda a: "Looking at what I've learned…",
        group="learning",
    ),
    Tool(
        "train_kairos",
        "Study a market's price history again to re-measure how every signal worked.",
        TrainArgs,
        train_kairos,
        lambda a: "Studying the history…",
        group="learning",
    ),
]


# ---------------------------------------------------------------- research


class ResearchArgs(Args):
    symbols: list[str] | None = Field(None, description="Stocks to research (tickers or names).")
    market: str | None = Field(None, description="IN or US (default: from the stocks).")
    timeframe: str = Field("1d", description="Candle size: 1d (default), 1h, 15m, 5m.")
    years: float | None = Field(None, description="Years of history to use (default 5).")


def research_strategy(env: Env, a: ResearchArgs) -> Result:
    from backend.kairos import research

    market = resolve.market_of(a.market) or resolve.market_of(env.state.market)
    names = a.symbols or env.state.symbols
    if not names:
        raise AgoraError(
            "NO_STOCKS",
            "Which stocks should I research?",
            "Name them, e.g. “find the best strategy for HDFC Bank and ICICI Bank”.",
        )
    insts = [i for i in resolve.stocks(env.ctx, names, market) if not i.is_index]
    if not insts:
        raise AgoraError("NO_STOCKS", "I couldn't find those stocks.", "Check the names.")
    insts = [i for i in insts if i.market is insts[0].market][:10]
    tf = resolve.timeframe(a.timeframe)
    cfg = env.ctx.services.get("kairos_research_config")
    job = env.ctx.jobs.submit(
        "kairos_research",
        "Kairos is researching strategies",
        lambda jc: research.research(
            env.ctx, insts, tf, a.years, cfg=cfg, progress=jc.progress, check=jc.check
        ),
        priority=True,  # the user is waiting in the chat (D-115)
    )
    out = wait_job(env, job.id, "research")
    m = out["market"]
    lines = [
        "Character: "
        + "; ".join(f"{c['symbol']} {c['label']}" for c in out["character"])
        + f". Tried {len(out['candidates'])} strategies in {out['runs']} backtests "
        "(tuned on the first 70% of the period, judged on the last 30%)."
    ]
    for c in out["candidates"][:6]:
        oos = c["out_of_sample_sharpe"]
        lines.append(
            f"- {c['name']}: {c['verdict']}"
            + (
                f" (unseen-years Sharpe {oos:.2f}, {c['out_of_sample_trades']} trades)"
                if oos is not None
                else ""
            )
        )
    w = out["winner"]
    items = [{"label": c["name"], "sub": c["verdict"], "link": None} for c in out["candidates"][:6]]
    card: dict[str, Any] = {"type": "list", "title": "Strategy research", "items": items}
    ui = None
    if w is not None:
        wait_job(env, f"backtest-{w['run_id']}", "backtest of the winner")
        env.state.strategy_id = w["strategy_id"]
        env.state.run_id = w["run_id"]
        env.state.runs.append(w["run_id"])
        env.state.symbols = out["symbols"]
        env.state.market = m
        tuned = ", ".join(f"{k}={v:g}" for k, v in w["params"].items()) or "its default settings"
        if w.get("note"):
            lines.append(
                f"Winner: {w['name']} with {tuned}. {w['note']} Full backtest #{w['run_id']} is "
                "on the results screen."
            )
        else:
            lines.append(
                f"Winner: {w['name']} with {tuned}, saved as strategy #{w['strategy_id']}; full "
                f"backtest #{w['run_id']} is on the results screen."
            )
        link = f"/backtests/{w['run_id']}"
        items.insert(
            0, {"label": f"Winner: {w['name']}", "sub": "open the full backtest", "link": link}
        )
        ui = {"navigate": link}
    lines += [f"Caution: {c}" for c in out["cautions"]]
    label = f"Researched {len(out['candidates'])} strategies"
    detail = "Winner found" if w else "Nothing held up"
    return Result(True, "\n".join(lines), label, detail, card, ui)


TOOLS.append(
    Tool(
        "research_strategy",
        "Find the best strategy for chosen stocks: profiles them, tunes every suitable strategy "
        "(and Kairos's own brain) on the first 70% of the history, keeps what survives the last "
        "30% and a walk-forward test, then saves and backtests the winner.",
        ResearchArgs,
        research_strategy,
        lambda a: "Researching strategies…",
        group="research",
    )
)
