"""paper_trades: closed paper trades, shaped like backtest_trades.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("entry_ts", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_ts", sa.Integer(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("gross_pnl", sa.Float(), nullable=False),
        sa.Column("charges", sa.Float(), nullable=False),
        sa.Column("net_pnl", sa.Float(), nullable=False),
        sa.Column("return_pct", sa.Float(), nullable=False),
        sa.Column("bars_held", sa.Integer(), nullable=False),
        sa.Column("entry_reason", sa.Text(), nullable=False),
        sa.Column("exit_reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "exit_reason IS NULL OR exit_reason IN ('signal', 'stop', 'target', 'trailing', 'time', 'square_off', 'end_of_test')",
            name=op.f("ck_paper_trades_exit_reason"),
        ),
        sa.CheckConstraint("side IN ('long', 'short')", name=op.f("ck_paper_trades_side")),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_paper_trades_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["paper_sessions.id"],
            name=op.f("fk_paper_trades_session_id_paper_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_trades")),
    )
    with op.batch_alter_table("paper_trades", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_paper_trades_session_id"), ["session_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("paper_trades", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_paper_trades_session_id"))
    op.drop_table("paper_trades")
