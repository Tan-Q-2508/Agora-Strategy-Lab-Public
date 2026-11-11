"""Opportunities and portfolios (docs/PORTFOLIO.md, D-80, D-84 to D-86): strategy-and-stocks
pairings that held up on unseen years, portfolios (one budget in one market), their sleeves, and
the diary of every plan, rebalance and move.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22 23:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("budget", sa.Float(), nullable=False),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("manage", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("backtest", sa.Text(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("paper_started_at", sa.Integer(), nullable=True),
        sa.Column("last_rebalance_at", sa.Integer(), nullable=True),
        sa.Column("last_review_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "risk IN ('careful', 'balanced', 'bold')", name=op.f("ck_portfolios_risk")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'paper', 'stopped', 'archived')", name=op.f("ck_portfolios_status")
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_portfolios_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolios")),
    )
    op.create_table(
        "portfolio_moves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('plan', 'rebalance', 'add', 'retire', 'transfer', 'start', 'stop', 'note')",
            name=op.f("ck_portfolio_moves_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_moves_portfolio_id_portfolios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_moves")),
    )
    with op.batch_alter_table("portfolio_moves", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_portfolio_moves_portfolio_id"), ["portfolio_id"], unique=False
        )

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("found_at", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("symbols", sa.Text(), nullable=False),
        sa.Column("overrides", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("study", sa.Text(), nullable=False),
        sa.Column("exam", sa.Text(), nullable=False),
        sa.Column("luck", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "source IN ('scanner', 'metis', 'kairos_research', 'user')",
            name=op.f("ck_opportunities_source"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_portfolio', 'dismissed', 'stale')",
            name=op.f("ck_opportunities_status"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name=op.f("fk_opportunities_strategy_id_strategies")
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_opportunities_version_id_strategy_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
    )
    with op.batch_alter_table("opportunities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_opportunities_fingerprint"), ["fingerprint"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_opportunities_market_code_status"),
            ["market_code", "status"],
            unique=False,
        )

    op.create_table(
        "portfolio_sleeves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("symbols", sa.Text(), nullable=False),
        sa.Column("overrides", sa.Text(), nullable=False),
        sa.Column("size_pct", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("capital", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("worst_drop_pct", sa.Float(), nullable=True),
        sa.Column("reasons", sa.Text(), nullable=False),
        sa.Column("added_at", sa.Integer(), nullable=False),
        sa.Column("retired_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'winding_down', 'retired')",
            name=op.f("ck_portfolio_sleeves_status"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_sleeves_portfolio_id_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_portfolio_sleeves_strategy_id_strategies"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_portfolio_sleeves_version_id_strategy_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_sleeves")),
    )
    with op.batch_alter_table("portfolio_sleeves", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_portfolio_sleeves_portfolio_id"), ["portfolio_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("portfolio_sleeves", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_portfolio_sleeves_portfolio_id"))

    op.drop_table("portfolio_sleeves")
    with op.batch_alter_table("opportunities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_opportunities_market_code_status"))
        batch_op.drop_index(batch_op.f("ix_opportunities_fingerprint"))

    op.drop_table("opportunities")
    with op.batch_alter_table("portfolio_moves", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_portfolio_moves_portfolio_id"))

    op.drop_table("portfolio_moves")
    op.drop_table("portfolios")
