"""The autopilot: Kairos and Metis start working the moment Agora opens (SPEC §18, D-99).

The user asked (2026-10-23) that, once he opens Agora (and Ollama is connected), Kairos and Metis
start on their own without him adding stocks or strategies. With the setting ``autopilot`` on
(the default), a thread that lives only while Agora is open does, in rounds:

1. **Prices**: tops up daily history for what the desks, sectors, factor lists and the world
   desk read: the market's index stocks, the broad index (Nifty 200 / S&P 500), the sector and
   volatility gauges, the confirming assets (oil, gold, the dollar, bonds, USD/INR) and the
   sector ETFs; then every other index stock, then every other stock on the exchange (D-102), a
   batch per round, four at a time, until all are in. Already-saved candles are never fetched
   again. While stocks are still waiting, the next round starts 20 seconds after the last.
2. **Reading the market**: rebuilds the factor lists and the sector readings (once a day).
3. **Kairos's picks and desks**: picks its own stocks (``kairos/picks.py``) and, for each of the
   user's markets with no Kairos desk running, starts one on those picks (paper money; the
   trading decisions are the Kairos brain's code, D-56). Once a week, when the autopilot's desk
   holds no open trades and the picks changed a lot, it moves the desk to the new picks with
   the money it has.
4. **Trials**: Kairos tries, on their own small paper money, the strategies Metis saved that
   it thinks work, at most ``kairos.trials`` per market, and keeps or retires each by how it
   does live (``kairos/trials.py``, D-139).
5. **Metis** researches on its own (``metis.enabled``, on by default); it thinks with the AI
   helper as soon as Ollama is ready and works from its playbook until then.

Nothing runs while Agora is closed (D-06): the desks resume when it opens again, without
back-filling trades. Switching the autopilot off stops new desks from being started (running
desks keep going until stopped on the Kairos desk screen).
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from backend import actions
from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.data import store
from backend.db.models import SettingRow
from backend.kairos import trials
from backend.logging_setup import get_logger
from backend.settings_store import read_all
from backend.watchlists import catalog, seed

log = get_logger("autopilot")
DAY_MS = 86_400_000
FIRST_WAIT_S = 20.0
TICK_S = 300.0  # a round every 5 minutes once every stock is in (D-102)
BUSY_TICK_S = 20.0  # while stocks are still waiting for their history, the next round soon
BATCH = 250  # new stocks downloaded per round while the market fills in
TOP_UP = 1000  # already-saved stocks brought up to date per round
# At most this long topping up prices in one round (D-186): a round of 1,000 downloads took about
# 90 minutes, and the desks, trials, forecasts and news waited behind it; the rest of the list
# carries on in the next round (20 seconds later while there's a backlog).
PRICE_BUDGET_S = 600.0
OPEN_BUDGET_S = 120.0  # … and this long while a market is open (D-192)
WORKERS = 4  # downloads at once; the Yahoo throttle still spaces every request (~1 a second)
STATE_KEY = "_autopilot.state"  # private (not a user setting)
SHORT_DESKS = ("1h", "15m")  # the short-term desks "All" runs (D-132; 5m and 1m retired, D-177)
RANK_EVERY_MS = 4 * 3_600_000  # rank the whole market again after this long (D-133)
CHANGE_SHARE = 0.4  # move the desk when this share of the picks changed
CLUE_SYMBOLS = {
    "US": ["SPY", "USO", "BNO", "GLD", "UUP", "TLT", "VIX"],
    "IN": ["NIFTY50", "USDINR"],
}
BROAD = {"IN": "nifty200", "US": "sp500"}


class Autopilot:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.doing = ""
        self.last: dict[str, Any] = {}
        self._rest_cache: dict[str, Any] = {}
        self._counts: dict[str, tuple[int, int]] = {}
        self._haves: dict[str, tuple[int, int]] = {}
        self._ranked: dict[str, tuple[int, list[dict[str, Any]]]] = {}
        self._topping_up: dict[str, int] = {}  # stocks still waiting for today's prices (D-182)
        self._recounting: set[str] = set()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self.ctx.data_mode != "real" and not os.environ.get("AGORA_AUTOPILOT"):
            return
        self._thread = threading.Thread(target=self._loop, name="autopilot", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def poke(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        if self._stop.wait(FIRST_WAIT_S):
            return
        while not self._stop.is_set():
            backlog = False
            try:
                if self.on():
                    out = self.round()
                    backlog = any(
                        isinstance(v, dict) and v.get("waiting", 0) > 0 and v.get("fetched", 0) > 0
                        for k, v in out.items()
                        if k.startswith("prices_")
                    )
            except Exception:  # the autopilot must never take the app down
                log.exception("Autopilot round failed")
            self._wake.wait(BUSY_TICK_S if backlog else TICK_S)
            self._wake.clear()

    def on(self) -> bool:
        with self.ctx.db.session() as s:
            return bool(read_all(s)["autopilot"])

    # ------------------------------------------------------------ state

    def _state(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            row = s.get(SettingRow, STATE_KEY)
            return dict(json.loads(row.value)) if row else {}

    def _save(self, state: dict[str, Any]) -> None:
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            row = s.get(SettingRow, STATE_KEY)
            if row is None:
                s.add(SettingRow(key=STATE_KEY, value=json.dumps(state), updated_at=now))
            else:
                row.value = json.dumps(state)
                row.updated_at = now

    # ------------------------------------------------------------ one round

    def round(self) -> dict[str, Any]:
        """One pass over every step (each step is skipped when it isn't due)."""
        if not self._lock.acquire(blocking=False):
            return {"skipped": "already running"}
        act = actions.track("autopilot_round", "Autopilot round", who="autopilot")
        try:
            out: dict[str, Any] = {}
            self.ctx.watchlists.ensure()
            with self.ctx.db.session() as s:
                markets = [m for m in read_all(s)["markets"] if m in ("IN", "US")]
            state = self._state()
            sectors = getattr(self.ctx, "sectors", None)
            for m in markets:  # first, so Watchlists is quick right after a restart (D-117)
                self.doing = "Reading sectors…"
                try:
                    if sectors is not None:
                        sectors.overview(m)
                except Exception:
                    log.exception("Autopilot couldn't read %s sectors", m)
            for m in markets:
                self.doing = f"Topping up {'Indian' if m == 'IN' else 'US'} prices…"
                out[f"prices_{m}"] = self.prices(m, state)
                self._topping_up[m] = int(out[f"prices_{m}"].get("waiting", 0))
                self._save(state)  # keep the progress even if Agora closes mid-round
            self.doing = "Reading sectors and factor lists…"
            out["factors"] = self.ctx.watchlists.refresh_factors()
            with self.ctx.db.session() as s:
                short = str(read_all(s)["autopilot.intraday_desk"])
            # shorter-timeframe desks too (D-118), every one of them by default (D-132)
            shorts = SHORT_DESKS if short == "all" else () if short == "off" else (short,)
            for m in markets:
                self.doing = f"Kairos is picking {'Indian' if m == 'IN' else 'US'} stocks…"
                out[f"desk_{m}"] = self.desk(m, state)
                for tf in shorts:
                    try:
                        out[f"desk_{m}_{tf}"] = self.desk(m, state, Timeframe(tf))
                    except Exception:
                        log.exception("Autopilot couldn't run the %s %s desk", m, tf)
                self.retire(m, state, shorts)
            for m in markets:  # forecasts made and checked every day, after the close (D-175)
                try:
                    with actions.track("forecasts", f"{m} forecasts", who="autopilot") as a:
                        out[f"forecasts_{m}"] = self.forecasts(m, state)
                        a.done(str(out[f"forecasts_{m}"])[:300])
                except Exception:
                    log.exception("Autopilot couldn't run the %s forecasts", m)
            for m in markets:  # Metis's strategies Kairos thinks work, on trial (D-139)
                self.doing = "Kairos is weighing Metis's strategies…"
                try:
                    with actions.track("kairos_trials", f"{m} trials", who="kairos") as a:
                        out[f"trials_{m}"] = trials.run(self.ctx, m, state)
                        a.done(str(out[f"trials_{m}"])[:300])
                except Exception:
                    log.exception("Autopilot couldn't run Kairos's %s trials", m)
            news = self.ctx.services.get("news")
            if news is not None and news.enabled():
                news.ensure_fresh(news.feeds() + news.world_feeds())
            metis = self.ctx.services.get("metis")
            if metis is not None:
                metis.poke()
            state["last_round"] = self.ctx.clock.now_ms()
            self._save(state)
            self.last = out
            act.done(
                "; ".join(
                    f"{k} {v.get('status')}"
                    for k, v in out.items()
                    if isinstance(v, dict) and v.get("status")
                )
            )
            return out
        except Exception as exc:
            act.failed(repr(exc))
            raise
        finally:
            self.doing = ""
            self._lock.release()

    # ------------------------------------------------------------ 1. prices

    def wanted(self, market: str) -> list[str]:
        """Symbols whose daily history the autopilot keeps, in the order it fetches them."""
        with self.ctx.db.session() as s:
            core = [i.symbol for i in data_service.default_symbols(s, Market(market))]
            broad = [
                sym
                for iid, sym in s.execute(
                    select_ids(seed.members(s, market, {"list": BROAD[market]}))
                ).all()
            ]
        gauges = [g[1] for g in catalog.GAUGES if g[0] == market]
        # every index on the Indices page keeps its daily history too (D-174)
        gauges += [g[1] for g in catalog.INDICES if g[0] == market and g[1] not in gauges]
        etfs = []
        if market == "US":
            etfs = [
                "XLK",
                "XLF",
                "XLE",
                "XLV",
                "XLY",
                "XLP",
                "XLI",
                "XLB",
                "XLU",
                "XLRE",
                "XLC",
            ]
        indexed, listed = self._rest(market)
        broad = [x for x in broad if not seed.is_test_symbol(x)]  # D-184
        seen: dict[str, None] = {}
        first = [*CLUE_SYMBOLS.get(market, []), *core, *gauges, *etfs, *broad]
        for sym in [*first, *indexed, *listed]:
            seen.setdefault(sym, None)
        return list(seen)

    def _rest(self, market: str) -> tuple[list[str], list[str]]:
        """After the broad index: every other index stock, then the rest of the market (the
        user's request 2026-10-24, D-102). Cached: the lists change only with the seed files."""
        key = market  # the seed files don't change while Agora runs
        if market not in self._rest_cache:
            from backend.db.models import Instrument, InstrumentProfile

            with self.ctx.db.session() as s:
                rows = s.execute(
                    select(Instrument.symbol, InstrumentProfile.lists)
                    .join(InstrumentProfile, InstrumentProfile.instrument_id == Instrument.id)
                    .where(
                        Instrument.market_code == market,
                        Instrument.instrument_type == "equity",
                        Instrument.is_active == 1,
                    )
                    .order_by(Instrument.symbol)
                ).all()
            indexed = [sym for sym, lists in rows if lists and lists != seed.LISTED_ONLY]
            listed = [sym for sym, lists in rows if lists == seed.LISTED_ONLY]
            self._rest_cache[market] = (key, indexed, listed)
        _, indexed, listed = self._rest_cache[market]
        return list(indexed), list(listed)

    def _session_key(self, market: str, now: int) -> int:
        """The date of the market's latest closed session, as a day number."""
        from backend.markets.calendar import local_date
        from backend.paper.timing import last_bar_close

        try:
            close = last_bar_close(self.ctx.calendar, Market(market), Timeframe.D1, now)
        except Exception:
            close = None
        if close is None:
            return int(now // DAY_MS)
        return local_date(Market(market), close).toordinal()

    def _any_market_open(self) -> bool:
        from backend.markets.calendar import is_open

        now = self.ctx.clock.now_ms()
        try:
            return any(is_open(self.ctx.calendar, m, now) for m in (Market.IN, Market.US))
        except Exception:  # a calendar problem mustn't stop the top-up
            return False

    def _last_daily(self, market: str) -> dict[str, int]:
        """Each stock's newest saved daily candle (one query for the whole market)."""
        from backend.db.models import Candle, Instrument

        with self.ctx.db.session() as s:
            rows = s.execute(
                select(Instrument.symbol, func.max(Candle.ts))
                .join(Candle, Candle.instrument_id == Instrument.id)
                .where(Instrument.market_code == market, Candle.timeframe == "1d")
                .group_by(Instrument.symbol)
            ).all()
        return {sym: int(ts or 0) for sym, ts in rows}

    def prices(self, market: str, state: dict[str, Any]) -> dict[str, int]:
        """Top up daily history: everything already started, plus the next batch of the broad
        index, at most once a day per symbol."""
        now = self.ctx.clock.now_ms()
        # "today" is the market's latest closed session, not the UTC day (D-203): India's UTC
        # day starts at 05:30 IST, before its 15:30 close, so its top-up always ran before the
        # close and most Indian stocks' daily prices lagged a day
        today = self._session_key(market, now)
        done: dict[str, int] = state.setdefault("prices", {}).setdefault(market, {})
        symbols = self.wanted(market)
        todo = [x for x in symbols if done.get(x, -1) != today]
        # the stalest first (D-185): after prices stopped for days, a round spent its hour on
        # stocks that were already current while thousands waited at the end of the list
        last = self._last_daily(market)
        # … but a stock silent for a month is likely delisted: Yahoo's refusals cost retries,
        # so those go after the ones that stopped recently
        dead = now - 30 * DAY_MS
        started = sorted(
            (x for x in todo if x in done),
            key=lambda x: (last.get(x, 0) < dead, last.get(x, 0)),
        )
        fresh = started[:TOP_UP] + [x for x in todo if x not in done][:BATCH]
        start = data_service.full_start_ms(Timeframe.D1, now)
        name = "Indian" if market == "IN" else "US"
        counts = {"got": 0, "failed": 0}
        count_lock = threading.Lock()

        # while a market trades, the desks' live candles come first (D-192): one download at a
        # time and a short budget, so the top-up doesn't crowd the desks' polls off Yahoo
        trading = self._any_market_open()
        workers = 1 if trading else WORKERS
        deadline = time.monotonic() + (OPEN_BUDGET_S if trading else PRICE_BUDGET_S)

        def one(sym: str) -> None:
            if self._stop.is_set() or time.monotonic() > deadline:
                return
            with self.ctx.db.session() as s:
                ref = store.find_instrument(s, Market(market), sym)
            if ref is None:
                return
            try:
                got = self.ctx.cache.ensure(ref, Timeframe.D1, start, now)
                # a paused source means nothing was asked for: not up to date (D-182: Yahoo
                # paused for a day on 4 Nov and ~5,000 stocks were marked done without a single
                # download, so Kairos ranked on prices up to ten days old)
                ok = not getattr(got, "waited", False)
            except Exception as exc:  # one stock's failure mustn't stop the rest
                log.info("Autopilot couldn't fetch %s: %r", sym, exc)
                ok = False
            with count_lock:
                if ok:
                    done[sym] = int(today)
                    counts["got"] += 1
                else:
                    counts["failed"] += 1
                n = counts["got"] + counts["failed"]
                self.doing = f"Topping up {name} prices… {n} of {len(fresh)} this round"

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="autopilot-prices") as pool:
            list(pool.map(one, fresh))
        got = counts["got"]
        return {"fetched": got, "failed": counts["failed"], "waiting": len(todo) - got}

    # ------------------------------------------------------------ 3. desks

    def ranked(self, market: str) -> list[dict[str, Any]]:
        """Kairos's ranking of every stock of the market (D-133), shared by all its desks and
        made again every few hours (daily prices change once a day; ranking thousands of stocks
        reads every one's saved prices)."""
        from backend.kairos import picks

        now = self.ctx.clock.now_ms()
        hit = self._ranked.get(market)
        # while the day's prices are still coming in, keep the last ranking rather than rank
        # on half-updated prices (D-182)
        topping_up = self._topping_up.get(market, 0) > 0 and hit is not None and bool(hit[1])
        if hit is None or (now - hit[0] >= RANK_EVERY_MS and not topping_up) or not hit[1]:
            hit = (now, picks.rank(self.ctx, market))
            self._ranked[market] = hit
            log.info("Kairos ranked %s stocks: %d picks", market, len(hit[1]))
        return hit[1]

    def desk(
        self, market: str, state: dict[str, Any], tf: Timeframe = Timeframe.D1
    ) -> dict[str, Any]:
        from backend.kairos import picks
        from backend.markets.calendar import is_open

        now = self.ctx.clock.now_ms()
        desks: dict[str, Any] = state.setdefault("desks", {})
        slot = market if tf is Timeframe.D1 else f"{market}:{tf.value}"
        mine = desks.get(slot) or {}
        # every desk takes the best of the whole market (D-133), as many as its candles allow;
        # a short desk's warm-up downloads the recent history its stocks don't have yet
        ranked = self.ranked(market)[: picks.DESK_SIZE.get(tf.value, picks.N_PICKS)]
        if not ranked:
            return {"status": "waiting", "why": "no stocks with saved prices yet"}
        if tf is Timeframe.D1:
            picks.save(self.ctx, market, ranked)
        symbols = [p["symbol"] for p in ranked]
        running = [
            d
            for d in self.ctx.desk.desks()
            if d["market"] == market
            and d["state"] != "stopped"
            and d.get("timeframe", "1d") == tf.value
        ]
        ours = next((d for d in running if d["id"] == mine.get("session_id")), None)
        if running and ours is None:
            return {"status": "user_desk", "session_id": running[0]["id"]}
        if ours is not None:
            # the stocks the desk really follows, not the list it was handed (D-191: a desk
            # handed 250 kept 30, and the autopilot thought it had 250)
            held = set(ours.get("symbols") or mine.get("symbols") or [])
            changed = len(set(symbols) - held) / max(1, len(symbols))
            # every desk follows the market's best each day (D-133), moved before the open so a
            # desk isn't reloading during trading; 258 big days of October happened in stocks of
            # the 250 that a desk hadn't taken up yet (D-224)
            stale = now - int(mine.get("started_at") or 0) >= DAY_MS and not is_open(
                self.ctx.calendar, Market(market), now
            )
            # flat: no open trades and no order waiting for the next candle (D-169: a daily
            # desk restarted with ten buys waiting for the open lost them all)
            flat = not ours.get("open_positions") and not self._waiting(ours["id"])
            # the desk's list grew (30 → 250 stocks, D-177)
            grown = len(symbols) >= 1.5 * max(1, len(held))
            # Settings → Kairos changed since the desk started (D-128): restart it once flat
            outdated = flat and self.ctx.desk.rules_outdated(ours["id"])
            if not outdated and (grown or (stale and changed >= CHANGE_SHARE)):
                # Move the list where the desk stands (D-217, replacing D-213's pause): a daily
                # desk's trades last weeks, so waiting to be flat cost it weeks of new trades.
                return self._relist(market, tf, ours, mine, symbols, held, now)
            if not outdated:
                return {"status": "running", "session_id": ours["id"]}
            if outdated:
                log.info("Autopilot restarts the %s %s desk with new settings", market, tf.value)
            capital = float(ours.get("equity") or 0) or None
            # the new run carries on the old one's money, so its return counts from the first
            first = float(ours.get("first_capital") or 0) or None
            self.ctx.desk.stop(
                ours["id"], "The autopilot ended this run; the desk carries on in a new one."
            )
        else:
            capital = first = None
        if tf is Timeframe.D1:
            insts = self.ctx.watchlists.instruments(
                self.ctx.watchlists.find(f"Kairos · {picks.NAME[market]}", market)["id"]
            )
        else:
            with self.ctx.db.session() as s:
                insts = [
                    i for sym in symbols if (i := store.find_instrument(s, Market(market), sym))
                ]
        held = set(mine.get("symbols") or [])
        d = self.ctx.desk.launch(insts, tf, capital, first)
        if held and set(symbols) != held:
            # new stocks: study again so the trade judge's verdict (trade or stand aside) is
            # about the stocks the desk now trades (D-172: the US 15-minute desk kept trading on
            # a verdict from its old stocks, then stood aside once re-studied)
            try:
                self.ctx.learning.start_training(Market(market), tf)
            except Exception:  # a study that can't start now runs at the learner's next round
                log.exception("Couldn't start a study for the %s %s desk", market, tf.value)
        desks[slot] = {"session_id": d["id"], "symbols": symbols, "started_at": now}
        log.info("Autopilot started Kairos's %s %s desk on %d stocks", market, tf.value, len(insts))
        actions.note(
            "desk_started",
            f"{market} {tf.value} desk",
            f"Session {d['id']} on {len(insts)} stocks",
            who="autopilot",
            session_id=d["id"],
        )
        return {"status": "started", "session_id": d["id"], "stocks": len(insts)}

    def _relist(
        self,
        market: str,
        tf: Timeframe,
        ours: dict[str, Any],
        mine: dict[str, Any],
        symbols: list[str],
        held: set[str],
        now: int,
    ) -> dict[str, Any]:
        """A running desk moves to its new list with its money and open trades (D-217)."""
        sid = int(ours["id"])
        message = (
            f"The desk now follows {len(symbols)} stocks (it followed {len(held)}). "
            "Open trades carry on."
        )
        if not self.ctx.paper.relist(sid, symbols, message):
            return {"status": "running", "session_id": sid}
        mine.update(symbols=symbols, started_at=now)
        actions.note(
            "desk_moved",
            f"{market} {tf.value} desk",
            message,
            who="autopilot",
            why="its list changed",
            session_id=sid,
        )
        log.info(
            "Autopilot moved the %s %s desk from %d to %d stocks",
            market,
            tf.value,
            len(held),
            len(symbols),
        )
        try:  # as after any change of stocks (D-172)
            self.ctx.learning.start_training(Market(market), tf)
        except Exception:  # a study that can't start now runs at the learner's next round
            log.exception("Couldn't start a study for the %s %s desk", market, tf.value)
        return {"status": "moved", "session_id": sid, "stocks": len(symbols)}

    def retire(self, market: str, state: dict[str, Any], shorts: tuple[str, ...]) -> list[int]:
        """Stop the autopilot's short desks on timeframes it no longer runs (D-177: the 5- and
        1-minute desks, which lost to costs on every test, were retired at the user's request),
        once they have no open trades; a desk with trades open finishes them first."""
        desks: dict[str, Any] = state.setdefault("desks", {})
        stopped: list[int] = []
        live = {d["id"]: d for d in self.ctx.desk.desks()}
        for slot in list(desks):
            if not slot.startswith(f"{market}:") or slot.split(":", 1)[1] in shorts:
                continue
            sid = desks[slot].get("session_id")
            d = live.get(sid)
            if d is not None and d["state"] != "stopped":
                if d.get("open_positions") or self._waiting(int(sid)):
                    continue
                self.ctx.desk.stop(sid, "The autopilot retired this desk.")
                stopped.append(int(sid))
                log.info("Autopilot retired Kairos's %s %s desk", market, slot.split(":", 1)[1])
            desks.pop(slot)
        return stopped

    def forecasts(self, market: str, state: dict[str, Any]) -> dict[str, Any]:
        """Once a trading day, after the close: forecast every stock the daily desk trades and
        check every forecast that has come due (D-175)."""
        from backend.kairos import forecast_desk
        from backend.markets.calendar import local_date

        now = self.ctx.clock.now_ms()
        today = local_date(Market(market), now)
        # the latest session that has closed, not just today's: Agora opened after midnight in
        # the market's own time still runs the round for the day that just ended
        sessions = self.ctx.calendar.sessions(Market(market), today - timedelta(days=7), today)
        done = [x for x in sessions if now >= x.close_ms + 15 * 60_000]
        key = f"forecasts_{market}"
        if not done:
            return {"status": "waiting", "why": "after the close"}
        day = local_date(Market(market), done[-1].close_ms)
        if state.get(key) == day.isoformat():
            return {"status": "done today"}
        mine = (state.get("desks") or {}).get(market) or {}
        out = forecast_desk.daily(self.ctx, market, list(mine.get("symbols") or []))
        state[key] = day.isoformat()
        log.info(
            "Kairos forecast %s stocks and checked %s forecasts (%s)",
            out["made"],
            out["checked"],
            market,
        )
        return {"status": "done", **out}

    def _waiting(self, sid: int) -> int:
        """Orders the desk's engine holds for the next candle (0 when it isn't running)."""
        runner = self.ctx.paper.runner(sid)
        engine = getattr(runner, "engine", None)
        if engine is None:
            return 0
        return sum(len(st.pending) for st in engine.symbols)

    # ------------------------------------------------------------ status

    def _have_count(self, market: str) -> int:
        """Stocks of the market with saved daily prices (one primary-key look-up each;
        cached for a minute)."""
        from backend.db.models import Candle, Instrument

        now = self.ctx.clock.now_ms()
        got = self._haves.get(market)
        if got is None or now - got[0] > 60_000:
            with self.ctx.db.session() as s:
                n = s.scalar(
                    select(func.count(Instrument.id)).where(
                        Instrument.market_code == market,
                        select(Candle.instrument_id)
                        .where(Candle.instrument_id == Instrument.id, Candle.timeframe == "1d")
                        .exists(),
                    )
                )
            got = (now, int(n or 0))
            self._haves[market] = got
        return got[1]

    def _want_count(self, market: str) -> int:
        """How many stocks the autopilot keeps (cached for 10 minutes: the Home card asks
        every few seconds, and counting walks every stock's profile)."""
        now = self.ctx.clock.now_ms()
        got = self._counts.get(market)
        if got is None:
            got = (now, len(self.wanted(market)))
            self._counts[market] = got
        elif now - got[0] > 600_000 and market not in self._recounting:
            # an old count is fine for a status card: recount in the background instead of
            # making the screen wait (up to 15 s under load, D-117)
            self._recounting.add(market)

            def recount() -> None:
                try:
                    self._counts[market] = (self.ctx.clock.now_ms(), len(self.wanted(market)))
                finally:
                    self._recounting.discard(market)

            threading.Thread(target=recount, name="autopilot-count", daemon=True).start()
        return got[1]

    def status(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            st = read_all(s)
        state = self._state()
        metis = self.ctx.services.get("metis")
        ready, why = metis.ai_ready() if metis is not None else (False, "")
        desks = []
        for d in self.ctx.desk.desks():
            # every slot, not only the daily ones: the short desks read "started by you"
            ours = any(
                slot.get("session_id") == d["id"] for slot in (state.get("desks") or {}).values()
            )
            desks.append({**{k: d.get(k) for k in ("id", "market", "state", "name")}, "auto": ours})
        prices = {
            m: {
                "have": self._have_count(m),
                "want": self._want_count(m),
            }
            for m in st["markets"]
            if m in ("IN", "US")
        }
        return {
            "on": bool(st["autopilot"]),
            "running": self._thread is not None,
            "doing": self.doing,
            "last_round": state.get("last_round"),
            "desks": desks,
            "prices": prices,
            "metis": {"on": bool(st["metis.enabled"]), "ai_ready": ready, "why": why},
            "last": self.last,
        }


def select_ids(ids: list[int]) -> Any:
    from backend.db.models import Instrument

    return select(Instrument.id, Instrument.symbol).where(Instrument.id.in_(ids or [-1]))
