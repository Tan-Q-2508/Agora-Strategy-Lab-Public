"""Saving and reading check results (``strategy_checks``)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import StrategyCheck, StrategyVersion


def save(
    s: Session,
    *,
    kind: str,
    now: int,
    strategy_id: int,
    version_id: int,
    result: dict[str, Any],
    baseline_version_id: int | None = None,
    sleeve_id: int | None = None,
    portfolio_id: int | None = None,
    action: str = "",
) -> StrategyCheck:
    row = StrategyCheck(
        kind=kind,
        created_at=now,
        strategy_id=strategy_id,
        version_id=version_id,
        baseline_version_id=baseline_version_id,
        sleeve_id=sleeve_id,
        portfolio_id=portfolio_id,
        verdict=str(result["verdict"]),
        title=str(result.get("title", "")),
        result=json.dumps(result),
        action=action,
    )
    s.add(row)
    s.flush()
    return row


def public(row: StrategyCheck, version: int | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "created_at": row.created_at,
        "strategy_id": row.strategy_id,
        "version_id": row.version_id,
        "version": version,
        "baseline_version_id": row.baseline_version_id,
        "sleeve_id": row.sleeve_id,
        "portfolio_id": row.portfolio_id,
        "verdict": row.verdict,
        "title": row.title,
        "result": json.loads(row.result or "{}"),
        "action": row.action,
    }


def for_strategy(
    s: Session, strategy_id: int, kind: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    stmt = (
        select(StrategyCheck, StrategyVersion.version)
        .join(StrategyVersion, StrategyVersion.id == StrategyCheck.version_id)
        .where(StrategyCheck.strategy_id == strategy_id)
    )
    if kind:
        stmt = stmt.where(StrategyCheck.kind == kind)
    rows = s.execute(stmt.order_by(StrategyCheck.id.desc()).limit(limit)).all()
    return [public(r, v) for r, v in rows]
