"""Dates before 1970 must convert on every OS (Windows ``fromtimestamp`` raises for them)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from backend.core.clock import ms_to_dt


def test_dividend_from_1962_converts() -> None:
    ms = -237_513_600_000  # 1962-06-23 00:00 UTC, like IBM's oldest dividends on Yahoo
    assert ms_to_dt(ms, ZoneInfo("America/New_York")).strftime("%Y-%m-%d") == "1962-06-22"


def test_matches_fromtimestamp_after_1970() -> None:
    from datetime import UTC, datetime

    ms = 1_761_300_000_123
    assert ms_to_dt(ms, UTC) == datetime.fromtimestamp(ms / 1000, UTC)
