"""Open/closed status and countdown for each market, shown in the top bar."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.clock import ms_to_dt
from backend.core.types import Market
from backend.markets.calendar import Calendar, next_session, tz

MARKET_NAME = {Market.IN: "India", Market.US: "US"}
TZ_LABEL = {Market.IN: "IST", Market.US: "ET"}


@dataclass(frozen=True)
class MarketStatus:
    market: Market
    is_open: bool
    next_change_ms: int  # when it next opens (if closed) or closes (if open)
    approximate: bool = False


def market_status(cal: Calendar, market: Market, now_ms: int) -> MarketStatus:
    s = next_session(cal, market, now_ms)
    if s is None:
        raise RuntimeError(f"No {market} session found in the next few weeks")
    if now_ms < s.open_ms:
        return MarketStatus(market, False, s.open_ms, cal.approximate)
    return MarketStatus(market, True, s.close_ms, cal.approximate)


def describe(status: MarketStatus, now_ms: int) -> dict[str, object]:
    """JSON for /api/markets/status, with pre-formatted plain-English text."""
    zone = tz(status.market)
    change = ms_to_dt(status.next_change_ms, zone)
    now = ms_to_dt(now_ms, zone)
    when = change.strftime("%H:%M") if change.date() == now.date() else change.strftime("%a %H:%M")
    verb = "Closes" if status.is_open else "Opens"
    return {
        "market": status.market.value,
        "name": MARKET_NAME[status.market],
        "is_open": status.is_open,
        "next_change": status.next_change_ms,
        "next_change_display": f"{verb} {when} {TZ_LABEL[status.market]}",
        "seconds_to_change": max(0, (status.next_change_ms - now_ms) // 1000),
        "approximate": status.approximate,
    }
