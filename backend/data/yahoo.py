"""Yahoo Finance via ``yfinance``: the primary source for daily, intraday and live bars.

Yahoo is unofficial and rate-limits without published thresholds (D-03), so this module
only translates: it spaces requests with a ``Throttle`` and turns Yahoo's quirks into the
canonical ``Bar``. Retries, back-off and fallback live in the cache manager.

Quirks handled here (verified 2026-10-21 against yfinance 1.7.0, see D-28):
- Even with ``auto_adjust=False``, Open/High/Low/Close and Volume come back
  **split-adjusted**. We convert back to raw prices using the split list (D-07).
- Daily rows are stamped at local midnight; we restamp them at the session open (D-20).
- Intraday rows are stamped at the bar open in exchange-local time.
- History windows: 1m ≈ 30 days (7 days per request), 5m/15m ≈ 60 days, 1h ≈ 730 days.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.core.clock import Clock, utc_to_ms
from backend.core.types import Bar, CorporateAction, Market, Timeframe
from backend.data.adjust import factor_at, split_events, unadjust
from backend.data.errors import EmptyResponse, NotFound, RateLimited, SourceError
from backend.data.throttle import Throttle
from backend.markets.calendar import Calendar, daily_ts, local_date, session_at
from backend.core.clock import ms_to_dt

# What Yahoo serves per interval (days back from now), and the largest request it allows.
WINDOW_DAYS: dict[Timeframe, int | None] = {
    Timeframe.M1: 29,
    Timeframe.M5: 59,
    Timeframe.M15: 59,
    Timeframe.H1: 729,
    Timeframe.D1: None,
}
CHUNK_DAYS: dict[Timeframe, int] = {
    Timeframe.M1: 7,
    Timeframe.M5: 59,
    Timeframe.M15: 59,
    Timeframe.H1: 180,
    Timeframe.D1: 365 * 30,
}
INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}


@dataclass(frozen=True)
class Row:
    """One row of a Yahoo history table, before normalisation."""

    when: datetime  # tz-aware, exchange-local
    open: float
    high: float
    low: float
    close: float
    volume: float


# (yahoo_symbol, kwargs for Ticker.history) → rows. Swapped for a fake in tests.
HistoryFn = Callable[[str, dict[str, Any]], list[Row]]
# yahoo_symbol → corporate actions as (when, dividend, split ratio)
ActionsFn = Callable[[str], list[tuple[datetime, float, float]]]


# Indian index and currency symbols on Yahoo (D-204): only ^NSEI was known, so the Sensex, Bank
# Nifty, every ^CNX sector index and India VIX were read as US symbols, their daily candles
# stamped with US session dates, and the Indices page showed them days old.
IN_INDEX_PREFIXES = ("^NSE", "^BSE", "^CNX", "^NSMIDCP", "^CRSLDX", "^INDIAVIX", "^NIFTY")
IN_OTHER = {"INR=X"}


def market_of(yahoo_symbol: str) -> Market:
    if yahoo_symbol.endswith((".NS", ".BO")) or yahoo_symbol in IN_OTHER:
        return Market.IN
    if yahoo_symbol.startswith(IN_INDEX_PREFIXES):
        return Market.IN
    return Market.US


def _translate(exc: Exception, symbol: str) -> SourceError:
    name = type(exc).__name__
    text = str(exc)
    if "RateLimit" in name or "Too Many Requests" in text or "429" in text:
        return RateLimited(
            "Yahoo Finance is limiting requests right now.", detail=f"{name}: {text}"
        )
    if "PricesMissing" in name or "Data doesn't exist for" in text:
        # nothing in that date range (before the listing, or a stock that stopped trading):
        # an empty answer, not Yahoo failing. Treating it as a failure paused Yahoo for every
        # stock for 15 minutes (D-114).
        return EmptyResponse(
            f"Yahoo Finance has no prices for {symbol} in that period.", detail=f"{name}: {text}"
        )
    if "delisted" in text.lower() or "not found" in text.lower() or "No data found" in text:
        return NotFound(
            f"Yahoo Finance doesn't know the symbol {symbol}.", detail=f"{name}: {text}"
        )
    return SourceError("Yahoo Finance didn't answer properly.", detail=f"{name}: {text}")


def _yf_history(symbol: str, kwargs: dict[str, Any]) -> list[Row]:
    import yfinance as yf  # imported lazily: slow, and tests never need it

    try:
        df = yf.Ticker(symbol).history(
            auto_adjust=False, actions=False, raise_errors=True, **kwargs
        )
    except Exception as exc:
        raise _translate(exc, symbol) from exc
    rows: list[Row] = []
    for when, r in df.iterrows():
        rows.append(
            Row(
                when=when.to_pydatetime(),
                open=float(r["Open"]),
                high=float(r["High"]),
                low=float(r["Low"]),
                close=float(r["Close"]),
                volume=float(r["Volume"]),
            )
        )
    return rows


def _yf_actions(symbol: str) -> list[tuple[datetime, float, float]]:
    import yfinance as yf

    try:
        df = yf.Ticker(symbol).actions
    except Exception as exc:
        raise _translate(exc, symbol) from exc
    out: list[tuple[datetime, float, float]] = []
    if df is None or len(df) == 0:
        return out
    for when, r in df.iterrows():
        out.append(
            (
                when.to_pydatetime(),
                float(r.get("Dividends", 0.0)),
                float(r.get("Stock Splits", 0.0)),
            )
        )
    return out


def _valid(r: Row) -> bool:
    vals = (r.open, r.high, r.low, r.close)
    if any(math.isnan(v) or v <= 0 for v in vals):
        return False
    return not math.isnan(r.volume)


POLL_WORKERS = 8  # live-poll requests in flight at once (D-194)
# Seconds between requests (D-195). Yahoo answers in 0.1-0.5 s; one request a second, shared by
# every desk's poll, the price top-up and the intraday saver, queued requests for up to a minute
# on 6 Nov and left the 250-stock 15-minute desk without today's candles. A "slow down" answer
# still pauses the source (cache cool-down, D-114).
MIN_INTERVAL_S = 0.34


class YahooSource:
    name = "yahoo"

    def __init__(
        self,
        clock: Clock,
        calendar: Calendar,
        *,
        history: HistoryFn = _yf_history,
        actions: ActionsFn = _yf_actions,
        throttle: Throttle | None = None,
        actions_ttl_s: float = 6 * 3600,
    ) -> None:
        self.clock = clock
        self.calendar = calendar
        self._history = history
        self._actions = actions
        self.throttle = throttle or Throttle(MIN_INTERVAL_S)
        self._actions_cache: dict[str, tuple[float, list[CorporateAction]]] = {}
        self._actions_ttl_s = actions_ttl_s

    # -- protocol extras used by the cache manager

    def symbol_for(self, market: Market, symbol: str, yahoo_symbol: str) -> str | None:
        return yahoo_symbol

    def window_start_ms(self, timeframe: Timeframe) -> int | None:
        """Oldest bar Yahoo will still serve for this timeframe (None = no limit)."""
        days = WINDOW_DAYS[timeframe]
        return None if days is None else self.clock.now_ms() - days * 86_400_000

    def supports(self, market: Market, timeframe: Timeframe) -> bool:
        return True

    # -- normalisation

    def _to_bars(
        self, symbol: str, timeframe: Timeframe, rows: list[Row], *, ask_actions: bool = True
    ) -> list[Bar]:
        market = market_of(symbol)
        if ask_actions:
            actions = self.fetch_corporate_actions(symbol)
        else:
            # live polls (D-197): a second request per stock just for its split list doubled
            # every poll and, with the list held only in memory, came back after each restart;
            # the newest candles come after any split anyway, and the feed applies the stored ones
            hit = self._actions_cache.get(symbol)
            actions = hit[1] if hit is not None else []
        splits = split_events(actions)
        now = self.clock.now_ms()
        bars: dict[int, Bar] = {}
        for r in rows:
            if not _valid(r):
                continue
            if timeframe is Timeframe.D1:
                ts = daily_ts(self.calendar, market, r.when.date())
            else:
                ts = utc_to_ms(r.when)
            bar = Bar(ts, r.open, r.high, r.low, r.close, r.volume, source="yahoo")
            bar = unadjust(bar, factor_at(ts, splits))
            if self._bar_end(market, timeframe, ts) > now:
                bar = replace(bar, is_final=False)
            bars[ts] = bar  # Yahoo occasionally repeats the live row; keep the last
        return [bars[k] for k in sorted(bars)]

    def _bar_end(self, market: Market, timeframe: Timeframe, ts: int) -> int:
        s = session_at(self.calendar, market, ts)
        if s is None:  # the calendar doesn't know this session; assume it is over
            return ts + timeframe.minutes * 60_000 if timeframe.is_intraday else ts
        if timeframe is Timeframe.D1:
            return s.close_ms
        return min(ts + timeframe.minutes * 60_000, s.close_ms)

    # -- DataSource protocol

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        lo, hi = utc_to_ms(start), utc_to_ms(end)
        window = self.window_start_ms(timeframe)
        if window is not None:
            lo = max(lo, window)
        if lo >= hi:
            return []
        rows: list[Row] = []
        chunk = CHUNK_DAYS[timeframe] * 86_400_000
        cur = lo
        while cur < hi:
            nxt = min(hi, cur + chunk)
            kwargs: dict[str, Any] = {"interval": INTERVAL[timeframe.value]}
            if timeframe is Timeframe.D1:
                # Yahoo's daily "end" is exclusive and date-based: pad a day each side.
                market = market_of(symbol)
                kwargs["start"] = (local_date(market, cur) - timedelta(days=1)).isoformat()
                kwargs["end"] = (local_date(market, nxt) + timedelta(days=1)).isoformat()
            else:
                kwargs["start"] = ms_to_dt(cur, UTC)
                kwargs["end"] = ms_to_dt(nxt, UTC)
            self.throttle.wait()
            rows.extend(self._history(symbol, kwargs))
            cur = nxt
        bars = [b for b in self._to_bars(symbol, timeframe, rows) if lo <= b.ts < hi and b.is_final]
        if not bars:
            raise EmptyResponse(
                f"Yahoo Finance sent no prices for {symbol}.",
                detail=f"{timeframe.value} {lo}..{hi}: {len(rows)} raw rows",
            )
        return bars

    def fetch_corporate_actions(self, symbol: str) -> list[CorporateAction]:
        cached = self._actions_cache.get(symbol)
        if cached is not None and time.monotonic() - cached[0] < self._actions_ttl_s:
            return cached[1]
        self.throttle.wait()
        market = market_of(symbol)
        raw = [
            (daily_ts(self.calendar, market, when.date()), dividend, split)
            for when, dividend, split in self._actions(symbol)
        ]
        out = [
            CorporateAction(ex_date=ex, kind="split", ratio=split)
            for ex, _, split in raw
            if split and split > 0 and split != 1.0
        ]
        splits = split_events(out)
        # Yahoo's dividends are split-adjusted like its prices; store the cash actually
        # paid per share held on the ex-date.
        out += [
            CorporateAction(
                ex_date=ex, kind="dividend", amount=round(dividend / factor_at(ex, splits), 6)
            )
            for ex, dividend, _ in raw
            if dividend and dividend > 0
        ]
        out.sort(key=lambda a: (a.ex_date, a.kind))
        self._actions_cache[symbol] = (time.monotonic(), out)
        return out

    def latest_bars(self, symbols: list[str], timeframe: Timeframe) -> dict[str, list[Bar]]:
        """The newest candles of each symbol. Requests overlap (D-194): they still start at most
        one a second (the throttle), but a slow answer no longer holds up the next request. On
        6 Nov Yahoo took 5-13 s an answer, so one-after-another a 250-stock poll took about
        25 minutes and the 15-minute desk fell two candles behind. A stock Yahoo has no prices
        for is left out instead of failing the whole poll; being told to slow down still stops
        it (the source cools down)."""
        from concurrent.futures import ThreadPoolExecutor

        period = "5d" if timeframe is Timeframe.D1 or timeframe is Timeframe.H1 else "1d"

        def one(symbol: str) -> list[Bar]:
            self.throttle.wait()
            rows = self._history(symbol, {"interval": INTERVAL[timeframe.value], "period": period})
            return self._to_bars(symbol, timeframe, rows, ask_actions=False)[-5:]

        out: dict[str, list[Bar]] = {}
        errors: list[SourceError] = []
        workers = max(1, min(POLL_WORKERS, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yahoo-poll") as pool:
            futures = {sym: pool.submit(one, sym) for sym in symbols}
            for sym, fut in futures.items():
                try:
                    out[sym] = fut.result()
                except (NotFound, EmptyResponse):
                    out[sym] = []
                except RateLimited:
                    raise
                except SourceError as exc:
                    errors.append(exc)
        if errors and not any(out.values()):
            raise errors[0]
        return out
