"""The whole story of a trade (WEEKEND_BRIEF §8, task 27.11).

The user wants to read, for every trade, why it happened and what did or didn't work. A closing
review used to say only "it didn't work". This module puts together, for any closed paper trade:
the plan, what was known at entry, what the market then did (the best and worst point reached),
what closed it, what happened next, and the lesson, for the user, for Kairos and for a Claude
session. It is worked out from what is saved, so it covers every trade already made.

What a trade teaches is one of a few plain kinds (``KINDS``), and those counts feed the lessons
Kairos reads (``lessons``): how often trades gave back a gain, or never worked at all, says more
about what to fix than any single trade.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.core.types import Market, Timeframe
from backend.data import store
from backend.db.models import (
    Candle,
    Instrument,
    KairosJournal,
    PaperSession,
    PaperTrade,
    StrategyVersion,
)

KINDS = {
    "worked": "The plan worked.",
    "gave_back": "It was well ahead, then gave the gain back: the exit let a winner turn.",
    "never_worked": "It never went the right way: the entry was wrong.",
    "gap": "The price jumped past the stop: no stop could have held it.",
    "early": "The exit was early: the move came after it closed.",
    "plain_loss": "It moved a little, then hit its stop: an ordinary loss.",
}
AHEAD = 1.0  # "well ahead": this many times the planned risk
NOWHERE = 0.25  # "never went the right way": never this far in its favour
GAP = 1.5  # closed this many times the risk beyond the stop
AFTER_BARS = {"1d": 5, "1h": 14, "15m": 26, "5m": 78, "1m": 120}
DEFAULT_RISK_PCT = 2.0  # for trades whose plan named no stop


@dataclass
class Path:
    best_pct: float
    best_ts: int
    worst_pct: float
    worst_ts: int
    after_pct: float | None


def _path(
    bars: Sequence[Any], side: int, entry: float, exit_ts: int, exit_price: float, tf: str
) -> Path:
    held = [b for b in bars if b.ts <= exit_ts]
    later = [b for b in bars if b.ts > exit_ts]
    if not held:
        return Path(0.0, 0, 0.0, 0, None)
    if side > 0:
        hi, lo = max(held, key=lambda b: b.high), min(held, key=lambda b: b.low)
        best, worst = 100 * (hi.high / entry - 1), 100 * (lo.low / entry - 1)
    else:
        hi, lo = min(held, key=lambda b: b.low), max(held, key=lambda b: b.high)
        best, worst = 100 * (1 - hi.low / entry), 100 * (1 - lo.high / entry)
    n = AFTER_BARS.get(tf, 26)
    after = None
    if len(later) >= min(n, 3) and exit_price > 0:
        last = later[min(n, len(later)) - 1]
        after = side * 100 * (last.close / exit_price - 1)
    return Path(best, hi.ts, worst, lo.ts, after)


def lesson_kind(net_pct: float, risk_pct: float, path: Path, exit_reason: str | None) -> str:
    """What the trade teaches. Order matters: a gap explains a loss before anything else does."""
    if net_pct > 0:
        if path.after_pct is not None and path.after_pct >= 2 * risk_pct:
            return "early"
        return "worked"
    if exit_reason in ("stop", "trailing") and -net_pct >= GAP * risk_pct:
        return "gap"
    if path.best_pct >= AHEAD * risk_pct:
        return "gave_back"
    if path.best_pct < NOWHERE * risk_pct:
        return "never_worked"
    if path.after_pct is not None and path.after_pct >= 2 * risk_pct:
        return "early"
    return "plain_loss"


def _risk_pct(thesis_text: str) -> float:
    marker = "(risking "
    at = thesis_text.find(marker)
    if at >= 0:
        try:
            return float(thesis_text[at + len(marker) :].split("%")[0])
        except ValueError:
            pass
    return DEFAULT_RISK_PCT


def _bars(s: Any, iid: int, tf: str, start: int, end: int) -> list[Any]:
    return list(
        s.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == iid,
                Candle.timeframe == tf,
                Candle.ts >= start,
                Candle.ts <= end,
            )
            .order_by(Candle.ts)
        )
    )


def story(ctx: Any, trade_id: int) -> dict[str, Any] | None:
    from backend.kairos.learning import label_of

    with ctx.db.session() as s:
        t = s.get(PaperTrade, trade_id)
        if t is None or t.exit_ts is None or t.exit_price is None:
            return None
        row = s.get(PaperSession, t.session_id)
        version = s.get(StrategyVersion, row.strategy_version_id) if row else None
        d = json.loads(version.definition) if version else {}
        tf = str(d.get("timeframe") or "1d")
        inst = s.get(Instrument, t.instrument_id)
        notes = list(
            s.scalars(
                select(KairosJournal).where(
                    KairosJournal.session_id == t.session_id,
                    KairosJournal.instrument_id == t.instrument_id,
                    KairosJournal.kind.in_(("thesis", "review")),
                )
            )
        )
        thesis = next((n for n in notes if n.kind == "thesis" and _entry(n) == t.entry_ts), None)
        review = next(
            (n for n in notes if n.kind == "review" and n.trade_id == t.id), None
        ) or next((n for n in notes if n.kind == "review" and _entry(n) == t.entry_ts), None)
        step = Timeframe(tf).minutes * 60_000
        room = AFTER_BARS.get(tf, 26) * step * (3 if tf == "1d" else 8)
        bars = _bars(s, t.instrument_id, tf, t.entry_ts, t.exit_ts + room)
        groups = store.groups(s, [t.instrument_id])
    side = 1 if t.side == "long" else -1
    plan = thesis.text if thesis else t.entry_reason
    risk = _risk_pct(plan)
    path = _path(bars, side, t.entry_price, t.exit_ts, t.exit_price, tf)
    kind = lesson_kind(t.return_pct, risk, path, t.exit_reason)
    keys = json.loads(thesis.signals).get("keys", []) if thesis else []
    fors = [label_of(k) for k, v in keys if int(v) == side]
    againsts = [label_of(k) for k, v in keys if int(v) != side]
    return {
        "id": t.id,
        "session_id": t.session_id,
        "symbol": inst.symbol if inst else "",
        "side": t.side,
        "timeframe": tf,
        "plan": plan,
        "known_at_entry": {
            "score": thesis.score if thesis else None,
            "for": list(dict.fromkeys(fors))[:8],
            "against": list(dict.fromkeys(againsts))[:8],
            "sector": groups.get(t.instrument_id, ""),
        },
        "market_did": {
            "best_pct": round(path.best_pct, 2),
            "best_ts": path.best_ts,
            "worst_pct": round(path.worst_pct, 2),
            "worst_ts": path.worst_ts,
            "after_exit_pct": None if path.after_pct is None else round(path.after_pct, 2),
        },
        "closed_by": t.exit_reason,
        "result": {
            "return_pct": round(t.return_pct, 2),
            "net": round(t.net_pnl, 2),
            "charges": round(t.charges, 2),
            "bars": t.bars_held,
        },
        "kairos_concluded": review.text if review else "",
        "lesson": {"kind": kind, "text": KINDS[kind]},
    }


def _entry(note: Any) -> int | None:
    try:
        return int(json.loads(note.signals).get("entry_ts"))
    except (TypeError, ValueError):
        return None


def sentence(st: dict[str, Any]) -> str:
    """The line added to a closing review: what the market did and what it teaches."""
    m = st["market_did"]
    return (
        f" It reached {m['best_pct']:+.2f}% at best and {m['worst_pct']:+.2f}% at worst. "
        f"{st['lesson']['text']}"
    )


def record(ctx: Any, market: Market, limit: int = 200) -> Counter[str]:
    """What the last closed Kairos trades taught, by kind."""
    from backend.db.models import PaperAccount, Strategy

    with ctx.db.session() as s:
        ids = list(
            s.scalars(
                select(PaperTrade.id)
                .join(PaperSession, PaperSession.id == PaperTrade.session_id)
                .join(PaperAccount, PaperAccount.id == PaperSession.account_id)
                .join(StrategyVersion, StrategyVersion.id == PaperSession.strategy_version_id)
                .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
                .where(Strategy.kind == "kairos", PaperAccount.market_code == market.value)
                .order_by(PaperTrade.id.desc())
                .limit(limit)
            )
        )
    out: Counter[str] = Counter()
    for tid in ids:
        st = story(ctx, tid)
        if st is not None:
            out[st["lesson"]["kind"]] += 1
    return out


def teach(ctx: Any, market: Market) -> str | None:
    """Put what the record says into Kairos's lessons, which its prompts and the desk page read."""
    from backend.kairos import memory

    counts = record(ctx, market)
    n = sum(counts.values())
    if n < 20:
        return None
    where = "Indian" if market is Market.IN else "US"
    bits = ", ".join(
        f"{KINDS[k].split(':')[0].rstrip('.').lower()} {v}" for k, v in counts.most_common()
    )
    text = f"My last {n} {where} trades: {bits}."
    # only when it changed: a study round every two minutes wrote the same lesson each time
    changed = memory.note(ctx, f"trade-kinds-{market.value}", text, market.value, weight=1.5)
    return text if changed else None
