"""What Metis reads before it thinks: the brief (METIS §3, §11, §13, D-76, D-81, D-83).

For each strategy it studies, code runs the latest version over its usual stocks and period
and cuts the period in time: the first 70% are the **study years**, the last 30% the **exam
years**. The brief holds numbers from the study years only. The exam years are kept for the
test (``trial.py``), so an idea can't be shaped to fit them.

On top of the numbers, each strategy gets **a senior quant's first look** (``diagnose.py``):
findings and first experiments from the same study-year evidence, plus the stocks' character
(variance ratio, Hurst exponent), and the brief ends with the **library** sections those
findings call for. What the brief covers depends on the round's direction: strategies in use,
the other strategies, or discovering new ones.

Kairos's lessons and signal statistics are left out on purpose: they were measured on all the
years, exam years included.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import numpy as np
from sqlalchemy import select

from backend.ai.draft import indicator_list
from backend.backtest.manager import BacktestRequest, latest_run_for
from backend.backtest.run import RunOutput, RunSpec, run
from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import service as data_service
from backend.data import store
from backend.db.models import Strategy
from backend.engine.types import Trade
from backend.kairos import review as rv
from backend.kairos.coach import Coach
from backend.kairos.improve import _trades_in
from backend.logging_setup import get_logger
from backend.metis import autopsy, diagnose, library, notebook
from backend.metrics.summary import money
from backend.quant import series as qseries
from backend.quant import stats
from backend.strategy import service as strategies
from backend.strategy.definition import AnyDefinition, VisualDefinition
from backend.strategy.words import condition_text, parts

log = get_logger("metis.brief")
STUDY_SHARE = 0.7
MAX_STRATEGIES = 3
MAX_CHARACTERS = 12
MARKET_NAME = {"IN": "India (NSE)", "US": "US"}
LIBRARY_BUDGET = 1800
WEB_BUDGET = 2000  # characters of web excerpts in a brief (D-129)


@dataclass
class Baseline:
    """A strategy's current version, run once a round: the yardstick for its ideas."""

    strategy_id: int
    name: str
    kind: str
    version_id: int
    version: int
    definition: AnyDefinition
    spec: RunSpec
    split_ms: int
    out: RunOutput
    study: dict[str, Any]
    exam: dict[str, Any]
    template_key: str | None = None

    @property
    def market(self) -> Market:
        return Market(self.definition.market)

    def daily(self, *, study: bool = True) -> np.ndarray:
        """Daily returns of the study years (or the exam years)."""
        tz = MARKET_TZ[self.market]
        if study:
            return stats.daily_returns(self.out.equity, tz, lo=self.spec.start_ms, hi=self.split_ms)
        return stats.daily_returns(self.out.equity, tz, lo=self.split_ms)


@dataclass
class Brief:
    text: str
    baselines: dict[int, Baseline] = field(default_factory=dict)
    markets: list[str] = field(default_factory=list)
    direction: str = "improve"
    findings: dict[int, list[diagnose.Finding]] = field(default_factory=dict)
    seeds: list[dict[str, Any]] = field(default_factory=list)  # the playbook's first experiments
    library: list[str] = field(default_factory=list)  # titles of the sections it read
    web: list[str] = field(default_factory=list)  # pages it read on the web (D-129)
    trimmed: list[str] = field(default_factory=list)  # what was left out to fit (D-141)


# ---------------------------------------------------------------- numbers for a part


def part(trades: Sequence[Trade], lo: int, hi: int) -> dict[str, Any]:
    """Closed trades that *entered* in [lo, hi): count, wins, money after costs, exits."""
    rows = [t for t in trades if t.closed and lo <= t.entry_ts < hi]
    n = len(rows)
    wins = [t for t in rows if t.net_pnl > 0]
    losses = [t for t in rows if t.net_pnl <= 0]
    won = sum(t.net_pnl for t in wins)
    lost = -sum(t.net_pnl for t in losses)
    return {
        "trades": n,
        "wins": len(wins),
        "win_rate": round(len(wins) / n, 3) if n else None,
        "net": round(sum(t.net_pnl for t in rows), 2),
        "gross": round(sum(t.gross_pnl for t in rows), 2),
        "charges": round(sum(t.charges for t in rows), 2),
        "avg_win": round(won / len(wins), 2) if wins else None,
        "avg_loss": round(lost / len(losses), 2) if losses else None,
        "profit_factor": round(won / lost, 3) if lost > 0 else (None if not wins else 99.0),
        "exits": dict(Counter(str(t.exit_reason) for t in rows).most_common(5)),
    }


def part_line(p: dict[str, Any], market: Market) -> str:
    if not p["trades"]:
        return "no closed trades"
    wr = f"{p['win_rate'] * 100:.0f}%"
    bits = [
        f"{p['trades']} trades, won {wr}, made {money(p['net'], market)} after "
        f"{money(p['charges'], market)} of costs"
    ]
    if p["avg_win"] is not None and p["avg_loss"] is not None:
        win, loss = money(p["avg_win"], market), money(p["avg_loss"], market)
        bits.append(f"average win {win}, average loss {loss}")
    if p["exits"]:
        bits.append("exits: " + ", ".join(f"{k} {v}" for k, v in p["exits"].items()))
    return "; ".join(bits)


# ---------------------------------------------------------------- rules in words


def _numbered(rule: Any) -> str:
    items = parts(rule)
    if len(items) <= 1:
        return condition_text(rule)
    return " AND ".join(f"({k}) {x}" for k, x in enumerate(items, start=1))


def rules_text(d: AnyDefinition) -> list[str]:
    if not isinstance(d, VisualDefinition):
        return [f"A {d.kind} strategy (its code isn't shown; only its settings can change)."]
    data = json.loads(d.model_dump_json())
    out = [f"Buy when: {_numbered(data['entry'].get('long'))}."]
    if data["entry"].get("short"):
        out.append(f"Short when: {_numbered(data['entry']['short'])}.")
    ex = data["exit"]
    if ex.get("long"):
        out.append(f"Sell when: {condition_text(ex['long'])}.")
    if ex.get("short"):
        out.append(f"Cover shorts when: {condition_text(ex['short'])}.")
    for key, label in (
        ("stop_loss", "Stop loss"),
        ("take_profit", "Take profit"),
        ("trailing_stop", "Trailing stop"),
    ):
        if ex.get(key):
            unit = "%" if ex[key]["kind"] == "percent" else "× ATR"
            out.append(f"{label}: {ex[key]['value']}{unit}.")
    if ex.get("max_bars"):
        out.append(f"Time limit: {ex['max_bars']} candles.")
    return out


def short_rules(d: AnyDefinition) -> str:
    """One line for the list of strategies the user already has."""
    if not isinstance(d, VisualDefinition):
        return f"a {d.kind} strategy"
    data = json.loads(d.model_dump_json())
    return f"buys when {condition_text(data['entry'].get('long'))}"[:220]


# ---------------------------------------------------------------- baselines


def pick(
    ctx: Any, focus: str, *, only: Sequence[int] | None = None, skip: Sequence[int] = ()
) -> list[int]:
    """Up to three strategies: those the focus names first, then the most recently tested.
    ``only`` limits the choice (strategies in use); ``skip`` leaves some out."""
    low = focus.lower()
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy).where(
                Strategy.archived_at.is_(None), Strategy.kind.in_(("visual", "code"))
            )
        ).all()
        scored = []
        for r in rows:
            if (only is not None and r.id not in only) or r.id in skip:
                continue
            named = bool(low) and (r.name.lower() in low or f"#{r.id}" in low)
            last = latest_run_for(s, r.id)
            scored.append(
                (not named, last is None, -(last.created_at if last else r.updated_at), r.id)
            )
    return [sid for *_, sid in sorted(scored)[:MAX_STRATEGIES]]


def baseline(ctx: Any, strategy_id: int) -> Baseline | None:
    """Run the strategy's latest version over its latest backtest's stocks and period
    (or Agora's defaults), without saving anything."""
    with ctx.db.session() as s:
        strat = s.get(Strategy, strategy_id)
        version = strategies.latest_version(s, strategy_id)
        if strat is None or version is None:
            return None
        last = latest_run_for(s, strategy_id)
        params = json.loads(last.params) if last is not None else {}
        name, kind, template = strat.name, strat.kind, strat.template_key
    req = BacktestRequest(
        strategy_version_id=version.id,
        symbols=params.get("symbols") or None,
        timeframe=params.get("timeframe"),
        start=params.get("start"),
        end=params.get("end"),
        capital=params.get("capital"),
    )
    spec, _extra = ctx.backtests.spec_for(version.definition, req)
    ctx.backtests.ensure_data_for(spec)
    out = run(ctx.cache, spec)
    split = spec.start_ms + int((spec.end_ms - spec.start_ms) * STUDY_SHARE)
    return Baseline(
        strategy_id=strategy_id,
        name=name,
        kind=kind,
        version_id=version.id,
        version=version.version,
        definition=version.definition,
        spec=spec,
        split_ms=split,
        out=out,
        study=part(out.trades, spec.start_ms, split),
        exam=part(out.trades, split, spec.end_ms + 1),
        template_key=template,
    )


def _day(ms: int) -> str:
    return ms_to_dt(ms, UTC).strftime("%Y-%m-%d")


MIN_FOR_CASEBOOK = 3  # study trades before the losers are explained one by one (D-128)


def study_review(ctx: Any, b: Baseline) -> dict[str, Any] | None:
    """Kairos's review of the study-year trades only: where the losers clustered and, trade by
    trade, why each loser lost (the casebook works from three trades; the statistics need a
    dozen and stay quiet below that)."""
    trades = [t for t in _trades_in(b.out) if t.entry_ts < b.split_ms and t.exit_ts < b.split_ms]
    if len(trades) < MIN_FOR_CASEBOOK:
        return None
    coach = Coach(ctx)
    series = coach._series(
        {i.symbol: i for i in b.spec.instruments}, b.spec.timeframe, b.spec.start_ms, b.split_ms
    )
    m = Market(b.definition.market)
    with ctx.db.session() as s:
        bench = store.find_instrument(s, m, data_service.BENCHMARK[m])
    index = None
    if bench is not None:
        got = coach._series({bench.symbol: bench}, b.spec.timeframe, b.spec.start_ms, b.split_ms)
        index = got.get(bench.symbol)
    return rv.review(trades, series, b.market, market_series=index)


def casebook_lines(review: dict[str, Any] | None, market: Market, limit: int = 5) -> list[str]:
    """The worst losing trades one by one, for the brief (D-128)."""
    losers = (review or {}).get("losers") or []
    if not losers:
        return []
    out = ["Losing trades one by one (study years, worst first):"]
    for x in losers[:limit]:
        day = ms_to_dt(int(x["entry_ts"])).strftime("%Y-%m-%d")
        out.append(
            f"- {x['symbol']} {x['side']} {day}: {money(float(x['net']), market)} "
            f"({x['exit_reason']}); " + "; ".join(x["why"]) + "."
        )
    return out


def characters(
    ctx: Any, insts: dict[str, Any], tf: Any, lo: int, split: int
) -> dict[str, dict[str, Any]]:
    """Each stock's character in the study years (nothing from the exam years)."""
    series = Coach(ctx)._series(dict(list(insts.items())[:MAX_CHARACTERS]), tf, lo, split)
    out = {}
    for sym, ser in series.items():
        cut = ser.upto(int((ser.ts < split).sum()))
        if len(cut) > 60:
            out[sym] = qseries.character(cut.close)
    return out


def character_line(chars: dict[str, dict[str, Any]]) -> str:
    groups: dict[str, list[str]] = {}
    for sym, c in chars.items():
        groups.setdefault(str(c["label"]), []).append(
            f"{sym} (VR {c['variance_ratio']:.2f}, H {c['hurst']:.2f})"
        )
    return "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(groups.items()))


def strategy_block(ctx: Any, b: Baseline, brief: Brief | None = None) -> str:
    d = b.definition
    syms = [i.symbol for i in b.spec.instruments]
    head = (
        f"STRATEGY #{b.strategy_id} “{b.name}” ({b.kind}, {MARKET_NAME[d.market]}, "
        f"{d.timeframe} candles, product {d.product}; stocks: {', '.join(syms[:12])}"
        f"{' …' if len(syms) > 12 else ''})"
    )
    lines = [head, *rules_text(d)]
    if d.parameters:
        lines.append(
            "Settings you may change: "
            + "; ".join(
                f"{p.name} = {p.default:g} (allowed {p.min:g} to {p.max:g})" for p in d.parameters
            )
            + "."
        )
    lines.append(
        f"Study years {_day(b.spec.start_ms)} to {_day(b.split_ms)}: "
        f"{part_line(b.study, b.market)}."
    )
    try:
        review = study_review(ctx, b)
    except Exception:
        log.exception("Metis couldn't review strategy %s", b.strategy_id)
        review = None
    reasons = [str(r["text"]) for r in (review or {}).get("failure_reasons", [])[:3]]
    if reasons:
        lines.append("Where its losing trades clustered (study years): " + " ".join(reasons))
    lines += casebook_lines(review, Market(b.definition.market))
    shared = [str(p["text"]) for p in ((review or {}).get("casebook") or {}).get("patterns", [])]
    if shared:
        lines.append("What the losers had in common: " + " ".join(shared[:3]))
    try:
        chars = characters(
            ctx,
            {i.symbol: i for i in b.spec.instruments},
            b.spec.timeframe,
            b.spec.start_ms,
            b.split_ms,
        )
    except Exception:
        log.exception("Metis couldn't read the stocks of strategy %s", b.strategy_id)
        chars = {}
    if chars:
        lines.append(f"How its stocks behaved (study years): {character_line(chars)}.")
    findings = diagnose.first_look(b, review=review, characters=chars, daily=b.daily())
    try:
        found = autopsy.run_autopsy(ctx, b)
    except Exception:
        log.exception("Metis couldn't run the trade autopsy of strategy %s", b.strategy_id)
        found = None
    if found is not None:
        lines += found.lines
        # the autopsy's filters first: they come from this strategy's own bad trades (D-109)
        findings.insert(
            0,
            diagnose.Finding(
                "autopsy",
                "Trade autopsy: " + (found.lines[-1] if found.lines else ""),
                "false signals filter volume bigger chart losers cluster regime",
                found.seeds,
            ),
        )
    findings, tried = _untried(ctx, b, findings)
    if findings:
        lines.append("A senior quant's first look:")
        lines += diagnose.lines(findings)
    if tried:
        # every idea these findings suggest was already tested: say so in a line, or the
        # model proposes the same ideas again and the round ends with only repeats (D-156)
        lines.append(
            "Already tested on this strategy (look for a different cause): "
            + "; ".join(tried)
            + "."
        )
    if brief is not None:
        brief.findings[b.strategy_id] = findings
        brief.seeds += [s for f in findings for s in f.seeds]
    return "\n".join(lines)


def _untried(
    ctx: Any, b: Baseline, findings: list[diagnose.Finding]
) -> tuple[list[diagnose.Finding], list[str]]:
    """(findings with an idea not yet tested, what was already tested). A finding whose every
    suggested idea is in the notebook only gets a one-line mention."""
    from backend.metis import trial

    keep: list[diagnose.Finding] = []
    tried: list[str] = []
    for f in findings:
        seeds = [s for s in f.seeds if s.get("kind")]
        try:
            done = bool(seeds) and all(
                notebook.seen(ctx, trial.fingerprint_of(s, {b.strategy_id: b})) for s in seeds
            )
        except Exception:  # never lose a finding to the check
            log.debug("Couldn't check finding %s against the notebook", f.key, exc_info=True)
            done = False
        if done:
            tried.append(", ".join(dict.fromkeys(str(s.get("title") or f.key) for s in seeds)))
        else:
            keep.append(f)
    return keep, tried


# ---------------------------------------------------------------- discovering


def families_text(ctx: Any, markets: Sequence[str]) -> list[str]:
    """The strategies the user already has, so new ideas can be different."""
    out = []
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy)
            .where(Strategy.archived_at.is_(None), Strategy.market_code.in_(list(markets)))
            .order_by(Strategy.updated_at.desc())
            .limit(20)
        ).all()
        for r in rows:
            v = strategies.latest_version(s, r.id)
            if v is not None:
                tf = v.definition.timeframe
                rules = short_rules(v.definition)
                out.append(f"- #{r.id} “{r.name}” ({r.market_code}, {tf}): {rules}")
    return out


def market_characters(ctx: Any, market: str) -> str:
    """The character of the market's stocks over Agora's default daily period (study part)."""
    with ctx.db.session() as s:
        insts = [i for i in data_service.default_symbols(s, Market(market)) if not i.is_index]
    now = ctx.clock.now_ms()
    start = data_service.default_start_ms(Timeframe.D1, now) + 365 * 86_400_000
    split = start + int((now - start) * STUDY_SHARE)
    chars = characters(ctx, {i.symbol: i for i in insts}, Timeframe.D1, start, split)
    return character_line(chars)


# ---------------------------------------------------------------- the brief


def build(
    ctx: Any,
    focus: str,
    markets: Sequence[str],
    *,
    direction: str = "improve",
    in_use: Sequence[int] = (),
    discover_seeds: Sequence[dict[str, Any]] = (),
    budget: int | None = None,
) -> Brief:
    brief = Brief(text="", markets=list(markets), direction=direction)
    blocks: list[tuple[int, str]] = []
    if direction in ("improve_live", "improve"):
        ids = (
            pick(ctx, focus, only=list(in_use))
            if direction == "improve_live"
            else pick(ctx, focus, skip=list(in_use) if not focus.strip() else ())
        )
        for sid in ids:
            try:
                b = baseline(ctx, sid)
            except Exception:
                log.exception("Metis couldn't run strategy %s", sid)
                continue
            if b is None:
                continue
            brief.baselines[sid] = b
            blocks.append((sid, strategy_block(ctx, b, brief)))
    parts_out = []
    if focus.strip():
        parts_out.append(f"The user asked you to look into: {focus.strip()}")
    parts_out.append(
        "The user's markets: "
        + ", ".join(MARKET_NAME.get(m, m) for m in markets)
        + ". India allows short selling only intraday; daily strategies there buy only."
    )
    backdrop = market_backdrop(ctx, markets)
    if backdrop:
        parts_out.append(backdrop)
    topics: list[str] = []
    if direction == "improve_live":
        parts_out.append("This round: improve the strategies the user is paper trading now.")
    elif direction == "improve":
        parts_out.append("This round: improve the user's other strategies.")
    if blocks:
        parts_out.append(STRATEGIES_MARK)
        topics = [f.topics for fs in brief.findings.values() for f in fs]
    else:
        parts_out.append(
            "This round: discover NEW strategies, different from the ones the user has. "
            "Propose new strategies (kind new_strategy)."
        )
        from backend.metis import timeframes

        tfs = timeframes.summary(ctx, list(markets))
        if tfs:
            parts_out.append(
                "Timeframes you can research (strategies the user has, stocks with saved history; "
                "new strategies may use any of them, the ones with few strategies first):\n"
                + "\n".join(tfs)
            )
        fams = families_text(ctx, markets)
        if fams:
            parts_out.append(
                "Strategies the user already has (don't propose these again):\n" + "\n".join(fams)
            )
        for m in markets:
            try:
                line = market_characters(ctx, m)
            except Exception:
                log.exception("Metis couldn't read %s's stocks", m)
                line = ""
            if line:
                parts_out.append(
                    f"How {MARKET_NAME.get(m, m)} stocks behaved (study years): {line}."
                )
        if discover_seeds:
            parts_out.append(
                "Textbook strategies the user doesn't have yet (being tested from the playbook): "
                + ", ".join(str(s["title"]) for s in discover_seeds)
                + "."
            )
        brief.seeds += list(discover_seeds)
        topics = ["discover new strategy documented anomaly", "trend following momentum reversal"]
    memory = notebook.memory_lines(ctx)
    query = " ".join(topics[:4]) or "research method simple rules"
    sections = library.search(query, k=3)
    lib = library.for_prompt(query, LIBRARY_BUDGET, k=3) if sections else ""
    if sections:
        brief.library = [s.title for s in sections]
    web = web_text(ctx, brief, markets)
    fit(brief, parts_out, blocks, memory, lib, web, budget)
    return brief


def market_backdrop(ctx: Any, markets: Sequence[str]) -> str:
    """Today's market, in a few lines (D-159): each market's regime, the news risk gauge, the
    world events moving it and the sectors they help or hurt. Metis researched without any of
    this, though the user asked (2026-10-23) for Kairos and Metis to weigh geopolitics, news
    and sectors; Kairos's desks already read the news (D-69). Each part is optional."""
    from backend.analysis.regime_map import WORDS
    from backend.core.types import Market
    from backend.metis import agenda

    out: list[str] = []
    for m in markets:
        name = MARKET_NAME.get(m, m)
        bits: list[str] = []
        try:
            regime = agenda.market_regime(ctx, m)
            if regime and regime in WORDS:
                bits.append(f"its index is {WORDS[regime]}")
        except Exception:
            log.debug("No regime for %s", m, exc_info=True)
        news = ctx.services.get("news") or getattr(ctx, "news", None)
        try:
            if news is not None:
                risk = news.risk(Market(m))
                if risk.get("text"):
                    bits.append(f"news risk {risk.get('level', 0):.0f}/100 ({risk['text']})")
        except Exception:
            log.debug("No news risk for %s", m, exc_info=True)
        world = ctx.services.get("world")
        try:
            if world is not None:
                v = world.view(m)
                drivers = [str(d["title"]) for d in (v.get("drivers") or [])[:3]]
                if drivers:
                    bits.append("world events in play: " + "; ".join(drivers))
                tags = v.get("tags") or {}
                up = [k for k, x in sorted(tags.items(), key=lambda kv: -kv[1]) if x >= 0.5][:3]
                down = [k for k, x in sorted(tags.items(), key=lambda kv: kv[1]) if x <= -0.5][:3]
                if up or down:
                    bits.append(
                        "they help "
                        + (", ".join(up).replace("_", " ") or "no group")
                        + " and hurt "
                        + (", ".join(down).replace("_", " ") or "no group")
                    )
        except Exception:
            log.debug("No world view for %s", m, exc_info=True)
        if bits:
            out.append(f"- {name}: " + "; ".join(bits) + ".")
    if not out:
        return ""
    return (
        "Today's market (weigh it: a trend filter or a sector or regime condition can keep a "
        "strategy out when the backdrop is against it):\n" + "\n".join(out)
    )


STRATEGIES_MARK = "\x00strategies\x00"
MEMORY_HEAD = (
    "Your notebook (your latest ideas and how they did; don't repeat what failed, "
    "build on what held up):\n"
)


def _text(
    head: Sequence[str],
    blocks: Sequence[tuple[int, str]],
    memory: Sequence[str],
    lib: str,
    web: str,
) -> str:
    out: list[str] = []
    for part_text in head:
        if part_text == STRATEGIES_MARK:
            if blocks:
                out.append("The user's strategies:\n\n" + "\n\n".join(b for _, b in blocks))
        else:
            out.append(part_text)
    if memory:
        out.append(MEMORY_HEAD + "\n".join(memory))
    if lib:
        out.append("From your library:\n" + lib)
    if web:
        out.append(web)
    out.append("Indicators you may use (key: settings):\n" + indicator_list())
    return "\n\n".join(out)


def fit(
    brief: Brief,
    head: Sequence[str],
    blocks: list[tuple[int, str]],
    memory: list[str],
    lib: str,
    web: str,
    budget: int | None,
) -> None:
    """Set ``brief.text``, leaving out the least needed parts until it fits ``budget`` tokens
    (D-141). Before this, a brief bigger than the model's reading size lost its *start*
    (Ollama drops the oldest text), so Metis read the indicator list but not its strategies.

    Order of leaving out: the web excerpts, the library, older notebook lines (down to 5),
    strategies after the first (the one named in the focus comes first), then the notebook.
    A strategy left out is also removed from ``brief.baselines``, so an idea about it is
    "not shown" rather than tested blind."""
    from backend.ai.reading import tokens

    def size() -> int:
        return tokens(_text(head, blocks, memory, lib, web))

    if budget is not None:
        if size() > budget and web:
            web = ""
            brief.trimmed.append("the web excerpts")
            brief.web = []
        if size() > budget and lib:
            lib = ""
            brief.trimmed.append("the library")
            brief.library = []
        if size() > budget and len(memory) > 5:
            memory = memory[:5]  # the newest come first
            brief.trimmed.append("older notebook lines")
        while size() > budget and len(blocks) > 1:
            sid, _ = blocks.pop()
            brief.baselines.pop(sid, None)
            brief.findings.pop(sid, None)
            brief.trimmed.append(f"strategy #{sid}")
        if size() > budget and memory:
            memory = []
            brief.trimmed.append("the notebook")
    brief.text = _text(head, blocks, memory, lib, web)
    if brief.trimmed:
        log.info("Metis's brief left out %s to fit the reading size", ", ".join(brief.trimmed))


# Questions for discovery rounds, one an hour in turn: what traders and researchers report
DISCOVER_QUESTIONS = (
    "high win rate swing trading strategy backtest results {market}",
    "intraday trading strategy backtest {market} stocks 15 minute",
    "institutional buying signals delivery volume strategy {market}",
    "mean reversion strategy stocks backtest after costs {market}",
    "momentum breakout strategy partial profit booking backtest",
    "trend following strategy stocks drawdown win rate {market}",
)
MARKET_WORD = {"IN": "India NSE", "US": "US stocks"}


def web_question(ctx: Any, brief: Brief, markets: Sequence[str]) -> str:
    """One web question for this round: about the first strategy studied (why its kind loses
    and how traders improve it), or, when discovering, a strategy family in turn."""
    for sid, b in brief.baselines.items():
        name = b.name.split("·")[0].replace("Metis", "").strip(" ·")
        weak = any(
            f.key in ("casebook", "below_break_even", "losses_run", "costs", "autopsy")
            for f in brief.findings.get(sid, [])
        )
        extra = "why it loses how to improve" if weak else "how to improve results"
        return f"{name} trading strategy {extra} {MARKET_WORD.get(b.market.value, '')}".strip()
    hour = int(ctx.clock.now_ms() // 3_600_000)
    market = markets[hour % len(markets)] if markets else "IN"
    q = DISCOVER_QUESTIONS[hour % len(DISCOVER_QUESTIONS)]
    return q.format(market=MARKET_WORD.get(market, market))


def web_text(ctx: Any, brief: Brief, markets: Sequence[str]) -> str:
    """What the web says about this round's question (D-129); empty when switched off,
    offline, or nothing useful was found."""
    research = ctx.services.get("research")
    if research is None:
        return ""
    found = research.research(web_question(ctx, brief, markets))
    brief.web = [s.url for s in found.sources]
    return str(found.as_text(WEB_BUDGET))
