"""The one door through which Kairos and Metis save strategies (docs/REVISIONS.md, D-79).

Before anything "new" is saved, it is checked against the user's strategies:

- **identical** to a strategy's current revision → nothing is saved; that strategy is reused;
- **the same logic** (``lineage.find_family``) → saved as that strategy's next revision;
- **different logic** → a new strategy, and Metis may add only ``metis.new_per_day`` a day.

Callers that must first prove a revision is better (Metis judges it against the strategy's
current revision on its own stocks) use ``match`` to look before they ``save``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Strategy, StrategyVersion
from backend.strategy import lineage, service
from backend.strategy.definition import AnyDefinition, content_hash

DAY_MS = 86_400_000
Author = Literal["user", "ai_draft", "kairos", "metis"]


class NewStrategyLimit(Exception):
    """Metis already added its new strategies for today (the message says so plainly)."""


@dataclass(frozen=True)
class Match:
    kind: Literal["identical", "family"]
    strategy_id: int
    name: str
    version_id: int
    version: int
    definition: AnyDefinition
    why: str
    similarity: float


@dataclass
class Saved:
    outcome: Literal["new_strategy", "revision", "unchanged"]
    strategy_id: int
    name: str
    version_id: int
    version: int
    changes: list[str] = field(default_factory=list)
    why: str = ""

    def sentence(self) -> str:
        if self.outcome == "unchanged":
            return f"You already have this strategy: “{self.name}” (#{self.strategy_id})."
        if self.outcome == "revision":
            return (
                f"Saved as version {self.version} of “{self.name}” (#{self.strategy_id}): "
                f"it is {self.why}."
            )
        return f"Saved as a new strategy: “{self.name}” (#{self.strategy_id})."

    def public(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "version_id": self.version_id,
            "version": self.version,
            "changes": self.changes,
            "why": self.why,
            "sentence": self.sentence(),
        }


def match(
    s: Session, definition: AnyDefinition, *, template_key: str | None = None
) -> Match | None:
    """The user's strategy this definition already is (identical first, then same logic)."""
    h = content_hash(definition)
    rows = s.scalars(
        select(Strategy).where(
            Strategy.archived_at.is_(None),
            Strategy.kind == definition.kind,
            Strategy.market_code == definition.market,
        )
    ).all()
    for row in rows:
        latest = service.latest_version(s, row.id)
        if latest is not None and latest.content_hash == h:
            return Match(
                "identical",
                row.id,
                row.name,
                latest.id,
                latest.version,
                latest.definition,
                "the same rules and settings",
                1.0,
            )
    fam = lineage.find_family(s, definition, template_key=template_key)
    if fam is None:
        return None
    latest = service.latest_version(s, fam.strategy_id)
    assert latest is not None
    return Match(
        "family",
        fam.strategy_id,
        fam.name,
        latest.id,
        latest.version,
        latest.definition,
        fam.why,
        fam.similarity,
    )


def new_today(s: Session, author: str, now: int) -> int:
    """How many strategies ``author`` created in the last 24 hours."""
    return int(
        s.scalar(
            select(func.count(StrategyVersion.id)).where(
                StrategyVersion.version == 1,
                StrategyVersion.created_by == author,
                StrategyVersion.created_at > now - DAY_MS,
            )
        )
        or 0
    )


def revise(
    s: Session,
    strategy_id: int,
    definition: AnyDefinition,
    now: int,
    *,
    author: Author,
    note: str,
    evidence: dict[str, Any] | None = None,
    source: str = "",
    why: str = "an improved version",
) -> Saved:
    """Save ``definition`` as the next revision of an existing strategy."""
    row = s.get(Strategy, strategy_id)
    if row is None or row.archived_at is not None:
        raise ValueError("That strategy was deleted or archived.")
    before = service.latest_version(s, strategy_id)
    v = service.add_version(
        s, row, definition, now, note=note, created_by=author, evidence=evidence, source=source
    )
    unchanged = before is not None and v.id == before.id
    return Saved(
        "unchanged" if unchanged else "revision",
        row.id,
        row.name,
        v.id,
        v.version,
        [] if unchanged else list(v.changes),
        why,
    )


def save(
    s: Session,
    *,
    definition: AnyDefinition,
    author: Author,
    name: str,
    description: str,
    now: int,
    note: str,
    template_key: str | None = None,
    evidence: dict[str, Any] | None = None,
    source: str = "",
    new_per_day: int | None = None,
) -> Saved:
    """Reuse, revise or create, by the rules above. ``new_per_day`` caps new strategies by
    ``author`` (Metis); ``NewStrategyLimit`` is raised when it is reached."""
    found = match(s, definition, template_key=template_key)
    if found is not None and found.kind == "identical":
        return Saved(
            "unchanged",
            found.strategy_id,
            found.name,
            found.version_id,
            found.version,
            [],
            found.why,
        )
    if found is not None:
        return revise(
            s,
            found.strategy_id,
            definition,
            now,
            author=author,
            note=note,
            evidence=evidence,
            source=source,
            why=found.why,
        )
    if new_per_day is not None and new_today(s, author, now) >= new_per_day:
        raise NewStrategyLimit(
            f"{author.capitalize()} already added {new_per_day} new "
            f"strateg{'y' if new_per_day == 1 else 'ies'} today."
        )
    row, v = service.create(
        s,
        name=name,
        description=description,
        definition=definition,
        now=now,
        template_key=template_key,
        created_by=author,
        note=note,
        evidence=evidence,
        source=source,
    )
    return Saved("new_strategy", row.id, row.name, v.id, v.version, list(v.changes), "")
