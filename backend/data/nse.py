"""NSE bhavcopy: official end-of-day files, the India backup for daily bars.

One zip per trading day. Two layouts exist, each parsed by its own small function so a
future format change touches one place (DATA_SOURCES §3):
- "UDiFF" (from 8 July 2024): ``BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip``
- legacy (before that): ``cmDDMONYYYYbhav.csv.zip``

Bhavcopy prices are raw (as traded), which is exactly what we store; the split factor is
added by the cache manager from Yahoo's split list. Only the ``EQ`` series is used.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Callable
from datetime import date, datetime, timedelta

import httpx

from backend.core.clock import Clock, utc_to_ms
from backend.core.types import Bar, CorporateAction, Market, Timeframe
from backend.data.errors import EmptyResponse, NotFound, RateLimited, SourceError
from backend.data.throttle import Throttle
from backend.markets.calendar import Calendar, daily_ts, local_date

UDIFF_FROM = date(2024, 7, 8)
BASE = "https://nsearchives.nseindia.com/content"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
# One file per day, so the backup fills gaps of recent days only (D-184: for four NSE test
# symbols Yahoo doesn't know, every Indian top-up asked for 400 day files each, held all four
# download threads for hours, and left most Indian stocks' prices days old).
MAX_DAYS_PER_CALL = 10

# url → zip bytes, or None when NSE has no file for that day. Swapped in tests.
Downloader = Callable[[str], bytes | None]


def url_for(day: date) -> str:
    if day >= UDIFF_FROM:
        return f"{BASE}/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    mon = day.strftime("%b").upper()
    return f"{BASE}/historical/EQUITIES/{day:%Y}/{mon}/cm{day:%d}{mon}{day:%Y}bhav.csv.zip"


def _csv_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        return zf.read(name).decode("utf-8", errors="replace")


def parse_udiff(text: str) -> dict[str, tuple[float, float, float, float, float]]:
    """symbol → (open, high, low, close, volume) for the EQ series."""
    out: dict[str, tuple[float, float, float, float, float]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("SctySrs") or "").strip() != "EQ":
            continue
        out[r["TckrSymb"].strip()] = (
            float(r["OpnPric"]),
            float(r["HghPric"]),
            float(r["LwPric"]),
            float(r["ClsPric"]),
            float(r["TtlTradgVol"]),
        )
    return out


def parse_legacy(text: str) -> dict[str, tuple[float, float, float, float, float]]:
    out: dict[str, tuple[float, float, float, float, float]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("SERIES") != "EQ":
            continue
        out[r["SYMBOL"]] = (
            float(r["OPEN"]),
            float(r["HIGH"]),
            float(r["LOW"]),
            float(r["CLOSE"]),
            float(r["TOTTRDQTY"]),
        )
    return out


def _http_download(url: str) -> bytes | None:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SourceError("NSE's website didn't answer.", detail=f"{url}: {exc}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code in (403, 429):
        raise RateLimited(
            "NSE is refusing requests right now.", detail=f"{url}: {resp.status_code}"
        )
    if resp.status_code != 200:
        raise SourceError("NSE's website returned an error.", detail=f"{url}: {resp.status_code}")
    return resp.content


class NseBhavcopySource:
    name = "nse"

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
        self._day_cache: dict[date, dict[str, tuple[float, float, float, float, float]]] = {}

    def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str | None:
        if market is not Market.IN or yahoo_symbol.startswith("^"):
            return None  # bhavcopy has stocks only, not the index
        return symbol

    def window_start_ms(self, timeframe: Timeframe) -> int | None:
        return None

    def supports(self, market: Market, timeframe: Timeframe) -> bool:
        return market is Market.IN and timeframe is Timeframe.D1

    def day_table(self, day: date) -> dict[str, tuple[float, float, float, float, float]] | None:
        if day in self._day_cache:
            return self._day_cache[day]
        self.throttle.wait()
        blob = self._download(url_for(day))
        if blob is None:
            return None
        text = _csv_text(blob)
        table = parse_udiff(text) if day >= UDIFF_FROM else parse_legacy(text)
        if len(self._day_cache) > 64:
            self._day_cache.clear()
        self._day_cache[day] = table
        return table

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        if timeframe is not Timeframe.D1:
            return []
        lo, hi = utc_to_ms(start), utc_to_ms(end)
        now = self.clock.now_ms()
        days = [
            s
            for s in self.calendar.sessions(
                Market.IN, local_date(Market.IN, lo), local_date(Market.IN, hi)
            )
            if lo <= s.open_ms < hi and s.close_ms <= now
        ]
        if len(days) > MAX_DAYS_PER_CALL:
            days = days[-MAX_DAYS_PER_CALL:]
        bars: list[Bar] = []
        files = 0
        for s in days:
            table = self.day_table(s.day)
            if table is None:
                continue
            files += 1
            row = table.get(symbol)
            if row is None:
                continue
            o, h, low, c, v = row
            bars.append(Bar(daily_ts(self.calendar, Market.IN, s.day), o, h, low, c, v, "nse"))
        if not bars:
            if files:
                raise NotFound(f"NSE's files don't list {symbol}.")
            raise EmptyResponse(f"NSE had no prices for {symbol} in that period.")
        return bars

    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]:
        return []  # splits and dividends come from Yahoo

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        now = self.clock.now_ms()
        today = local_date(Market.IN, now)
        start = datetime.combine(today - timedelta(days=10), datetime.min.time()).astimezone()
        end = datetime.fromtimestamp(now / 1000).astimezone()
        out: dict[str, list[Bar]] = {}
        for sym in symbols:
            try:
                out[sym] = self.fetch_bars(sym, Timeframe.D1, start, end)[-5:]
            except SourceError:
                out[sym] = []
        return out
