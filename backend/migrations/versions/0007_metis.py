"""Metis, Kairos's AI researcher (docs/METIS.md, D-76): its rounds of research and the
notebook of every idea it had, how code tested it and what was kept.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metis_rounds",
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
            "status IN ('running', 'done', 'failed', 'skipped')",
            name=op.f("ck_metis_rounds_status"),
        ),
        sa.CheckConstraint("trigger IN ('auto', 'user')", name=op.f("ck_metis_rounds_trigger")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metis_rounds")),
    )
    op.create_table(
        "metis_ideas",
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
        sa.CheckConstraint(
            "kind IN ('filter', 'tweak', 'new_strategy')", name=op.f("ck_metis_ideas_kind")
        ),
        sa.CheckConstraint(
            "status IN ('held_up', 'rejected', 'untestable', 'saved')",
            name=op.f("ck_metis_ideas_status"),
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["metis_rounds.id"], name=op.f("fk_metis_ideas_round_id_metis_rounds")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metis_ideas")),
    )
    with op.batch_alter_table("metis_ideas", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_metis_ideas_round_id"), ["round_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_metis_ideas_fingerprint"), ["fingerprint"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("metis_ideas", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_metis_ideas_fingerprint"))
        batch_op.drop_index(batch_op.f("ix_metis_ideas_round_id"))
    op.drop_table("metis_ideas")
    op.drop_table("metis_rounds")
