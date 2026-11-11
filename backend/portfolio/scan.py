"""The opportunity scanner: your strategies on new stocks (PORTFOLIO §3, D-80, D-83).

For each strategy (up to 12 per market, the most recently changed first), one pass over the
market's whole universe with **independent positions**: every stock may hold a trade at the
same time and each trade has the same fixed size, so each stock's trades are what it would have
done alone (vectorbt's trick of testing many at once). The period is Agora's default, split in
time into study years (first 70%) and exam years (last 30%).

- Stocks are chosen on the **study years only**: at least 4 trades, made money after costs,
  won at least 1.2× what they lost; the best five by average profit per trade × √trades.
- The group is judged on the **exam years**, which played no part in choosing it: at least 8
  trades, made money after costs, won at least 1.1× what it lost.
- The strategy's own stocks are judged the same way (the strategy as it is).
- A group that passes is run once as a real sleeve for its daily returns and the luck check
  (deflated Sharpe over the number of strategies scanned) and becomes an opportunity.

Nothing here saves a strategy: an opportunity is a revision plus stocks (D-80).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from backend.backtest.manager import BacktestRequest, latest_run_for
from backend.backtest.run import run
from backend.core.types import Market
from backend.data import service as data_service
from backend.db.models import Opportunity, Strategy
from backend.logging_setup import get_logger
from backend.metis.brief import STUDY_SHARE
from backend.metrics.summary import money
from backend.portfolio import sleeves
from backend.strategy import service as strategies
from backend.strategy.definition import Limits, Sizing

log = get_logger("portfolio.scan")
MAX_STRATEGIES = 12
GROUP = 5
STUDY_MIN_TRADES = 4
STUDY_MIN_PF = 1.2
EXAM_MIN_TRADES = 8
EXAM_MIN_PF = 1.1
REFERENCE_CAPITAL = {"IN": 1_000_000.0, "US": 100_000.0}
Progress = Callable[[float, str], None]


def fingerprint(version_id: int, symbols: list[str], overrides: dict[str, float]) -> str:
    key = json.dumps([version_id, sorted(symbols), sorted(overrides.items())])
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _stats(rows: list[Any]) -> dict[str, Any]:
    n = len(rows)
    won = sum(t.net_pnl for t in rows if t.net_pnl > 0)
    lost = -sum(t.net_pnl for t in rows if t.net_pnl <= 0)
    return {
        "trades": n,
        "wins": sum(1 for t in rows if t.net_pnl > 0),
        "net": round(sum(t.net_pnl for t in rows), 2),
        "profit_factor": round(won / lost, 3) if lost > 0 else (99.0 if won > 0 else None),
        "avg_return_pct": round(sum(t.return_pct for t in rows) / n, 4) if n else 0.0,
    }


def per_stock(trades: list[Any], lo: int, hi: int) -> dict[str, dict[str, Any]]:
    by: dict[str, list[Any]] = {}
    for t in trades:
        if t.closed and lo <= t.entry_ts < hi:
            by.setdefault(t.symbol, []).append(t)
    return {sym: _stats(rows) for sym, rows in by.items()}


def choose(study: dict[str, dict[str, Any]], k: int = GROUP) -> list[str]:
    """The best ``k`` stocks on the study years (the exam years play no part)."""
    ok = [
        (s["avg_return_pct"] * math.sqrt(s["trades"]), sym)
        for sym, s in study.items()
        if s["trades"] >= STUDY_MIN_TRADES
        and s["net"] > 0
        and (s["profit_factor"] or 0) >= STUDY_MIN_PF
    ]
    return [sym for _score, sym in sorted(ok, reverse=True)[:k]]


def exam_ok(rows: list[Any]) -> tuple[bool, dict[str, Any]]:
    st = _stats(rows)
    ok = (
        st["trades"] >= EXAM_MIN_TRADES
        and st["net"] > 0
        and (st["profit_factor"] or 0) >= EXAM_MIN_PF
    )
    return ok, st


def _own_symbols(ctx: Any, strategy_id: int, d: Any, universe: list[str]) -> list[str]:
    with ctx.db.session() as s:
        last = latest_run_for(s, strategy_id)
        if last is not None:
            syms = json.loads(last.params).get("symbols") or []
            if syms:
                return [x for x in syms if x in universe] or list(syms)
    if d.universe.kind == "symbols" and d.universe.symbols:
        return list(d.universe.symbols)
    return universe[:GROUP]


def evidence_text(ev: dict[str, Any], market: Market) -> str:
    ex, luck = ev["exam"], ev["luck"]
    wr = (ex["wins"] / ex["trades"] * 100) if ex.get("trades") else 0
    pf = ex.get("profit_factor")
    return (
        f"On unseen years: {ex['trades']} trades, won {wr:.0f}%, made "
        f"{money(ex['net'], market)} after costs"
        + (f" ({pf:.1f}× won to lost)" if pf else "")
        + f"; {luck['dsr'] * 100:.0f}% chance it isn't luck."
    )


def record(
    ctx: Any,
    spec: sleeves.SleeveSpec,
    ev: dict[str, Any],
    source: str,
) -> int:
    """Save (or refresh) an opportunity. A dismissed or in-portfolio one keeps its status."""
    market = Market(spec.market)
    fp = fingerprint(spec.version_id, spec.symbols, spec.overrides)
    now = ctx.clock.now_ms()
    score = round(max(ev["sharpe"], 0.0) * ev["luck"]["dsr"], 4)
    text = evidence_text(ev, market)
    with ctx.db.session() as s:
        row = s.scalars(select(Opportunity).where(Opportunity.fingerprint == fp)).first()
        if row is None:
            row = Opportunity(
                found_at=now,
                market_code=spec.market,
                strategy_id=spec.strategy_id,
                version_id=spec.version_id,
                symbols=json.dumps(spec.symbols),
                overrides=json.dumps(spec.overrides),
                source=source,
                status="open",
                fingerprint=fp,
            )
            s.add(row)
        elif row.status == "stale":
            row.status = "open"
        row.checked_at = now
        row.score = score
        row.study = json.dumps(ev["study"])
        row.exam = json.dumps(ev["exam"])
        row.luck = json.dumps(ev["luck"])
        row.evidence = text
        s.flush()
        return int(row.id)


def _rankings(
    ctx: Any,
    market: str,
    tries: int,
    kept_fps: dict[int, set[str]],
    say: Progress,
) -> list[dict[str, Any]]:
    """Ranking strategies (D-91) pick their own stocks each month, so each is judged as a whole
    on the index (``symbols`` empty: the strategy's own universe), on the same exam rules."""
    m = Market(market)
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy).where(
                Strategy.archived_at.is_(None),
                Strategy.kind == "ranking",
                Strategy.market_code == market,
            )
        ).all()
        picked = [(r.id, r.name) for r in rows][:MAX_STRATEGIES]
    found: list[dict[str, Any]] = []
    for sid, name in picked:
        say(95, f"Judging the ranking {name}…")
        with ctx.db.session() as s:
            v = strategies.latest_version(s, sid)
        sl = sleeves.spec_of(ctx, v.id, []) if v is not None else None
        if sl is None:
            continue
        kept_fps.setdefault(sl.version_id, set())
        try:
            r = sleeves.run_sleeve(ctx, sl, REFERENCE_CAPITAL[market])
        except Exception:
            log.exception("The scanner couldn't run the ranking %s", name)
            continue
        ev = sleeves.evidence(r, tries)
        ex = ev["exam"]
        if (
            ex["trades"] < EXAM_MIN_TRADES
            or ex["net"] <= 0
            or (ex.get("profit_factor") or 0) < EXAM_MIN_PF
        ):
            continue
        oid = record(ctx, sl, ev, "scanner")
        kept_fps[sl.version_id].add(fingerprint(sl.version_id, [], {}))
        found.append(
            {
                "opportunity_id": oid,
                "strategy_id": sid,
                "name": name,
                "symbols": [],
                "which": "the whole index (it ranks them monthly)",
                "evidence": evidence_text(ev, m),
            }
        )
    return found


def scan(ctx: Any, market: str, *, progress: Progress | None = None) -> dict[str, Any]:
    """Scan one market; returns what was found, in plain words and numbers."""
    say = progress or (lambda _p, _m: None)
    m = Market(market)
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy)
            .where(
                Strategy.archived_at.is_(None),
                Strategy.kind.in_(("visual", "code")),
                Strategy.market_code == market,
            )
            .order_by(Strategy.updated_at.desc())
            .limit(MAX_STRATEGIES)
        ).all()
        picked = [(r.id, r.name) for r in rows]
        universe = [i.symbol for i in data_service.default_symbols(s, m) if not i.is_index]
    lists = ctx.services.get("watchlists")
    if lists is not None:  # plus the stocks Kairos's and Metis's lists brought in (D-94)
        universe = [i.symbol for i in lists.discovery(market)]
    capital = REFERENCE_CAPITAL[market]
    tries = max(1, len(picked))
    found: list[dict[str, Any]] = []
    kept_fps: dict[int, set[str]] = {}
    for n, (sid, name) in enumerate(picked):
        say(5 + 90 * n / max(len(picked), 1), f"Trying {name} on every stock…")
        with ctx.db.session() as s:
            v = strategies.latest_version(s, sid)
        if v is None or not universe:
            continue
        d = v.definition
        kept_fps[v.id] = set()
        independent = d.model_copy(
            update={
                "limits": Limits(
                    max_open_positions=min(100, len(universe)),
                    max_daily_loss_pct=None,
                ),
                "sizing": Sizing(kind="fixed_amount", value=round(capital / len(universe), 2)),
            }
        )
        try:
            spec, _x = ctx.backtests.spec_for(
                independent,
                BacktestRequest(strategy_version_id=0, symbols=universe, capital=capital * 2),
            )
            ctx.backtests.ensure_data_for(spec)
            out = run(ctx.cache, spec)
        except Exception:
            log.exception("The scanner couldn't run %s", name)
            continue
        split = spec.start_ms + int((spec.end_ms - spec.start_ms) * STUDY_SHARE)
        study = per_stock(out.trades, spec.start_ms, split)
        groups = []
        chosen = choose(study)
        if chosen:
            groups.append(("new stocks", chosen))
        own = _own_symbols(ctx, sid, d, universe)
        if own and sorted(own) != sorted(chosen):
            groups.append(("its own stocks", own))
        for label, syms in groups:
            rows_exam = [
                t for t in out.trades if t.closed and t.symbol in syms and t.entry_ts >= split
            ]
            ok, _st = exam_ok(rows_exam)
            if not ok:
                continue
            sl = sleeves.spec_of(ctx, v.id, syms)
            if sl is None:
                continue
            try:
                r = sleeves.run_sleeve(ctx, sl, capital)
            except Exception:
                log.exception("The scanner couldn't run %s as a sleeve", name)
                continue
            ev = sleeves.evidence(r, tries)
            if ev["exam"]["trades"] < EXAM_MIN_TRADES or ev["exam"]["net"] <= 0:
                continue
            oid = record(ctx, sl, ev, "scanner")
            kept_fps[v.id].add(fingerprint(v.id, syms, {}))
            found.append(
                {
                    "opportunity_id": oid,
                    "strategy_id": sid,
                    "name": name,
                    "symbols": syms,
                    "which": label,
                    "evidence": evidence_text(ev, m),
                }
            )
    found += _rankings(ctx, market, tries, kept_fps, say)
    # what didn't pass again goes stale (the scanner only re-checks versions it scanned)
    with ctx.db.session() as s:
        for row in s.scalars(
            select(Opportunity).where(
                Opportunity.market_code == market,
                Opportunity.source == "scanner",
                Opportunity.status == "open",
                Opportunity.version_id.in_(list(kept_fps)),
            )
        ):
            if row.fingerprint not in kept_fps.get(row.version_id, set()):
                row.status = "stale"
        # an archived strategy is never scanned again, so its offers would stay open for ever
        # (two for the retired "%B at least %B" strategy, 2026-11-05)
        archived = select(Strategy.id).where(Strategy.archived_at.is_not(None))
        for row in s.scalars(
            select(Opportunity).where(
                Opportunity.market_code == market,
                Opportunity.status == "open",
                Opportunity.strategy_id.in_(archived),
            )
        ):
            row.status = "stale"
    say(100, "Done.")
    return {
        "market": market,
        "strategies": len(picked),
        "found": found,
        "note": (
            f"Tried {len(picked)} strateg{'y' if len(picked) == 1 else 'ies'} on "
            f"{len(universe)} stocks; {len(found)} opportunit"
            f"{'y' if len(found) == 1 else 'ies'} held up on unseen years."
        ),
    }
