"""One paper-trading session: the shared engine (D-04) driven by live candles (SPEC §7).

The runner owns an ``Engine`` built exactly as a backtest builds it. A few seconds after
each candle close it asks the live feed for new candles and steps the engine through
them, so fills, costs, stops and square-off are the same code as in backtests.

What is different from a backtest, and why:

- **History vs live.** Candles that closed before the session (re)started only feed the
  indicators; the engine never trades on them. That is also how a restart works: candles
  from while Agora was closed become history and the gap is shown (D-06).
- **Pauses.** While paused by the user, or while prices arrive late, exits and stops keep
  working but no new trades open (``Engine.entry_block``).
- **Outages.** When the data source fails, the session waits and retries with back-off;
  nothing trades on stale prices.

The same class runs replays: give it a ``FakeClock`` and a fixture source and drive it
with ``run_replay`` instead of the wall-clock loop (task 6.5).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError

from backend import actions
from backend.backtest.run import warmup_ms
from backend.core.clock import Clock, ms_to_dt
from backend.core.types import Bar, Market, Timeframe
from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.data import store
from backend.data.adjust import split_events, with_factors
from backend.data.store import InstrumentRef
from backend.db.models import (
    BrokerageProfile,
    PaperAccount,
    PaperEquity,
    PaperEvent,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperSession,
    PaperTrade,
    Strategy,
)
from backend.engine.core import Engine, EngineConfig, SymbolState
from backend.logging_setup import get_logger
from backend.markets.calendar import is_open, local_date, next_session, tz
from backend.markets.status import TZ_LABEL
from backend.paper.feed import ACCEPT_AFTER_MS, LiveFeed, PollResult
from backend.paper.state import restore, restore_orders, snapshot
from backend.paper.timing import (
    POLL_DELAY_MS,
    bar_end_ms,
    bar_open_for_close,
    last_bar_close,
    next_bar_close,
    poll_interval_ms,
)
from backend.settings_store import read_all
from backend.strategy import service as strategies
from backend.strategy.compiler import CompileError, compile_definition
from backend.strategy.sandbox import SandboxError

log = get_logger("paper.runner")

DAY_MS = 86_400_000
BACKOFF_MS = (5_000, 10_000, 20_000, 40_000, 60_000)
OUTAGE_AFTER = 2  # failed polls in a row before the session counts as "waiting for data"
RETRY_BEHIND_MS = 60_000
GIVE_UP_BEHIND_MS = 6 * 3_600_000  # a candle this overdue isn't coming; wait for the next one
MAX_LOG_EVENTS = 20
MAX_HISTORY_MS = 400 * DAY_MS
KEEP_BARS = 3000  # candles kept in memory per stock (plenty for any indicator to settle)
TRIM_SLACK = 500


def with_session_settings(d: Any, notes: dict[str, Any]) -> Any:
    """The revision as this session runs it: its own trade size when it has one (D-80)."""
    size = notes.get("size_pct")
    if not size:
        return d
    from backend.strategy.definition import Sizing

    return d.model_copy(update={"sizing": Sizing(kind="percent_equity", value=float(size))})


def late_after_ms(timeframe: Timeframe) -> int:
    """A candle processed this long after it closed is "late": no new trades on it."""
    return max(2 * timeframe.minutes * 60_000, 120_000) + ACCEPT_AFTER_MS


@dataclass
class Freshness:
    level: str  # green | amber | red | closed
    text: str
    delay_s: int
    last_bar_ts: int | None
    delayed: bool


BOOT_TRIES = 6
BOOT_WAIT_S = 30.0


class PaperRunner:
    def __init__(
        self,
        ctx: Any,  # AppContext
        session_id: int,
        *,
        clock: Clock,
        feed: LiveFeed,
        replay_end_ms: int | None = None,
        refresh_actions: bool = True,
        on_finish: Callable[[int], None] | None = None,
    ) -> None:
        self.ctx = ctx
        self.id = session_id
        self.clock = clock
        self.feed = feed
        self.calendar = ctx.calendar
        self.replay_end_ms = replay_end_ms
        self.refresh_actions = refresh_actions
        self.on_finish = on_finish
        self.lock = threading.RLock()
        self.state = "starting"  # starting | running | paused_data | paused_user | stopped
        self.engine: Engine | None = None
        self.instruments: list[InstrumentRef] = []
        self.market = Market.IN
        self.tf = Timeframe.D1
        self.name = ""
        self.last_ts: dict[int, int | None] = {}
        self.live_from = 0
        self.failures = 0
        self.last_poll_ms: int | None = None
        self.behind_close: int | None = None
        self.delayed = False
        self.problem: str | None = None  # plain-English banner while something is wrong
        self.notes: dict[str, Any] = {}
        self.pause_note = "Paused by you"
        self.realized: dict[int, float] = {}
        self._events: list[tuple[str, str, str, dict[str, Any]]] = []
        self._actions_day: str | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._pace = 0.0
        self.strategy_id = 0

    # ------------------------------------------------------------ text helpers

    def _when(self, ms: int) -> str:
        zone = tz(self.market)
        d = ms_to_dt(ms, zone)
        today = ms_to_dt(self.clock.now_ms(), zone).date()
        fmt = "%H:%M" if d.date() == today else "%a %d %b, %H:%M"
        return f"{d.strftime(fmt)} {TZ_LABEL[self.market]}"

    def _dated(self, ms: int) -> str:
        return (
            f"{ms_to_dt(ms, tz(self.market)).strftime('%a %d %b, %H:%M')} {TZ_LABEL[self.market]}"
        )

    def _event(self, level: str, kind: str, message: str, **detail: Any) -> None:
        self._events.append((level, kind, message, detail))
        actions.note(
            "desk_event",
            f"{self.name}: {kind}",
            message,
            status="failed" if level == "error" else "ok",
            session_id=self.id,
        )

    def _watchlist_move(self) -> float | None:
        """The watchlist's average % move on its latest closed candle (the news guard's
        price confirmation)."""
        if self.engine is None:
            return None
        moves = [
            100.0 * (st.raw[-1].close / st.raw[-2].close - 1.0)
            for st in self.engine.symbols
            if len(st.raw) >= 2 and st.raw[-2].close > 0
        ]
        return sum(moves) / len(moves) if moves else None

    def _day_move(self) -> float | None:
        """The watchlist's average % move today: its latest close against the last close of
        the previous trading day (D-198: whether world news has reached this market)."""
        if self.engine is None:
            return None
        moves = []
        for st in self.engine.symbols:
            if len(st.raw) < 2:
                continue
            last = st.raw[-1]
            day = local_date(self.market, last.ts)
            prev = next(
                (b for b in reversed(st.raw[:-1]) if local_date(self.market, b.ts) != day), None
            )
            if prev is not None and prev.close > 0:
                moves.append(100.0 * (last.close / prev.close - 1.0))
        return sum(moves) / len(moves) if moves else None

    def _bar_end(self, ts: int) -> int:
        return bar_end_ms(self.calendar, self.market, self.tf, ts)

    # ------------------------------------------------------------ loading

    def load(self) -> None:
        """Build the engine from the saved session: strategy, account, warm-up candles and
        (when resuming) the saved account state."""
        ctx = self.ctx
        with ctx.db.session() as s:
            row = s.get(PaperSession, self.id)
            assert row is not None
            acct = s.get(PaperAccount, row.account_id)
            assert acct is not None
            version = strategies.get_version(s, row.strategy_version_id)
            assert version is not None
            strat_name = s.scalar(select(Strategy.name).where(Strategy.id == version.strategy_id))
            self.strategy_id = version.strategy_id
            started_at = row.started_at
            d = version.definition
            self.market = Market(d.market)
            self.tf = Timeframe(d.timeframe)
            self.notes = json.loads(row.notes or "{}")
            d = with_session_settings(d, self.notes)
            insts, _, _ = ctx.backtests._instruments(
                s, d, self.notes.get("symbols") or None, self.market
            )
            profile = s.get(BrokerageProfile, acct.brokerage_profile_id)
            assert profile is not None
            rules = json.loads(profile.rules)
            settings = read_all(s)
            table = ChargeTable.load(s, self.market.value)
            saved_last = row.last_bar_ts
            saved_state = row.state
            capital = acct.starting_capital
            slippage = acct.slippage_bps
            for iid, total in s.execute(
                select(PaperTrade.instrument_id, func.sum(PaperTrade.net_pnl))
                .where(PaperTrade.session_id == self.id)
                .group_by(PaperTrade.instrument_id)
            ):
                self.realized[iid] = float(total or 0.0)
        self.name = strat_name or "Strategy"
        self.instruments = insts
        program = compile_definition(
            d, {k: float(v) for k, v in self.notes.get("overrides", {}).items()}
        )
        if program.brain is not None:
            # Kairos sessions lean on what Kairos has learned so far, refreshed each day and
            # after every lesson (D-60, D-138).
            learning = ctx.services.get("kairos_learning")
            if learning is not None:
                market, tf = self.market, self.tf
                program.brain.refresh = lambda: (
                    learning.weights(market, tf) or program.brain.weights
                )
                program.brain.stamp = lambda: int(getattr(learning, "version", 0))
                if hasattr(learning, "exit_plan"):
                    program.brain.exits = lambda: self._exit_plan(learning, market, tf)
                if self.replay_end_ms is None and hasattr(learning, "trade_judge"):
                    # live desks ask the trade judge before each entry (D-145)
                    program.brain.judge = lambda: self._judge(learning, market, tf)
                if self.replay_end_ms is None and tf is Timeframe.D1:
                    # live daily desks lean on today's forecast where it proved skill (D-175)
                    ids = {i.symbol: i.id for i in insts}
                    program.brain.forecast = lambda sym, ts: self._forecast(market, ids, sym, ts)
            if self.replay_end_ms is None and self._smaller_on():
                # live desks look at the smaller chart before an entry (D-177)
                refs = {i.symbol: i for i in insts}
                program.brain.closer = lambda sym, ts, side: self._closer(refs, sym, ts, side)
            if self.replay_end_ms is None and getattr(ctx, "news", None) is not None:
                # Live desks read the news for damage control (D-69); replays don't.
                from backend.kairos.news_guard import NewsGuard

                program.brain.news = NewsGuard(
                    ctx,
                    self.id,
                    self.market,
                    {i.symbol: i.id for i in insts},
                    live_from=self.clock.now_ms(),
                    bar_ms=self.tf.minutes * 60_000,
                    move_pct=self._watchlist_move,
                    home_move=self._day_move,
                )
        now = self.clock.now_ms()
        snap: dict[str, Any] | None = self.notes.get("engine")
        lo = now - warmup_ms(self.tf, program.warmup)
        hist = self.notes.get("history_from")
        if hist is not None:  # resume: same history start, so indicators continue unchanged
            lo = max(int(hist), now - MAX_HISTORY_MS)
        else:
            self.notes["history_from"] = lo
        if snap and snap.get("positions"):
            lo = min(lo, min(int(p["entry_ts"]) for p in snap["positions"].values()) - DAY_MS)
        states = []
        # Candles that closed while Agora was closed, recently enough to act on (D-181): they
        # are held back from the warm-up and traded as live candles once the engine is built,
        # as if Agora had been open. Before, a daily desk only decided if Agora was running at
        # the close: India closes at 2 am on the user's laptop, so its daily desk rarely did.
        held: dict[int, list[Bar]] = {}
        catch_up = saved_last is not None and self.replay_end_ms is None
        late = late_after_ms(self.tf)
        # a stock with an open trade replays every missed candle, however old (D-219): a real
        # stop rests at the broker while the laptop is off. On 29 Oct IOVA fell 28% overnight with
        # Agora closed, and the desk's stop only acted six days and 41% later. Entries stay blocked
        # on old candles (the "arrived late" rule in ``_process``), so only exits happen.
        holding = set((snap or {}).get("positions") or {}) if catch_up else set()
        missed_from: int | None = None
        for inst in insts:
            try:
                ctx.cache.ensure(inst, self.tf, lo, now)
            except Exception as exc:  # history is best effort; live candles still come
                log.warning("Warm-up fetch for %s failed: %r", inst.symbol, exc)
            raw = [
                b for b in ctx.cache.bars(inst, self.tf, lo, now + 1) if self._bar_end(b.ts) <= now
            ]
            if catch_up and saved_last is not None:
                later = [b for b in raw if b.ts > saved_last]
                recent = bool(later) and now - self._bar_end(later[0].ts) <= late
                if later and (recent or str(inst.id) in holding):
                    raw = raw[: len(raw) - len(later)]
                    held[inst.id] = later
                    if not recent:
                        missed_from = saved_last
            st = SymbolState(inst=inst, raw=raw, dividends=self._dividends(inst))
            st.last_index = len(raw) - 1
            states.append(st)
            self.last_ts[inst.id] = raw[-1].ts if raw else None
        if d.limits.max_per_group is not None:
            with ctx.db.session() as s:
                named = store.groups(s, [x.inst.id for x in states])
            for x in states:
                x.group = named.get(x.inst.id, "")
        cfg = EngineConfig(
            market=self.market,
            product=d.product,
            timeframe=self.tf,
            capital=capital,
            slippage_bps=slippage,
            volume_cap_pct=float(settings["volume_cap_pct"]),
            square_off=str(settings["intraday_square_off_time"]),
            max_open_positions=d.limits.max_open_positions,
            max_daily_loss_pct=d.limits.max_daily_loss_pct,
            max_position_pct=d.limits.max_position_pct,
            max_per_group=d.limits.max_per_group,
        )
        costs = CostModel(self.market.value, d.product, rules, table)
        engine = Engine(cfg, program, costs, states, listener=self._on_engine_event)
        check_mode = str(self.notes.get("trade_check") or "off")
        if check_mode != "off":
            # Kairos's trade check (KAIROS §16): it starts from what was known when the session
            # began, so a resumed session and a backtest of it judge the same way (D-71).
            from backend.kairos import samples as kairos_samples
            from backend.kairos.quality import TradeCheck, score_reader

            with ctx.db.session() as s:
                seed = kairos_samples.seed(
                    s,
                    strategy_id=self.strategy_id,
                    market=self.market.value,
                    timeframe=self.tf.value,
                    known_before=started_at,
                    saved_before=started_at,
                )
            engine.check = TradeCheck(check_mode, seed, score_for=score_reader())  # type: ignore[arg-type]
        resumed = snap is not None or saved_last is not None
        if snap is not None:
            for note in restore(engine, snap):
                self._event("info", "split", note)
            # orders saved before D-152 have only a count; they can't be put back
            kept, n = restore_orders(engine, snap) if "orders" in snap else (0, 0)
            if "orders" not in snap:
                n = int(snap.get("pending") or 0)
            if kept:
                self._event(
                    "info",
                    "resume",
                    f"{kept} order{'s' if kept != 1 else ''} waiting for the next candle "
                    f"{'were' if kept != 1 else 'was'} kept: no candle closed while Agora "
                    "was closed.",
                )
            if n:
                self._event(
                    "info",
                    "resume",
                    f"{n} order{'s' if n != 1 else ''} waiting for the next candle "
                    "were cancelled because a candle closed while Agora was closed.",
                )
        self.engine = engine
        self._trim(0)
        self.live_from = now
        self._actions_day = local_date(self.market, now).isoformat()
        if held:
            # trade the candles that closed while Agora was closed (D-181)
            self.live_from = min(self._bar_end(b[0].ts) for b in held.values()) - 1
        if missed_from is not None or (not held and resumed and saved_last is not None):
            assert saved_last is not None
            self._note_gap(self._bar_end(saved_last), now)
        if self.state == "stopped":
            # stopped while it loaded its prices (D-170): the autopilot stopped a desk mid-start
            # and the start then set it running again, so two desks ran for one slot
            return
        self.state = "paused_user" if saved_state == "paused_user" else "running"
        if not resumed:
            self._event("info", "started", f"Paper trading started with {len(insts)} stock(s).")
        else:
            self._event("info", "resumed", "Paper trading resumed.")
        if held:
            n = len({b.ts for bars in held.values() for b in bars})
            self._event(
                "info",
                "caught_up",
                f"{n} candle{'s' if n != 1 else ''} closed while Agora was closed; "
                f"{'they were' if n != 1 else 'it was'} traded as if Agora had been open.",
            )
            with self.lock:
                self._process(PollResult(ok=True, bars=held), now)
                self._save(now)

    def _trim(self, slack: int) -> None:
        """Keep a bounded number of candles in memory so a session left running for weeks
        stays as fast as on day one. Indices into ``raw`` shift with the cut."""
        engine = self.engine
        assert engine is not None
        keep = max(KEEP_BARS, 4 * engine.program.warmup)
        for st in engine.symbols:
            extra = len(st.raw) - keep
            if extra <= slack:
                continue
            st.raw = st.raw[extra:]
            st.last_index -= extra
            if st.position is not None:
                st.position.entry_index -= extra
            for o in st.pending:
                o.created_index -= extra
            st.build_series(self.tf)
            if st.ctx is not None and st.series is not None:
                st.ctx._provider.set_series(st.series)

    def _dividends(self, inst: InstrumentRef) -> dict[str, float]:
        zone = tz(inst.market)
        with self.ctx.db.session() as s:
            actions = store.load_actions(s, inst.id)
        return {
            ms_to_dt(a.ex_date, zone).strftime("%Y-%m-%d"): float(a.amount)
            for a in actions
            if a.kind == "dividend" and a.amount
        }

    def _note_gap(self, from_ms: int, to_ms: int) -> None:
        nxt = next_bar_close(self.calendar, self.market, self.tf, from_ms)
        if nxt is None or nxt > to_ms:
            return  # no candle closed while Agora was away
        gaps = self.notes.setdefault("gaps", [])
        gaps.append({"from": from_ms, "to": to_ms})
        checked = (
            " Open trades' stops and targets were checked on the missed candles."
            if (self.engine is not None and any(st.position for st in self.engine.symbols))
            else ""
        )
        self._event(
            "warn",
            "gap",
            # both dates, always: a six-day gap read "from Wed 28 Oct, 11:15 ET to 20:10 ET"
            f"Agora was closed from {self._dated(from_ms)} to {self._dated(to_ms)}. "
            f"New trades it would have made in that time were not simulated.{checked}",
            start=from_ms,
            end=to_ms,
        )

    def _on_engine_event(self, kind: str, data: dict[str, object]) -> None:
        if kind == "pause":
            self._event("warn", "daily_loss", str(data["message"]))
        elif kind == "dividend":
            amount = float(data["amount"])  # type: ignore[arg-type]
            self._event(
                "info", "dividend", f"Dividend of {amount:,.2f} credited for {data['symbol']}."
            )

    # ------------------------------------------------------------ one poll

    def tick(self) -> None:
        """Ask for new candles and process them (one cycle at the clock's now)."""
        if self.state in ("starting", "stopped") or self.engine is None:
            return
        now = self.clock.now_ms()
        if self.replay_end_ms is not None and now >= self.replay_end_ms:
            self.stop("The practice replay reached the end of the practice prices.")
            return
        since = {k: v for k, v in self.last_ts.items() if v is not None}
        result = self.feed.poll(self.instruments, self.tf, since)
        with self.lock:
            if self.state == "stopped":
                return
            self.last_poll_ms = now
            if not result.ok:
                self._poll_failed(result, now)
            else:
                self._poll_ok(now)
                self._process(result, now)
                self._check_behind(result, now)
                self._trim(TRIM_SLACK)
            self._save(now)
        if self.state == "stopped" and self.on_finish:
            self.on_finish(self.id)

    def _poll_failed(self, result: PollResult, now: int) -> None:
        self.failures += 1
        # once when an outage starts and when it pauses trading; every poll after that went to
        # the log 6,223 times in half an hour on 4 Nov, burying real problems
        say = log.warning if self.failures in (1, OUTAGE_AFTER) else log.debug
        say("Session %s: live poll failed: %s", self.id, result.detail)
        if self.failures == OUTAGE_AFTER:
            self.problem = (
                "Live prices aren't arriving right now. New trades are paused; open trades "
                "are kept. Agora keeps trying."
            )
            if self.state == "running":
                self.state = "paused_data"
            self._event("warn", "outage", self.problem, detail=result.detail)

    def _poll_ok(self, now: int) -> None:
        if self.failures >= OUTAGE_AFTER:
            self._event("info", "recovered", "Live prices are back. Trading continues.")
        self.failures = 0
        self.problem = None
        if self.state == "paused_data":
            self.state = "running"

    def _process(self, result: PollResult, now: int) -> None:
        engine = self.engine
        assert engine is not None
        by_ts: dict[int, list[tuple[SymbolState, Bar]]] = {}
        for iid, bars in result.bars.items():
            st = engine.by_id.get(iid)
            if st is None:
                continue
            for b in bars:
                by_ts.setdefault(b.ts, []).append((st, b))
        late = late_after_ms(self.tf)
        for ts in sorted(by_ts):
            end = self._bar_end(ts)
            live = end > self.live_from
            items: list[tuple[SymbolState, int]] = []
            for st, b in by_ts[ts]:
                if st.raw and b.ts <= st.raw[-1].ts:
                    continue
                st.raw.append(b)
                self.last_ts[st.inst.id] = b.ts
                if live:
                    items.append((st, len(st.raw) - 1))
                else:
                    st.last_index = len(st.raw) - 1
            if not items:
                continue
            day = local_date(self.market, ts).isoformat()
            if day != self._actions_day:
                self._actions_day = day
                self._new_day()
            if self.state == "paused_user":
                engine.entry_block = f"{self.pause_note}: no new trades."
            elif now - end > late:
                engine.entry_block = (
                    "Prices for this candle arrived late, so no new trade was opened on it."
                )
            else:
                engine.entry_block = None
            if live:
                self._news_hold()
            try:
                engine.step(ts, items)
            except SandboxError as exc:
                self._strategy_failed(f"Your strategy code stopped: {exc.sentence()}", repr(exc))
                return
            except (CompileError, ValueError, ArithmeticError) as exc:
                self._strategy_failed(f"The strategy couldn't run: {exc}", repr(exc))
                return

    def _new_day(self) -> None:
        """Once per trading day: pick up new splits and dividends (they change rarely, and
        dividends must be known by their ex-date)."""
        if not self.refresh_actions:
            return
        engine = self.engine
        assert engine is not None
        for st in engine.symbols:
            if st.inst.is_index:
                continue
            try:
                self.ctx.cache.refresh_actions(st.inst)
            except Exception as exc:
                log.warning("Corporate actions refresh failed for %s: %r", st.inst.symbol, exc)
                continue
            with self.ctx.db.session() as s:
                splits = split_events(store.load_actions(s, st.inst.id))
            refactored = with_factors(st.raw, splits)
            if [b.split_factor for b in refactored] != [b.split_factor for b in st.raw]:
                st.raw = refactored
                st.build_series(self.tf)
                if st.ctx is not None and st.series is not None:
                    st.ctx._provider.set_series(st.series)
            st.dividends = self._dividends(st.inst)

    def _strategy_failed(self, message: str, detail: str) -> None:
        log.warning("Session %s strategy error: %s", self.id, detail)
        self._event("error", "strategy_error", message, detail=detail)
        self.problem = message
        self._set_stopped("Paper trading stopped because the strategy hit an error.")

    def _check_behind(self, result: PollResult, now: int) -> None:
        expected = last_bar_close(self.calendar, self.market, self.tf, now - POLL_DELAY_MS)
        have = [self._bar_end(t) for t in self.last_ts.values() if t is not None]
        have_end = max(have) if have else None
        if expected is not None and (have_end is None or have_end < expected):
            self.behind_close = expected
        else:
            self.behind_close = None
        delayed = False
        if result.newest_seen and is_open(self.calendar, self.market, now):
            current = next_bar_close(self.calendar, self.market, self.tf, now)
            if current is not None:
                forming = bar_open_for_close(self.calendar, self.market, self.tf, current)
                step = self.tf.minutes * 60_000
                delayed = max(result.newest_seen.values()) < forming - 2 * step
        if delayed and not self.delayed:
            newest = max(result.newest_seen.values())
            self._event(
                "warn",
                "delayed",
                f"The data source is running late: its newest candle is from {self._when(newest)}.",
            )
        self.delayed = delayed

    # ------------------------------------------------------------ saving

    def _save(self, now: int) -> None:
        engine = self.engine
        assert engine is not None
        sid = self.id
        fills: list[dict[str, Any]] = []
        with self.ctx.db.session() as s:
            if engine.check is not None and engine.check.new_samples:
                from backend.kairos import samples as kairos_samples

                kairos_samples.save(
                    s,
                    strategy_id=self.strategy_id,
                    strategy_kind=engine.program.kind,
                    market=self.market.value,
                    timeframe=self.tf.value,
                    source="paper",
                    ref_id=sid,
                    samples=engine.check.new_samples,
                    now=now,
                )
                engine.check.new_samples = []
            for o in engine.orders:
                actions.note(
                    "desk_order",
                    f"{self.name}: {o.side} {o.qty:g} {o.symbol}",
                    o.reason,
                    who="engine",
                    status="ok" if o.status == "filled" else "skipped",
                    session_id=sid,
                    order_status=o.status,
                    price=o.price,
                    candle=o.ts,
                )
                row = PaperOrder(
                    session_id=sid,
                    instrument_id=o.instrument_id,
                    created_ts=o.ts,
                    type=o.type,
                    side=o.side,
                    qty=o.qty,
                    status=o.status,
                    reason=o.reason,
                )
                s.add(row)
                if o.status == "filled" and o.price is not None:
                    s.flush()
                    s.add(
                        PaperFill(
                            order_id=row.id,
                            ts=o.ts,
                            price=o.price,
                            qty=o.qty,
                            charges=o.charges,
                            slippage=o.slippage,
                        )
                    )
                    fills.append(
                        {
                            "session_id": sid,
                            "symbol": o.symbol,
                            "side": o.side,
                            "qty": o.qty,
                            "price": o.price,
                            "reason": o.reason,
                            "ts": o.ts,
                        }
                    )
            closed: list[tuple[PaperTrade, Any]] = []
            for t in engine.trades:
                if t.exit_reason == "end_of_test":
                    continue
                trade_row = PaperTrade(
                    session_id=sid,
                    instrument_id=t.instrument_id,
                    side=t.side,
                    qty=t.qty,
                    entry_ts=t.entry_ts,
                    entry_price=t.entry_price,
                    exit_ts=t.exit_ts,
                    exit_price=t.exit_price,
                    gross_pnl=t.gross_pnl,
                    charges=t.charges,
                    net_pnl=t.net_pnl,
                    return_pct=t.return_pct,
                    bars_held=t.bars_held,
                    entry_reason=t.entry_reason,
                    exit_reason=t.exit_reason,
                )
                s.add(trade_row)
                closed.append((trade_row, t))
                actions.note(
                    "trade_closed",
                    f"{self.name}: {t.side} {t.symbol}",
                    f"{t.exit_reason}: net {t.net_pnl:+.2f} ({t.return_pct:+.2f}%)",
                    who="engine",
                    why=t.entry_reason[:300],
                    session_id=sid,
                    net=t.net_pnl,
                    bars=t.bars_held,
                )
                self.realized[t.instrument_id] = self.realized.get(t.instrument_id, 0.0) + t.net_pnl
            if closed:
                s.flush()
            closed_info = [
                {
                    "id": row.id,
                    "instrument_id": t.instrument_id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "qty": t.qty,
                    "entry_ts": t.entry_ts,
                    "entry_price": t.entry_price,
                    "exit_ts": t.exit_ts,
                    "net_pnl": t.net_pnl,
                    "return_pct": t.return_pct,
                    "bars_held": t.bars_held,
                    "exit_reason": t.exit_reason,
                }
                for row, t in closed
            ]
            unrealized = self._unrealized()
            for p in engine.equity:
                s.merge(
                    PaperEquity(
                        session_id=sid,
                        ts=p.ts,
                        equity=p.equity,
                        cash=p.cash,
                        unrealized_pnl=unrealized,
                    )
                )
            s.execute(delete(PaperPosition).where(PaperPosition.session_id == sid))
            for st in engine.symbols:
                pos = st.position
                if pos is None:
                    continue
                s.add(
                    PaperPosition(
                        session_id=sid,
                        instrument_id=st.inst.id,
                        qty=pos.qty * pos.sign,
                        avg_price=pos.entry_price,
                        opened_ts=pos.entry_ts,
                        realized_pnl=self.realized.get(st.inst.id, 0.0),
                    )
                )
            for line in engine.logs[-MAX_LOG_EVENTS:]:
                self._event("info", "strategy_log", line)
            events = list(self._events)
            for level, kind, message, detail in events:
                s.add(
                    PaperEvent(
                        session_id=sid,
                        ts=now,
                        level=level,
                        kind=kind,
                        message_plain=message,
                        detail=json.dumps(detail),
                    )
                )
            row = s.get(PaperSession, sid)
            assert row is not None
            snap = snapshot(engine)
            snap["pending"] = sum(len(st.pending) for st in engine.symbols)
            self.notes["engine"] = snap
            self.notes["now"] = now
            row.notes = json.dumps(self.notes)
            stamps = [t for t in self.last_ts.values() if t is not None]
            if stamps:
                row.last_bar_ts = max(stamps)
            row.state = self.state
            if self.state == "stopped" and row.stopped_at is None:
                row.stopped_at = now
        engine.orders.clear()
        engine.trades.clear()
        engine.equity.clear()
        engine.logs.clear()
        self._events.clear()
        if engine.program.brain is not None:
            # A Kairos desk: its diary and learning (backend/kairos/desk.py). Never let it
            # stop paper trading.
            desk = self.ctx.services.get("kairos_desk")
            if desk is not None:
                try:
                    desk.after_save(self, closed_info)
                except Exception:
                    log.exception("Kairos desk bookkeeping failed for session %s", sid)
        bus = self.ctx.events
        for f in fills:
            bus.publish("paper.fill", f)
        for level, kind, message, _ in events:
            if kind == "strategy_log":
                continue
            bus.publish(
                "paper.event",
                {
                    "session_id": sid,
                    "level": level,
                    "kind": kind,
                    "message_plain": message,
                    "ts": now,
                },
            )
        bus.publish("paper.tick", self.tick_payload())

    def _unrealized(self) -> float:
        engine = self.engine
        assert engine is not None
        total = 0.0
        for st in engine.symbols:
            p = st.position
            if p is None or st.last_index < 0:
                continue
            total += (st.raw[st.last_index].close - p.entry_price) * p.qty * p.sign
        return total

    # ------------------------------------------------------------ status

    def freshness(self) -> Freshness:
        now = self.clock.now_ms()
        stamps = [t for t in self.last_ts.values() if t is not None]
        last = max(stamps) if stamps else None
        if self.state == "paused_data" or self.failures >= OUTAGE_AFTER:
            since = self._bar_end(last) if last else now
            return Freshness(
                "red",
                f"No live prices since {self._when(since)}",
                (now - since) // 1000,
                last,
                self.delayed,
            )
        if self.behind_close is not None and now - self.behind_close < GIVE_UP_BEHIND_MS:
            delay = max(0, now - self.behind_close - ACCEPT_AFTER_MS - POLL_DELAY_MS)
            level = "green" if delay < 120_000 else "amber" if delay < 600_000 else "red"
            return Freshness(
                level,
                f"Waiting for the {self._when(self.behind_close)} candle",
                delay // 1000,
                last,
                self.delayed,
            )
        if not is_open(self.calendar, self.market, now):
            nxt = next_session(self.calendar, self.market, now)
            text = (
                f"Market closed. Next open: {self._when(nxt.open_ms)}" if nxt else "Market closed"
            )
            return Freshness("closed", text, 0, last, False)
        text = f"Up to date · last candle {self._when(last)}" if last else "Up to date"
        if self.delayed:
            text = "Delayed data · " + text
        return Freshness("amber" if self.delayed else "green", text, 0, last, self.delayed)

    def positions(self) -> list[dict[str, Any]]:
        engine = self.engine
        if engine is None:
            return []
        out = []
        for st in engine.symbols:
            p = st.position
            if p is None:
                continue
            last = st.raw[st.last_index].close if st.last_index >= 0 else p.entry_price
            pnl = (last - p.entry_price) * p.qty * p.sign
            stop = p.stop
            if p.trail_level is not None:
                stop = (
                    p.trail_level
                    if stop is None
                    else (
                        max(stop, p.trail_level) if p.side == "long" else min(stop, p.trail_level)
                    )
                )
            out.append(
                {
                    "instrument_id": st.inst.id,
                    "symbol": st.inst.symbol,
                    "side": p.side,
                    "qty": p.qty,
                    "entry_price": p.entry_price,
                    "entry_ts": p.entry_ts,
                    "last_price": last,
                    "unrealized": pnl,
                    "unrealized_pct": 100.0 * pnl / (p.entry_price * p.qty) if p.qty else 0.0,
                    "stop": stop,
                    "target": p.target,
                    # the exits on show (D-210: the user couldn't see the trailing stop and the
                    # partial sale Kairos had chosen)
                    "trailing": p.trail is not None,
                    "trail_on": p.trail_level is not None and stop == p.trail_level,
                    "partial_at": p.scale[0].price if p.scale else None,
                    "reason": p.entry_reason,
                }
            )
        return out

    def tick_payload(self) -> dict[str, Any]:
        engine = self.engine
        f = self.freshness()
        equity = engine.equity_now() if engine else None
        return {
            "session_id": self.id,
            "state": self.state,
            "equity": equity,
            "cash": engine.cash if engine else None,
            "day_pnl": (equity - engine._day_start_equity)
            if engine and equity is not None
            else 0.0,
            "positions": self.positions(),
            "freshness_s": f.delay_s,
            "freshness": f.__dict__,
            "problem": self.problem,
            "now": self.clock.now_ms(),
        }

    # ------------------------------------------------------------ control

    def next_due(self) -> int | None:
        """When to poll next (clock ms), or None when the session is over."""
        if self.state == "stopped" or self.engine is None:
            return None
        now = self.clock.now_ms()
        if self.failures:
            wait = BACKOFF_MS[min(self.failures - 1, len(BACKOFF_MS) - 1)]
            return max(now, (self.last_poll_ms or now) + wait)
        if self.last_poll_ms is None:
            # just started: poll now, unless it already holds the latest closed candle, in which
            # case wait for the next close (D-197: after each restart the US desks polled 250
            # stocks each with their market closed and nothing new to fetch)
            have = [t for t in self.last_ts.values() if t is not None]
            done = last_bar_close(self.calendar, self.market, self.tf, now)
            if have and done is not None and self._bar_end(max(have)) >= done:
                nxt = next_bar_close(self.calendar, self.market, self.tf, now)
                return now if nxt is None else max(now, nxt + POLL_DELAY_MS)
            return now
        if self.behind_close is not None and now - self.behind_close < GIVE_UP_BEHIND_MS:
            return max(now, self.last_poll_ms + RETRY_BEHIND_MS)
        # The first candle whose poll moment (close + POLL_DELAY_MS) comes after the last poll.
        # Counted from the last poll, not from now: counted from now, a live loop that wakes
        # exactly at the due moment finds the following candle instead, sleeps again and never
        # polls (the desks missed all of 2026-10-26 that way).
        nxt = next_bar_close(self.calendar, self.market, self.tf, self.last_poll_ms - POLL_DELAY_MS)
        if nxt is None:
            return None
        return max(
            now, nxt + POLL_DELAY_MS, self.last_poll_ms + min(poll_interval_ms(self.tf), 60_000)
        )

    def transfer(self, amount: float, note: str) -> float:
        """Move portfolio money into (+) or out of (−) this session (PORTFOLIO §6, D-86). Out
        only up to free cash; open trades are never cut. Recorded in the session's notes so its
        P&L counts money moved, and saved at once."""
        with self.lock:
            if self.engine is None or self.state == "stopped":
                return 0.0
            now = self.clock.now_ms()
            moved = self.engine.transfer(amount, now, note)
            if moved:
                self.notes["moved"] = float(self.notes.get("moved", 0.0)) + moved
                self._event("info", "transfer", note)
                self._save(now)
            return moved

    def pause(self, message: str = "Paused by you.") -> None:
        with self.lock:
            if self.state in ("running", "paused_data"):
                self.state = "paused_user"
                self.pause_note = message.rstrip(".")
                self._event(
                    "info", "paused", f"{message} Open trades are still watched; no new trades."
                )
                self._save(self.clock.now_ms())
        self._wake.set()

    def resume(self) -> None:
        with self.lock:
            if self.state == "paused_user":
                self.state = "running"
                self._event("info", "resumed", "Resumed. New trades are allowed again.")
                self._save(self.clock.now_ms())
        self._wake.set()

    def relist(self, symbols: list[str], message: str) -> bool:
        """Save the session on a new stock list and end this runner's loop (D-217); the service
        then starts a fresh runner, which resumes exactly as after a restart. Open trades and
        waiting orders stay: their stocks are kept on the list whatever it says, so they still
        end by their own rules. ``False`` if the session isn't loaded yet (try again later)."""
        with self.lock:
            if self.engine is None or self.state in ("starting", "stopped"):
                return False
            keep = [
                st.inst.symbol
                for st in self.engine.symbols
                if st.position is not None or st.pending
            ]
            self.notes["symbols"] = list(dict.fromkeys([*symbols, *keep]))
            self._event("info", "list_moved", message)
            self._save(self.clock.now_ms())
            self._stop.set()
        self._wake.set()
        return True

    def _set_stopped(self, message: str) -> None:
        self.state = "stopped"
        self._event("info", "stopped", message)
        self._stop.set()
        self._wake.set()

    def stop(self, message: str = "Paper trading stopped by you.") -> None:
        with self.lock:
            if self.state == "stopped":
                return
            self._set_stopped(message)
            if self.engine is not None:
                self._save(self.clock.now_ms())
            else:
                self._save_state_only()
        if self.on_finish:
            self.on_finish(self.id)

    def _save_state_only(self) -> None:
        with self.ctx.db.session() as s:
            row = s.get(PaperSession, self.id)
            if row is not None:
                row.state = self.state
                row.stopped_at = row.stopped_at or self.clock.now_ms()
                for level, kind, message, detail in self._events:
                    s.add(
                        PaperEvent(
                            session_id=self.id,
                            ts=self.clock.now_ms(),
                            level=level,
                            kind=kind,
                            message_plain=message,
                            detail=json.dumps(detail),
                        )
                    )
        self._events.clear()

    # ------------------------------------------------------------ driving

    def _forecast(self, market: Market, ids: dict[str, int], sym: str, ts: int) -> float:
        """Score points from today's forecast for ``sym``, if forecasts proved skill (D-175).
        The skill test is read once a day per session."""
        from backend.kairos import forecast_desk

        day = local_date(market, self.clock.now_ms()).isoformat()
        if getattr(self, "_fc_day", None) != day:
            self._fc_day = day
            self._fc_ok = bool(forecast_desk.skill(self.ctx, market.value)["proven"])
        if not self._fc_ok or sym not in ids:
            return 0.0
        return forecast_desk.nudge(forecast_desk.todays(self.ctx, ids[sym], Timeframe.D1, ts))

    def _news_hold(self) -> int:
        """Cancel a desk's buys waiting for the next open when severe news has reached this
        market (D-190): the India daily desk queued ten buys at the 5 Nov close on calm news, and
        by the next open a global sell-off read 84. Since D-211 (news is caution, not a stop) the
        buys go only when the market itself is down 1%+ today, and buys in a sector the news
        helps stand. Exits still go ahead. Only Kairos desks have a news guard."""
        engine = self.engine
        brain = getattr(getattr(engine, "program", None), "brain", None)
        guard = getattr(brain, "news", None)
        if engine is None or guard is None:
            return 0
        try:
            if guard.mode() != "protective":
                return 0
            gauge = self.ctx.news.risk(self.market)
            level = float(gauge.get("level") or 0.0)
        except Exception:  # the news must never stop the desk
            return 0
        from backend.kairos.news_guard import CONFIRM_MOVE_PCT, SECTOR_EDGE, SEVERE, sector_effect

        if level < SEVERE:
            return 0
        today = self._day_move()
        if today is None or today > CONFIRM_MOVE_PCT:
            return 0  # the market isn't falling with the news: the buys stand (D-198, D-211)
        exposure = getattr(guard, "exposure", None)
        dropped = 0
        for st in engine.symbols:
            if exposure is not None:
                push, _ = sector_effect(gauge, exposure(st.inst.id))
                if push >= SECTOR_EDGE:
                    continue  # the news helps this stock's sector: an opportunity, keep it
            keep = [o for o in st.pending if o.kind != "entry"]
            dropped += len(st.pending) - len(keep)
            st.pending = keep
        if dropped:
            self._event(
                "warn",
                "news_cancel",
                f"{dropped} order{'s' if dropped != 1 else ''} to buy at this open "
                f"{'were' if dropped != 1 else 'was'} cancelled: the news risk is severe "
                f"({level:.0f}/100) and this market is {today:+.1f}% today.",
            )
        return dropped

    def _smaller_on(self) -> bool:
        from backend.kairos import closer

        if self.tf.value not in closer.SMALLER:
            return False
        try:
            with self.ctx.db.session() as s:
                return bool(read_all(s)["kairos.smaller_chart"])
        except Exception:
            return False

    def _closer(self, refs: dict[str, InstrumentRef], sym: str, ts: int, side: int) -> bool:
        """The smaller chart's verdict on an entry at the candle ``ts`` (D-177): read only its
        candles that closed by the end of this candle (one request, only for this stock)."""
        from backend.kairos import closer

        inst = refs.get(sym)
        if inst is None:
            return False
        small = Timeframe(closer.SMALLER[self.tf.value])
        end = self._bar_end(ts)
        start = end - closer.LOOKBACK_DAYS[small.value] * 86_400_000
        step = small.minutes * 60_000
        try:
            self.ctx.cache.ensure(inst, small, start, end)
            bars = self.ctx.cache.bars(inst, small, start, end)
        except Exception as exc:
            log.debug("No %s candles for %s: %r", small.value, sym, exc)
            return False
        closes = [b.close for b in bars if b.ts + step <= end]
        return closer.says_no(closes, side)

    def _judge(self, learning: Any, market: Market, tf: Timeframe) -> Any:
        try:
            with self.ctx.db.session() as s:
                if not bool(read_all(s)["kairos.judge"]):
                    return None
            return learning.trade_judge(market, tf)
        except Exception:
            log.exception("Couldn't read the trade judge")
            return None

    def _exit_plan(self, learning: Any, market: Market, tf: Timeframe) -> Any:
        """Kairos's chosen exits (D-140), unless Settings → Kairos says to use the numbers."""
        with self.ctx.db.session() as s:
            if not read_all(s)["kairos.auto_exits"]:
                return None
        return learning.exit_plan(market, tf)

    def start_thread(self, *, replay_pace_s: float | None = None) -> None:
        target = self._replay_loop if replay_pace_s is not None else self._live_loop
        self._pace = replay_pace_s or 0.0
        self._thread = threading.Thread(target=target, name=f"agora-paper-{self.id}", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        """Agora is closing: stop the loop but keep the session's state for a resume."""
        self._stop.set()
        self._wake.set()

    def _boot(self) -> bool:
        """Load the session. A busy database is a reason to wait, never to stop: on 6 Nov a list
        update of 50 seconds made seven sessions fail at their start, each marked stopped for good
        (D-225). If it is still busy after a few minutes the session stays as it was saved and
        carries on at the next start."""
        for attempt in range(BOOT_TRIES):
            try:
                return self._boot_once()
            except OperationalError as exc:
                log.warning("Paper session %s: database busy (try %d)", self.id, attempt + 1)
                self._events.clear()
                self.engine = None
                detail = repr(exc)
                if self._stop.wait(BOOT_WAIT_S):
                    return False
        self.state = "paused_data"
        self.problem = "The database was too busy to start this session. Restart Agora."
        actions.note("desk_event", f"{self.name or self.id}: start", detail, status="failed")
        return False

    def _boot_once(self) -> bool:
        try:
            self.load()
            with self.lock:
                self._save(self.clock.now_ms())
            return True
        except OperationalError:
            raise
        except SandboxError as exc:
            self._strategy_failed(f"Your strategy code stopped: {exc.sentence()}", repr(exc))
        except Exception as exc:
            log.exception("Paper session %s couldn't start", self.id)
            self._event(
                "error",
                "start_failed",
                "Paper trading couldn't start. Try starting it again.",
                detail=repr(exc),
            )
            self.problem = "Paper trading couldn't start."
            self.state = "stopped"
        with self.lock:
            self._save_state_only()
        if self.on_finish:
            self.on_finish(self.id)
        return False

    def _safe_tick(self) -> None:
        try:
            self.tick()
        except Exception as exc:  # keep the session alive; count it like an outage
            log.exception("Paper session %s tick failed", self.id)
            with self.lock:
                self.failures += 1
                self.last_poll_ms = self.clock.now_ms()
                if self.failures == OUTAGE_AFTER:
                    self._event(
                        "error",
                        "tick_failed",
                        "Something went wrong while updating this session. Agora keeps trying.",
                        detail=repr(exc),
                    )

    def _live_loop(self) -> None:
        if not self._boot():
            return
        while not self._stop.is_set():
            due = self.next_due()
            if due is None:
                break
            wait = (due - self.clock.now_ms()) / 1000
            if wait > 0:
                if self._wake.wait(min(wait, 30.0)):
                    self._wake.clear()
                continue
            self._safe_tick()

    def _replay_loop(self) -> None:
        if not self._boot():
            return
        while not self._stop.is_set():
            if not self.replay_step():
                break
            self._stop.wait(self._pace)

    def replay_step(self) -> bool:
        """Jump the (fake) clock to the next poll and run it. False when finished."""
        due = self.next_due()
        if due is None:
            return False
        set_clock = getattr(self.clock, "set", None)
        if set_clock is not None:
            set_clock(max(due, self.clock.now_ms()))
        self._safe_tick()
        return self.state != "stopped"
