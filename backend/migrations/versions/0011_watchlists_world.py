"""Phase 18: stock profiles (sector, industry, size, exposure tags), watchlists (yours,
ready-made, and made by Kairos or Metis), world events and what they did to markets, and
investigations of sudden market and sector moves (D-93 to D-97).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23 16:31:18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "world_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.Integer(), nullable=False),
        sa.Column("last_seen", sa.Integer(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("headlines", sa.Text(), nullable=False),
        sa.Column("reactions", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'fading', 'measured')", name=op.f("ck_world_events_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_events")),
    )
    with op.batch_alter_table("world_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_world_events_scenario_first_seen"),
            ["scenario", "first_seen"],
            unique=False,
        )

    op.create_table(
        "move_investigations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("start_ts", sa.Integer(), nullable=False),
        sa.Column("end_ts", sa.Integer(), nullable=False),
        sa.Column("move_pct", sa.Float(), nullable=False),
        sa.Column("zscore", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "verdict IN ('news', 'world', 'contagion', 'unclear')",
            name=op.f("ck_move_investigations_verdict"),
        ),
        sa.ForeignKeyConstraint(
            ["market_code"],
            ["markets.code"],
            name=op.f("fk_move_investigations_market_code_markets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_move_investigations")),
    )
    with op.batch_alter_table("move_investigations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_move_investigations_market_code_created_at"),
            ["market_code", "created_at"],
            unique=False,
        )

    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "category IN ('custom', 'index', 'sector', 'size', 'factor', 'theme', 'etf', 'ai')",
            name=op.f("ck_watchlists_category"),
        ),
        sa.CheckConstraint(
            "kind IN ('custom', 'ready', 'kairos', 'metis')", name=op.f("ck_watchlists_kind")
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_watchlists_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlists")),
        sa.UniqueConstraint("market_code", "name", name=op.f("uq_watchlists_market_code_name")),
    )
    op.create_table(
        "world_effects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("mean", sa.Float(), nullable=False),
        sa.Column("m2", sa.Float(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("source IN ('history', 'live')", name=op.f("ck_world_effects_source")),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_world_effects_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_effects")),
        sa.UniqueConstraint(
            "scenario",
            "market_code",
            "target",
            "horizon",
            "source",
            name=op.f("uq_world_effects_scenario_market_code_target_horizon_source"),
        ),
    )
    op.create_table(
        "instrument_profiles",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("sector", sa.String(), nullable=False),
        sa.Column("industry", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("lists", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.CheckConstraint(
            "size IN ('large', 'mid', 'small', 'micro', '')",
            name=op.f("ck_instrument_profiles_size"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_instrument_profiles_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("instrument_id", name=op.f("pk_instrument_profiles")),
    )
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_watchlist_items_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
            name=op.f("fk_watchlist_items_watchlist_id_watchlists"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_items")),
        sa.UniqueConstraint(
            "watchlist_id",
            "instrument_id",
            name=op.f("uq_watchlist_items_watchlist_id_instrument_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("watchlist_items")
    op.drop_table("instrument_profiles")
    op.drop_table("world_effects")
    op.drop_table("watchlists")
    with op.batch_alter_table("move_investigations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_move_investigations_market_code_created_at"))

    op.drop_table("move_investigations")
    with op.batch_alter_table("world_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_world_events_scenario_first_seen"))

    op.drop_table("world_events")
