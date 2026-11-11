"""Canonical market-data types shared by every data source, the engine and the UI API.

Times are UTC epoch milliseconds. A bar's ``ts`` is when the bar OPENS; for daily bars
that is the session open (see D-20), so "bar end" is always ``ts`` + its duration or the
session close, whichever comes first.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Market(StrEnum):
    IN = "IN"
    US = "US"


MARKET_TZ: dict[Market, str] = {Market.IN: "Asia/Kolkata", Market.US: "America/New_York"}


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"

    @property
    def minutes(self) -> int:
        return {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}[self.value]

    @property
    def is_intraday(self) -> bool:
        return self is not Timeframe.D1


@dataclass(frozen=True, slots=True)
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    is_final: bool = True
    split_factor: float = 1.0  # multiply raw prices by this to get today's split-adjusted terms


@dataclass(frozen=True, slots=True)
class CorporateAction:
    ex_date: int  # UTC ms of the ex-date's session open
    kind: str  # "split" | "dividend"
    ratio: float | None = None  # 2.0 means 2-for-1
    amount: float | None = None  # cash per share, in the market's currency
