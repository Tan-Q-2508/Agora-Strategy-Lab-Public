"""The live feed: newly closed candles for paper trading (DATA_SOURCES §5).

The runner asks a few seconds after each candle close. The feed asks the data source for
the latest candles of every symbol in one batch, keeps only candles that are really over,
and stores them in the same candle store backtests use (so a later backtest over the same
days sees the same prices).

A candle counts as final only once a later candle exists, or a minute has passed since it
closed: Yahoo sometimes still revises the newest candle for a few seconds. Sources that
fail are reported, not retried here; the runner decides when to try again.

Two sessions polling the same stocks at the same moment share one answer (the response is
reused for ``SHARE_MS``), so running several sessions doesn't multiply requests.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC

from backend.core.clock import Clock, ms_to_dt
from backend.core.data_source import DataSource
from backend.core.types import Bar, Timeframe
from backend.data import store
from backend.data.adjust import factor_at, split_events, unadjust, with_factors
from backend.data.errors import SourceError
from backend.data.store import InstrumentRef
from backend.db.engine import Database
from backend.logging_setup import get_logger
from backend.markets.calendar import Calendar
from backend.markets.status import MARKET_NAME
from backend.paper.timing import bar_end_ms, bar_open_for_close, next_bar_close

log = get_logger("paper.feed")
_QUIET: dict[str, str] = {}  # symbol → the day its failed catch-up was last logged

ACCEPT_AFTER_MS = 60_000  # a candle with no later candle is final this long after it closes
SHARE_MS = 15_000
CATCH_UP_LIMIT = 4 * 86_400_000  # never back-fill more than this through the live feed


@dataclass
class PollResult:
    ok: bool
    bars: dict[int, list[Bar]] = field(default_factory=dict)  # instrument id → new final bars
    newest_seen: dict[int, int] = field(default_factory=dict)  # incl. the still-forming candle
    source: str | None = None
    message: str = ""  # plain English when not ok
    detail: str = ""


class LiveFeed:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        calendar: Calendar,
        sources: Sequence[DataSource],
        *,
        available: Callable[[str], bool] | None = None,
    ) -> None:
        self.db = db
        self.clock = clock
        self.calendar = calendar
        self.sources = list(sources)
        self._available = available or (lambda name: True)
        self._shared: dict[tuple[str, str, str], tuple[int, list[Bar]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ fetching

    def _latest(
        self, src: DataSource, symbols: list[str], timeframe: Timeframe
    ) -> dict[str, list[Bar]]:
        now = self.clock.now_ms()
        out: dict[str, list[Bar]] = {}
        todo: list[str] = []
        with self._lock:
            for sym in symbols:
                hit = self._shared.get((src.name, sym, timeframe.value))
                if hit is not None and 0 <= now - hit[0] < SHARE_MS:
                    out[sym] = hit[1]
                else:
                    todo.append(sym)
        if todo:
            got = src.latest_bars(todo, timeframe)
            with self._lock:
                for sym in todo:
                    bars = list(got.get(sym, []))
                    self._shared[(src.name, sym, timeframe.value)] = (now, bars)
                    out[sym] = bars
        return out

    def _normalise(self, src: DataSource, inst: InstrumentRef, bars: list[Bar]) -> list[Bar]:
        with self.db.session() as s:
            splits = split_events(store.load_actions(s, inst.id))
        if getattr(src, "returns_adjusted", False):
            return [unadjust(b, factor_at(b.ts, splits)) for b in bars]
        return with_factors(bars, splits)

    # ------------------------------------------------------------ polling

    def poll(
        self,
        instruments: Sequence[InstrumentRef],
        timeframe: Timeframe,
        since: dict[int, int],
    ) -> PollResult:
        """New final candles after ``since[instrument id]`` (a candle's ``ts``)."""
        if not instruments:
            return PollResult(ok=True)
        market = instruments[0].market
        chain = [src for src in self.sources if src.supports(market, timeframe)]
        problems: list[str] = []
        for src in chain:
            if not self._available(src.name):
                problems.append(f"{src.name}: cooling down")
                continue
            names = {}
            for inst in instruments:
                sym = src.symbol_for(inst.market, inst.symbol, inst.yahoo_symbol)
                if sym is not None:
                    names[inst.id] = sym
            if not names:
                continue
            try:
                got = self._latest(src, sorted(set(names.values())), timeframe)
            except SourceError as exc:
                problems.append(f"{src.name}: {exc.message} {exc.detail}".strip())
                continue
            except Exception as exc:  # a library bug must not stop paper trading
                log.exception("Live poll via %s failed", src.name)
                problems.append(f"{src.name}: {exc!r}")
                continue
            if not any(got.values()):
                problems.append(f"{src.name}: no candles")
                continue
            result = PollResult(ok=True, source=src.name)
            now = self.clock.now_ms()
            for inst in instruments:
                sym = names.get(inst.id)
                bars = self._normalise(src, inst, got.get(sym, [])) if sym else []
                if bars:
                    result.newest_seen[inst.id] = bars[-1].ts
                new = self._accept(inst, timeframe, bars, since.get(inst.id), now)
                new = self._catch_up(src, sym, inst, timeframe, new, since.get(inst.id), now)
                if new:
                    with self.db.session() as s:
                        store.upsert_bars(s, inst.id, timeframe, new, now)
                    result.bars[inst.id] = new
            return result
        return PollResult(
            ok=False,
            message=f"Couldn't get live {MARKET_NAME[market]} prices right now.",
            detail="; ".join(problems) or "no source for this market and timeframe",
        )

    def _accept(
        self,
        inst: InstrumentRef,
        timeframe: Timeframe,
        bars: list[Bar],
        after: int | None,
        now: int,
    ) -> list[Bar]:
        out = []
        for n, b in enumerate(bars):
            if after is not None and b.ts <= after:
                continue
            end = bar_end_ms(self.calendar, inst.market, timeframe, b.ts)
            if end > now:
                continue
            later = n + 1 < len(bars)
            if b.is_final and (later or now >= end + ACCEPT_AFTER_MS):
                out.append(b)
        return out

    def _catch_up(
        self,
        src: DataSource,
        sym: str | None,
        inst: InstrumentRef,
        timeframe: Timeframe,
        new: list[Bar],
        after: int | None,
        now: int,
    ) -> list[Bar]:
        """If candles are missing between ``after`` and what the latest batch returned
        (e.g. after an outage), fetch the range in between."""
        if sym is None or after is None or not new:
            return new
        end = bar_end_ms(self.calendar, inst.market, timeframe, after)
        nxt_close = next_bar_close(self.calendar, inst.market, timeframe, end)
        if nxt_close is None:
            return new
        expected = bar_open_for_close(self.calendar, inst.market, timeframe, nxt_close)
        if new[0].ts <= expected or new[0].ts - expected > CATCH_UP_LIMIT:
            return new
        try:
            fill = src.fetch_bars(
                sym,
                timeframe,
                ms_to_dt(expected, UTC),
                ms_to_dt(new[0].ts, UTC),
            )
        except Exception as exc:  # best effort: the gap is shown instead
            # once a stock a day: small stocks with no recent prices failed on every poll,
            # ~30 warnings every half hour that buried real problems
            day = ms_to_dt(self.clock.now_ms(), UTC).date().isoformat()
            say = log.debug if _QUIET.get(inst.symbol) == day else log.warning
            _QUIET[inst.symbol] = day
            say("Catch-up fetch for %s failed: %r", inst.symbol, exc)
            return new
        fill = [
            b for b in self._normalise(src, inst, fill) if b.is_final and after < b.ts < new[0].ts
        ]
        return [*fill, *new]
