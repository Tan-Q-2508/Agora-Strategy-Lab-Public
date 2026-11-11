"""Lessons: what Kairos's own paper trades taught it, in one sentence each (KAIROS §8.3).

After every closed desk trade, Kairos looks at its recent trades (the last ``RECENT``) and,
for each signal that was in play in at least ``MIN_TRADES`` of them, writes a lesson when
the record is clearly good or clearly bad ("Bull flag breakouts worked 4 of 5 times
lately"). One lesson per signal and market is kept and rewritten as the record changes,
so memory doesn't fill with near-copies.

The most relevant lessons (sharing words with the question, else the newest) go into the
chat prompt so Kairos can say "last time this failed" without making anything up.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from backend.core.types import Market
from backend.db.models import KairosJournal, KairosMemory

RECENT = 20
MIN_TRADES = 3
GOOD = 0.75
BAD = 0.25


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


def recent_reviews(ctx: Any, market: Market, limit: int = RECENT) -> list[dict[str, Any]]:
    """The latest closed desk trades in a market (from the journal's reviews)."""
    with ctx.db.session() as s:
        rows = s.scalars(
            select(KairosJournal)
            .where(KairosJournal.kind == "review")
            .order_by(KairosJournal.id.desc())
            .limit(5 * limit)
        ).all()
        out = []
        for r in rows:
            data = json.loads(r.signals or "{}")
            if data.get("market") == market.value:
                out.append(data)
            if len(out) >= limit:
                break
        return out


def update_lessons(ctx: Any, market: Market) -> list[str]:
    """Rewrite the lessons the recent record supports. Returns the lessons written."""
    from backend.kairos.learning import label_of

    reviews = recent_reviews(ctx, market)
    by_signal: dict[str, list[bool]] = defaultdict(list)
    for r in reviews:
        won = bool(r.get("won"))
        side = int(r.get("side", 1))
        for key, d in r.get("keys", []):
            by_signal[str(key)].append(won == (int(d) == side))
    now = ctx.clock.now_ms()
    where = "Indian" if market is Market.IN else "US"
    written: list[str] = []
    with ctx.db.session() as s:
        for key, results in sorted(by_signal.items()):
            n = len(results)
            if n < MIN_TRADES:
                continue
            wins = sum(results)
            rate = wins / n
            if BAD < rate < GOOD:
                continue
            label = label_of(key)
            verb = "worked" if rate >= GOOD else "failed"
            count = wins if rate >= GOOD else n - wins
            text = (
                f"{label} {verb} {count} of {n} times in my recent paper trades on {where} stocks."
            )
            tag = f"sig:{key}"
            row = s.scalars(
                select(KairosMemory).where(
                    KairosMemory.kind == "lesson",
                    KairosMemory.market_code == market.value,
                    KairosMemory.tags.like(f"{tag} %"),
                )
            ).first()
            tags = f"{tag} {' '.join(sorted(_words(label)))} {market.value.lower()}"
            if row is None:
                s.add(
                    KairosMemory(
                        kind="lesson",
                        text=text,
                        tags=tags,
                        market_code=market.value,
                        weight=float(n),
                        uses=0,
                        created_at=now,
                    )
                )
            elif row.text != text:
                row.text, row.weight, row.created_at = text, float(n), now
            else:
                continue
            written.append(text)
    return written


def lessons(ctx: Any, market: Market | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        q = select(KairosMemory).where(KairosMemory.kind == "lesson")
        if market is not None:
            q = q.where(KairosMemory.market_code == market.value)
        rows = s.scalars(q.order_by(KairosMemory.created_at.desc()).limit(limit)).all()
        return [
            {"id": r.id, "text": r.text, "market": r.market_code, "at": r.created_at} for r in rows
        ]


def for_prompt(ctx: Any, question: str, limit: int = 3) -> str:
    """A few lessons for the chat prompt: those sharing words with the question first."""
    words = _words(question)
    with ctx.db.session() as s:
        rows = s.scalars(
            select(KairosMemory)
            .where(KairosMemory.kind == "lesson")
            .order_by(KairosMemory.created_at.desc())
            .limit(200)
        ).all()
        if not rows:
            return ""
        scored = sorted(
            rows,
            key=lambda r: (-len(words & _words(r.tags + " " + r.text)), -r.created_at),
        )
        chosen = scored[:limit]
        now = ctx.clock.now_ms()
        for r in chosen:
            r.uses += 1
            r.last_used_at = now
        return "\n".join(f"- {r.text}" for r in chosen)


def note(ctx: Any, key: str, text: str, market: str | None = None, weight: float = 1.0) -> bool:
    """Keep one lesson under ``key`` (rewritten when it changes). Returns True when new or
    changed. Used by the always-on learner for what reviews and predictions taught it."""
    tag = f"key:{key}"
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.scalars(
            select(KairosMemory).where(
                KairosMemory.kind == "lesson", KairosMemory.tags.like(f"{tag} %")
            )
        ).first()
        tags = f"{tag} {' '.join(sorted(_words(text)))}"
        if row is None:
            s.add(
                KairosMemory(
                    kind="lesson",
                    text=text[:500],
                    tags=tags,
                    market_code=market,
                    weight=weight,
                    uses=0,
                    created_at=now,
                )
            )
            return True
        if row.text == text[:500]:
            return False
        row.text, row.tags, row.weight, row.created_at = text[:500], tags, weight, now
        return True
