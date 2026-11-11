"""Stooq: free daily CSVs, the US backup when Yahoo's daily history fails.

Stooq's prices are adjusted for splits *and* dividends, so bars from here are close but
not exact; they are only used to fill gaps and are marked ``source = "stooq"`` so the
honesty panel can say so. The split factor is re-applied by the cache manager.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from datetime import date, datetime

import httpx

from backend.core.clock import Clock, utc_to_ms
from backend.core.types import Bar, CorporateAction, Market, Timeframe
from backend.data.errors import Blocked, EmptyResponse, NotFound, RateLimited, SourceError
from backend.data.throttle import Throttle
from backend.markets.calendar import Calendar, daily_ts, local_date

URL = "https://stooq.com/q/d/l/"

# (stooq symbol, first day, last day) → CSV text. Swapped in tests.
Downloader = Callable[[str, date, date], str]


def _http_download(symbol: str, d1: date, d2: date) -> str:
    params = {"s": symbol, "i": "d", "d1": f"{d1:%Y%m%d}", "d2": f"{d2:%Y%m%d}"}
    try:
        resp = httpx.get(URL, params=params, timeout=20.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SourceError("Stooq didn't answer.", detail=str(exc)) from exc
    if resp.status_code == 429:
        raise RateLimited("Stooq is limiting requests right now.")
    if _is_page(resp.text):
        parse_csv(resp.text)  # a web page instead of prices: raises its plain message
    if resp.status_code != 200:
        raise SourceError("Stooq returned an error.", detail=f"HTTP {resp.status_code}")
    return resp.text


def _is_page(text: str) -> bool:
    head = text.lstrip()[:300].lower()
    return head.startswith("<") and ("<html" in head or "<meta" in head or "<title" in head)


def parse_csv(text: str) -> list[tuple[date, float, float, float, float, float]]:
    """Rows of (day, open, high, low, close, volume). Stooq answers "No data" for unknown
    symbols and a daily-limit message when overused; both raise."""
    head = text.strip()[:200].lower()
    if head.startswith("no data") or not head:
        raise NotFound("Stooq has no prices for that symbol.", detail=text[:200])
    if _is_page(text):
        # By October 2026 Stooq answers automatic downloads with a browser check or a "page
        # not found" page. Agora doesn't try to get around that, so the US backup is simply
        # unavailable (Yahoo stays the source).
        raise Blocked(
            "Stooq no longer allows automatic downloads (it asks for a browser check), so "
            "Agora can't use it as a backup. Yahoo Finance is still used for US prices.",
            detail=text[:200],
        )
    if "exceeded" in head or "limit" in head:
        raise RateLimited("Stooq's daily download limit was reached.", detail=text[:200])
    out: list[tuple[date, float, float, float, float, float]] = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            out.append(
                (
                    date.fromisoformat(r["Date"]),
                    float(r["Open"]),
                    float(r["High"]),
                    float(r["Low"]),
                    float(r["Close"]),
                    float(r.get("Volume") or 0.0),
                )
            )
        except (KeyError, ValueError):
            continue
    return out


class StooqSource:
    name = "stooq"
    returns_adjusted = True  # the cache manager converts back to raw prices

    def __init__(
        self,
        clock: Clock,
        calendar: Calendar,
        *,
        download: Downloader = _http_download,
        throttle: Throttle | None = None,
    ) -> None:
        self.clock = clock
        self.calendar = calendar
        self._download = download
        self.throttle = throttle or Throttle(1.5)

    def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str | None:
        if market is not Market.US:
            return None
        return f"{symbol.lower().replace('.', '-')}.us"

    def window_start_ms(self, timeframe: Timeframe) -> int | None:
        return None

    def supports(self, market: Market, timeframe: Timeframe) -> bool:
        return market is Market.US and timeframe is Timeframe.D1

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        if timeframe is not Timeframe.D1:
            return []
        lo, hi = utc_to_ms(start), utc_to_ms(end)
        self.throttle.wait()
        text = self._download(symbol, local_date(Market.US, lo), local_date(Market.US, hi))
        now = self.clock.now_ms()
        bars = []
        for day, o, h, low, c, v in parse_csv(text):
            ts = daily_ts(self.calendar, Market.US, day)
            if lo <= ts < hi and ts < now:
                bars.append(Bar(ts, o, h, low, c, v, "stooq"))
        if not bars:
            raise EmptyResponse(f"Stooq had no prices for {symbol} in that period.")
        return bars

    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]:
        return []

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        return {s: [] for s in symbols}  # backup for history only, never for live polling
