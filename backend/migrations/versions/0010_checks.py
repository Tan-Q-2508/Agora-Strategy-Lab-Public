"""Phase 16 (docs/LANDSCAPE.md §4): checks of strategy revisions (the look-ahead check, D-88;
forward checks of revisions and portfolio sleeves on new candles, D-90), ranking strategies
(``kind = 'ranking'``, D-91) and a portfolio's method (the best of your strategies, or a
momentum or low-volatility ranking).

SQLite can't change a CHECK constraint in place, so ``strategies`` and ``portfolios`` are rebuilt
(batch mode) from their full definition, as in 0004 and 0008.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS_OLD = "'visual', 'code', 'kairos'"
KINDS_NEW = "'visual', 'code', 'kairos', 'ranking'"
VERDICTS = "'clean', 'lookahead', 'history', 'no_data', 'waiting', 'holding', 'slipping', 'failed'"


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


def _portfolios() -> sa.Table:
    return sa.Table(
        "portfolios",
        sa.MetaData(),
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
        sa.CheckConstraint("risk IN ('careful', 'balanced', 'bold')", name="ck_portfolios_risk"),
        sa.CheckConstraint(
            "status IN ('draft', 'paper', 'stopped', 'archived')", name="ck_portfolios_status"
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name="fk_portfolios_market_code_markets"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_portfolios"),
    )


def upgrade() -> None:
    with op.batch_alter_table("strategies", recreate="always", copy_from=_strategies(KINDS_NEW)):
        pass
    with op.batch_alter_table("portfolios", recreate="always", copy_from=_portfolios()) as b:
        b.add_column(sa.Column("method", sa.String(), nullable=False, server_default="mix"))
        b.create_check_constraint("method", "method IN ('mix', 'momentum', 'low_volatility')")
    op.create_table(
        "strategy_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("baseline_version_id", sa.Integer(), nullable=True),
        sa.Column("sleeve_id", sa.Integer(), nullable=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('lookahead', 'forward')", name=op.f("ck_strategy_checks_kind")
        ),
        sa.CheckConstraint(f"verdict IN ({VERDICTS})", name=op.f("ck_strategy_checks_verdict")),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_strategy_checks_strategy_id_strategies"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_strategy_checks_version_id_strategy_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_checks")),
    )
    with op.batch_alter_table("strategy_checks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_strategy_checks_strategy_id"), ["strategy_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_strategy_checks_version_id"), ["version_id"], unique=False
        )


def downgrade() -> None:
    op.drop_table("strategy_checks")
    with op.batch_alter_table("portfolios", recreate="always", copy_from=_portfolios()):
        pass
    with op.batch_alter_table("strategies", recreate="always", copy_from=_strategies(KINDS_OLD)):
        pass
