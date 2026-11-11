"""The lab's ledger: every test of every sprint, kept (D-143).

Keeping the losers matters as much as the winners: the luck check needs the honest number of
tries, and the next sprint must not quietly retry what already failed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select

from backend.db.models import LabTest


def add(ctx: Any, **values: Any) -> int:
    row = LabTest(created_at=ctx.clock.now_ms(), **_dumped(values))
    with ctx.db.session() as s:
        s.add(row)
        s.flush()
        return int(row.id)


def _dumped(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    for k in ("variant", "definition", "symbols", "study", "exam", "regimes", "vault"):
        if k in out and not isinstance(out[k], str) and out[k] is not None:
            out[k] = json.dumps(out[k], separators=(",", ":"))
    return out


def update(ctx: Any, test_id: int, **values: Any) -> None:
    with ctx.db.session() as s:
        row = s.get(LabTest, test_id)
        if row is None:
            raise KeyError(test_id)
        for k, v in _dumped(values).items():
            setattr(row, k, v)


def rows(
    ctx: Any,
    sprint: str,
    *,
    status: Sequence[str] | None = None,
    ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    q = select(LabTest).where(LabTest.sprint == sprint).order_by(LabTest.id)
    if status:
        q = q.where(LabTest.status.in_(list(status)))
    if ids:
        q = q.where(LabTest.id.in_(list(ids)))
    with ctx.db.session() as s:
        return [as_dict(r) for r in s.scalars(q)]


def as_dict(r: LabTest) -> dict[str, Any]:
    def load(v: str | None) -> Any:
        return json.loads(v) if v else None

    return {
        "id": r.id,
        "sprint": r.sprint,
        "family": r.family,
        "variant": load(r.variant) or {},
        "market": r.market_code,
        "timeframe": r.timeframe,
        "def_hash": r.def_hash,
        "definition": load(r.definition),
        "symbols": load(r.symbols) or [],
        "start_ms": r.start_ms,
        "split_ms": r.split_ms,
        "vault_ms": r.vault_ms,
        "end_ms": r.end_ms,
        "study": load(r.study) or {},
        "exam": load(r.exam) or {},
        "regimes": load(r.regimes) or {},
        "vault": load(r.vault),
        "vault_opened_at": r.vault_opened_at,
        "status": r.status,
        "note": r.note,
    }


def tries(ctx: Any, sprint: str | None = None) -> int:
    """How many tests were run (in one sprint, or ever): the luck check's N."""
    q = select(func.count()).select_from(LabTest)
    if sprint:
        q = q.where(LabTest.sprint == sprint)
    with ctx.db.session() as s:
        return int(s.scalar(q) or 0)


def seen(
    ctx: Any, sprint: str, family: str, market: str, timeframe: str, variant: dict[str, float]
) -> bool:
    """This variant was already tested in the sprint. Matched by family, market, timeframe and
    settings, not by the exact stocks: the most-traded list can shift by a place between runs
    as new prices arrive, and a rerun must not count as another try against the luck check."""
    key = json.dumps(variant, separators=(",", ":"))
    with ctx.db.session() as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(LabTest)
                .where(
                    LabTest.sprint == sprint,
                    LabTest.family == family,
                    LabTest.market_code == market,
                    LabTest.timeframe == timeframe,
                    LabTest.variant == key,
                )
            )
            or 0
        ) > 0
