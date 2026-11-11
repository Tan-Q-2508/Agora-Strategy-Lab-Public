"""The cache manager: Agora's only way to get candles.

Everything (charts, backtests, paper trading, onboarding) asks here. It works out which
sessions are missing from the local store, fetches only those, and records every attempt
in ``data_fetch_log`` (DATA_SOURCES §7). Fetching is polite and resilient (§2):

- one request at a time per source, spaced by the source's ``Throttle``;
- rate limits and errors are retried after 2, 4, 8 and 16 seconds, then the source is
  marked "cooling down" for 15 minutes and skipped meanwhile;
- if a source fails, the next one in the chain is tried (India daily: Yahoo → NSE,
  US daily: Yahoo → Stooq) and the log says ``fallback``;
- sessions a source genuinely doesn't have (before a listing, a real exchange gap) are
  asked for once, not on every run.
"""

from __future__ import annotations

import bisect
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.core.clock import Clock, ms_to_dt
from backend.core.data_source import DataSource
from backend.core.types import Bar, Timeframe
from backend.data import store
from backend.data import repair
from backend.data.adjust import adjusted, factor_at, split_events, unadjust, with_factors
from backend.data.aggregate import aggregate
from backend.data.errors import Blocked, EmptyResponse, NotFound, RateLimited, SourceError
from backend.data.store import InstrumentRef
from backend.db.engine import Database
from backend.logging_setup import get_logger
from backend.markets.calendar import Calendar, Session, local_date, sessions_between_ms

log = get_logger("data.cache")

BACKOFF_S = (2.0, 4.0, 8.0, 16.0)
COOL_DOWN_MS = 15 * 60_000
BLOCKED_MS = 24 * 3_600_000
# A source is paused for everyone only when it limits us, refuses us, or fails for this many
# different stocks in a row; one odd stock mustn't stop the whole download (D-114).
FAILS_BEFORE_PAUSE = 3
# No internet at all (Wi-Fi off, DNS down) isn't the source refusing us: try again soon and
# don't lengthen its cool-down (D-165: a laptop's Wi-Fi switched off when it overheated, and
# Yahoo stayed "cooling down" for 8 hours after the connection came back)
OFFLINE_RETRY_MS = 60_000
_OFFLINE = (
    "could not resolve host",
    "getaddrinfo failed",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "network is unreachable",
    "no route to host",
    "failed to establish a new connection",
    "dnserror",
    "connection refused",
)


def offline(exc: BaseException) -> bool:
    """The error means this computer couldn't reach the internet, not that the source said no."""
    text = f"{getattr(exc, 'message', '')} {getattr(exc, 'detail', '')} {exc}".lower()
    return any(k in text for k in _OFFLINE)


DAY_MS = 86_400_000
_ACTIONS = "actions"  # lock key for a stock's splits and dividends
FINAL_AFTER_MS = 7 * DAY_MS  # daily bars older than this never change (§7)
REVISION_GRACE_MS = 6 * 3_600_000  # a daily bar fetched this soon after close may be revised
RETRY_RECENT_MS = 3_600_000  # don't re-ask for the same recent session within an hour
DERIVE_FROM: dict[Timeframe, tuple[Timeframe, ...]] = {
    Timeframe.M15: (Timeframe.M5, Timeframe.M1),
    Timeframe.H1: (Timeframe.M15, Timeframe.M5),
    Timeframe.M5: (Timeframe.M1,),
}

Progress = Callable[[float, str], None]


@dataclass
class EnsureResult:
    instrument: InstrumentRef
    timeframe: Timeframe
    fetched: int = 0
    missing_before: int = 0
    missing_after: int = 0
    sources: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)  # plain English
    details: list[str] = field(default_factory=list)  # technical
    # a source that would have been asked was cooling down, so missing candles weren't even
    # asked for (D-182): the caller mustn't count the stock as brought up to date
    waited: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems


class Cancelled(Exception):
    pass


def _dt(ms: int) -> datetime:
    return ms_to_dt(ms, UTC)


def _runs(missing: Sequence[Session], all_sessions: Sequence[Session]) -> list[list[Session]]:
    """Group missing sessions into runs of consecutive trading sessions."""
    pos = {s.day: i for i, s in enumerate(all_sessions)}
    runs: list[list[Session]] = []
    for s in missing:
        if runs and pos[s.day] == pos[runs[-1][-1].day] + 1:
            runs[-1].append(s)
        else:
            runs.append([s])
    return runs


class CacheManager:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        calendar: Calendar,
        sources: Sequence[DataSource],
        *,
        sleep: Callable[[float], None] = time.sleep,
        on_source_change: Callable[[str, str], None] | None = None,
    ) -> None:
        self.db = db
        self.clock = clock
        self.calendar = calendar
        self.sources = list(sources)
        self._sleep = sleep
        self._on_source_change = on_source_change
        self._locks: dict[tuple[int, str], threading.Lock] = {}
        self._actions_checked: set[int] = set()
        self._locks_guard = threading.Lock()
        # Downloads run several at once (the autopilot, D-102) but SQLite takes one writer at
        # a time: saving is queued here instead of failing with "database is locked".
        self._write = threading.Lock()
        self._fail_streak: dict[str, set[str]] = {}
        self._pauses: dict[str, int] = {}  # pauses in a row without a success (D-114)

    # ------------------------------------------------------------ sources

    def chain(self, inst: InstrumentRef, timeframe: Timeframe) -> list[tuple[DataSource, str]]:
        """Sources to try, in order, with each one's symbol for this instrument."""
        out = []
        for src in self.sources:
            if not src.supports(inst.market, timeframe):
                continue
            sym = src.symbol_for(inst.market, inst.symbol, inst.yahoo_symbol)
            if sym is not None:
                out.append((src, sym))
        return out

    def _available(self, name: str) -> bool:
        with self.db.session() as s:
            row = store.source_states(s).get(name)
        if row is None or row.state == "ok":
            return True
        return row.until is not None and row.until <= self.clock.now_ms()

    def _set_state(self, name: str, state: str, until: int | None, error: str | None) -> None:
        with self._write, self.db.session() as s:
            changed = store.set_source_state(s, name, state, self.clock.now_ms(), until, error)
        if changed:
            log.info("Data source %s is now %s", name, state)
            if self._on_source_change:
                self._on_source_change(name, state)

    def _lock(self, inst: InstrumentRef, what: Timeframe | str) -> threading.Lock:
        key = what if isinstance(what, str) else what.value
        with self._locks_guard:
            return self._locks.setdefault((inst.id, key), threading.Lock())

    # ------------------------------------------------------------ reading

    def bars(
        self,
        inst: InstrumentRef,
        timeframe: Timeframe,
        start_ms: int,
        end_ms: int,
        *,
        adjusted_prices: bool = False,
    ) -> list[Bar]:
        """Stored bars only (no fetching). Raw prices unless ``adjusted_prices``."""
        with self.db.session() as s:
            bars = store.load_bars(s, inst.id, timeframe, start_ms, end_ms)
        return [adjusted(b) for b in bars] if adjusted_prices else bars

    # ------------------------------------------------------------ gaps

    def expected_sessions(
        self, inst: InstrumentRef, timeframe: Timeframe, start_ms: int, end_ms: int
    ) -> list[Session]:
        """Sessions in range that have fully closed (only closed bars are ever stored)."""
        now = self.clock.now_ms()
        return [
            s
            for s in sessions_between_ms(self.calendar, inst.market, start_ms, min(end_ms, now))
            if s.close_ms <= now
        ]

    def missing_sessions(
        self,
        inst: InstrumentRef,
        timeframe: Timeframe,
        start_ms: int,
        end_ms: int,
        *,
        for_fetch: bool = True,
    ) -> tuple[list[Session], list[Session]]:
        """(missing sessions, all expected sessions). A session is missing when it has no
        bars (daily) or clearly too few (intraday). With ``for_fetch`` it also includes
        recent daily bars fetched so soon after the close that Yahoo may still revise
        them, and leaves out sessions that asking again would not help."""
        expected = self.expected_sessions(inst, timeframe, start_ms, end_ms)
        if not expected:
            return [], []
        lo, hi = expected[0].open_ms, expected[-1].close_ms
        now = self.clock.now_ms()
        with self.db.session() as s:
            have = store.stored_ts(s, inst.id, timeframe, lo, hi + 1)
            tried = store.attempted_ranges(s, inst.id, timeframe)
        missing: list[Session] = []
        if timeframe is Timeframe.D1:
            for sess in expected:
                fetched = have.get(sess.open_ms)
                if fetched is None or (
                    for_fetch
                    and now - sess.close_ms < FINAL_AFTER_MS
                    and fetched < sess.close_ms + REVISION_GRACE_MS
                ):
                    missing.append(sess)
        else:
            step = timeframe.minutes * 60_000
            counts: dict[int, int] = {}
            starts = [sess.open_ms for sess in expected]
            for ts in have:
                i = bisect.bisect_right(starts, ts) - 1
                if i >= 0 and ts < expected[i].close_ms:
                    counts[i] = counts.get(i, 0) + 1
            for i, sess in enumerate(expected):
                want = -(-(sess.close_ms - sess.open_ms) // step)
                if counts.get(i, 0) < max(1, int(want * 0.9)):
                    missing.append(sess)
        if for_fetch and tried:
            missing = [sess for sess in missing if not self._already_tried(sess, tried, now)]
        return missing, expected

    @staticmethod
    def _already_tried(sess: Session, tried: list[tuple[int, int, int, str]], now: int) -> bool:
        """True when asking again would be pointless: a fetch after the session closed
        returned data around it but not this session (old sessions: never ask again), or
        any fetch covered it within the last hour (recent sessions: don't hammer)."""
        for a, b, started, status in tried:
            if not (a <= sess.open_ms < b) or started < sess.close_ms:
                continue
            if now - started < RETRY_RECENT_MS:
                return True
            if status in ("ok", "fallback") and now - sess.close_ms > FINAL_AFTER_MS:
                return True
        return False

    # ------------------------------------------------------------ fetching

    def _fetch_with_retry(
        self, src: DataSource, symbol: str, timeframe: Timeframe, lo: int, hi: int
    ) -> list[Bar]:
        last: SourceError | None = None
        for attempt, wait in enumerate((0.0, *BACKOFF_S)):
            if wait:
                self._sleep(wait)
            try:
                bars = src.fetch_bars(symbol, timeframe, _dt(lo), _dt(hi))
                if not bars:
                    raise EmptyResponse(f"{src.name} sent no prices for {symbol}.")
                self._fail_streak.pop(src.name, None)
                self._pauses.pop(src.name, None)
                return bars
            except (NotFound, EmptyResponse):
                self._fail_streak.pop(src.name, None)  # the source answered
                raise
            except Blocked as exc:
                log.warning("%s refuses automatic downloads; leaving it alone for a day", src.name)
                until = self.clock.now_ms() + BLOCKED_MS
                self._set_state(
                    src.name, "cooling_down", until, f"{exc.message} {exc.detail}".strip()
                )
                raise
            except SourceError as exc:
                last = exc
                log.warning("%s attempt %d failed for %s: %s", src.name, attempt + 1, symbol, exc)
            except Exception as exc:  # a library bug must not kill the whole download
                last = SourceError(f"{src.name} failed unexpectedly.", detail=repr(exc))
                log.exception("%s crashed for %s", src.name, symbol)
        assert last is not None
        if offline(last):
            self._fail_streak.pop(src.name, None)
            self._set_state(
                src.name,
                "cooling_down",
                self.clock.now_ms() + OFFLINE_RETRY_MS,
                "No internet connection right now; Agora tries again in a minute.",
            )
            raise last
        streak = self._fail_streak.setdefault(src.name, set())
        streak.add(symbol)
        if isinstance(last, RateLimited) or len(streak) >= FAILS_BEFORE_PAUSE:
            self._fail_streak.pop(src.name, None)
            # each pause in a row without a success is twice as long, up to a day: a source
            # that stopped answering isn't asked every 15 minutes all day (D-114)
            n = self._pauses.get(src.name, 0)
            self._pauses[src.name] = n + 1
            until = self.clock.now_ms() + min(COOL_DOWN_MS * 2**n, BLOCKED_MS)
            self._set_state(
                src.name, "cooling_down", until, f"{last.message} {last.detail}".strip()
            )
        raise last

    def _normalise(self, src: DataSource, inst: InstrumentRef, bars: list[Bar]) -> list[Bar]:
        """Give every bar the split factor from our stored split list (sources differ in
        what they know); un-adjust sources that only offer adjusted prices."""
        with self.db.session() as s:
            splits = split_events(store.load_actions(s, inst.id))
        if getattr(src, "returns_adjusted", False):
            # Yahoo can mix adjusted and unadjusted rows around a split (D-228)
            return repair.fixed([unadjust(b, factor_at(b.ts, splits)) for b in bars])
        return with_factors(bars, splits)

    def ensure(
        self,
        inst: InstrumentRef,
        timeframe: Timeframe,
        start_ms: int,
        end_ms: int,
        *,
        cancel: threading.Event | None = None,
    ) -> EnsureResult:
        """Make the store hold every available closed bar in ``[start_ms, end_ms)``."""
        result = EnsureResult(inst, timeframe)
        with self._lock(inst, timeframe):
            missing, expected = self.missing_sessions(inst, timeframe, start_ms, end_ms)
            result.missing_before = len(missing)
            if not missing:
                return result
            if inst.id not in self._actions_checked and not inst.is_index:
                # Split factors must be known before bars are stored (D-07).
                self.refresh_actions(inst)
            chain = self.chain(inst, timeframe)
            for run in self._spans(missing, expected, timeframe):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                self._fetch_run(inst, timeframe, run, chain, result)
            if timeframe in DERIVE_FROM:
                self._derive(inst, timeframe, start_ms, end_ms, result)
            left, _ = self.missing_sessions(inst, timeframe, start_ms, end_ms, for_fetch=False)
            result.missing_after = len(left)
        return result

    def _spans(
        self, missing: list[Session], expected: list[Session], timeframe: Timeframe
    ) -> list[tuple[int, int]]:
        """Request ranges. Daily: one span (Yahoo returns whole histories cheaply).
        Intraday: one span per run of consecutive missing sessions."""
        if timeframe is Timeframe.D1:
            return [(missing[0].open_ms, missing[-1].open_ms + 1)]
        return [(run[0].open_ms, run[-1].close_ms) for run in _runs(missing, expected)]

    def _fetch_run(
        self,
        inst: InstrumentRef,
        timeframe: Timeframe,
        span: tuple[int, int],
        chain: list[tuple[DataSource, str]],
        result: EnsureResult,
    ) -> None:
        lo, hi = span
        primary = chain[0][0].name if chain else None
        for src, symbol in chain:
            window = src.window_start_ms(timeframe)
            if window is not None and hi <= window:
                continue  # entirely older than this source keeps
            if not self._available(src.name):
                result.details.append(f"{src.name} cooling down; skipped")
                result.waited = True
                continue
            started = self.clock.now_ms()
            t0 = time.monotonic()
            status, rows, message = "ok", 0, ""
            try:
                bars = self._fetch_with_retry(src, symbol, timeframe, lo, hi)
                bars = self._normalise(src, inst, bars)
                with self._write, self.db.session() as s:
                    rows = store.upsert_bars(s, inst.id, timeframe, bars, self.clock.now_ms())
                result.fetched += rows
                result.sources.add(src.name)
                if src.name != primary:
                    status = "fallback"
                self._set_state(src.name, "ok", None, None)
            except NotFound as exc:
                status, message = "error", f"{exc.message} {exc.detail}".strip()
                result.problems.append(exc.message)
            except EmptyResponse as exc:
                status, message = "empty", f"{exc.message} {exc.detail}".strip()
            except RateLimited as exc:
                status, message = "rate_limited", f"{exc.message} {exc.detail}".strip()
            except SourceError as exc:
                status, message = "error", f"{exc.message} {exc.detail}".strip()
            duration = int((time.monotonic() - t0) * 1000)
            with self._write, self.db.session() as s:
                store.log_fetch(
                    s,
                    source=src.name,
                    instrument_id=inst.id,
                    timeframe=timeframe,
                    range_start=lo,
                    range_end=hi,
                    status=status,
                    rows=rows,
                    message=message,
                    started_at=started,
                    duration_ms=duration,
                )
            if status in ("ok", "fallback"):
                return
            result.details.append(f"{src.name}: {message}")
        if not result.problems:
            result.problems.append(
                f"Couldn't download {timeframe.value} prices for {inst.symbol} right now."
            )

    def _derive(
        self,
        inst: InstrumentRef,
        timeframe: Timeframe,
        start_ms: int,
        end_ms: int,
        result: EnsureResult,
    ) -> None:
        missing, _ = self.missing_sessions(inst, timeframe, start_ms, end_ms)
        if not missing:
            return
        for lower in DERIVE_FROM[timeframe]:
            lo, hi = missing[0].open_ms, missing[-1].close_ms
            src_bars = self.bars(inst, lower, lo, hi)
            if not src_bars:
                continue
            by_open = {m.day: (m.open_ms, m.close_ms) for m in missing}

            def session_of(
                ts: int, by_open: dict[Any, tuple[int, int]] = by_open
            ) -> tuple[int, int] | None:
                return by_open.get(local_date(inst.market, ts))

            derived = aggregate(src_bars, timeframe, session_of, lower)
            if derived:
                with self._write, self.db.session() as s:
                    n = store.upsert_bars(s, inst.id, timeframe, derived, self.clock.now_ms())
                result.fetched += n
                result.sources.add("derived")
                result.problems = []
                return

    def probe(self, inst: InstrumentRef) -> tuple[bool, str]:
        """Does any source have recent daily prices for this (maybe new) instrument?
        Returns (found, technical detail). Nothing is stored."""
        now = self.clock.now_ms()
        details = []
        for src, symbol in self.chain(inst, Timeframe.D1):
            try:
                bars = src.fetch_bars(symbol, Timeframe.D1, _dt(now - 20 * DAY_MS), _dt(now))
            except SourceError as exc:
                details.append(f"{src.name}: {exc.message} {exc.detail}".strip())
                if isinstance(exc, RateLimited):
                    raise
                continue
            if bars:
                return True, ""
            details.append(f"{src.name}: no bars")
        return False, "; ".join(details)

    # ------------------------------------------------------------ corporate actions

    def refresh_actions(self, inst: InstrumentRef) -> bool:
        """Fetch splits/dividends from the first source that has them; re-factor stored
        candles if the split list changed. Returns True on success.

        One caller per stock at a time: the Welcome download and the autopilot both reach
        a stock's actions at first start, and two inserts of the same dividend collide."""
        with self._lock(inst, _ACTIONS):
            return self._refresh_actions(inst)

    def _refresh_actions(self, inst: InstrumentRef) -> bool:
        for src, symbol in self.chain(inst, Timeframe.D1):
            if not self._available(src.name):
                continue
            try:
                actions = src.fetch_corporate_actions(symbol)
            except SourceError as exc:
                log.warning("Corporate actions from %s failed for %s: %s", src.name, symbol, exc)
                continue
            with self._write, self.db.session() as s:
                if store.save_actions(s, inst.id, actions, src.name):
                    store.reapply_split_factors(s, inst.id)
            self._actions_checked.add(inst.id)
            return True
        return False


def describe_result(r: EnsureResult) -> dict[str, Any]:
    return {
        "symbol": r.instrument.symbol,
        "timeframe": r.timeframe.value,
        "fetched": r.fetched,
        "missing": r.missing_after,
        "sources": sorted(r.sources),
        "problems": r.problems,
    }
