"""Revision control for strategies (docs/REVISIONS.md, D-79) and Metis's agenda (D-83).

``strategy_versions`` gains where a revision came from and what changed, and accepts revisions
made by Metis. ``metis_rounds`` records the round's direction; ``metis_ideas`` accepts the new
idea kinds (``simplify``, ``universe``) and records whether the AI or the playbook thought of it.

SQLite can't change a CHECK constraint in place, so the tables are rebuilt (batch mode) from
their full definition with the wider constraints, as in 0004.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _versions(makers: str) -> sa.Table:
    return sa.Table(
        "strategy_versions",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint(f"created_by IN ({makers})", name="ck_strategy_versions_created_by"),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name="fk_strategy_versions_strategy_id_strategies",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_versions"),
        sa.UniqueConstraint(
            "strategy_id", "version", name="uq_strategy_versions_strategy_id_version"
        ),
    )


def _rounds() -> sa.Table:
    return sa.Table(
        "metis_rounds",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("noticed", sa.Text(), nullable=False),
        sa.Column("thinking", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("ideas", sa.Integer(), nullable=False),
        sa.Column("kept", sa.Integer(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'failed', 'skipped')", name="ck_metis_rounds_status"
        ),
        sa.CheckConstraint("trigger IN ('auto', 'user')", name="ck_metis_rounds_trigger"),
        sa.PrimaryKeyConstraint("id", name="pk_metis_rounds"),
    )


def _ideas(kinds: str) -> sa.Table:
    return sa.Table(
        "metis_ideas",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("strategy_version_id", sa.Integer(), nullable=True),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("saved_strategy_id", sa.Integer(), nullable=True),
        sa.Column("saved_version_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_metis_ideas_kind"),
        sa.CheckConstraint(
            "status IN ('held_up', 'rejected', 'untestable', 'saved')",
            name="ck_metis_ideas_status",
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["metis_rounds.id"], name="fk_metis_ideas_round_id_metis_rounds"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metis_ideas"),
        sa.Index("ix_metis_ideas_round_id", "round_id"),
        sa.Index("ix_metis_ideas_fingerprint", "fingerprint"),
    )


AUTHORS_OLD = "'user', 'ai_draft', 'kairos'"
AUTHORS_NEW = "'user', 'ai_draft', 'kairos', 'metis'"
KINDS_OLD = "'filter', 'tweak', 'new_strategy'"
KINDS_NEW = "'filter', 'tweak', 'new_strategy', 'simplify', 'universe'"
DIRECTIONS = "'improve_live', 'improve', 'discover', 'opportunities'"


def upgrade() -> None:
    with op.batch_alter_table(
        "strategy_versions", recreate="always", copy_from=_versions(AUTHORS_NEW)
    ) as b:
        b.add_column(sa.Column("parent_version_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("changes", sa.Text(), nullable=False, server_default="[]"))
        b.add_column(sa.Column("evidence", sa.Text(), nullable=False, server_default="{}"))
        b.add_column(sa.Column("source", sa.String(), nullable=False, server_default=""))
    with op.batch_alter_table("metis_rounds", recreate="always", copy_from=_rounds()) as b:
        b.add_column(sa.Column("direction", sa.String(), nullable=False, server_default="improve"))
        b.create_check_constraint("direction", f"direction IN ({DIRECTIONS})")
    with op.batch_alter_table("metis_ideas", recreate="always", copy_from=_ideas(KINDS_NEW)) as b:
        b.add_column(sa.Column("origin", sa.String(), nullable=False, server_default="ai"))
        b.create_check_constraint("origin", "origin IN ('ai', 'playbook')")


def downgrade() -> None:
    # Rebuilding from the old definitions leaves the new columns and constraints out.
    for table in (_ideas(KINDS_OLD), _rounds(), _versions(AUTHORS_OLD)):
        with op.batch_alter_table(table.name, recreate="always", copy_from=table):
            pass
