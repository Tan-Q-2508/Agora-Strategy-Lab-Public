"""Saving strategies and their versions (revisions).

Every save makes a new numbered version (unless nothing changed), so a backtest always
points at the exact rules it ran (SPEC §6.1 reproducibility). Archiving hides a strategy
but never deletes it or its backtests.

Revision control (docs/REVISIONS.md, D-79): each version records the one it came from, what
changed in plain words (worked out by ``diff.py``), the evidence behind it and its source.
Restoring an old version saves it again as the newest; history is never rewritten.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Strategy, StrategyVersion
from backend.strategy import diff
from backend.strategy.definition import (
    SCHEMA_VERSION,
    AnyDefinition,
    canonical_json,
    content_hash,
)


@dataclass(frozen=True)
class SavedVersion:
    id: int
    strategy_id: int
    version: int
    definition: AnyDefinition
    content_hash: str
    created_at: int
    note: str
    created_by: str
    parent_version_id: int | None = None
    changes: tuple[str, ...] = ()
    evidence: dict[str, Any] | None = None
    source: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "version": self.version,
            "definition": self.definition.model_dump(mode="json"),
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "note": self.note,
            "created_by": self.created_by,
            "author_label": AUTHOR_LABEL.get(self.created_by, self.created_by),
            "parent_version_id": self.parent_version_id,
            "changes": list(self.changes),
            "evidence": self.evidence or {},
            "source": self.source,
        }


AUTHOR_LABEL = {"user": "You", "ai_draft": "AI helper", "kairos": "Kairos", "metis": "Metis"}


def _load(row: StrategyVersion) -> SavedVersion:
    from backend.strategy.validator import _adapter

    defn = _adapter.validate_python(json.loads(row.definition))
    return SavedVersion(
        row.id,
        row.strategy_id,
        row.version,
        defn,
        row.content_hash,
        row.created_at,
        row.note,
        row.created_by,
        row.parent_version_id,
        tuple(json.loads(row.changes or "[]")),
        json.loads(row.evidence or "{}") or None,
        row.source or "",
    )


def create(
    s: Session,
    *,
    name: str,
    description: str,
    definition: AnyDefinition,
    now: int,
    template_key: str | None = None,
    created_by: str = "user",
    note: str = "",
    evidence: dict[str, Any] | None = None,
    source: str = "",
) -> tuple[Strategy, SavedVersion]:
    row = Strategy(
        name=name.strip()[:120] or "Untitled strategy",
        description=description.strip()[:2000],
        kind=definition.kind,
        market_code=definition.market,
        created_at=now,
        updated_at=now,
        template_key=template_key,
    )
    s.add(row)
    s.flush()
    version = add_version(
        s,
        row,
        definition,
        now,
        note=note or "First version",
        created_by=created_by,
        evidence=evidence,
        source=source,
    )
    return row, version


def add_version(
    s: Session,
    strategy: Strategy,
    definition: AnyDefinition,
    now: int,
    *,
    note: str = "",
    created_by: str = "user",
    evidence: dict[str, Any] | None = None,
    source: str = "",
) -> SavedVersion:
    """Save a new version, or return the latest one unchanged when nothing differs. The new
    version records its parent (the latest) and what changed from it, in plain words."""
    h = content_hash(definition)
    latest = latest_version(s, strategy.id)
    if latest is not None and latest.content_hash == h:
        return latest
    changed = diff.changes(latest.definition if latest is not None else None, definition)
    number = (
        s.scalar(
            select(func.max(StrategyVersion.version)).where(
                StrategyVersion.strategy_id == strategy.id
            )
        )
        or 0
    ) + 1
    row = StrategyVersion(
        strategy_id=strategy.id,
        version=number,
        definition=canonical_json(definition),
        schema_version=SCHEMA_VERSION,
        content_hash=h,
        created_at=now,
        note=note[:500],
        created_by=created_by,
        parent_version_id=latest.id if latest is not None else None,
        changes=json.dumps(changed),
        evidence=json.dumps(evidence or {}, default=str),
        source=source[:200],
    )
    s.add(row)
    strategy.updated_at = now
    strategy.kind = definition.kind
    strategy.market_code = definition.market
    s.flush()
    return _load(row)


def restore(
    s: Session, strategy: Strategy, version_id: int, now: int, *, created_by: str = "user"
) -> SavedVersion:
    """Bring an old version back by saving it again as the newest (history only grows)."""
    old = get_version(s, version_id)
    if old is None or old.strategy_id != strategy.id:
        raise ValueError("That version doesn't belong to this strategy.")
    return add_version(
        s,
        strategy,
        old.definition,
        now,
        note=f"Restored version {old.version}",
        created_by=created_by,
        source=f"restore:{old.id}",
    )


def latest_version(s: Session, strategy_id: int) -> SavedVersion | None:
    row = s.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.strategy_id == strategy_id)
        .order_by(StrategyVersion.version.desc())
        .limit(1)
    )
    return _load(row) if row else None


def get_version(s: Session, version_id: int) -> SavedVersion | None:
    row = s.get(StrategyVersion, version_id)
    return _load(row) if row else None


def versions(s: Session, strategy_id: int) -> list[SavedVersion]:
    rows = s.scalars(
        select(StrategyVersion)
        .where(StrategyVersion.strategy_id == strategy_id)
        .order_by(StrategyVersion.version.desc())
    )
    return [_load(r) for r in rows]


def strategy_json(row: Strategy) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "kind": row.kind,
        "market": row.market_code,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "archived": row.archived_at is not None,
        "template_key": row.template_key,
    }
