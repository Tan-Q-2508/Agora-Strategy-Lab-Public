"""Real-network checks. Skipped by default; Settings → Diagnostics runs them on the laptop.

They confirm that Yahoo, NSE and Stooq still answer in the formats Agora's parsers expect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.core.clock import SystemClock
from backend.core.types import Timeframe
from backend.data.errors import SourceError
from backend.data.nse import NseBhavcopySource
from backend.data.stooq import StooqSource
from backend.data.yahoo import YahooSource
from backend.markets.calendar import ExchangeCalendar

pytestmark = pytest.mark.live
CAL = ExchangeCalendar()


def _range(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    return end - timedelta(days=days), end


def test_yahoo_daily_india_and_us() -> None:
    src = YahooSource(SystemClock(), CAL)
    for sym in ("RELIANCE.NS", "^NSEI", "SPY"):
        bars = src.fetch_bars(sym, Timeframe.D1, *_range(20))
        assert len(bars) >= 5, sym
        assert all(b.high >= b.low > 0 for b in bars)


def test_yahoo_intraday() -> None:
    bars = YahooSource(SystemClock(), CAL).fetch_bars("AAPL", Timeframe.M5, *_range(7))
    assert len(bars) > 50


def test_nse_bhavcopy() -> None:
    bars = NseBhavcopySource(SystemClock(), CAL).fetch_bars("RELIANCE", Timeframe.D1, *_range(10))
    assert bars and bars[-1].close > 0


def test_stooq_daily() -> None:
    try:
        bars = StooqSource(SystemClock(), CAL).fetch_bars("spy.us", Timeframe.D1, *_range(20))
    except SourceError as exc:
        if "browser check" in exc.message:  # see backend/data/stooq.py
            pytest.skip(exc.message)  # Stooq's bot check (2026); Yahoo stays the US source
        raise
    assert len(bars) >= 5


def test_yahoo_latest_bars_for_paper_trading() -> None:
    """The live feed's batch call: the newest candles, the still-forming one marked."""
    src = YahooSource(SystemClock(), CAL)
    got = src.latest_bars(["RELIANCE.NS", "SPY"], Timeframe.M1)
    for sym, bars in got.items():
        assert bars, sym
        assert [b.ts for b in bars] == sorted(b.ts for b in bars)
        assert sum(1 for b in bars if not b.is_final) <= 1
