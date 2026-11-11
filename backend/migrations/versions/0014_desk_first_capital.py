"""D-146: a restarted Kairos desk counts its total return from its first run's money.

The autopilot restarts a desk with the money its last run ended with (D-128, D-133), so each
run's return only counted since the last restart (the user, 2026-11-03: "the total return is
wrongly calculated"). This links each desk run to the run before it (same market and timeframe,
stopped before it started, ending with exactly its starting money) and writes the first run's
money into the session's notes as ``first_capital``.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-03 18:00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    link_runs(op.get_bind())


def link_runs(conn: sa.Connection) -> int:
    """Write ``first_capital`` into each chained desk run; returns how many were linked."""
    rows = conn.execute(
        sa.text(
            "SELECT ps.id, ps.started_at, ps.stopped_at, ps.notes, pa.starting_capital, "
            "sv.definition FROM paper_sessions ps "
            "JOIN paper_accounts pa ON pa.id = ps.account_id "
            "JOIN strategy_versions sv ON sv.id = ps.strategy_version_id ORDER BY ps.started_at"
        )
    ).all()
    runs = []
    for sid, started, stopped, notes, capital, raw in rows:
        try:
            d = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if d.get("kind") != "kairos":
            continue
        last = conn.execute(
            sa.text(
                "SELECT equity FROM paper_equity WHERE session_id = :s ORDER BY ts DESC LIMIT 1"
            ),
            {"s": sid},
        ).scalar()
        runs.append(
            {
                "id": sid,
                "key": (d.get("market"), d.get("timeframe", "1d")),
                "started": started,
                "stopped": stopped,
                "notes": json.loads(notes or "{}"),
                "capital": float(capital),
                "last": float(last) if last is not None else float(capital),
            }
        )
    first: dict[int, float] = {}
    linked = 0
    for r in runs:
        before = [
            p
            for p in runs
            if p["key"] == r["key"]
            and p["id"] != r["id"]
            and p["stopped"] is not None
            and p["stopped"] <= r["started"]
            and abs(p["last"] - r["capital"]) <= 0.01 * max(1.0, abs(r["capital"])) / 100
        ]
        prev = max(before, key=lambda p: p["stopped"]) if before else None
        root = first.get(prev["id"], prev["capital"]) if prev else r["capital"]
        first[r["id"]] = root
        if prev is not None and not r["notes"].get("first_capital"):
            r["notes"]["first_capital"] = root
            conn.execute(
                sa.text("UPDATE paper_sessions SET notes = :n WHERE id = :s"),
                {"n": json.dumps(r["notes"]), "s": r["id"]},
            )
            linked += 1
    return linked


def downgrade() -> None:
    pass  # the note is harmless to keep
