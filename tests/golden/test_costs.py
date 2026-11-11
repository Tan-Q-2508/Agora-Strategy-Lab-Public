"""Golden cost tests (COST_MODEL.md §6), against the seeded charge schedule. Each case
writes out its arithmetic; rounding rules are in backend/costs/model.py."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from backend.costs.model import CostModel, slipped
from backend.costs.schedule import ChargeTable
from backend.db.engine import Database
from backend.db.models import BrokerageProfile

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")


def at(d: str, tz: ZoneInfo, hh: int = 10) -> int:
    return int(datetime.fromisoformat(d).replace(hour=hh, tzinfo=tz).timestamp() * 1000)


def model(db: Database, market: str, product: str, profile: str) -> CostModel:
    with db.session() as s:
        rules = s.scalar(select(BrokerageProfile.rules).where(BrokerageProfile.name == profile))
        table = ChargeTable.load(s, market)
    assert rules is not None
    return CostModel.from_profile_json(market, product, rules, table)


def D(x: str) -> Decimal:
    return Decimal(x)


def test_india_intraday_round_trip(db: Database) -> None:
    m = model(db, "IN", "intraday", "Discount broker (₹20 cap)")
    t = at("2025-06-02", IST)
    buy = m.order("buy", 100, 1000.0, t)
    # turnover ₹1,00,000. brokerage min(0.03% = 30, cap 20) = 20.00; STT none on intraday buys
    # NSE 0.00297% = 2.97; SEBI ₹10/crore = 0.10; stamp 0.003% = 3.00
    # GST 18% × (20 + 2.97 + 0.10 = 23.07) = 4.1526 → 4.15.   total 30.22
    assert buy.items == {
        "brokerage": D("20.00"),
        "stt": D("0"),
        "exchange_txn": D("2.97"),
        "sebi_fee": D("0.10"),
        "stamp_duty": D("3.00"),
        "dp_charge": D("0"),
        "gst": D("4.15"),
    }
    assert buy.total == D("30.22")
    sell = m.order("sell", 100, 1010.0, t)
    # turnover ₹1,01,000. brokerage 20.00; STT 0.025% = 25.25 → ₹25 (nearest rupee)
    # NSE 2.9997 → 3.00; SEBI 0.101 → 0.10; no stamp on sells
    # GST 18% × (20 + 3.00 + 0.10 = 23.10) = 4.158 → 4.16.   total 52.26
    assert sell.items["stt"] == D("25") and sell.items["gst"] == D("4.16")
    assert sell.total == D("52.26")
    # round trip: gross +₹1,000, charges ₹82.48 → net ₹917.52
    assert 1000 - (buy.total + sell.total) == D("917.52")


def test_india_delivery_round_trip_with_dp(db: Database) -> None:
    m = model(db, "IN", "delivery", "Discount broker (₹20 cap)")
    buy = m.order("buy", 50, 2500.0, at("2025-06-02", IST))
    # turnover ₹1,25,000. brokerage 0; STT 0.1% = 125; NSE 3.7125 → 3.71; SEBI 0.125 → 0.13
    # stamp 0.015% = 18.75; GST 18% × (0 + 3.71 + 0.13) = 0.6912 → 0.69.   total 148.28
    assert buy.total == D("148.28")
    sell = m.order("sell", 50, 2600.0, at("2025-06-10", IST))
    # turnover ₹1,30,000. STT 130; NSE 3.861 → 3.86; SEBI 0.13; DP ₹13.00 per scrip per day
    # GST 18% × (3.86 + 0.13 + 13.00 = 16.99) = 3.0582 → 3.06.   total 150.05
    assert sell.items["dp_charge"] == D("13.00")
    assert sell.total == D("150.05")
    second = m.order("sell", 1, 2600.0, at("2025-06-10", IST), first_sell_of_day=False)
    assert second.items["dp_charge"] == D("0")


def test_india_rate_change_is_applied_by_trade_date(db: Database) -> None:
    m = model(db, "IN", "intraday", "Discount broker (₹20 cap)")
    before = m.order("buy", 100, 1000.0, at("2024-09-30", IST))
    after = m.order("buy", 100, 1000.0, at("2024-10-01", IST))
    # NSE charge fell from 0.00322% to 0.00297% on 1 Oct 2024: 3.22 → 2.97 on ₹1,00,000
    assert before.items["exchange_txn"] == D("3.22")
    assert after.items["exchange_txn"] == D("2.97")
    # …and was 0.00345% during 2021–March 2023
    assert m.order("buy", 100, 1000.0, at("2022-06-01", IST)).items["exchange_txn"] == D("3.45")


def test_india_older_years_use_service_tax(db: Database) -> None:
    m = model(db, "IN", "intraday", "Discount broker (₹20 cap)")
    b = m.order("buy", 100, 1000.0, at("2016-03-01", IST))
    # 14.5% × (20 + 3.25 + 0.10 = 23.35) = 3.38575 → 3.39
    assert b.items["gst"] == D("3.39")


def test_us_round_trip(db: Database) -> None:
    m = model(db, "US", "cash", "US $0 commission")
    buy = m.order("buy", 100, 200.0, at("2026-06-01", ET))
    assert buy.total == D("0")  # $0 commission, regulatory fees are sell-only
    sell = m.order("sell", 100, 205.0, at("2026-06-01", ET))
    # SEC $20.60 per $1M × $20,500 = $0.4223 → rounded up to $0.43
    # FINRA $0.000195 × 100 shares = $0.0195 → $0.02 (cap $9.79 not reached)
    assert sell.items == {"commission": D("0.00"), "sec_fee": D("0.43"), "finra_taf": D("0.02")}
    assert sell.total == D("0.45")
    # Round trip: +$500 gross − $0.45 = $499.55
    assert 500 - (buy.total + sell.total) == D("499.55")


def test_us_fee_pause_and_cap(db: Database) -> None:
    m = model(db, "US", "cash", "US $0 commission")
    paused = m.order("sell", 100, 205.0, at("2026-11-02", ET))
    assert paused.items["finra_taf"] == D("0") and paused.items["sec_fee"] == D("0.43")
    big = m.order("sell", 100_000, 10.0, at("2026-06-01", ET))
    # 100,000 × $0.000195 = $19.50 → capped at $9.79
    assert big.items["finra_taf"] == D("9.79")
    zero_sec = m.order("sell", 100, 205.0, at("2025-08-01", ET))
    assert zero_sec.items["sec_fee"] == D("0.00")  # SEC fee was $0 from 14 May 2025


@pytest.mark.parametrize(
    ("price", "paying", "expected"),
    [(100.0, True, 100.05), (100.0, False, 99.95)],  # 5 bps
)
def test_slippage_works_against_the_trader(price: float, paying: bool, expected: float) -> None:
    # buys (long entries, short covers) pay more; sells (long exits, short entries) get less
    assert slipped(price, 5, paying=paying) == pytest.approx(expected)
