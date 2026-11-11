"""Reference data every fresh database needs: markets, symbols, universes, cost tables.

Seeding is idempotent: it only inserts rows that are missing (matched on their natural
key), so the launcher can run it on every start and a later version can add rows without
touching anything the user changed.

Charge rates follow D-09: each is an effective-dated row with its source URL. Rows with
``verified_at`` set were checked against a published source on the date in
``VERIFIED_ON``; the others are best-known values that Phase 4.3 must verify and extend
with earlier history.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import Clock
from backend.db.models import (
    BrokerageProfile,
    ChargeSchedule,
    Instrument,
    MarketRow,
    SlippageProfile,
    Universe,
    UniverseMember,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"
NIFTY50_CSV = SEED_DIR / "nifty50_constituents.csv"
NIFTY50_SOURCE = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
NIFTY50_AS_OF = date(2026, 10, 21)
VERIFIED_ON = date(2026, 10, 21)

US_WATCHLIST: tuple[tuple[str, str, str], ...] = (
    ("SPY", "SPDR S&P 500 ETF Trust", "etf"),
    ("QQQ", "Invesco QQQ Trust", "etf"),
    ("AAPL", "Apple Inc.", "equity"),
    ("MSFT", "Microsoft Corporation", "equity"),
    ("NVDA", "NVIDIA Corporation", "equity"),
    ("AMZN", "Amazon.com, Inc.", "equity"),
    ("GOOGL", "Alphabet Inc. (Class A)", "equity"),
    ("META", "Meta Platforms, Inc.", "equity"),
    ("TSLA", "Tesla, Inc.", "equity"),
    ("JPM", "JPMorgan Chase & Co.", "equity"),
)

TZ = {"IN": ZoneInfo("Asia/Kolkata"), "US": ZoneInfo("America/New_York")}


def day_ms(market: str, d: date) -> int:
    """Midnight of ``d`` in the market's timezone, as UTC ms (used for effective dates)."""
    return int(datetime.combine(d, time(0, 0), TZ[market]).timestamp() * 1000)


@dataclass(frozen=True)
class Rate:
    market: str
    charge: str
    product: str
    side: str
    rate_type: str
    rate: float
    effective_from: date
    effective_to: date | None
    source_url: str
    verified: bool = False
    cap: float | None = None


ZERODHA = "https://zerodha.com/charges"
Z_2023 = (
    "https://zerodha.com/marketintel/bulletin/347967/"
    "revision-in-transaction-charges-and-stt-from-1st-april-2023"
)
Z_2024_APR = "https://zerodha.com/marketintel/bulletin/373933/revision-in-nse-transaction-charges-from-april-1-2024"
Z_2024_OCT = (
    "https://zerodha.com/marketintel/bulletin/391488/"
    "revision-in-transactions-charges-from-1st-october-2024"
)
NSE_2021 = "https://archives.nseindia.com/content/circulars/FA46730.pdf"
NSE_2026 = "https://nsearchives.nseindia.com/content/circulars/FA73061.pdf"
SEC_ADV = "https://www.sec.gov/rules-regulations/fee-rate-advisories"
SEC = {
    2016: "https://www.sec.gov/news/pressrelease/2016-206.html",
    2017: "https://www.sec.gov/news/press-release/2017-111",
    2018: "https://www.sec.gov/news/press-release/2018-67",
    2019: "https://www.sec.gov/news/press-release/2019-30",
    2020: "https://www.finra.org/rules-guidance/notices/information-notice-021420",
    2021: "https://www.sec.gov/news/press-release/2021-36",
    2022: "https://www.sec.gov/news/press-release/2022-60",
    2023: "https://www.sec.gov/newsroom/press-releases/2023-41",
    2025: "https://www.sec.gov/rules-regulations/fee-rate-advisories/2025-2",
    2026: "https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2",
}
FINRA_SCHEDULE = (
    "https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule"
)
FINRA_PAUSE = "https://www.finra.org/sites/default/files/2026-09/SR-FINRA-2026-021.pdf"
FINRA_RULE = (
    "https://www.finra.org/rules-guidance/rulebooks/corporate-organization/"
    "section-1-member-regulatory-fees"
)
D2016 = date(2016, 1, 1)


def _d(y: int, m: int, d: int) -> date:
    return date(y, m, d)


# Verified 2026-10-21 against the listed sources (D-23, D-38). Rows with verified=False
# are best-known values whose history could not be confirmed from a primary source.
RATES: tuple[Rate, ...] = (
    # --- India: STT on cash equity (unchanged since 2013; Budgets 2024/25 changed F&O only)
    Rate("IN", "stt", "intraday", "sell", "percent", 0.025, D2016, None, ZERODHA, verified=True),
    Rate("IN", "stt", "delivery", "both", "percent", 0.1, D2016, None, ZERODHA, verified=True),
    # --- India: NSE transaction charge (top-slab rate brokers pass on), each side
    Rate(
        "IN",
        "exchange_txn",
        "any",
        "both",
        "percent",
        0.00325,
        D2016,
        _d(2020, 12, 31),
        NSE_2021,
        verified=True,
    ),
    Rate(
        "IN",
        "exchange_txn",
        "any",
        "both",
        "percent",
        0.00345,
        _d(2021, 1, 1),
        _d(2023, 3, 31),
        NSE_2021,
        verified=True,
    ),
    Rate(
        "IN",
        "exchange_txn",
        "any",
        "both",
        "percent",
        0.00325,
        _d(2023, 4, 1),
        _d(2024, 3, 31),
        Z_2023,
        verified=True,
    ),
    Rate(
        "IN",
        "exchange_txn",
        "any",
        "both",
        "percent",
        0.00322,
        _d(2024, 4, 1),
        _d(2024, 9, 30),
        Z_2024_APR,
        verified=True,
    ),
    Rate(
        "IN",
        "exchange_txn",
        "any",
        "both",
        "percent",
        0.00297,
        _d(2024, 10, 1),
        _d(2026, 2, 28),
        Z_2024_OCT,
        verified=True,
    ),
    Rate(
        "IN",
        "exchange_txn",
        "any",
        "both",
        "percent",
        0.00307,
        _d(2026, 3, 1),
        None,
        NSE_2026,
        verified=True,
    ),
    # --- India: SEBI turnover fee (₹10/crore today; earlier history not confirmed)
    Rate("IN", "sebi_fee", "any", "both", "per_crore", 10.0, D2016, None, ZERODHA),
    # --- India: stamp duty on buys. Uniform national rates from 1 Jul 2020; before that it
    # varied by state, so the earlier rows reuse today's rates as an approximation.
    Rate("IN", "stamp_duty", "intraday", "buy", "percent", 0.003, D2016, _d(2020, 6, 30), ZERODHA),
    Rate(
        "IN",
        "stamp_duty",
        "intraday",
        "buy",
        "percent",
        0.003,
        _d(2020, 7, 1),
        None,
        ZERODHA,
        verified=True,
    ),
    Rate("IN", "stamp_duty", "delivery", "buy", "percent", 0.015, D2016, _d(2020, 6, 30), ZERODHA),
    Rate(
        "IN",
        "stamp_duty",
        "delivery",
        "buy",
        "percent",
        0.015,
        _d(2020, 7, 1),
        None,
        ZERODHA,
        verified=True,
    ),
    # --- India: indirect tax on brokerage + exchange charge + SEBI fee (and DP charge).
    # Service tax 14.5% → 15% (Jun 2016) → GST 18% (Jul 2017).
    Rate("IN", "gst", "any", "both", "percent", 14.5, D2016, _d(2016, 5, 31), ZERODHA),
    Rate("IN", "gst", "any", "both", "percent", 15.0, _d(2016, 6, 1), _d(2017, 6, 30), ZERODHA),
    Rate("IN", "gst", "any", "both", "percent", 18.0, _d(2017, 7, 1), None, ZERODHA, verified=True),
    # --- India: depository charge per scrip per sell day (delivery), before GST:
    # ₹3.50 CDSL + ₹9.50 broker today. Earlier amounts not confirmed.
    Rate("IN", "dp_charge", "delivery", "sell", "flat_per_scrip_day", 13.0, D2016, None, ZERODHA),
    # --- US: SEC Section 31 fee on sells, per $1M of proceeds
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        21.80,
        D2016,
        _d(2017, 7, 3),
        SEC[2016],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        23.10,
        _d(2017, 7, 4),
        _d(2018, 5, 21),
        SEC[2017],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        13.00,
        _d(2018, 5, 22),
        _d(2019, 4, 15),
        SEC[2018],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        20.70,
        _d(2019, 4, 16),
        _d(2020, 2, 17),
        SEC[2019],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        22.10,
        _d(2020, 2, 18),
        _d(2021, 2, 24),
        SEC[2020],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        5.10,
        _d(2021, 2, 25),
        _d(2022, 5, 13),
        SEC[2021],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        22.90,
        _d(2022, 5, 14),
        _d(2023, 2, 26),
        SEC[2022],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        8.00,
        _d(2023, 2, 27),
        _d(2024, 5, 21),
        SEC[2023],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        27.80,
        _d(2024, 5, 22),
        _d(2025, 5, 13),
        SEC[2025],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        0.0,
        _d(2025, 5, 14),
        _d(2026, 4, 3),
        SEC[2025],
        verified=True,
    ),
    Rate(
        "US",
        "sec_fee",
        "cash",
        "sell",
        "per_million",
        20.60,
        _d(2026, 4, 4),
        None,
        SEC[2026],
        verified=True,
    ),
    # --- US: FINRA Trading Activity Fee on sells, per share with a per-trade cap.
    # 2016-2023 values are best-known (not confirmed); TAF paused Oct-Dec 2026.
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.000119,
        D2016,
        _d(2021, 12, 31),
        FINRA_RULE,
        cap=5.95,
    ),
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.000130,
        _d(2022, 1, 1),
        _d(2022, 12, 31),
        FINRA_RULE,
        cap=6.49,
    ),
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.000145,
        _d(2023, 1, 1),
        _d(2023, 12, 31),
        FINRA_RULE,
        cap=7.27,
    ),
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.000166,
        _d(2024, 1, 1),
        _d(2025, 12, 31),
        FINRA_SCHEDULE,
        verified=True,
        cap=8.30,
    ),
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.000195,
        _d(2026, 1, 1),
        _d(2026, 9, 30),
        FINRA_SCHEDULE,
        verified=True,
        cap=9.79,
    ),
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.0,
        _d(2026, 10, 1),
        _d(2026, 12, 31),
        FINRA_PAUSE,
        verified=True,
        cap=0.0,
    ),
    Rate(
        "US",
        "finra_taf",
        "cash",
        "sell",
        "per_share",
        0.000195,
        _d(2027, 1, 1),
        None,
        FINRA_PAUSE,
        verified=True,
        cap=9.79,
    ),
)

BROKERAGE: tuple[tuple[str, str, dict[str, object], bool], ...] = (
    (
        "IN",
        "Discount broker (₹20 cap)",
        {
            "intraday": {"percent": 0.03, "cap": 20.0},
            "delivery": {"flat": 0.0},
        },
        True,
    ),
    ("IN", "Zero brokerage", {"intraday": {"flat": 0.0}, "delivery": {"flat": 0.0}}, False),
    (
        "IN",
        "Full-service (0.3% delivery / 0.03% intraday)",
        {
            "intraday": {"percent": 0.03},
            "delivery": {"percent": 0.3},
        },
        False,
    ),
    ("US", "US $0 commission", {"cash": {"flat": 0.0}}, True),
)

SLIPPAGE: tuple[tuple[str, str, float], ...] = (
    ("IN", "Nifty 50 stocks (5 bps)", 5.0),
    ("US", "Large caps and ETFs (2 bps)", 2.0),
)


def _get_or_add_market(s: Session) -> None:
    for code, name, cur, tz, cal in (
        ("IN", "India (NSE)", "INR", "Asia/Kolkata", "NSE"),
        ("US", "United States", "USD", "America/New_York", "NYSE"),
    ):
        if s.get(MarketRow, code) is None:
            s.add(MarketRow(code=code, name=name, currency=cur, timezone=tz, calendar_name=cal))
    s.flush()


def _instrument(
    s: Session,
    market: str,
    symbol: str,
    yahoo: str,
    name: str,
    kind: str,
    isin: str | None,
    now: int,
) -> Instrument:
    row = s.scalar(
        select(Instrument).where(Instrument.market_code == market, Instrument.symbol == symbol)
    )
    if row is None:
        row = Instrument(
            market_code=market,
            symbol=symbol,
            yahoo_symbol=yahoo,
            name=name,
            instrument_type=kind,
            isin=isin,
            is_active=1,
            added_at=now,
        )
        s.add(row)
        s.flush()
    return row


def _universe(s: Session, market: str, name: str, description: str) -> Universe:
    row = s.scalar(select(Universe).where(Universe.name == name))
    if row is None:
        row = Universe(market_code=market, name=name, description=description)
        s.add(row)
        s.flush()
    return row


def _member(s: Session, universe: Universe, inst: Instrument, valid_from: int, source: str) -> None:
    exists = s.scalar(
        select(UniverseMember.id).where(
            UniverseMember.universe_id == universe.id, UniverseMember.instrument_id == inst.id
        )
    )
    if exists is None:
        s.add(
            UniverseMember(
                universe_id=universe.id,
                instrument_id=inst.id,
                valid_from=valid_from,
                valid_to=None,
                source=source,
            )
        )


def read_nifty50() -> list[dict[str, str]]:
    with NIFTY50_CSV.open(newline="", encoding="utf-8") as fh:
        return [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def seed(s: Session, clock: Clock) -> None:
    now = clock.now_ms()
    _get_or_add_market(s)

    # India: Nifty 50 constituents (today's list; survivorship badge until history exists)
    nifty = _universe(s, "IN", "NIFTY50", "Nifty 50 index constituents (NSE)")
    as_of = day_ms("IN", NIFTY50_AS_OF)
    source = f"{NIFTY50_SOURCE} (fetched {NIFTY50_AS_OF.isoformat()})"
    for row in read_nifty50():
        inst = _instrument(
            s,
            "IN",
            row["Symbol"],
            f"{row['Symbol']}.NS",
            row["Company Name"],
            "equity",
            row["ISIN Code"] or None,
            now,
        )
        _member(s, nifty, inst, as_of, source)
    _instrument(s, "IN", "NIFTY50", "^NSEI", "Nifty 50 index", "index", None, now)

    # US: default watchlist (SPY doubles as the benchmark)
    watch = _universe(s, "US", "US_WATCHLIST", "Your US stocks and ETFs")
    for sym, name, kind in US_WATCHLIST:
        inst = _instrument(s, "US", sym, sym, name, kind, None, now)
        _member(s, watch, inst, day_ms("US", NIFTY50_AS_OF), "default watchlist")

    for market, name, rules, default in BROKERAGE:
        if (
            s.scalar(
                select(BrokerageProfile.id).where(
                    BrokerageProfile.market_code == market, BrokerageProfile.name == name
                )
            )
            is None
        ):
            s.add(
                BrokerageProfile(
                    market_code=market,
                    name=name,
                    rules=json.dumps(rules, sort_keys=True),
                    is_default=int(default),
                )
            )

    for market, name, bps in SLIPPAGE:
        if (
            s.scalar(
                select(SlippageProfile.id).where(
                    SlippageProfile.market_code == market, SlippageProfile.name == name
                )
            )
            is None
        ):
            s.add(SlippageProfile(market_code=market, name=name, bps=bps, is_default=1))

    _sync_charges(s)
    s.flush()


def _sync_charges(s: Session) -> None:
    """Make ``charge_schedules`` match ``RATES`` exactly. Charge rates are reference data
    (not user data), so corrected rows replace old ones when a new version ships."""
    verified_ms = day_ms("IN", VERIFIED_ON)
    wanted: dict[tuple[str, str, str, str, int], Rate] = {}
    for r in RATES:
        wanted[(r.market, r.charge, r.product, r.side, day_ms(r.market, r.effective_from))] = r
    existing = {
        (row.market_code, row.charge, row.product, row.side, row.effective_from): row
        for row in s.scalars(select(ChargeSchedule))
    }
    for key, row in existing.items():
        if key not in wanted:
            s.delete(row)
    for key, r in wanted.items():
        # effective_to includes that whole day: store the ms before the next midnight
        # (computed per day so DST-change days stay correct).
        end = day_ms(r.market, r.effective_to + timedelta(days=1)) - 1 if r.effective_to else None
        values = {
            "rate_type": r.rate_type,
            "rate": r.rate,
            "cap": r.cap,
            "effective_to": end,
            "source_url": r.source_url,
            "verified_at": verified_ms if r.verified else None,
        }
        current = existing.get(key)
        if current is None:
            s.add(
                ChargeSchedule(
                    market_code=r.market,
                    charge=r.charge,
                    product=r.product,
                    side=r.side,
                    effective_from=key[4],
                    **values,
                )
            )
        else:
            for k, v in values.items():
                setattr(current, k, v)
