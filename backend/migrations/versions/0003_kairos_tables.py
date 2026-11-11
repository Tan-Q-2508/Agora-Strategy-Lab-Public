"""Kairos tables: news, conversations, signal statistics, journal, memory, forecasts
(docs/KAIROS.md §12, DATA_MODEL "Kairos").

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kairos_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('lesson', 'preference', 'fact')", name=op.f("ck_kairos_memory_kind")
        ),
        sa.CheckConstraint(
            "market_code IS NULL OR market_code IN ('IN', 'US')",
            name=op.f("ck_kairos_memory_market_code"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_memory")),
    )
    op.create_table(
        "kairos_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_threads")),
    )
    with op.batch_alter_table("kairos_threads", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_kairos_threads_updated_at"), ["updated_at"], unique=False
        )

    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(), nullable=False),
        sa.Column("published_at", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.Integer(), nullable=False),
        sa.Column("sentiment", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "market IS NULL OR market IN ('IN', 'US')", name=op.f("ck_news_items_market")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_items")),
        sa.UniqueConstraint("uid", name=op.f("uq_news_items_uid")),
    )
    with op.batch_alter_table("news_items", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_news_items_published_at"), ["published_at"], unique=False
        )

    op.create_table(
        "kairos_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'step')", name=op.f("ck_kairos_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["kairos_threads.id"],
            name=op.f("fk_kairos_messages_thread_id_kairos_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_messages")),
    )
    with op.batch_alter_table("kairos_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_kairos_messages_thread_id"), ["thread_id"], unique=False
        )

    op.create_table(
        "kairos_signal_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Float(), nullable=False),
        sa.Column("sum_ret", sa.Float(), nullable=False),
        sa.Column("sum_ret2", sa.Float(), nullable=False),
        sa.Column("base_n", sa.Integer(), nullable=False),
        sa.Column("base_wins", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source IN ('history', 'paper')", name=op.f("ck_kairos_signal_stats_source")
        ),
        sa.CheckConstraint(
            "timeframe IN ('1m', '5m', '15m', '1h', '1d')",
            name=op.f("ck_kairos_signal_stats_timeframe"),
        ),
        sa.ForeignKeyConstraint(
            ["market_code"],
            ["markets.code"],
            name=op.f("fk_kairos_signal_stats_market_code_markets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_signal_stats")),
        sa.UniqueConstraint(
            "market_code",
            "timeframe",
            "signal",
            "source",
            "horizon",
            name=op.f("uq_kairos_signal_stats_market_code_timeframe_signal_source_horizon"),
        ),
    )
    op.create_table(
        "kairos_forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("made_at", sa.Integer(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("origin", sa.Float(), nullable=False),
        sa.Column("p10", sa.Float(), nullable=False),
        sa.Column("p50", sa.Float(), nullable=False),
        sa.Column("p90", sa.Float(), nullable=False),
        sa.Column("up_prob", sa.Float(), nullable=False),
        sa.Column("resolved_at", sa.Integer(), nullable=True),
        sa.Column("actual", sa.Float(), nullable=True),
        sa.Column("hit", sa.Integer(), nullable=True),
        sa.Column("inside80", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "timeframe IN ('1m', '5m', '15m', '1h', '1d')",
            name=op.f("ck_kairos_forecasts_timeframe"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_kairos_forecasts_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_forecasts")),
        sa.UniqueConstraint(
            "instrument_id",
            "timeframe",
            "made_at",
            "horizon",
            name=op.f("uq_kairos_forecasts_instrument_id_timeframe_made_at_horizon"),
        ),
    )
    op.create_table(
        "news_links",
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_news_links_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["news_id"],
            ["news_items.id"],
            name=op.f("fk_news_links_news_id_news_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("news_id", "instrument_id", name=op.f("pk_news_links")),
    )
    with op.batch_alter_table("news_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_news_links_instrument_id"), ["instrument_id"], unique=False
        )

    op.create_table(
        "kairos_journal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("signals", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('thesis', 'review', 'note', 'day')", name=op.f("ck_kairos_journal_kind")
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_kairos_journal_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["paper_sessions.id"],
            name=op.f("fk_kairos_journal_session_id_paper_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"], ["paper_trades.id"], name=op.f("fk_kairos_journal_trade_id_paper_trades")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kairos_journal")),
    )
    with op.batch_alter_table("kairos_journal", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_kairos_journal_session_id"), ["session_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("kairos_journal", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_kairos_journal_session_id"))

    op.drop_table("kairos_journal")
    with op.batch_alter_table("news_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_news_links_instrument_id"))

    op.drop_table("news_links")
    op.drop_table("kairos_forecasts")
    op.drop_table("kairos_signal_stats")
    with op.batch_alter_table("kairos_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_kairos_messages_thread_id"))

    op.drop_table("kairos_messages")
    with op.batch_alter_table("news_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_news_items_published_at"))

    op.drop_table("news_items")
    with op.batch_alter_table("kairos_threads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_kairos_threads_updated_at"))

    op.drop_table("kairos_threads")
    op.drop_table("kairos_memory")
