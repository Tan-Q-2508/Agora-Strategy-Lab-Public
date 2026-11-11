"""All Agora tables (docs/DATA_MODEL.md is the source of truth).

Conventions: timestamps are UTC epoch milliseconds (INTEGER), money is REAL here and
``Decimal`` in cost/P&L code, JSON lives in TEXT columns, and enums are TEXT with CHECK
constraints so bad values can never be stored.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MARKETS = ("IN", "US")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "1d")
SOURCES = ("yahoo", "nse", "stooq", "derived", "fake")
LEVELS = ("info", "warn", "error")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def one_of(column: str, values: tuple[str, ...], *, nullable: bool = False) -> CheckConstraint:
    """CHECK constraint that limits a TEXT column to a fixed list of values."""
    quoted = ", ".join(f"'{v}'" for v in values)
    expr = f"{column} IN ({quoted})"
    if nullable:
        expr = f"{column} IS NULL OR {expr}"
    return CheckConstraint(expr, name=column)


def _pk() -> Mapped[int]:
    return mapped_column(Integer, primary_key=True)


# ---------------------------------------------------------------- reference data


class MarketRow(Base):
    __tablename__ = "markets"
    __table_args__ = (one_of("code", MARKETS), one_of("currency", ("INR", "USD")))
    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String)
    calendar_name: Mapped[str] = mapped_column(String)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("market_code", "symbol"),
        one_of("instrument_type", ("equity", "etf", "index", "option", "future")),
    )
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    symbol: Mapped[str] = mapped_column(String)
    yahoo_symbol: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, default="")
    instrument_type: Mapped[str] = mapped_column(String, default="equity")
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    added_at: Mapped[int] = mapped_column(Integer)


class InstrumentAlias(Base):
    __tablename__ = "instrument_aliases"
    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    alias_symbol: Mapped[str] = mapped_column(String)
    valid_from: Mapped[int] = mapped_column(Integer)
    valid_to: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Universe(Base):
    __tablename__ = "universes"
    __table_args__ = (UniqueConstraint("name"),)
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")


class UniverseMember(Base):
    __tablename__ = "universe_members"
    __table_args__ = (Index(None, "universe_id", "valid_from"),)
    id: Mapped[int] = _pk()
    universe_id: Mapped[int] = mapped_column(ForeignKey("universes.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    valid_from: Mapped[int] = mapped_column(Integer)
    valid_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String, default="")


class HolidayOverride(Base):
    __tablename__ = "holiday_overrides"
    __table_args__ = (
        UniqueConstraint("market_code", "date"),
        one_of("kind", ("closed", "open", "early_close")),
    )
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    date: Mapped[str] = mapped_column(String)  # YYYY-MM-DD in the market's timezone
    kind: Mapped[str] = mapped_column(String)
    close_time: Mapped[str | None] = mapped_column(String, nullable=True)  # HH:MM local
    note: Mapped[str] = mapped_column(String, default="")


# ---------------------------------------------------------------- market data


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        PrimaryKeyConstraint("instrument_id", "timeframe", "ts"),
        one_of("timeframe", TIMEFRAMES),
        one_of("source", SOURCES),
        {"sqlite_with_rowid": False},
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String)
    ts: Mapped[int] = mapped_column(Integer)  # bar OPEN time, UTC ms
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    split_factor: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[int] = mapped_column(Integer)


class CorporateActionRow(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("instrument_id", "ex_date", "kind"),
        one_of("kind", ("split", "dividend")),
    )
    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    ex_date: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String)


class DataFetchLog(Base):
    __tablename__ = "data_fetch_log"
    __table_args__ = (
        one_of("status", ("ok", "empty", "rate_limited", "error", "fallback")),
        Index(None, "started_at"),
    )
    id: Mapped[int] = _pk()
    source: Mapped[str] = mapped_column(String)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String, nullable=True)
    range_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    range_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class SourceStatus(Base):
    __tablename__ = "source_status"
    __table_args__ = (one_of("state", ("ok", "cooling_down", "down")),)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String)
    until: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------- costs


class BrokerageProfile(Base):
    __tablename__ = "brokerage_profiles"
    __table_args__ = (UniqueConstraint("market_code", "name"),)
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    name: Mapped[str] = mapped_column(String)
    rules: Mapped[str] = mapped_column(Text)  # JSON
    is_default: Mapped[int] = mapped_column(Integer, default=0)


CHARGES = (
    "stt",
    "exchange_txn",
    "sebi_fee",
    "stamp_duty",
    "gst",
    "dp_charge",
    "sec_fee",
    "finra_taf",
)
RATE_TYPES = (
    "percent",
    "per_crore",
    "flat_per_order",
    "flat_per_scrip_day",
    "per_share",
    "per_million",
)


class ChargeSchedule(Base):
    __tablename__ = "charge_schedules"
    __table_args__ = (
        one_of("charge", CHARGES),
        one_of("product", ("intraday", "delivery", "cash", "any")),
        one_of("side", ("buy", "sell", "both")),
        one_of("rate_type", RATE_TYPES),
        Index(None, "market_code", "charge", "effective_from"),
    )
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    charge: Mapped[str] = mapped_column(String)
    product: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    rate_type: Mapped[str] = mapped_column(String)
    rate: Mapped[float] = mapped_column(Float)
    cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_from: Mapped[int] = mapped_column(Integer)
    effective_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str] = mapped_column(String, default="")
    verified_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SlippageProfile(Base):
    __tablename__ = "slippage_profiles"
    __table_args__ = (UniqueConstraint("market_code", "name"),)
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    name: Mapped[str] = mapped_column(String)
    bps: Mapped[float] = mapped_column(Float)
    is_default: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------- strategies


STRATEGY_KINDS = ("visual", "code", "kairos", "ranking")


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (one_of("kind", STRATEGY_KINDS),)
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String)
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_key: Mapped[str | None] = mapped_column(String, nullable=True)


VERSION_AUTHORS = ("user", "ai_draft", "kairos", "metis")


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version"),
        one_of("created_by", VERSION_AUTHORS),
    )
    id: Mapped[int] = _pk()
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[str] = mapped_column(Text)  # JSON
    schema_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String, default="user")
    # Revision control (docs/REVISIONS.md, D-79): where it came from and what changed
    parent_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changes: Mapped[str] = mapped_column(Text, default="[]")  # JSON: plain-English lines
    evidence: Mapped[str] = mapped_column(Text, default="{}")  # JSON: the test behind it
    source: Mapped[str] = mapped_column(String, default="")  # e.g. "metis-idea:12"


# ---------------------------------------------------------------- backtests

RUN_STATUS = ("queued", "running", "done", "failed", "cancelled")
EXIT_REASONS = ("signal", "stop", "target", "trailing", "time", "square_off", "end_of_test")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (one_of("status", RUN_STATUS), Index(None, "strategy_version_id"))
    id: Mapped[int] = _pk()
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    status: Mapped[str] = mapped_column(String, default="queued")
    params: Mapped[str] = mapped_column(Text)  # JSON
    repro: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    metrics: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_plain: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    starred: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        one_of("side", ("long", "short")),
        one_of("exit_reason", EXIT_REASONS, nullable=True),
        Index(None, "run_id"),
    )
    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    bars_held: Mapped[int] = mapped_column(Integer, default=0)
    entry_reason: Mapped[str] = mapped_column(Text, default="")
    exit_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class BacktestEquity(Base):
    __tablename__ = "backtest_equity"
    __table_args__ = (PrimaryKeyConstraint("run_id", "ts"), {"sqlite_with_rowid": False})
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"))
    ts: Mapped[int] = mapped_column(Integer)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    exposure: Mapped[float] = mapped_column(Float)
    drawdown: Mapped[float] = mapped_column(Float)


class BacktestOrder(Base):
    __tablename__ = "backtest_orders"
    __table_args__ = (Index(None, "run_id"),)
    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"))
    ts: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    type: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- paper trading

ORDER_TYPES = ("market", "limit", "stop", "stop_limit")


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String)
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    starting_capital: Mapped[float] = mapped_column(Float)
    brokerage_profile_id: Mapped[int] = mapped_column(ForeignKey("brokerage_profiles.id"))
    slippage_bps: Mapped[float] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PaperSession(Base):
    __tablename__ = "paper_sessions"
    __table_args__ = (one_of("state", ("running", "paused_data", "paused_user", "stopped")),)
    id: Mapped[int] = _pk()
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"))
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    state: Mapped[str] = mapped_column(String)
    started_at: Mapped[int] = mapped_column(Integer)
    stopped_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_bar_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="{}")  # JSON


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        one_of("type", ORDER_TYPES),
        one_of("side", ("buy", "sell")),
        one_of("status", ("open", "filled", "cancelled", "rejected")),
        Index(None, "session_id"),
    )
    id: Mapped[int] = _pk()
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    created_ts: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text, default="")


class PaperFill(Base):
    __tablename__ = "paper_fills"
    id: Mapped[int] = _pk()
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"))
    ts: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float)
    slippage: Mapped[float] = mapped_column(Float)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (PrimaryKeyConstraint("session_id", "instrument_id"),)
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    qty: Mapped[float] = mapped_column(Float)  # negative = short
    avg_price: Mapped[float] = mapped_column(Float)
    opened_ts: Mapped[int] = mapped_column(Integer)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)


class PaperTrade(Base):
    """Closed paper trades, the same shape as backtest_trades (for backtest-vs-live)."""

    __tablename__ = "paper_trades"
    __table_args__ = (
        one_of("side", ("long", "short")),
        one_of("exit_reason", EXIT_REASONS, nullable=True),
        Index(None, "session_id"),
    )
    id: Mapped[int] = _pk()
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    bars_held: Mapped[int] = mapped_column(Integer, default=0)
    entry_reason: Mapped[str] = mapped_column(Text, default="")
    exit_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class PaperEquity(Base):
    __tablename__ = "paper_equity"
    __table_args__ = (PrimaryKeyConstraint("session_id", "ts"), {"sqlite_with_rowid": False})
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"))
    ts: Mapped[int] = mapped_column(Integer)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float)


class PaperEvent(Base):
    __tablename__ = "paper_events"
    __table_args__ = (one_of("level", LEVELS), Index(None, "session_id", "ts"))
    id: Mapped[int] = _pk()
    session_id: Mapped[int] = mapped_column(ForeignKey("paper_sessions.id"))
    ts: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    message_plain: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON


# ---------------------------------------------------------------- AI


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        one_of("context_kind", ("backtest", "trade", "strategy_draft", "paper_day", "general")),
    )
    id: Mapped[int] = _pk()
    context_kind: Mapped[str] = mapped_column(String)
    context_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (one_of("role", ("user", "assistant", "system")),)
    id: Mapped[int] = _pk()
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- app


class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON
    updated_at: Mapped[int] = mapped_column(Integer)


class AppEvent(Base):
    __tablename__ = "app_events"
    __table_args__ = (one_of("level", LEVELS), Index(None, "ts"))
    id: Mapped[int] = _pk()
    ts: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String)
    area: Mapped[str] = mapped_column(String)
    message_plain: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON


# ---------------------------------------------------------------- Kairos (docs/KAIROS.md §12)


class NewsItem(Base):
    """A headline from a public RSS feed (D-59). ``uid`` de-duplicates the same story
    seen through several feeds."""

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("uid"),
        one_of("market", MARKETS, nullable=True),
        Index(None, "published_at"),
    )
    id: Mapped[int] = _pk()
    uid: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    market: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[int] = mapped_column(Integer)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    # What it is about and how much it matters (D-68; migration 0005). NULL on rows saved
    # before 0005: the news service classifies those the first time it reads them.
    topics: Mapped[str | None] = mapped_column(Text, nullable=True)  # "conflict,energy"
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 … 5
    impact: Mapped[float | None] = mapped_column(Float, nullable=True)  # −1 risk-off … +1
    scope: Mapped[str | None] = mapped_column(String, nullable=True)  # IN / US / WORLD


class NewsLink(Base):
    """Which stocks a headline is about."""

    __tablename__ = "news_links"
    __table_args__ = (
        PrimaryKeyConstraint("news_id", "instrument_id"),
        Index(None, "instrument_id"),
    )
    news_id: Mapped[int] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))


class KairosThread(Base):
    __tablename__ = "kairos_threads"
    __table_args__ = (Index(None, "updated_at"),)
    id: Mapped[int] = _pk()
    title: Mapped[str] = mapped_column(String, default="New conversation")
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class KairosMessage(Base):
    """One turn: the user's words, Kairos's reply, or a step (a tool Kairos ran)."""

    __tablename__ = "kairos_messages"
    __table_args__ = (one_of("role", ("user", "assistant", "step")), Index(None, "thread_id"))
    id: Mapped[int] = _pk()
    thread_id: Mapped[int] = mapped_column(ForeignKey("kairos_threads.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON: tool, args, cards, ui
    created_at: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class KairosSignalStat(Base):
    """How a signal has worked (D-61): ``history`` from training on stored prices,
    ``paper`` from Kairos's own paper trades. ``wins`` counts moves in the signal's
    direction after ``horizon`` candles; ``base_*`` is the same count for every candle."""

    __tablename__ = "kairos_signal_stats"
    __table_args__ = (
        UniqueConstraint("market_code", "timeframe", "signal", "source", "horizon"),
        one_of("source", ("history", "paper")),
        one_of("timeframe", TIMEFRAMES),
    )
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    timeframe: Mapped[str] = mapped_column(String)
    signal: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    horizon: Mapped[int] = mapped_column(Integer)
    n: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[float] = mapped_column(Float, default=0.0)
    sum_ret: Mapped[float] = mapped_column(Float, default=0.0)
    sum_ret2: Mapped[float] = mapped_column(Float, default=0.0)
    base_n: Mapped[int] = mapped_column(Integer, default=0)
    base_wins: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[int] = mapped_column(Integer)


class KairosJournal(Base):
    """The desk's diary: a thesis when a trade opens, a review when it closes, notes."""

    __tablename__ = "kairos_journal"
    __table_args__ = (
        one_of("kind", ("thesis", "review", "note", "day")),
        Index(None, "session_id"),
    )
    id: Mapped[int] = _pk()
    session_id: Mapped[int | None] = mapped_column(ForeignKey("paper_sessions.id"), nullable=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("paper_trades.id"), nullable=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String)
    signals: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)


class KairosMemory(Base):
    """Lessons and preferences Kairos keeps; the most relevant go into its prompt."""

    __tablename__ = "kairos_memory"
    __table_args__ = (
        one_of("kind", ("lesson", "preference", "fact")),
        one_of("market_code", MARKETS, nullable=True),
    )
    id: Mapped[int] = _pk()
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(Text, default="")  # space-separated words
    market_code: Mapped[str | None] = mapped_column(String, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    last_used_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class KairosForecast(Base):
    """A forecast Kairos showed, scored once its horizon has passed (D-58)."""

    __tablename__ = "kairos_forecasts"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "made_at", "horizon"),
        one_of("timeframe", TIMEFRAMES),
    )
    id: Mapped[int] = _pk()
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String)
    made_at: Mapped[int] = mapped_column(Integer)  # ts of the candle it was made from
    horizon: Mapped[int] = mapped_column(Integer)
    origin: Mapped[float] = mapped_column(Float)
    p10: Mapped[float] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float)
    p90: Mapped[float] = mapped_column(Float)
    up_prob: Mapped[float] = mapped_column(Float)
    resolved_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inside80: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Migration 0006 (KAIROS §17): the predicted candles and each model's range, and, once
    # the candles have formed, how the prediction compared with them.
    p25: Mapped[float | None] = mapped_column(Float, nullable=True)
    p75: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    review: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON


class KairosTradeSample(Base):
    """One trade (or followed skipped signal) and the market's condition when it fired:
    what Kairos's trade check learns from (KAIROS §16, D-71)."""

    __tablename__ = "kairos_trade_samples"
    __table_args__ = (
        UniqueConstraint("strategy_id", "source", "symbol", "signal_ts", "side", "origin"),
        one_of("source", ("backtest", "paper")),
        one_of("origin", ("trade", "shadow")),
        one_of("timeframe", TIMEFRAMES),
        one_of("market_code", MARKETS),
        Index(None, "strategy_id"),
    )
    id: Mapped[int] = _pk()
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    strategy_kind: Mapped[str] = mapped_column(String)
    market_code: Mapped[str] = mapped_column(String)
    timeframe: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    ref_id: Mapped[int] = mapped_column(Integer)  # backtest run or paper session
    origin: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    side: Mapped[int] = mapped_column(Integer)
    signal_ts: Mapped[int] = mapped_column(Integer)
    known_ts: Mapped[int] = mapped_column(Integer)
    features: Mapped[str] = mapped_column(Text)  # JSON
    ret_pct: Mapped[float] = mapped_column(Float)
    win: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[int] = mapped_column(Integer)


class KairosReview(Base):
    """Kairos's study of a set of trades: costs, win rate, why trades failed, filters that
    would have helped (KAIROS §16), and what the always-on learner did (§18)."""

    __tablename__ = "kairos_reviews"
    __table_args__ = (
        one_of("kind", ("backtest", "paper", "improvement", "learner")),
        Index(None, "kind", "ref_id"),
    )
    id: Mapped[int] = _pk()
    kind: Mapped[str] = mapped_column(String)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trades_seen: Mapped[int] = mapped_column(Integer, default=0)
    headline: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------- Metis (Phase 12, docs/METIS.md)


METIS_DIRECTIONS = ("improve_live", "improve", "discover", "opportunities")
METIS_KINDS = ("filter", "tweak", "new_strategy", "simplify", "universe")


class MetisRound(Base):
    """One round of Metis's research: what it noticed, how it thought, what it tried."""

    __tablename__ = "metis_rounds"
    __table_args__ = (
        one_of("status", ("running", "done", "failed", "skipped")),
        one_of("trigger", ("auto", "user")),
        one_of("direction", METIS_DIRECTIONS),
    )
    id: Mapped[int] = _pk()
    started_at: Mapped[int] = mapped_column(Integer)
    finished_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    trigger: Mapped[str] = mapped_column(String, default="auto")
    focus: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String, default="")
    noticed: Mapped[str] = mapped_column(Text, default="")  # the model's own summary
    thinking: Mapped[str] = mapped_column(Text, default="")  # the model's thinking (trimmed)
    note: Mapped[str] = mapped_column(Text, default="")  # code's plain-English outcome
    ideas: Mapped[int] = mapped_column(Integer, default=0)
    kept: Mapped[int] = mapped_column(Integer, default=0)
    brief: Mapped[str] = mapped_column(Text, default="")  # what Metis was shown
    # the agenda's choice for this round (METIS §13, D-83)
    direction: Mapped[str] = mapped_column(String, default="improve")


class MetisIdea(Base):
    """One idea Metis had, how code tested it, and what was kept (the notebook)."""

    __tablename__ = "metis_ideas"
    __table_args__ = (
        one_of("kind", METIS_KINDS),
        one_of("status", ("held_up", "rejected", "untestable", "saved")),
        one_of("origin", ("ai", "playbook")),
        Index(None, "fingerprint"),
    )
    id: Mapped[int] = _pk()
    round_id: Mapped[int] = mapped_column(ForeignKey("metis_rounds.id"), index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text, default="")  # the model's reasoning
    market_code: Mapped[str | None] = mapped_column(String, nullable=True)
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spec: Mapped[str] = mapped_column(Text, default="{}")  # JSON: the idea as rules
    fingerprint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    verdict: Mapped[str] = mapped_column(Text, default="")  # code's plain-English verdict
    result: Mapped[str] = mapped_column(Text, default="{}")  # JSON: study/exam numbers
    saved_strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saved_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # who thought of it: the AI model, or the expert's playbook in code (METIS §11, §14)
    origin: Mapped[str] = mapped_column(String, default="ai")


# ---------------------------------------------------------------- opportunities and portfolios
# docs/PORTFOLIO.md, D-80, D-84 to D-86


class Opportunity(Base):
    """A strategy revision on a set of stocks that held up on unseen years (PORTFOLIO §3)."""

    __tablename__ = "opportunities"
    __table_args__ = (
        one_of("status", ("open", "in_portfolio", "dismissed", "stale")),
        one_of("source", ("scanner", "metis", "kairos_research", "user")),
        Index(None, "fingerprint"),
        Index(None, "market_code", "status"),
    )
    id: Mapped[int] = _pk()
    found_at: Mapped[int] = mapped_column(Integer)
    checked_at: Mapped[int] = mapped_column(Integer)
    market_code: Mapped[str] = mapped_column(String)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    symbols: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    overrides: Mapped[str] = mapped_column(Text, default="{}")  # JSON: tuned settings
    source: Mapped[str] = mapped_column(String, default="scanner")
    status: Mapped[str] = mapped_column(String, default="open")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    study: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    exam: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    luck: Mapped[str] = mapped_column(Text, default="{}")  # JSON: the deflated Sharpe check
    evidence: Mapped[str] = mapped_column(Text, default="")  # plain words
    fingerprint: Mapped[str] = mapped_column(String)


PORTFOLIO_METHODS = ("mix", "momentum", "low_volatility")


class Portfolio(Base):
    """One budget in one market, split into sleeves and a cash reserve (PORTFOLIO §1)."""

    __tablename__ = "portfolios"
    __table_args__ = (
        one_of("status", ("draft", "paper", "stopped", "archived")),
        one_of("risk", ("careful", "balanced", "bold")),
        one_of("method", PORTFOLIO_METHODS),
    )
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String)
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    budget: Mapped[float] = mapped_column(Float)
    risk: Mapped[str] = mapped_column(String, default="balanced")
    status: Mapped[str] = mapped_column(String, default="draft")
    manage: Mapped[int] = mapped_column(Integer, default=1)  # "Manage on its own"
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    plan: Mapped[str] = mapped_column(Text, default="{}")  # JSON: the allocator's latest plan
    backtest: Mapped[str] = mapped_column(Text, default="{}")  # JSON: the latest backtest
    cash: Mapped[float] = mapped_column(Float, default=0.0)  # the reserve while paper trading
    paper_started_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_rebalance_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_review_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # how the money is spread (PORTFOLIO §9, D-91): the best of your strategies, or a ranking
    method: Mapped[str] = mapped_column(String, default="mix")


class PortfolioSleeve(Base):
    """A slice of a portfolio's money run by one strategy revision on its stocks."""

    __tablename__ = "portfolio_sleeves"
    __table_args__ = (
        one_of("status", ("planned", "active", "winding_down", "retired")),
        Index(None, "portfolio_id"),
    )
    id: Mapped[int] = _pk()
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    opportunity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbols: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    overrides: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    size_pct: Mapped[float] = mapped_column(Float)  # % of the sleeve's money per trade
    weight: Mapped[float] = mapped_column(Float)
    capital: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="planned")
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worst_drop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # backtest's
    reasons: Mapped[str] = mapped_column(Text, default="[]")  # JSON: plain-English lines
    added_at: Mapped[int] = mapped_column(Integer)
    retired_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PortfolioMove(Base):
    """The portfolio's diary: every plan, rebalance, transfer, new and retired sleeve."""

    __tablename__ = "portfolio_moves"
    __table_args__ = (
        one_of("kind", ("plan", "rebalance", "add", "retire", "transfer", "start", "stop", "note")),
        Index(None, "portfolio_id"),
    )
    id: Mapped[int] = _pk()
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    ts: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON


# ---------------------------------------------------------------- checks (Phase 16, D-88, D-90)

CHECK_VERDICTS = (
    "clean",  # look-ahead check: nothing found
    "lookahead",  # it used candles that hadn't closed
    "history",  # its signals depend on how much history is loaded
    "no_data",
    "waiting",  # forward check: too few new candles or trades yet
    "holding",  # held up on the new candles
    "slipping",  # did worse, but not clearly enough to undo
    "failed",  # stopped holding up
)


class StrategyCheck(Base):
    """A check of one strategy revision: the look-ahead check (D-88), or a forward check of a
    revision Kairos or Metis saved, or of a portfolio sleeve, on candles formed after it was
    saved (D-90)."""

    __tablename__ = "strategy_checks"
    __table_args__ = (
        one_of("kind", ("lookahead", "forward")),
        one_of("verdict", CHECK_VERDICTS),
        Index(None, "strategy_id"),
        Index(None, "version_id"),
    )
    id: Mapped[int] = _pk()
    kind: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    baseline_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleeve_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    action: Mapped[str] = mapped_column(Text, default="")  # what was done about it, if anything


# ---------------------------------------------------------------- Phase 18 (watchlists, the world)

SIZES = ("large", "mid", "small", "micro", "")
WATCHLIST_KINDS = ("custom", "ready", "kairos", "metis")
WATCHLIST_CATEGORIES = ("custom", "index", "sector", "size", "factor", "theme", "etf", "ai")


class InstrumentProfile(Base):
    """What kind of company a stock is (D-93): its sector (GICS's 11 for both markets), its
    industry (NSE's industry or GICS sub-industry), its size (large, mid, small, micro by the
    index it belongs to), the indices it belongs to and its exposure tags (oil importer,
    exporter, defence, …) that the world map uses."""

    __tablename__ = "instrument_profiles"
    __table_args__ = (one_of("size", SIZES),)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    sector: Mapped[str] = mapped_column(String, default="")
    industry: Mapped[str] = mapped_column(String, default="")
    size: Mapped[str] = mapped_column(String, default="")
    lists: Mapped[str] = mapped_column(Text, default="")  # ";"-joined index keys
    tags: Mapped[str] = mapped_column(Text, default="")  # ";"-joined exposure tags
    as_of: Mapped[str] = mapped_column(String, default="")


class Watchlist(Base):
    """A named list of stocks: yours (custom), ready-made (index, sector, size, factor, theme,
    ETF), or made by Kairos or Metis with the reason they made it (D-94)."""

    __tablename__ = "watchlists"
    __table_args__ = (
        one_of("kind", WATCHLIST_KINDS),
        one_of("category", WATCHLIST_CATEGORIES),
        UniqueConstraint("market_code", "name"),
    )
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    key: Mapped[str | None] = mapped_column(String, nullable=True)  # ready-made lists only
    description: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")  # why Kairos or Metis made it
    rule: Mapped[str] = mapped_column(Text, default="{}")  # JSON: how a live list is rebuilt
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_id"),)
    id: Mapped[int] = _pk()
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    note: Mapped[str] = mapped_column(Text, default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[int] = mapped_column(Integer)


class WorldEvent(Base):
    """A world event Kairos noticed in the news (D-95): which kind of event it is (a scenario
    of the world map), how strong the coverage was, the headlines, and, once the days have
    passed, how markets and sectors actually reacted (that is what it learns from)."""

    __tablename__ = "world_events"
    __table_args__ = (
        one_of("status", ("active", "fading", "measured")),
        Index(None, "scenario", "first_seen"),
    )
    id: Mapped[int] = _pk()
    scenario: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text, default="")
    first_seen: Mapped[int] = mapped_column(Integer)
    last_seen: Mapped[int] = mapped_column(Integer)
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="active")
    headlines: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    reactions: Mapped[str] = mapped_column(Text, default="{}")  # JSON, measured later


class WorldEffect(Base):
    """What a kind of world event did to a market or a sector, ``horizon`` trading days later:
    measured on history (past events) and on live events since (D-95). Running mean and
    variance (Welford), so learning is one update per event."""

    __tablename__ = "world_effects"
    __table_args__ = (
        one_of("source", ("history", "live")),
        UniqueConstraint("scenario", "market_code", "target", "horizon", "source"),
    )
    id: Mapped[int] = _pk()
    scenario: Mapped[str] = mapped_column(String)
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    target: Mapped[str] = mapped_column(String)  # "market" or a sector name
    horizon: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)
    n: Mapped[int] = mapped_column(Integer, default=0)
    mean: Mapped[float] = mapped_column(Float, default=0.0)  # excess return, %
    m2: Mapped[float] = mapped_column(Float, default=0.0)
    hits: Mapped[int] = mapped_column(Integer, default=0)  # moved the way the map expected
    updated_at: Mapped[int] = mapped_column(Integer)


class MoveInvestigation(Base):
    """A sudden move of a market or a sector and what most likely caused it (D-96)."""

    __tablename__ = "move_investigations"
    __table_args__ = (
        one_of("verdict", ("news", "world", "contagion", "unclear")),
        Index(None, "market_code", "created_at"),
    )
    id: Mapped[int] = _pk()
    market_code: Mapped[str] = mapped_column(ForeignKey("markets.code"))
    target: Mapped[str] = mapped_column(String)  # "market" or a sector name
    timeframe: Mapped[str] = mapped_column(String)
    start_ts: Mapped[int] = mapped_column(Integer)
    end_ts: Mapped[int] = mapped_column(Integer)
    move_pct: Mapped[float] = mapped_column(Float)
    zscore: Mapped[float] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON: causes, clues, sectors


class LabTest(Base):
    """One test in a research sprint (D-143): a strategy family's variant on one market,
    with its study, exam and (once opened) vault numbers. Every test is kept, winners and
    losers, so the luck check knows how many were tried."""

    __tablename__ = "lab_tests"
    __table_args__ = (
        one_of("status", ("tested", "finalist", "promoted", "failed_vault", "dropped")),
        Index(None, "sprint", "family"),
    )
    id: Mapped[int] = _pk()
    sprint: Mapped[str] = mapped_column(String)
    family: Mapped[str] = mapped_column(String)
    variant: Mapped[str] = mapped_column(Text, default="{}")  # JSON: the settings tried
    market_code: Mapped[str] = mapped_column(String)
    timeframe: Mapped[str] = mapped_column(String)
    def_hash: Mapped[str] = mapped_column(String)
    definition: Mapped[str] = mapped_column(Text)  # JSON
    symbols: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    start_ms: Mapped[int] = mapped_column(Integer)
    split_ms: Mapped[int] = mapped_column(Integer)
    vault_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    study: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    exam: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    regimes: Mapped[str] = mapped_column(Text, default="{}")  # JSON: study+exam by regime
    vault: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON, once opened
    vault_opened_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="tested")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(Integer)


ALL_TABLES: dict[str, Any] = dict(Base.metadata.tables)
