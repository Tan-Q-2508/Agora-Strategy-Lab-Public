"""The market-data interface (docs/DATA_SOURCES.md §1).

Yahoo, NSE bhavcopy, Stooq and the fake source all implement this, so the cache manager
and the engine never know (or care) where bars came from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.core.types import Bar, CorporateAction, Market, Timeframe


class DataSource(Protocol):
    name: str

    def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str | None:
        """This source's name for an instrument, or None if it doesn't carry it."""
        ...

    def window_start_ms(self, timeframe: Timeframe) -> int | None:
        """Oldest bar the source can still serve for ``timeframe`` (None = no limit)."""
        ...

    def supports(self, market: Market, timeframe: Timeframe) -> bool: ...

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        """Bars whose open time is in ``[start, end)``, oldest first."""
        ...

    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]: ...

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        """Most recent bars per symbol; the still-forming bar has ``is_final=False``."""
        ...
