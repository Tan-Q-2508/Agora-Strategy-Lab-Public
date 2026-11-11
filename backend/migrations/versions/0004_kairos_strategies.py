"""The Kairos brain is a strategy kind (D-60): allow ``kind = 'kairos'`` and versions
saved by Kairos (``created_by = 'kairos'``).

SQLite can't change a CHECK constraint in place, so both tables are rebuilt (batch mode)
from their full definition with the wider constraint.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _strategies(kinds: str) -> sa.Table:
    return sa.Table(
        "strategies",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.Integer(), nullable=True),
        sa.Column("template_key", sa.String(), nullable=True),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_strategies_kind"),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name="fk_strategies_market_code_markets"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategies"),
    )


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


def _rebuild(table: sa.Table) -> None:
    with op.batch_alter_table(table.name, recreate="always", copy_from=table):
        pass


def upgrade() -> None:
    _rebuild(_strategies("'visual', 'code', 'kairos'"))
    _rebuild(_versions("'user', 'ai_draft', 'kairos'"))


def downgrade() -> None:
    _rebuild(_versions("'user', 'ai_draft'"))
    _rebuild(_strategies("'visual', 'code'"))
