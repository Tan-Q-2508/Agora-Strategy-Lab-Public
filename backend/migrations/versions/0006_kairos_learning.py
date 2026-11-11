"""Kairos learns from results (KAIROS §16–18, D-71 to D-73): the trade check's samples, its
reviews of backtests and paper sessions, and predicted candles kept with each forecast so
they can be compared with the candles that actually formed.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMEFRAMES = "('1d', '1h', '15m', '5m', '1m')"


def upgrade() -> None:
    with op.batch_alter_table("kairos_forecasts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("p25", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("p75", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("detail", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("review", sa.Text(), nullable=True))
    op.create_table(
        "kairos_trade_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("strategy_kind", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.Integer(), nullable=False),
        sa.Column("signal_ts", sa.Integer(), nullable=False),
        sa.Column("known_ts", sa.Integer(), nullable=False),
        sa.Column("features", sa.Text(), nullable=False),
        sa.Column("ret_pct", sa.Float(), nullable=False),
        sa.Column("win", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source IN ('backtest', 'paper')", name=op.f("ck_kairos_trade_samples_source")
        ),
        sa.CheckConstraint(
            "origin IN ('trade', 'shadow')", name=op.f("ck_kairos_trade_samples_origin")
        ),
        sa.CheckConstraint(
            f"timeframe IN {TIMEFRAMES}", name=op.f("ck_kairos_trade_samples_timeframe")
        ),
        sa.CheckConstraint(
            "market_code IN ('IN', 'US')", name=op.f("ck_kairos_trade_samples_market_code")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_kairos_trade_samples_strategy_id_strategies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_trade_samples")),
        sa.UniqueConstraint(
            "strategy_id",
            "source",
            "symbol",
            "signal_ts",
            "side",
            "origin",
            name=op.f("uq_kairos_trade_samples_strategy_id_source_symbol_signal_ts_side_origin"),
        ),
    )
    with op.batch_alter_table("kairos_trade_samples", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_kairos_trade_samples_strategy_id"), ["strategy_id"], unique=False
        )

    op.create_table(
        "kairos_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("trades_seen", sa.Integer(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('backtest', 'paper', 'improvement', 'learner')",
            name=op.f("ck_kairos_reviews_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_reviews")),
    )
    with op.batch_alter_table("kairos_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_kairos_reviews_kind_ref_id"), ["kind", "ref_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("kairos_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_kairos_reviews_kind_ref_id"))
    op.drop_table("kairos_reviews")
    with op.batch_alter_table("kairos_trade_samples", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_kairos_trade_samples_strategy_id"))
    op.drop_table("kairos_trade_samples")
    with op.batch_alter_table("kairos_forecasts", schema=None) as batch_op:
        batch_op.drop_column("review")
        batch_op.drop_column("detail")
        batch_op.drop_column("p75")
        batch_op.drop_column("p25")
