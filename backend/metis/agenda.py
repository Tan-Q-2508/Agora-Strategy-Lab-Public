"""Metis's research agenda: which direction each round takes (METIS §13, D-83).

Four directions:

- ``improve_live``: the strategies in use (running paper sessions, portfolio sleeves);
- ``improve``: the user's other strategies and Kairos's;
- ``discover``: new strategies, starting from the textbook ones the user doesn't have;
- ``opportunities``: the scanner tries working strategies on new stocks (code only).

The choice works like RD-Agent(Q)'s scheduler: **Thompson sampling** on each direction's record
(a draw from Beta(1 + kept, 1 + failed)), seeded by the round number so a round can be
replayed. Fixed rules come first: a focus naming a strategy means improving it; strategies in
use get a round at least every third round; the scanner runs at least every fourth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any

import numpy as np
from sqlalchemy import func, select

from backend.db.models import (
    MetisRound,
    PaperSession,
    Strategy,
    StrategyVersion,
)
from backend.metis import notebook
from backend.strategy import revisions, templates

DIRECTIONS = ("improve_live", "improve", "discover", "opportunities")
WORDS = {
    "improve_live": "improving the strategies you're paper trading",
    "improve": "improving your other strategies",
    "discover": "discovering new strategies",
    "opportunities": "looking for new stocks for strategies that work",
}
log = logging.getLogger("agora.metis")
LIVE_EVERY = 3
LIVE_REST_AFTER = 6  # empty improve_live rounds in a row before those strategies rest (D-128)
SCAN_EVERY = 4
# While the research sprint's playbook has strategies not yet re-tested on the user's stocks,
# discovery gets at least every third round: its record from inventing strategies from scratch
# (18 kept of ~2,500) would otherwise almost never win the draw against the scanner (D-149).
PLAYBOOK_EVERY = 3
SCAN_GAP_MS = 6 * 3_600_000  # with nothing new, the scanner would only find the same again


def scan_worth_it(ctx: Any) -> bool:
    """Is there anything new for the scanner since its last round: a strategy version saved
    after it, or six hours passed (new prices)? Metis works all the time now (D-103), so
    without this it reran the same scan every few minutes."""
    with ctx.db.session() as s:
        last = s.scalar(
            select(func.max(MetisRound.started_at)).where(
                MetisRound.direction == "opportunities", MetisRound.status == "done"
            )
        )
        if last is None:
            return True
        newest = s.scalar(select(func.max(StrategyVersion.created_at))) or 0
    return bool(newest > last or ctx.clock.now_ms() - last >= SCAN_GAP_MS)


DISCOVER_SEEDS = 2


@dataclass(frozen=True)
class Choice:
    direction: str
    why: str


def in_use(ctx: Any) -> list[int]:
    """Strategies with a running paper session or in an active portfolio sleeve."""
    with ctx.db.session() as s:
        ids = set(
            s.scalars(
                select(StrategyVersion.strategy_id)
                .join(PaperSession, PaperSession.strategy_version_id == StrategyVersion.id)
                .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
                .where(PaperSession.state != "stopped", Strategy.kind.in_(("visual", "code")))
            )
        )
        try:
            from backend.db.models import PortfolioSleeve

            ids |= set(
                s.scalars(
                    select(PortfolioSleeve.strategy_id).where(PortfolioSleeve.status == "active")
                )
            )
        except ImportError:  # before the portfolio tables (Phase 15)
            pass
    return sorted(ids)


def strategy_count(ctx: Any) -> int:
    with ctx.db.session() as s:
        return int(
            s.scalar(
                select(func.count(Strategy.id)).where(
                    Strategy.archived_at.is_(None), Strategy.kind.in_(("visual", "code"))
                )
            )
            or 0
        )


def rounds_done(ctx: Any) -> int:
    with ctx.db.session() as s:
        return int(s.scalar(select(func.count(MetisRound.id))) or 0)


def named_strategy(ctx: Any, focus: str) -> int | None:
    low = focus.lower().strip()
    if not low:
        return None
    with ctx.db.session() as s:
        for r in s.scalars(select(Strategy).where(Strategy.archived_at.is_(None))):
            if r.name.lower() in low or f"#{r.id}" in low:
                return int(r.id)
    return None


def live_resting(ctx: Any, live: list[int]) -> bool:
    """The strategies in use have had ``LIVE_REST_AFTER`` rounds in a row with nothing kept and
    none of them has changed since (a new version, or new trades bringing a new backtest, ends
    the rest). Without this Metis kept coming back to the same few-trade strategy every third
    round with nothing new to say (D-128). They still compete in the record-based draw."""
    if not live:
        return False
    with ctx.db.session() as s:
        rows = list(
            s.execute(
                select(MetisRound.kept, MetisRound.started_at)
                .where(MetisRound.direction == "improve_live", MetisRound.status == "done")
                .order_by(MetisRound.id.desc())
                .limit(LIVE_REST_AFTER)
            )
        )
        if len(rows) < LIVE_REST_AFTER or any(int(k or 0) > 0 for k, _ in rows):
            return False
        since = min(int(t) for _, t in rows)
        changed = s.scalar(
            select(func.max(StrategyVersion.created_at)).where(
                StrategyVersion.strategy_id.in_(live)
            )
        )
    return changed is None or int(changed) < since


def choose(ctx: Any, focus: str = "", *, round_no: int | None = None) -> Choice:
    live = in_use(ctx)
    n_strategies = strategy_count(ctx)
    named = named_strategy(ctx, focus)
    if named is not None:
        return Choice(
            "improve_live" if named in live else "improve", "you asked Metis to look into it"
        )
    if n_strategies == 0:
        return Choice("discover", "there are no strategies to improve yet")
    recent = notebook.recent_directions(ctx, SCAN_EVERY)
    if not recent:
        return Choice(
            "improve_live" if live else "improve",
            "the first round starts with the strategies you have",
        )
    resting = live_resting(ctx, live)
    if live and not resting and "improve_live" not in recent[: LIVE_EVERY - 1]:
        return Choice("improve_live", "strategies in use get a round at least every third round")
    scan = scan_worth_it(ctx)
    if scan and len(recent) >= SCAN_EVERY - 1 and "opportunities" not in recent[: SCAN_EVERY - 1]:
        return Choice("opportunities", "the scanner runs at least every fourth round")
    if "discover" not in recent[: PLAYBOOK_EVERY - 1] and playbook_waiting(ctx):
        return Choice(
            "discover", "the sprint's playbook has strategies not yet tested on your stocks"
        )
    eligible = ["discover", "opportunities"] if scan else ["discover"]
    if live:
        eligible.insert(0, "improve_live")
    if n_strategies > len(live):
        eligible.insert(0, "improve")
    rec = notebook.record(ctx)
    rng = np.random.default_rng(rounds_done(ctx) if round_no is None else round_no)
    draws = {}
    for d in eligible:
        kept, failed = rec.get(d, (0, 0))
        draws[d] = float(rng.beta(1 + kept, 1 + failed))
    best = max(eligible, key=lambda d: draws[d])
    kept, failed = rec.get(best, (0, 0))
    return Choice(best, f"chosen by its record ({kept} kept of {kept + failed} tested)")


def playbook_waiting(ctx: Any) -> bool:
    """A playbook entry is waiting to be re-tested on the user's stocks (D-144, D-149)."""
    try:
        return any(sprint_seeds(ctx, m, 1) for m in ("IN", "US"))
    except Exception:  # never let the playbook stop Metis choosing a direction
        log.debug("Couldn't read the playbook", exc_info=True)
        return False


def discover_seeds(
    ctx: Any, markets: list[str], limit: int = DISCOVER_SEEDS
) -> list[dict[str, Any]]:
    """Strategies the user doesn't have yet, as playbook ideas: first the research sprint's
    playbook entries that suit today's market (D-144), then textbook strategies (Agora's
    templates) on every timeframe with enough saved history: the timeframes with the fewest
    strategies first, the markets taking turns (D-118)."""
    from backend.metis import timeframes

    per_market: list[list[dict[str, Any]]] = []
    for market in markets:
        found: list[dict[str, Any]] = sprint_seeds(ctx, market, limit)
        for tf in timeframes.order(ctx, market):
            for key, t in templates.TEMPLATES.items():
                if len(found) >= limit:
                    break
                if tf not in templates.timeframes_for(key):
                    continue
                rules: dict[str, Any] = {"template": key, "market": market}
                if tf != t.timeframe:
                    rules["timeframe"] = tf
                if notebook.seen(ctx, notebook.fingerprint("new_strategy", None, rules)):
                    continue
                d = templates.template_definition(key, market, timeframe=tf)
                with ctx.db.session() as s:
                    if revisions.match(s, d, template_key=key) is not None:
                        continue
                found.append(_template_seed(key, t, market, tf))
        per_market.append(found)
    out = [x for group in zip_longest(*per_market) for x in group if x is not None]
    return out[:limit]


def market_regime(ctx: Any, market: str) -> str | None:
    """Today's regime of the market's index on daily candles (``regime_map``), or None."""
    from backend.analysis import regime_map
    from backend.core.types import Market, Timeframe
    from backend.data import service as data_service
    from backend.data import store
    from backend.indicators.series import from_bars

    m = Market(market)
    with ctx.db.session() as s:
        inst = store.find_instrument(s, m, data_service.BENCHMARK[m])
    if inst is None:
        return None
    now = ctx.clock.now_ms()
    bars = ctx.cache.bars(inst, Timeframe.D1, now - 800 * 86_400_000, now, adjusted_prices=True)
    if len(bars) < 300:
        return None
    return regime_map.regimes(from_bars(bars, Timeframe.D1, m))[-1]


def sprint_seeds(ctx: Any, market: str, limit: int) -> list[dict[str, Any]]:
    """Playbook entries for ``market`` the user doesn't have, those that suit today's regime
    first, on timeframes with saved history (D-144)."""
    from backend.lab import playbook
    from backend.metis import timeframes
    from backend.strategy.validator import validate

    entries = playbook.load()
    if not entries:
        return []
    regime = market_regime(ctx, market)
    have = set(timeframes.order(ctx, market))
    out: list[dict[str, Any]] = []
    for tf in ("1d", "1h", "15m", "5m", "1m"):
        if tf not in have:
            continue
        for e in playbook.for_regime(entries, market, tf, regime):
            if len(out) >= limit:
                return out
            rules = {"playbook": e["key"], "market": market}
            if notebook.seen(ctx, notebook.fingerprint("new_strategy", None, rules)):
                continue
            res = validate(e["definition"])
            if not res.ok or res.definition is None:
                continue
            with ctx.db.session() as s:
                if revisions.match(s, res.definition) is not None:
                    continue
            out.append(_sprint_seed(e, regime))
    return out


def _sprint_seed(e: dict[str, Any], regime: str | None) -> dict[str, Any]:
    from backend.analysis.regime_map import WORDS

    ex, v = e.get("exam") or {}, e.get("vault") or {}
    fits = (
        f" It suits today's market ({WORDS[regime]})."
        if regime and regime in e.get("works_in", [])
        else ""
    )
    return {
        "kind": "new_strategy",
        "strategy_id": None,
        "title": f"Playbook: {e['name']}",
        "why": (
            f"Survived research sprint {e.get('sprint', '')}: {ex.get('trades', 0)} exam and "
            f"{v.get('trades', 0)} vault trades, profitable in both.{fits} {e.get('why', '')}"
        )[:1000],
        "conditions": [],
        "side": "long",
        "changes": {},
        "remove": None,
        "add": [],
        "drop": [],
        "idea": "",
        "market": e["market"],
        "symbols": list(e.get("tested_on") or [])[:8],
        "template": None,
        "playbook": e["key"],
        "timeframe": e["timeframe"],
        "origin": "playbook",
    }


def _template_seed(key: str, t: Any, market: str, tf: str) -> dict[str, Any]:
    from backend.metis.timeframes import LABEL

    on = "" if tf == "1d" else f" on {LABEL[tf]} candles"
    return {
        "kind": "new_strategy",
        "strategy_id": None,
        "title": f"{t.name}{on}",
        "why": f"A documented strategy you don't have yet{on}: {t.summary}",
        "conditions": [],
        "side": "long",
        "changes": {},
        "remove": None,
        "add": [],
        "drop": [],
        "idea": "",
        "market": market,
        "symbols": [],
        "template": key,
        "timeframe": tf,
        "origin": "playbook",
    }
