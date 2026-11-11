"""initial schema: every table in docs/DATA_MODEL.md (v3.0).

Revision ID: 0001
Revises:
Create Date: 2026-10-21 05:18:35.563757
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("context_kind", sa.String(), nullable=False),
        sa.Column("context_id", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "context_kind IN ('backtest', 'trade', 'strategy_draft', 'paper_day', 'general')",
            name=op.f("ck_ai_conversations_context_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
    )
    op.create_table(
        "app_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("area", sa.String(), nullable=False),
        sa.Column("message_plain", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint("level IN ('info', 'warn', 'error')", name=op.f("ck_app_events_level")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_events")),
    )
    with op.batch_alter_table("app_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_app_events_ts"), ["ts"], unique=False)

    op.create_table(
        "markets",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("calendar_name", sa.String(), nullable=False),
        sa.CheckConstraint("code IN ('IN', 'US')", name=op.f("ck_markets_code")),
        sa.CheckConstraint("currency IN ('INR', 'USD')", name=op.f("ck_markets_currency")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_markets")),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "source_status",
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("until", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "state IN ('ok', 'cooling_down', 'down')", name=op.f("ck_source_status_state")
        ),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_source_status")),
    )
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name=op.f("ck_ai_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name=op.f("fk_ai_messages_conversation_id_ai_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
    )
    op.create_table(
        "brokerage_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_code"],
            ["markets.code"],
            name=op.f("fk_brokerage_profiles_market_code_markets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brokerage_profiles")),
        sa.UniqueConstraint(
            "market_code", "name", name=op.f("uq_brokerage_profiles_market_code_name")
        ),
    )
    op.create_table(
        "charge_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("charge", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("rate_type", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("cap", sa.Float(), nullable=True),
        sa.Column("effective_from", sa.Integer(), nullable=False),
        sa.Column("effective_to", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("verified_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "charge IN ('stt', 'exchange_txn', 'sebi_fee', 'stamp_duty', 'gst', 'dp_charge', 'sec_fee', 'finra_taf')",
            name=op.f("ck_charge_schedules_charge"),
        ),
        sa.CheckConstraint(
            "product IN ('intraday', 'delivery', 'cash', 'any')",
            name=op.f("ck_charge_schedules_product"),
        ),
        sa.CheckConstraint(
            "rate_type IN ('percent', 'per_crore', 'flat_per_order', 'flat_per_scrip_day', 'per_share', 'per_million')",
            name=op.f("ck_charge_schedules_rate_type"),
        ),
        sa.CheckConstraint(
            "side IN ('buy', 'sell', 'both')", name=op.f("ck_charge_schedules_side")
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_charge_schedules_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_charge_schedules")),
    )
    with op.batch_alter_table("charge_schedules", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_charge_schedules_market_code_charge_effective_from"),
            ["market_code", "charge", "effective_from"],
            unique=False,
        )

    op.create_table(
        "holiday_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("close_time", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('closed', 'open', 'early_close')", name=op.f("ck_holiday_overrides_kind")
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_holiday_overrides_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holiday_overrides")),
        sa.UniqueConstraint(
            "market_code", "date", name=op.f("uq_holiday_overrides_market_code_date")
        ),
    )
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("yahoo_symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("instrument_type", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "instrument_type IN ('equity', 'etf', 'index', 'option', 'future')",
            name=op.f("ck_instruments_instrument_type"),
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_instruments_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruments")),
        sa.UniqueConstraint(
            "market_code", "symbol", name=op.f("uq_instruments_market_code_symbol")
        ),
    )
    op.create_table(
        "slippage_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("bps", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_slippage_profiles_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_slippage_profiles")),
        sa.UniqueConstraint(
            "market_code", "name", name=op.f("uq_slippage_profiles_market_code_name")
        ),
    )
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.Integer(), nullable=True),
        sa.Column("template_key", sa.String(), nullable=True),
        sa.CheckConstraint("kind IN ('visual', 'code')", name=op.f("ck_strategies_kind")),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_strategies_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
    )
    op.create_table(
        "universes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_universes_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_universes")),
        sa.UniqueConstraint("name", name=op.f("uq_universes_name")),
    )
    op.create_table(
        "candles",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("split_factor", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source IN ('yahoo', 'nse', 'stooq', 'derived', 'fake')", name=op.f("ck_candles_source")
        ),
        sa.CheckConstraint(
            "timeframe IN ('1m', '5m', '15m', '1h', '1d')", name=op.f("ck_candles_timeframe")
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=op.f("fk_candles_instrument_id_instruments")
        ),
        sa.PrimaryKeyConstraint("instrument_id", "timeframe", "ts", name=op.f("pk_candles")),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("ex_date", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.CheckConstraint("kind IN ('split', 'dividend')", name=op.f("ck_corporate_actions_kind")),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_corporate_actions_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_actions")),
        sa.UniqueConstraint(
            "instrument_id",
            "ex_date",
            "kind",
            name=op.f("uq_corporate_actions_instrument_id_ex_date_kind"),
        ),
    )
    op.create_table(
        "data_fetch_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("timeframe", sa.String(), nullable=True),
        sa.Column("range_start", sa.Integer(), nullable=True),
        sa.Column("range_end", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ok', 'empty', 'rate_limited', 'error', 'fallback')",
            name=op.f("ck_data_fetch_log_status"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_data_fetch_log_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_fetch_log")),
    )
    with op.batch_alter_table("data_fetch_log", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_data_fetch_log_started_at"), ["started_at"], unique=False
        )

    op.create_table(
        "instrument_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("alias_symbol", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Integer(), nullable=False),
        sa.Column("valid_to", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_instrument_aliases_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instrument_aliases")),
    )
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("starting_capital", sa.Float(), nullable=False),
        sa.Column("brokerage_profile_id", sa.Integer(), nullable=False),
        sa.Column("slippage_bps", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["brokerage_profile_id"],
            ["brokerage_profiles.id"],
            name=op.f("fk_paper_accounts_brokerage_profile_id_brokerage_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["market_code"], ["markets.code"], name=op.f("fk_paper_accounts_market_code_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_accounts")),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint(
            "created_by IN ('user', 'ai_draft')", name=op.f("ck_strategy_versions_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_strategy_versions_strategy_id_strategies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_versions")),
        sa.UniqueConstraint(
            "strategy_id", "version", name=op.f("uq_strategy_versions_strategy_id_version")
        ),
    )
    op.create_table(
        "universe_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Integer(), nullable=False),
        sa.Column("valid_to", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_universe_members_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["universe_id"],
            ["universes.id"],
            name=op.f("fk_universe_members_universe_id_universes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_universe_members")),
    )
    with op.batch_alter_table("universe_members", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_universe_members_universe_id_valid_from"),
            ["universe_id", "valid_from"],
            unique=False,
        )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("repro", sa.Text(), nullable=True),
        sa.Column("metrics", sa.Text(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("error_plain", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.Integer(), nullable=True),
        sa.Column("parent_run_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("starred", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name=op.f("ck_backtest_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_runs_parent_run_id_backtest_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_backtest_runs_strategy_version_id_strategy_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )
    with op.batch_alter_table("backtest_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_backtest_runs_strategy_version_id"),
            ["strategy_version_id"],
            unique=False,
        )

    op.create_table(
        "paper_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("strategy_version_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=False),
        sa.Column("stopped_at", sa.Integer(), nullable=True),
        sa.Column("last_bar_ts", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "state IN ('running', 'paused_data', 'paused_user', 'stopped')",
            name=op.f("ck_paper_sessions_state"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name=op.f("fk_paper_sessions_account_id_paper_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_paper_sessions_strategy_version_id_strategy_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_sessions")),
    )
    op.create_table(
        "backtest_equity",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("exposure", sa.Float(), nullable=False),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_equity_run_id_backtest_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "ts", name=op.f("pk_backtest_equity")),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "backtest_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_backtest_orders_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_orders_run_id_backtest_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_orders")),
    )
    with op.batch_alter_table("backtest_orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backtest_orders_run_id"), ["run_id"], unique=False)

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
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
            name=op.f("ck_backtest_trades_exit_reason"),
        ),
        sa.CheckConstraint("side IN ('long', 'short')", name=op.f("ck_backtest_trades_side")),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_backtest_trades_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_trades_run_id_backtest_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_trades")),
    )
    with op.batch_alter_table("backtest_trades", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backtest_trades_run_id"), ["run_id"], unique=False)

    op.create_table(
        "paper_equity",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["paper_sessions.id"],
            name=op.f("fk_paper_equity_session_id_paper_sessions"),
        ),
        sa.PrimaryKeyConstraint("session_id", "ts", name=op.f("pk_paper_equity")),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "paper_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("message_plain", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "level IN ('info', 'warn', 'error')", name=op.f("ck_paper_events_level")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["paper_sessions.id"],
            name=op.f("fk_paper_events_session_id_paper_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_events")),
    )
    with op.batch_alter_table("paper_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_paper_events_session_id_ts"), ["session_id", "ts"], unique=False
        )

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("created_ts", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.CheckConstraint("side IN ('buy', 'sell')", name=op.f("ck_paper_orders_side")),
        sa.CheckConstraint(
            "status IN ('open', 'filled', 'cancelled', 'rejected')",
            name=op.f("ck_paper_orders_status"),
        ),
        sa.CheckConstraint(
            "type IN ('market', 'limit', 'stop', 'stop_limit')", name=op.f("ck_paper_orders_type")
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_paper_orders_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["paper_sessions.id"],
            name=op.f("fk_paper_orders_session_id_paper_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_orders")),
    )
    with op.batch_alter_table("paper_orders", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_paper_orders_session_id"), ["session_id"], unique=False
        )

    op.create_table(
        "paper_positions",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=False),
        sa.Column("opened_ts", sa.Integer(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_paper_positions_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["paper_sessions.id"],
            name=op.f("fk_paper_positions_session_id_paper_sessions"),
        ),
        sa.PrimaryKeyConstraint("session_id", "instrument_id", name=op.f("pk_paper_positions")),
    )
    op.create_table(
        "paper_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("charges", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"], ["paper_orders.id"], name=op.f("fk_paper_fills_order_id_paper_orders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_fills")),
    )


def downgrade() -> None:
    op.drop_table("paper_fills")
    op.drop_table("paper_positions")
    with op.batch_alter_table("paper_orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_paper_orders_session_id"))

    op.drop_table("paper_orders")
    with op.batch_alter_table("paper_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_paper_events_session_id_ts"))

    op.drop_table("paper_events")
    op.drop_table("paper_equity")
    with op.batch_alter_table("backtest_trades", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_trades_run_id"))

    op.drop_table("backtest_trades")
    with op.batch_alter_table("backtest_orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_orders_run_id"))

    op.drop_table("backtest_orders")
    op.drop_table("backtest_equity")
    op.drop_table("paper_sessions")
    with op.batch_alter_table("backtest_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_runs_strategy_version_id"))

    op.drop_table("backtest_runs")
    with op.batch_alter_table("universe_members", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_universe_members_universe_id_valid_from"))

    op.drop_table("universe_members")
    op.drop_table("strategy_versions")
    op.drop_table("paper_accounts")
    op.drop_table("instrument_aliases")
    with op.batch_alter_table("data_fetch_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_data_fetch_log_started_at"))

    op.drop_table("data_fetch_log")
    op.drop_table("corporate_actions")
    op.drop_table("candles")
    op.drop_table("universes")
    op.drop_table("strategies")
    op.drop_table("slippage_profiles")
    op.drop_table("instruments")
    op.drop_table("holiday_overrides")
    with op.batch_alter_table("charge_schedules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_charge_schedules_market_code_charge_effective_from"))

    op.drop_table("charge_schedules")
    op.drop_table("brokerage_profiles")
    op.drop_table("ai_messages")
    op.drop_table("source_status")
    op.drop_table("settings")
    op.drop_table("markets")
    with op.batch_alter_table("app_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_app_events_ts"))

    op.drop_table("app_events")
    op.drop_table("ai_conversations")
