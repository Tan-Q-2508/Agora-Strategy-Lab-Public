"""High-level data operations behind the Data screen, onboarding and backtests.

The cache manager knows how to fill one instrument's gaps; this module decides *what* to
fill (which symbols, timeframes and date ranges), reports progress for long downloads,
and summarises coverage for the user.
"""

from __future__ import annotations

import bisect
import threading
from concurrent.futures import ThreadPoolExecutor

import csv
import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.core.types import Market, Timeframe
from backend.data import store
from backend.data.cache import CacheManager, Cancelled, EnsureResult
from backend.data.store import InstrumentRef
from backend.db.models import Instrument, Universe, UniverseMember
from backend.markets.calendar import Calendar, local_date, sessions_between_ms, tz
from backend.core.clock import ms_to_dt

DAILY_YEARS = 11  # ten years of backtests plus a year of indicator warm-up (D-29)
INTRADAY_DEFAULT_DAYS = {"1m": 29, "5m": 59, "15m": 59, "1h": 729}
BENCHMARK = {Market.IN: "NIFTY50", Market.US: "SPY"}
UNIVERSE = {Market.IN: "NIFTY50", Market.US: "US_WATCHLIST"}


def default_start_ms(timeframe: Timeframe, now_ms: int) -> int:
    if timeframe is Timeframe.D1:
        return now_ms - DAILY_YEARS * 365 * 86_400_000
    return now_ms - INTRADAY_DEFAULT_DAYS[timeframe.value] * 86_400_000


# The market calendars start here, so it is the oldest daily candle Agora can place.
FULL_DAILY_FROM_MS = int(datetime(2000, 1, 1, tzinfo=UTC).timestamp() * 1000)


def full_start_ms(timeframe: Timeframe, now_ms: int) -> int:
    """The oldest candle worth asking the sources for: every daily candle since 2000, and
    for intraday whatever Yahoo still keeps (older intraday candles only exist if Agora
    saved them earlier; they are read from the store, never re-downloaded)."""
    if timeframe is Timeframe.D1:
        return FULL_DAILY_FROM_MS
    return default_start_ms(timeframe, now_ms)


# ---------------------------------------------------------------- instruments & universes


def instruments(
    s: Session, market: Market | None = None, q: str | None = None, active_only: bool = True
) -> list[InstrumentRef]:
    stmt = select(Instrument)
    if market is not None:
        stmt = stmt.where(Instrument.market_code == market.value)
    if active_only:
        stmt = stmt.where(Instrument.is_active == 1)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Instrument.symbol.ilike(like) | Instrument.name.ilike(like))
    return [store.ref(r) for r in s.scalars(stmt.order_by(Instrument.symbol))]


def universe_id(s: Session, name: str) -> int:
    uid = s.scalar(select(Universe.id).where(Universe.name == name))
    if uid is None:
        raise LookupError(f"Universe {name} is missing; the database seed didn't run.")
    return uid


def members(s: Session, universe: int, as_of_ms: int | None = None) -> list[InstrumentRef]:
    """Instruments in the universe on ``as_of_ms`` (default: current members)."""
    stmt = select(Instrument).join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
    stmt = stmt.where(UniverseMember.universe_id == universe)
    if as_of_ms is None:
        stmt = stmt.where(UniverseMember.valid_to.is_(None))
    else:
        stmt = stmt.where(
            UniverseMember.valid_from <= as_of_ms,
            (UniverseMember.valid_to.is_(None)) | (UniverseMember.valid_to > as_of_ms),
        )
    return [store.ref(r) for r in s.scalars(stmt.order_by(Instrument.symbol)).unique()]


def has_membership_history(s: Session, universe: int) -> bool:
    """True once a historical membership list has been imported (no survivorship bias)."""
    return (
        s.scalar(
            select(UniverseMember.id).where(
                UniverseMember.universe_id == universe, UniverseMember.source.like("import%")
            )
        )
        is not None
    )


def default_symbols(s: Session, market: Market) -> list[InstrumentRef]:
    """What onboarding downloads: the market's universe plus its benchmark."""
    out = members(s, universe_id(s, UNIVERSE[market]))
    bench = store.find_instrument(s, market, BENCHMARK[market])
    if bench is not None and all(i.id != bench.id for i in out):
        out.append(bench)
    return out


def saved_symbols(s: Session, market: Market, tf: Timeframe) -> list[InstrumentRef]:
    """The starter list plus every stock of the market that already has saved prices on this
    timeframe: what "Refresh now" brings up to date (the user's request 2026-10-24, D-107)."""
    from backend.db.models import Candle

    out = default_symbols(s, market)
    seen = {i.id for i in out}
    ids = s.scalars(
        select(Instrument.id)
        .where(
            Instrument.market_code == market.value,
            select(Candle.instrument_id)
            .where(Candle.instrument_id == Instrument.id, Candle.timeframe == tf.value)
            .exists(),
        )
        .order_by(Instrument.symbol)
    ).all()
    for iid in ids:
        if iid not in seen:
            inst = store.get_instrument(s, iid)
            if inst is not None:
                out.append(inst)
                seen.add(iid)
    return out


@dataclass(frozen=True)
class ImportReport:
    rows: int
    instruments_added: int
    problems: list[str]


def import_membership_history(
    s: Session, universe: int, market: Market, text: str, now_ms: int
) -> ImportReport:
    """Replace a universe's membership with a CSV of ``symbol,start_date,end_date``
    (dates as YYYY-MM-DD; an empty end date means "still a member")."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    if not {"symbol", "start_date"} <= cols:
        raise ValueError("The file needs the columns symbol, start_date and end_date.")
    parsed: list[tuple[str, int, int | None]] = []
    problems: list[str] = []
    zone = tz(market)
    for n, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        sym = row.get("symbol", "").upper()
        try:
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"]) if row.get("end_date") else None
        except ValueError:
            problems.append(f"Line {n}: dates must look like 2019-03-29.")
            continue
        if not sym:
            problems.append(f"Line {n}: the symbol is empty.")
            continue
        if end is not None and end < start:
            problems.append(f"Line {n}: the end date is before the start date.")
            continue
        start_ms = int(datetime.combine(start, time(0), zone).timestamp() * 1000)
        end_ms = int(datetime.combine(end, time(0), zone).timestamp() * 1000) if end else None
        parsed.append((sym, start_ms, end_ms))
    if not parsed:
        raise ValueError("The file has no usable rows.")
    added = 0
    s.query(UniverseMember).filter(UniverseMember.universe_id == universe).delete()
    for sym, start_ms, end_ms in parsed:
        inst = store.find_instrument(s, market, sym)
        if inst is None:
            yahoo = f"{sym}.NS" if market is Market.IN else sym
            new = Instrument(
                market_code=market.value,
                symbol=sym,
                yahoo_symbol=yahoo,
                name=sym,
                instrument_type="equity",
                is_active=1,
                added_at=now_ms,
            )
            s.add(new)
            s.flush()
            inst_id = new.id
            added += 1
        else:
            inst_id = inst.id
        s.add(
            UniverseMember(
                universe_id=universe,
                instrument_id=inst_id,
                valid_from=start_ms,
                valid_to=end_ms,
                source=f"import {ms_to_dt(now_ms, UTC):%Y-%m-%d}",
            )
        )
    s.flush()
    return ImportReport(len(parsed), added, problems)


def deactivate(s: Session, instrument_id: int, now_ms: int) -> None:
    """Remove a ticker from the user's lists. Its saved candles are kept."""
    s.execute(update(Instrument).where(Instrument.id == instrument_id).values(is_active=0))
    s.execute(
        update(UniverseMember)
        .where(UniverseMember.instrument_id == instrument_id, UniverseMember.valid_to.is_(None))
        .values(valid_to=now_ms)
    )


# ---------------------------------------------------------------- refresh


@dataclass
class RefreshSummary:
    symbols: int
    fetched: int
    failed: list[dict[str, Any]]
    fallback_used: bool

    def public(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "fetched": self.fetched,
            "failed": self.failed,
            "fallback_used": self.fallback_used,
        }


def refresh(
    cache: CacheManager,
    targets: Sequence[InstrumentRef],
    timeframes: Iterable[Timeframe],
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    progress: Callable[[float, str], None] | None = None,
    check_cancel: Callable[[], None] | None = None,
    with_actions: bool = True,
    workers: int = 1,
) -> RefreshSummary:
    """Download what's missing for each stock and timeframe.

    ``workers`` > 1 fetches that many stocks at once: "Refresh now" over every saved stock
    (hundreds, D-107) would otherwise take hours one at a time.
    """
    tfs = list(timeframes)
    total = max(1, len(targets) * len(tfs))
    lock = threading.Lock()
    tally: dict[str, Any] = {"done": 0, "fetched": 0, "fallback": False}
    failed: list[dict[str, Any]] = []
    now = cache.clock.now_ms()

    def one(inst: InstrumentRef) -> None:
        if check_cancel:
            check_cancel()
        if with_actions and Timeframe.D1 in tfs and not inst.is_index:
            cache.refresh_actions(inst)
        for tf in tfs:
            if check_cancel:
                check_cancel()
            if progress:
                with lock:
                    pct = 100.0 * tally["done"] / total
                progress(pct, f"Downloading {inst.symbol} ({_tf_word(tf)})…")
            lo = start_ms if start_ms is not None else default_start_ms(tf, now)
            hi = end_ms if end_ms is not None else now + 1
            r: EnsureResult = cache.ensure(inst, tf, lo, hi)
            with lock:
                tally["fetched"] += r.fetched
                tally["fallback"] = tally["fallback"] or bool(
                    r.sources - {"yahoo", "fake", "derived"}
                )
                if r.problems:
                    failed.append(
                        {"symbol": inst.symbol, "timeframe": tf.value, "problem": r.problems[0]}
                    )
                tally["done"] += 1

    if workers <= 1:
        for inst in targets:
            one(inst)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="refresh") as pool:
            futures = [pool.submit(one, inst) for inst in targets]
            try:
                for f in futures:
                    f.result()  # re-raises a cancel (or a crash) from any worker
            except BaseException:
                for f in futures:
                    f.cancel()
                raise
    if progress:
        progress(100.0, "Download finished.")
    return RefreshSummary(len(targets), int(tally["fetched"]), failed, bool(tally["fallback"]))


def _tf_word(tf: Timeframe) -> str:
    return {
        "1d": "daily",
        "1h": "hourly",
        "15m": "15-minute",
        "5m": "5-minute",
        "1m": "1-minute",
    }[tf.value]


# ---------------------------------------------------------------- coverage


@dataclass(frozen=True)
class Coverage:
    instrument: InstrumentRef
    first: int | None
    last: int | None
    bars: int
    gaps: int  # trading sessions with no bar between first and last
    stale: bool  # newest closed session is missing
    source: str | None

    def public(self, now_ms: int) -> dict[str, Any]:
        inst = self.instrument
        status = (
            "empty"
            if self.bars == 0
            else "stale"
            if self.stale
            else ("gaps" if self.gaps else "ok")
        )
        return {
            "instrument_id": inst.id,
            "symbol": inst.symbol,
            "name": inst.name,
            "market": inst.market.value,
            "type": inst.instrument_type,
            "first": self.first,
            "last": self.last,
            "bars": self.bars,
            "gaps": self.gaps,
            "stale": self.stale,
            "source": self.source,
            "status": status,
        }


def coverage(
    s: Session,
    calendar: Calendar,
    targets: Sequence[InstrumentRef],
    timeframe: Timeframe,
    now_ms: int,
) -> list[Coverage]:
    stats = store.coverage_stats(s, timeframe, [i.id for i in targets])
    out: list[Coverage] = []
    # the calendar is read once a market, not once a stock: 8,000 stocks took 16 seconds
    opens: dict[Market, list[int]] = {}
    newest: dict[Market, int | None] = {}
    for market in {i.market for i in targets}:
        low = min((v[0] for k, v in stats.items()), default=now_ms)
        opens[market] = [x.open_ms for x in sessions_between_ms(calendar, market, low, now_ms + 1)]
        latest = [
            x
            for x in sessions_between_ms(calendar, market, now_ms - 10 * 86_400_000, now_ms)
            if x.close_ms <= now_ms
        ]
        newest[market] = latest[-1].open_ms if latest else None
    for inst in targets:
        st = stats.get(inst.id)
        if st is None:
            out.append(Coverage(inst, None, None, 0, 0, False, None))
            continue
        first, last, count, source = st
        if timeframe is Timeframe.D1:
            days = opens[inst.market]
            expected = bisect.bisect_right(days, last) - bisect.bisect_left(days, first)
            gaps = max(0, expected - count)
        else:
            gaps = 0  # intraday coverage is reported as a count of days instead
        fresh_from = newest[inst.market]
        stale = fresh_from is not None and last < fresh_from
        out.append(Coverage(inst, first, last, count, gaps, stale, source))
    return out


def intraday_days(s: Session, inst: InstrumentRef, timeframe: Timeframe) -> int:
    """How many distinct trading days of this intraday timeframe are stored.

    Counted in the database by UTC day: NSE (03:45–10:00 UTC) and US (13:30–21:00 UTC) sessions
    each fall inside one UTC day, so that is the trading day; loading every candle's time took
    seconds per stock under load (D-116)."""
    from backend.db.models import Candle

    c = Candle.__table__.c
    n = s.scalar(
        select(func.count(func.distinct(c.ts.op("/")(86_400_000)))).where(
            c.instrument_id == inst.id, c.timeframe == timeframe.value
        )
    )
    return int(n or 0)


def window_note(timeframe: Timeframe, days: int) -> str | None:
    """Honesty text for short intraday history (SPEC §4)."""
    if not timeframe.is_intraday:
        return None
    label = {"1m": "1-minute", "5m": "5-minute", "15m": "15-minute", "1h": "hourly"}[
        timeframe.value
    ]
    if days < 250:
        return f"Only {days} days of {label} data available."
    return None


def day_bounds_ms(market: Market, d: date) -> tuple[int, int]:
    zone = tz(market)
    start = int(datetime.combine(d, time(0), zone).timestamp() * 1000)
    end = int(datetime.combine(d + timedelta(days=1), time(0), zone).timestamp() * 1000)
    return start, end
