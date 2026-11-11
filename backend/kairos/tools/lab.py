"""Kairos's lab tools: strategies, backtests, optimisation, comparisons, paper trading,
downloads and moving around the app. Each goes through the same services the screens use
(D-56): there is no hidden path, and nothing here can touch real money."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select

from backend.backtest.manager import (
    BacktestRequest,
    SweepIn,
    SweepParamIn,
    WalkForwardIn,
    latest_run_for,
)
from backend.core.types import Market, Timeframe
from backend.db.models import BacktestRun, Strategy
from backend.errors import AgoraError
from backend.kairos import resolve
from backend.kairos.tools.base import Args, Env, Result, Tool, money, pct
from backend.paper.service import AccountIn, SessionIn
from backend.strategy import revisions, templates
from backend.strategy import service as strategy_service
from backend.strategy.definition import Universe, VisualDefinition, content_hash

WAIT_LIMIT_S = 20 * 60


def wait_job(env: Env, job_id: str, what: str) -> Any:
    """Follow a background job, passing its progress on, until it ends."""
    start = time.monotonic()
    while True:
        job = env.ctx.jobs.get(job_id)
        if job is None:
            raise AgoraError("JOB_LOST", f"The {what} stopped unexpectedly.", "Try again.")
        if job.status in ("done", "failed", "cancelled"):
            if job.status != "done":
                err = job.error or {}
                raise AgoraError(
                    "JOB_FAILED",
                    err.get("message") or f"The {what} didn't finish.",
                    err.get("action") or "Try again, or open the screen for details.",
                    detail=err.get("detail", ""),
                )
            return job.result
        env.progress(job.pct, job.message)
        if time.monotonic() - start > WAIT_LIMIT_S:
            raise AgoraError(
                "JOB_SLOW",
                f"The {what} is taking very long.",
                "Check its screen; it keeps running there.",
            )
        time.sleep(0.25)


# ---------------------------------------------------------------- list strategies / templates


class NoArgs(Args):
    pass


def _pct(x: Any) -> str:
    return "?" if x is None else f"{float(x) * 100:.1f}%"


def _last_words(last: dict[str, Any] | None) -> str:
    if not last:
        return "; not backtested yet"
    return (
        f"; latest backtest #{last['run_id']}: return {_pct(last['total_return'])}, won "
        f"{_pct(last['win_rate'])} of {last['trades'] or '?'} trades, worst drop "
        f"{_pct(last['max_drawdown'])}"
    )


def list_strategies(env: Env, _a: NoArgs) -> Result:
    with env.ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy)
            .where(Strategy.archived_at.is_(None))
            .order_by(Strategy.updated_at.desc())
            .limit(30)
        ).all()
        items = []
        for r in rows:
            v = strategy_service.latest_version(s, r.id)
            if v is None:
                continue
            d = v.definition
            last = latest_run_for(s, r.id)
            m = json.loads(last.metrics or "{}") if last is not None else {}
            items.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "market": d.market,
                    "timeframe": d.timeframe,
                    "kind": d.kind,
                    "symbols": d.universe.symbols if d.universe.kind == "symbols" else "all",
                    # its latest backtest, so "which is doing best?" needs no new runs (D-122)
                    "last": {
                        "run_id": last.id,
                        "at": last.created_at,
                        "total_return": m.get("total_return"),
                        "win_rate": m.get("win_rate"),
                        "trades": m.get("trades") or m.get("num_trades"),
                        "max_drawdown": m.get("max_drawdown"),
                    }
                    if last is not None
                    else None,
                }
            )
    if not items:
        return Result(
            True,
            "No saved strategies yet. Offer to create one from a template or an idea.",
            "Listed strategies",
            "None yet",
        )
    items.sort(key=lambda i: -((i["last"] or {}).get("total_return") or -9e9))
    lines = [f"{len(items)} saved strategies, best latest backtest first:"]
    lines += [
        f"- #{i['id']} {i['name']} ({i['market']}, {i['timeframe']}, {i['kind']}; stocks: {i['symbols'] if i['symbols'] == 'all' else ', '.join(i['symbols'][:8])})"
        + _last_words(i["last"])
        for i in items
    ]
    card = {
        "type": "list",
        "title": "Your strategies",
        "items": [
            {
                "label": i["name"],
                "sub": f"{i['market']} · {i['timeframe']}",
                "link": f"/strategies/{i['id']}",
            }
            for i in items[:12]
        ],
    }
    return Result(True, "\n".join(lines), "Listed your strategies", f"{len(items)} found", card)


class TemplatesArgs(Args):
    market: str | None = Field(None, description="IN or US (templates exist for both).")


def list_templates(env: Env, _a: TemplatesArgs) -> Result:
    lines = ["Starter strategies (template keys):"]
    lines += [
        f"- {t.key}: {t.name}, {t.timeframe}. {t.summary}" for t in templates.TEMPLATES.values()
    ]
    card = {
        "type": "list",
        "title": "Starter strategies",
        "items": [{"label": t.name, "sub": t.summary} for t in templates.TEMPLATES.values()],
    }
    return Result(
        True,
        "\n".join(lines),
        "Listed starter strategies",
        f"{len(templates.TEMPLATES)} templates",
        card,
    )


# ---------------------------------------------------------------- create_strategy


class CreateArgs(Args):
    template: str | None = Field(
        None,
        description=(
            "A starter strategy: ma_crossover, rsi_mean_reversion, bollinger_reversion, donchian_breakout, "
            "supertrend, opening_range_breakout, macd_momentum, high_52w_momentum (or its name), "
            "or kairos for Kairos's own brain."
        ),
    )
    idea: str | None = Field(
        None, description="Or: the user's idea in plain English, when no template fits."
    )
    market: str | None = Field(None, description="IN or US.")
    symbols: list[str] | None = Field(
        None, description="Stocks to trade (tickers or names). Leave out for the whole market."
    )
    name: str | None = Field(None, description="A short name for the strategy.")
    timeframe: str | None = Field(
        None, description="Candle size, e.g. 1d or 15m (default: the template's)."
    )


def create_strategy(env: Env, a: CreateArgs) -> Result:
    market = resolve.market_of(a.market) or resolve.market_of(env.state.market)
    insts = resolve.stocks(env.ctx, a.symbols, market) if a.symbols else []
    if insts:
        market = market or insts[0].market
        insts = [i for i in insts if i.market is market]
    market = market or Market.IN
    symbols = [i.symbol for i in insts if not i.is_index]
    key = resolve.template_key(a.template)
    if a.template and key is None and not a.idea and not resolve.means_kairos(a.template):
        raise AgoraError(
            "TEMPLATE_NOT_FOUND",
            f"Agora has no starter strategy called “{a.template}”.",
            "Pick one of: " + ", ".join(t.name for t in templates.TEMPLATES.values()) + ".",
        )
    created_by = "ai_draft"
    note = "Created by Kairos"
    definition: Any
    if resolve.means_kairos(a.template):
        definition = _kairos_definition(env, market, symbols, a.timeframe)
        tname = "Kairos brain"
        description = (
            "Kairos's own rules: chart patterns, levels, momentum, volume and candles, weighted "
            "by how each signal has worked on this market's history."
        )
        created_by = "kairos"
        key = None
    elif key:
        definition = templates.template_definition(key, market.value, symbols or None)
        tname = templates.TEMPLATES[key].name
        description = templates.TEMPLATES[key].description
    elif a.idea:
        env.progress(10, "Turning the idea into rules…")
        draft = env.ctx.ai_service.draft(a.idea, market.value)
        if not draft.get("ok") or not draft.get("definition"):
            problems = "; ".join(i.get("message", "") for i in draft.get("issues", []))[:300]
            raise AgoraError(
                "DRAFT_FAILED",
                "I couldn't turn that idea into valid rules.",
                "Try describing it more simply, or start from a template.",
                detail=problems,
            )
        definition = VisualDefinition.model_validate(draft["definition"])
        if symbols:
            definition = definition.model_copy(
                update={"universe": Universe(kind="symbols", symbols=symbols)}
            )
        tname = "Idea"
        description = draft.get("explanation") or a.idea
    else:
        raise AgoraError(
            "NO_RULES",
            "Which strategy should I build?",
            "Name a template (like RSI mean reversion) or describe the idea.",
        )
    tf = resolve.timeframe(a.timeframe, Timeframe(definition.timeframe)) if a.timeframe else None
    if tf and tf.value != definition.timeframe:
        definition = definition.model_copy(update={"timeframe": tf.value})
    who = (
        ", ".join(symbols[:4]) + ("…" if len(symbols) > 4 else "")
        if symbols
        else ("Nifty 50" if market is Market.IN else "US watchlist")
    )
    name = (a.name or f"{tname} · {who}")[:120]
    with env.ctx.db.session() as s:
        # Revision control (D-79): a strategy the user already has is reused or revised, never
        # copied. Stocks alone don't make a new strategy (D-80): they go with the next steps.
        found = revisions.match(s, definition, template_key=key)
        if found is not None and symbols:
            same_stocks = definition.model_copy(update={"universe": found.definition.universe})
            if content_hash(same_stocks) == content_hash(found.definition):
                definition = same_stocks
        saved = revisions.save(
            s,
            definition=definition,
            author=created_by,  # type: ignore[arg-type]
            name=name,
            description=description,
            now=env.ctx.clock.now_ms(),
            note=note,
            template_key=key,
            source="kairos-create",
        )
        sid, name, version_id = saved.strategy_id, saved.name, saved.version_id
    env.state.strategy_id = sid
    env.state.market = market.value
    if symbols:
        env.state.symbols = symbols
    params = ", ".join(f"{p.name}={p.default:g}" for p in definition.parameters) or "none"
    opening = {
        "new_strategy": f"Created strategy #{sid} “{name}”",
        "revision": f"You already had this strategy, so I saved version {saved.version} of #{sid} “{name}” instead of a copy ({saved.why}; changes: {'; '.join(saved.changes) or 'none'})",
        "unchanged": f"You already have this strategy: #{sid} “{name}”, so I'm using it instead of making a copy",
    }[saved.outcome]
    summary = (
        f"{opening} ({market.value}, {definition.timeframe}, stocks: {who}). "
        f"Adjustable settings: {params}. Version id {version_id}."
    )
    card = {
        "type": "strategy",
        "id": sid,
        "name": name,
        "market": market.value,
        "timeframe": definition.timeframe,
        "symbols": symbols,
        "description": description[:240],
        "link": f"/strategies/{sid}",
    }
    headline = {
        "new_strategy": f"Created “{name}”",
        "revision": f"Saved version {saved.version} of “{name}”",
        "unchanged": f"Using your “{name}”",
    }[saved.outcome]
    return Result(True, summary, headline, f"Strategy #{sid}", card)


def _kairos_definition(env: Env, market: Market, symbols: list[str], tf_text: str | None) -> Any:
    """The Kairos brain as a strategy, with the signal weights it has learned so far."""
    from backend.kairos import brain

    tf = resolve.timeframe(tf_text)
    learning = env.ctx.learning
    if learning.trained(market, tf) is None:
        env.progress(5, "Studying this market's history first…")
        jid = learning.ensure_trained(market, tf)
        if jid:
            wait_job(env, jid, "study of the history")
    if not symbols:
        symbols = [i.symbol for i in resolve.universe(env.ctx, market)][:30]
    info = learning.trained(market, tf)
    return brain.definition(
        market.value,
        symbols,
        timeframe=tf.value,
        weights=learning.weights(market, tf),
        trained_at=info["at"] if info else None,
    )


# ---------------------------------------------------------------- run_backtest


class BacktestArgs(Args):
    strategy: str | None = Field(
        None, description="Strategy name or id. Leave out for the one just created or used."
    )
    symbols: list[str] | None = Field(
        None,
        description="Stocks to test on (tickers or names). Leave out for the strategy's own list.",
    )
    years: float | None = Field(None, description="How many years back to test, e.g. 5.")
    start: str | None = Field(None, description="Or a start date, YYYY-MM-DD.")
    end: str | None = Field(None, description="End date, YYYY-MM-DD (default: today).")
    capital: float | None = Field(None, description="Starting money (default from Settings).")
    timeframe: str | None = Field(None, description="Candle size (default: the strategy's).")


def _metrics_lines(run: dict[str, Any], market: str) -> list[str]:
    m = run["metrics"] or {}
    b = (m.get("benchmark") or {}).get("total_return")
    lines = [
        f"Total return {pct(m.get('total_return'))} (CAGR {pct(m.get('cagr'))}); benchmark {pct(b)}.",
        f"Max drawdown {pct(m.get('max_drawdown'))}; Sharpe {m.get('sharpe', 0) or 0:.2f}; "
        f"{m.get('trades', 0)} trades, win rate {pct(m.get('win_rate'), 0)}; profit factor {m.get('profit_factor') or 0:.2f}.",
        f"Final equity {money(m.get('final_equity') or 0, market)}.",
    ]
    return lines


def _load_run(env: Env, run_id: int) -> dict[str, Any]:
    with env.ctx.db.session() as s:
        row = s.get(BacktestRun, run_id)
        assert row is not None
        return {
            "id": row.id,
            "params": json.loads(row.params),
            "metrics": json.loads(row.metrics) if row.metrics else None,
            "warnings": json.loads(row.warnings) if row.warnings else [],
            "summary": row.summary_text or "",
        }


def run_backtest(env: Env, a: BacktestArgs) -> Result:
    sref = resolve.strategy(env.ctx, a.strategy, latest_id=env.state.strategy_id)
    insts = resolve.stocks(env.ctx, a.symbols, sref.market) if a.symbols else []
    symbols = [i.symbol for i in insts if i.market is sref.market and not i.is_index] or None
    lo, hi = resolve.period(env.ctx.clock.now_ms(), a.years, a.start, a.end)
    req = BacktestRequest(
        strategy_version_id=sref.version_id,
        symbols=symbols,
        timeframe=resolve.timeframe(a.timeframe).value if a.timeframe else None,
        start=lo,
        end=hi,
        capital=a.capital,
        name=f"Kairos: {sref.name}"[:120],
    )
    run_id = env.ctx.backtests.submit(req, priority=True)
    wait_job(env, f"backtest-{run_id}", "backtest")
    run = _load_run(env, run_id)
    env.state.strategy_id = sref.strategy_id
    env.state.run_id = run_id
    env.state.runs.append(run_id)
    if symbols:
        env.state.symbols = symbols
    m = run["metrics"] or {}
    market = run["params"].get("market", sref.market.value)
    lines = [
        f"Backtest #{run_id} of “{sref.name}” on {', '.join(run['params'].get('symbols', [])[:10]) or 'its stocks'}."
    ]
    lines += _metrics_lines(run, market)
    if run["summary"]:
        lines.append(run["summary"])
    warn = [w.get("title", "") for w in run["warnings"] if w.get("level") in ("warn", "error")]
    if warn:
        lines.append("Warnings: " + "; ".join(warn[:4]))
    link = f"/backtests/{run_id}"
    card = {
        "type": "backtest",
        "id": run_id,
        "strategy": sref.name,
        "market": market,
        "symbols": run["params"].get("symbols", []),
        "total_return": m.get("total_return"),
        "cagr": m.get("cagr"),
        "max_drawdown": m.get("max_drawdown"),
        "sharpe": m.get("sharpe"),
        "trades": m.get("trades"),
        "win_rate": m.get("win_rate"),
        "vs_benchmark": m.get("vs_benchmark"),
        "summary": run["summary"],
        "warnings": warn[:3],
        "link": link,
    }
    detail = f"{pct(m.get('total_return'))} · {m.get('trades', 0)} trades"
    return Result(
        True, "\n".join(lines), f"Backtested “{sref.name}”", detail, card, {"navigate": link}
    )


# ---------------------------------------------------------------- optimize_strategy


class OptimizeArgs(Args):
    strategy: str | None = Field(None, description="Strategy name or id (default: the one in use).")
    method: Literal["sweep", "walk_forward"] = Field(
        "walk_forward",
        description=(
            "sweep (try a grid of settings) or walk_forward (tune on a window, test on the next; "
            "more honest)."
        ),
    )
    parameters: list[str] | None = Field(
        None, description="Which settings to tune (at most 2). Default: the first two."
    )
    symbols: list[str] | None = Field(None, description="Stocks to test on.")
    years: float | None = Field(None, description="Years of history to use.")


def _grid(p: Any) -> list[float]:
    """Up to 6 values across a parameter's range, always including its default."""
    lo, hi, step = float(p.min), float(p.max), p.step
    if step:
        vals = [lo + i * float(step) for i in range(int((hi - lo) / float(step)) + 1)]
    else:
        vals = [lo + (hi - lo) * i / 5 for i in range(6)]
    if len(vals) > 6:
        k = len(vals) / 6
        vals = [vals[int(i * k)] for i in range(6)]
    vals.append(float(p.default))
    if p.type == "int":
        vals = [float(round(v)) for v in vals]
    return sorted(set(vals))


def optimize_strategy(env: Env, a: OptimizeArgs) -> Result:
    sref = resolve.strategy(env.ctx, a.strategy, latest_id=env.state.strategy_id)
    with env.ctx.db.session() as s:
        v = strategy_service.get_version(s, sref.version_id)
    assert v is not None
    params = list(v.definition.parameters)
    if not params:
        raise AgoraError(
            "NO_SETTINGS",
            f"“{sref.name}” has no adjustable settings to tune.",
            "Pick a strategy with settings, such as a template.",
        )
    if a.parameters:
        want = {x.lower() for x in a.parameters}
        chosen = [p for p in params if p.name.lower() in want or p.label.lower() in want] or params[
            :2
        ]
    else:
        chosen = params[:2]
    chosen = chosen[:2]
    grid = [SweepParamIn(name=p.name, values=_grid(p)) for p in chosen]
    insts = resolve.stocks(env.ctx, a.symbols, sref.market) if a.symbols else []
    symbols = [i.symbol for i in insts if i.market is sref.market] or None
    lo, hi = resolve.period(env.ctx.clock.now_ms(), a.years, None, None)
    if a.method == "sweep":
        req = BacktestRequest(
            strategy_version_id=sref.version_id,
            symbols=symbols,
            start=lo,
            end=hi,
            mode="sweep",
            sweep=SweepIn(params=grid),
            name=f"Kairos sweep: {sref.name}"[:120],
        )
    else:
        req = BacktestRequest(
            strategy_version_id=sref.version_id,
            symbols=symbols,
            start=lo,
            end=hi,
            mode="walk_forward",
            walk_forward=WalkForwardIn(params=grid),
            name=f"Kairos walk-forward: {sref.name}"[:120],
        )
    run_id = env.ctx.backtests.submit(req, priority=True)
    wait_job(env, f"backtest-{run_id}", "optimisation")
    run = _load_run(env, run_id)
    env.state.run_id = run_id
    env.state.runs.append(run_id)
    m = run["metrics"] or {}
    market = run["params"].get("market", sref.market.value)
    tried = ", ".join(f"{g.name} in {', '.join(f'{x:g}' for x in g.values)}" for g in grid)
    lines = [
        f"{'Parameter sweep' if a.method == 'sweep' else 'Walk-forward test'} #{run_id} of “{sref.name}”; "
        f"tried {tried}."
    ]
    if a.method == "sweep":
        sw = m.get("sweep") or {}
        best = sw.get("best") or {}
        lines.append("Best settings: " + ", ".join(f"{k}={val:g}" for k, val in best.items()) + ".")
        if sw.get("isolated_peak"):
            lines.append("Warning: the best setting is an isolated peak (likely overfitting).")
    else:
        lines.append(
            "These are stitched out-of-sample results (each window tested on data its settings never "
            "saw):"
        )
    lines += _metrics_lines(run, market)
    link = f"/backtests/{run_id}"
    card = {
        "type": "backtest",
        "id": run_id,
        "strategy": sref.name,
        "market": market,
        "mode": a.method,
        "total_return": m.get("total_return"),
        "cagr": m.get("cagr"),
        "max_drawdown": m.get("max_drawdown"),
        "sharpe": m.get("sharpe"),
        "trades": m.get("trades"),
        "win_rate": m.get("win_rate"),
        "vs_benchmark": m.get("vs_benchmark"),
        "summary": run["summary"],
        "warnings": [w.get("title", "") for w in run["warnings"]][:3],
        "link": link,
    }
    return Result(
        True,
        "\n".join(lines),
        f"{'Swept' if a.method == 'sweep' else 'Walk-forward tested'} “{sref.name}”",
        pct(m.get("total_return")),
        card,
        {"navigate": link},
    )


# ---------------------------------------------------------------- compare_backtests


class CompareArgs(Args):
    run_ids: list[int] | None = Field(
        None,
        description="Backtest ids to compare (2-4). Default: the latest ones in this conversation.",
    )


def compare_backtests(env: Env, a: CompareArgs) -> Result:
    ids = [int(x) for x in (a.run_ids or env.state.runs[-4:])][:4]
    if len(ids) < 2:
        with env.ctx.db.session() as s:
            ids = list(
                s.scalars(
                    select(BacktestRun.id)
                    .where(BacktestRun.parent_run_id.is_(None), BacktestRun.status == "done")
                    .order_by(BacktestRun.id.desc())
                    .limit(4)
                )
            )
    if len(ids) < 2:
        raise AgoraError(
            "NOTHING_TO_COMPARE",
            "There aren't two finished backtests to compare yet.",
            "Run another backtest first.",
        )
    lines = ["Comparison:"]
    for rid in ids:
        r = _load_run(env, rid)
        m = r["metrics"] or {}
        lines.append(
            f"- #{rid} {r['params'].get('strategy_name', '')}: return {pct(m.get('total_return'))}, "
            f"max drawdown {pct(m.get('max_drawdown'))}, Sharpe {m.get('sharpe') or 0:.2f}, {m.get('trades', 0)} "
            "trades"
        )
    link = "/compare?runs=" + ",".join(str(i) for i in ids)
    return Result(
        True,
        "\n".join(lines),
        "Compared backtests",
        f"{len(ids)} runs",
        {"type": "link", "label": "Open the comparison", "link": link},
        {"navigate": link},
    )


# ---------------------------------------------------------------- paper trading


class PaperArgs(Args):
    strategy: str | None = Field(None, description="Strategy name or id (default: the one in use).")
    symbols: list[str] | None = Field(
        None, description="Stocks to paper trade (default: the strategy's list)."
    )
    capital: float | None = Field(
        None, description="Paper money to start with (default from Settings)."
    )


def start_paper_trading(env: Env, a: PaperArgs) -> Result:
    sref = resolve.strategy(env.ctx, a.strategy, latest_id=env.state.strategy_id)
    version_id = sref.version_id
    insts = resolve.stocks(env.ctx, a.symbols, sref.market) if a.symbols else []
    symbols = [i.symbol for i in insts if i.market is sref.market and not i.is_index]
    # Other stocks don't make a new version (D-80): the session carries its own stock list.
    own = symbols if symbols and tuple(symbols) != sref.symbols else None
    sid = env.ctx.paper.start_session(
        SessionIn(
            strategy_version_id=version_id,
            account=AccountIn(
                name=f"Kairos · {sref.name}"[:80], market=sref.market, starting_capital=a.capital
            ),
            symbols=own,
        )
    )
    env.state.session_id = sid
    env.state.strategy_id = sref.strategy_id
    d = env.ctx.paper.detail(sid)
    mode = (
        "a practice replay"
        if d.get("mode") == "replay"
        else "live prices (it waits for the market to open)"
    )
    who = ", ".join(d.get("symbols") or []) or "its whole universe"
    summary = (
        f"Started paper session #{sid} for “{sref.name}” on {who} with {money(d['account']['starting_capital'], sref.market.value)} "
        f"of paper money, using {mode}. It keeps running until stopped or Agora is closed."
    )
    link = f"/paper/{sid}"
    card = {
        "type": "paper",
        "id": sid,
        "strategy": sref.name,
        "market": sref.market.value,
        "symbols": d.get("symbols") or [],
        "capital": d["account"]["starting_capital"],
        "mode": d.get("mode"),
        "link": link,
    }
    return Result(
        True,
        summary,
        f"Started paper trading “{sref.name}”",
        f"Session #{sid}",
        card,
        {"navigate": link},
    )


class StopArgs(Args):
    session: str | None = Field("all", description="A session id, a strategy name, or 'all'.")


def stop_paper_trading(env: Env, a: StopArgs) -> Result:
    sessions = [x for x in env.ctx.paper.sessions() if x["state"] != "stopped"]
    target = (a.session or "all").strip().lower()
    if target != "all":
        if target.isdigit():
            sessions = [x for x in sessions if x["id"] == int(target)]
        else:
            sessions = [x for x in sessions if target in x["name"].lower()]
    if not sessions:
        return Result(
            True,
            "No running paper sessions matched; nothing to stop.",
            "Checked paper trading",
            "Nothing running",
        )
    for x in sessions:
        env.ctx.paper.stop(x["id"])
    names = ", ".join(f"#{x['id']} {x['name']}" for x in sessions)
    return Result(
        True,
        f"Stopped {len(sessions)} paper session(s): {names}. Open positions were left as they are "
        "in the paper account's history.",
        "Stopped paper trading",
        f"{len(sessions)} stopped",
        {"type": "link", "label": "Open paper trading", "link": "/paper"},
    )


def paper_status(env: Env, _a: NoArgs) -> Result:
    sessions = env.ctx.paper.sessions()
    if not sessions:
        return Result(True, "No paper sessions yet.", "Checked paper trading", "None")
    lines = [f"{len(sessions)} paper session(s):"]
    for x in sessions[:10]:
        lines.append(
            f"- #{x['id']} {x['name']} ({x['market']}, {x['state']}): equity {money(x['equity'], x['market'])}, "
            f"return {x['total_return']:+.2f}%, today {money(x['day_pnl'], x['market'])}, {x['open_positions']} "
            f"open, {x['trades']} trades"
        )
    card = {
        "type": "list",
        "title": "Paper sessions",
        "items": [
            {
                "label": f"{x['name']} · {x['state']}",
                "sub": f"{x['total_return']:+.2f}% · {x['trades']} trades",
                "link": f"/paper/{x['id']}",
            }
            for x in sessions[:8]
        ],
    }
    return Result(
        True, "\n".join(lines), "Checked paper trading", f"{len(sessions)} sessions", card
    )


# ---------------------------------------------------------------- data & navigation


class RefreshArgs(Args):
    symbols: list[str] | None = Field(
        None, description="Stocks to download (default: the whole market)."
    )
    market: str | None = Field(None, description="IN or US.")
    timeframe: str = Field("1d", description="1d, 1h, 15m, 5m or 1m.")


def refresh_data(env: Env, a: RefreshArgs) -> Result:
    from backend.api.data import _start_refresh

    market = resolve.market_of(a.market)
    insts = (
        resolve.stocks(env.ctx, a.symbols, market)
        if a.symbols
        else [
            i for m in ([market] if market else list(Market)) for i in resolve.universe(env.ctx, m)
        ]
    )
    tf = resolve.timeframe(a.timeframe)
    job_id = _start_refresh(
        env.ctx, insts, [tf], f"Kairos: downloading {len(insts)} stocks ({tf.value})"
    )
    result = wait_job(env, job_id, "download") or {}
    failed = result.get("failed") or []
    summary = f"Downloaded {tf.value} prices for {len(insts)} stocks." + (
        f" {len(failed)} need a retry later." if failed else " All up to date."
    )
    return Result(
        True,
        summary,
        "Downloaded prices",
        f"{len(insts)} stocks",
        {"type": "link", "label": "Open the Data screen", "link": "/data"},
    )


SCREENS = {
    "home": "/",
    "strategies": "/strategies",
    "backtests": "/backtests",
    "compare": "/compare",
    "paper": "/paper",
    "charts": "/charts",
    "data": "/data",
    "settings": "/settings",
}


class OpenArgs(Args):
    screen: Literal[
        "home", "strategies", "backtests", "compare", "paper", "charts", "data", "settings"
    ] = Field(description="Which screen to open.")
    symbol: str | None = Field(None, description="For charts: the stock to show.")


def open_screen(env: Env, a: OpenArgs) -> Result:
    link = SCREENS[a.screen]
    if a.screen == "charts" and a.symbol:
        inst = resolve.stock(env.ctx, a.symbol)
        link = f"/charts?symbol={inst.symbol}&market={inst.market.value}&tf=1d"
    return Result(True, f"Opened {a.screen}.", f"Opened {a.screen}", "", None, {"navigate": link})


TOOLS = [
    Tool(
        "list_strategies",
        "The user's saved strategies with each one's latest backtest (return, win rate, trades, "
        "worst drop), best first: use it to compare strategies before running new backtests.",
        NoArgs,
        list_strategies,
        lambda a: "Listing your strategies…",
    ),
    Tool(
        "list_templates",
        "Agora's starter strategies (templates).",
        TemplatesArgs,
        list_templates,
        lambda a: "Listing starter strategies…",
        group="create",
    ),
    Tool(
        "create_strategy",
        "Create and save a strategy from a template or a plain-English idea, optionally for chosen "
        "stocks.",
        CreateArgs,
        create_strategy,
        lambda a: "Creating a strategy…",
    ),
    Tool(
        "run_backtest",
        "Backtest a saved strategy on chosen stocks and dates, wait for it, and return the results. "
        "Opens the results screen.",
        BacktestArgs,
        run_backtest,
        lambda a: "Backtesting…",
    ),
    Tool(
        "optimize_strategy",
        "Tune a strategy's settings with a parameter sweep or an honest walk-forward test.",
        OptimizeArgs,
        optimize_strategy,
        lambda a: "Optimising…",
        group="optimize",
    ),
    Tool(
        "compare_backtests",
        "Compare backtests side by side on the Compare screen.",
        CompareArgs,
        compare_backtests,
        lambda a: "Comparing backtests…",
        group="compare",
    ),
    Tool(
        "start_paper_trading",
        "Start paper trading (simulated money) a saved strategy, optionally on chosen stocks.",
        PaperArgs,
        start_paper_trading,
        lambda a: "Starting paper trading…",
    ),
    Tool(
        "stop_paper_trading",
        "Stop paper trading sessions (one, by name or id, or all).",
        StopArgs,
        stop_paper_trading,
        lambda a: "Stopping paper trading…",
        group="paper",
    ),
    Tool(
        "paper_status",
        "How the paper trading sessions are doing.",
        NoArgs,
        paper_status,
        lambda a: "Checking paper trading…",
        group="paper",
    ),
    Tool(
        "refresh_data",
        "Download missing price history for stocks.",
        RefreshArgs,
        refresh_data,
        lambda a: "Downloading prices…",
        group="data",
    ),
    Tool(
        "open_screen",
        "Move the app to a screen (home, strategies, backtests, compare, paper, charts, data, settings).",
        OpenArgs,
        open_screen,
        lambda a: f"Opening {a.screen}…",
    ),
]
