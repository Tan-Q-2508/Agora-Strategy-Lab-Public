"""Paper accounts and sessions: start, stop, pause, resume, list, and resume after a
restart (SPEC §7.1, D-06).

Each running session has its own ``PaperRunner`` on its own thread. Nothing runs while
Agora is closed: on the next start, sessions that were running pick up from now (the gap
is shown) and sessions that were stopped stay stopped.

In practice-data mode (``AGORA_FAKE_DATA=1``, cloud sessions and tests) there are no live
prices, so every session is a **replay**: it runs on its own fake clock through the last
months of the practice prices, a few candles per second (D-47).
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.core.types import Market
from backend.db.models import (
    BrokerageProfile,
    Instrument,
    PaperAccount,
    PaperEquity,
    PaperEvent,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperSession,
    PaperTrade,
    SlippageProfile,
    Strategy,
)
from backend.errors import AgoraError
from backend.fakes.clock import FakeClock
from backend.fakes.data_source import FakeSource
from backend.logging_setup import get_logger
from backend.markets.calendar import tz
from backend.paper.feed import LiveFeed
from backend.paper.runner import PaperRunner
from backend.paper.stats import summarize
from backend.settings_store import read_all
from backend.strategy import service as strategies
from backend.strategy.compiler import CompileError, compile_definition
from backend.strategy.sandbox import SandboxError

log = get_logger("paper.service")

REPLAY_BACK_DAYS = {"1d": 180, "1h": 40, "15m": 40, "5m": 40, "1m": 5}
REPLAY_PACE_S = {"1d": 1.0, "1h": 0.6, "15m": 0.4, "5m": 0.3, "1m": 0.25}
MAX_EQUITY_POINTS = 2000
MAX_CLOSED_TRADES = 2000


def _err(code: str, message: str, action: str, status: int = 422) -> AgoraError:
    return AgoraError(code, message, action, status=status)


class AccountIn(BaseModel):
    name: str = Field("", max_length=80)
    market: Market
    starting_capital: float | None = Field(None, gt=0, le=1e12)
    brokerage_profile_id: int | None = None
    slippage_bps: float | None = Field(None, ge=0, le=500)


class SessionIn(BaseModel):
    strategy_version_id: int
    account_id: int | None = None
    account: AccountIn | None = None
    # Kairos's trade check (KAIROS §16); Kairos desks use the kairos.trade_check setting
    trade_check: Literal["off", "learn", "balanced", "strict"] = "off"
    # D-80: run the revision on these stocks, with these settings and this trade size (% of the
    # money per trade), without saving a new version; portfolio sleeves use all three
    symbols: list[str] | None = Field(None, max_length=100)
    overrides: dict[str, float] = Field(default_factory=dict)
    size_pct: float | None = Field(None, gt=0, le=100)
    portfolio_id: int | None = None  # a sleeve of this portfolio (D-86)
    # a desk restarted with the money its last run ended with keeps counting its total return
    # from the money the first run started with (D-146)
    first_capital: float | None = Field(None, gt=0, le=1e12)


class PaperService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx  # AppContext
        self.replay = ctx.data_mode == "fake"
        self.threaded = True  # tests turn this off and drive runners themselves
        self.pace_scale = 1.0
        self.runners: dict[int, PaperRunner] = {}
        self._lock = threading.Lock()
        self.feed = LiveFeed(
            ctx.db, ctx.clock, ctx.calendar, ctx.sources, available=ctx.cache._available
        )

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """App start: resume every session that was running when Agora closed."""
        with self.ctx.db.session() as s:
            ids = list(s.scalars(select(PaperSession.id).where(PaperSession.state != "stopped")))
        for sid in ids:
            self._launch(sid)

    def shutdown(self) -> None:
        with self._lock:
            runners = list(self.runners.values())
        for r in runners:
            r.shutdown()

    def _fixtures(self) -> FakeSource:
        for src in self.ctx.sources:
            if isinstance(src, FakeSource):
                return src
        raise RuntimeError("Practice mode needs the fixture source")

    def replay_window(self, timeframe: str, market: Market) -> tuple[int, int]:
        """(start, end) of a practice replay for this timeframe, in UTC ms."""
        last = date.fromisoformat(self._fixtures().manifest["range"][1])
        zone = tz(market)
        start_day = last - timedelta(days=REPLAY_BACK_DAYS[timeframe])
        start = int(datetime.combine(start_day, datetime.min.time(), zone).timestamp() * 1000)
        end_day = last + timedelta(days=1)
        end = int(datetime.combine(end_day, datetime.min.time(), zone).timestamp() * 1000)
        return start, end

    def _make_runner(self, sid: int) -> PaperRunner:
        if not self.replay:
            return PaperRunner(self.ctx, sid, clock=self.ctx.clock, feed=self.feed)
        with self.ctx.db.session() as s:
            row = s.get(PaperSession, sid)
            assert row is not None
            notes = json.loads(row.notes or "{}")
            started = row.started_at
        replay = notes.get("replay", {})
        clock = FakeClock(max(int(notes.get("now", started)), started))
        fixtures = self._fixtures()
        source = FakeSource(clock, fixtures.dir)
        feed = LiveFeed(self.ctx.db, clock, self.ctx.calendar, [source])
        return PaperRunner(
            self.ctx,
            sid,
            clock=clock,
            feed=feed,
            replay_end_ms=int(replay.get("end", 0)) or None,
            refresh_actions=False,
        )

    def _launch(self, sid: int) -> PaperRunner:
        runner = self._make_runner(sid)
        with self._lock:
            self.runners[sid] = runner
        if self.threaded:
            pace = None
            if self.replay:
                tf = self._timeframe(sid)
                pace = REPLAY_PACE_S.get(tf, 0.5) * self.pace_scale
            runner.start_thread(replay_pace_s=pace)
        return runner

    def _timeframe(self, sid: int) -> str:
        with self.ctx.db.session() as s:
            row = s.get(PaperSession, sid)
            assert row is not None
            v = strategies.get_version(s, row.strategy_version_id)
            assert v is not None
            return v.definition.timeframe

    def runner(self, sid: int) -> PaperRunner | None:
        with self._lock:
            return self.runners.get(sid)

    # ------------------------------------------------------------ accounts

    def create_account(self, req: AccountIn) -> dict[str, Any]:
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            settings = read_all(s)
            market = req.market.value
            profile_id = req.brokerage_profile_id
            if profile_id is not None:
                p = s.get(BrokerageProfile, profile_id)
                if p is None or p.market_code != market:
                    raise _err(
                        "BAD_PROFILE",
                        "That brokerage profile doesn't fit this market.",
                        "Pick another profile.",
                    )
            else:
                profile_id = s.scalar(
                    select(BrokerageProfile.id).where(
                        BrokerageProfile.market_code == market, BrokerageProfile.is_default == 1
                    )
                )
            if profile_id is None:
                raise _err(
                    "NO_PROFILE",
                    "No brokerage profile is set up.",
                    "Restart Agora to restore the defaults.",
                    500,
                )
            slip = req.slippage_bps
            if slip is None:
                slip = (
                    s.scalar(
                        select(SlippageProfile.bps).where(
                            SlippageProfile.market_code == market, SlippageProfile.is_default == 1
                        )
                    )
                    or 0.0
                )
            n = s.scalar(select(func.count()).select_from(PaperAccount)) or 0
            row = PaperAccount(
                name=req.name.strip() or f"Paper account {n + 1}",
                market_code=market,
                starting_capital=float(
                    req.starting_capital or settings[f"default_capital.{market}"]
                ),
                brokerage_profile_id=profile_id,
                slippage_bps=float(slip),
                created_at=now,
            )
            s.add(row)
            s.flush()
            return _account(row)

    def accounts(self, *, include_kairos: bool = False) -> list[dict[str, Any]]:
        """The user's paper accounts. Kairos's own (one for each desk run, trial and portfolio,
        named "Kairos…") and Metis's ("Metis…") are left out unless asked for (D-208: the
        user's account picker listed 61 of them, with odd amounts: a run's leftover money)."""
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(PaperAccount)
                .where(PaperAccount.archived_at.is_(None))
                .order_by(PaperAccount.id)
            ).all()
            if not include_kairos:
                rows = [r for r in rows if not r.name.startswith(("Kairos", "Metis"))]
            return [_account(r) for r in rows]

    # ------------------------------------------------------------ sessions

    def start_session(self, req: SessionIn) -> int:
        with self.ctx.db.session() as s:
            version = strategies.get_version(s, req.strategy_version_id)
            if version is None:
                raise _err(
                    "STRATEGY_NOT_FOUND",
                    "That strategy version doesn't exist.",
                    "Pick a strategy from the list.",
                    404,
                )
            d = version.definition
        try:
            compile_definition(d)
        except SandboxError as exc:
            raise _err(
                "STRATEGY_ERROR",
                f"The strategy code has a problem: {exc.sentence()}",
                "Fix it in the strategy editor first.",
            ) from exc
        except (CompileError, ValueError) as exc:
            raise _err(
                "STRATEGY_ERROR", f"The strategy can't run: {exc}", "Fix it in the strategy editor."
            ) from exc
        if req.account_id is not None:
            account_id = req.account_id
            with self.ctx.db.session() as s:
                acct = s.get(PaperAccount, account_id)
                if acct is None:
                    raise _err(
                        "ACCOUNT_NOT_FOUND",
                        "That paper account doesn't exist.",
                        "Pick or create an account.",
                        404,
                    )
                if acct.market_code != d.market:
                    raise _err(
                        "WRONG_MARKET",
                        "That paper account is for a different market than the strategy.",
                        "Pick an account for the same market, or create one.",
                    )
        else:
            spec = req.account or AccountIn(market=Market(d.market))
            if spec.market.value != d.market:
                raise _err(
                    "WRONG_MARKET",
                    "The account's market doesn't match the strategy's market.",
                    "Use the strategy's market for the account.",
                )
            account_id = int(self.create_account(spec)["id"])
        now = self.ctx.clock.now_ms()
        notes: dict[str, Any] = {"mode": "replay" if self.replay else "live"}
        if req.trade_check != "off":
            notes["trade_check"] = req.trade_check
        if req.symbols:
            notes["symbols"] = list(req.symbols)
        if req.overrides:
            notes["overrides"] = dict(req.overrides)
        if req.size_pct:
            notes["size_pct"] = float(req.size_pct)
        if req.portfolio_id:
            notes["portfolio_id"] = int(req.portfolio_id)
        if req.first_capital:
            notes["first_capital"] = float(req.first_capital)
        started = now
        if self.replay:
            start, end = self.replay_window(d.timeframe, Market(d.market))
            notes["replay"] = {"start": start, "end": end}
            notes["now"] = start
            started = start
        with self.ctx.db.session() as s:
            # The instruments must exist before anything runs (unknown symbols fail here).
            self.ctx.backtests._instruments(s, d, req.symbols or None, Market(d.market))
            row = PaperSession(
                account_id=account_id,
                strategy_version_id=req.strategy_version_id,
                state="running",
                started_at=started,
                notes=json.dumps(notes),
            )
            s.add(row)
            s.flush()
            sid = row.id
        self._launch(sid)
        return sid

    def _active(self, sid: int) -> PaperRunner:
        r = self.runner(sid)
        if r is None or r.state == "stopped":
            with self.ctx.db.session() as s:
                if s.get(PaperSession, sid) is None:
                    raise _err("NOT_FOUND", "That paper session doesn't exist.", "Go back.", 404)
            raise _err(
                "SESSION_STOPPED",
                "This paper session has already stopped.",
                "Start a new session to paper trade again.",
                409,
            )
        return r

    def stop(self, sid: int, message: str | None = None) -> None:
        """``message`` says who stopped it when it wasn't the user: a note that says "by you" on
        the autopilot's restart is a note claiming something that didn't happen."""
        r = self._active(sid)
        r.stop(message) if message else r.stop()

    def pause(self, sid: int, message: str | None = None) -> None:
        r = self._active(sid)
        r.pause(message) if message else r.pause()

    def resume(self, sid: int) -> None:
        self._active(sid).resume()

    def relist(self, sid: int, symbols: list[str], message: str) -> bool:
        """Move a running session to a new stock list where it stands (D-217): no pause, no
        waiting to be flat, same account, open trades kept. ``False`` if it can't be moved yet."""
        runner = self._active(sid)
        if not runner.relist(symbols, message):
            return False
        if runner._thread is not None:
            runner._thread.join(timeout=60.0)
        self._launch(sid)
        return True

    # ------------------------------------------------------------ reading

    def _summary(self, s: Any, row: PaperSession) -> dict[str, Any]:
        acct = s.get(PaperAccount, row.account_id)
        version = strategies.get_version(s, row.strategy_version_id)
        assert acct is not None and version is not None
        strat = s.get(Strategy, version.strategy_id)
        notes = json.loads(row.notes or "{}")
        last_eq = s.execute(
            select(PaperEquity.equity, PaperEquity.ts)
            .where(PaperEquity.session_id == row.id)
            .order_by(PaperEquity.ts.desc())
            .limit(1)
        ).first()
        trades = (
            s.scalar(
                select(func.count())
                .select_from(PaperTrade)
                # a desk's earlier runs too, like its page (D-209)
                .where(PaperTrade.session_id.in_([row.id, *self._earlier_runs(s, row)]))
            )
            or 0
        )
        runner = self.runner(row.id)
        live = runner.tick_payload() if runner is not None and runner.engine is not None else None
        first = float(notes.get("first_capital") or acct.starting_capital)
        equity = live["equity"] if live else (last_eq[0] if last_eq else acct.starting_capital)
        n_pos = (
            len(live["positions"])
            if live
            else s.scalar(
                select(func.count())
                .select_from(PaperPosition)
                .where(PaperPosition.session_id == row.id)
            )
            or 0
        )
        state = runner.state if runner is not None else row.state
        if state == "starting":
            freshness = {"level": "closed", "text": "Getting prices ready…", "delay_s": 0}
        elif live:
            freshness = live["freshness"]
        else:
            freshness = None
        d = version.definition
        return {
            "id": row.id,
            "name": strat.name if strat else "Strategy",
            "strategy_id": version.strategy_id,
            "strategy_version_id": version.id,
            "version": version.version,
            "kind": d.kind,
            "market": d.market,
            "timeframe": d.timeframe,
            "product": d.product,
            # the list really followed: a moved desk's differs from its strategy's (D-217)
            "symbols": notes.get("symbols")
            or (d.universe.symbols if d.universe.kind == "symbols" else []),
            "universe": d.universe.kind,
            "account": _account(acct),
            "state": state,
            "mode": notes.get("mode", "live"),
            "trade_check": notes.get("trade_check", "off"),
            "started_at": row.started_at,
            "stopped_at": row.stopped_at,
            "last_bar_ts": row.last_bar_ts,
            "equity": equity,
            # money a portfolio moved in or out isn't profit or loss (D-86)
            "moved": float(notes.get("moved", 0.0)),
            "first_capital": first,
            "total_return": 100.0 * ((equity - float(notes.get("moved", 0.0))) / first - 1.0),
            "portfolio_id": notes.get("portfolio_id"),
            "day_pnl": live["day_pnl"] if live else 0.0,
            "open_positions": n_pos,
            "trades": trades,
            "freshness": freshness,
            "problem": live["problem"] if live else None,
            "now": live["now"] if live else notes.get("now", row.last_bar_ts),
            "gaps": notes.get("gaps", []),
        }

    def sessions(self, *, include_hidden: bool = False) -> list[dict[str, Any]]:
        """Every session, newest first; stopped ones the user cleared from the Paper page
        (D-206) are left out unless asked for (their trades still count for Kairos)."""
        with self.ctx.db.session() as s:
            rows = s.scalars(select(PaperSession).order_by(PaperSession.id.desc())).all()
            if not include_hidden:
                rows = [r for r in rows if not json.loads(r.notes or "{}").get("hidden")]
            return [self._summary(s, r) for r in rows]

    def clear_stopped(self) -> int:
        """Take every stopped session off the Paper page (D-206: the user found 49 stopped
        runs, mostly older runs of the same desks, confusing). Nothing is deleted: their
        trades stay in Kairos's record and each one still opens by its link."""
        now = self.ctx.clock.now_ms()
        n = 0
        with self.ctx.db.session() as s:
            for r in s.scalars(select(PaperSession).where(PaperSession.state == "stopped")):
                notes = json.loads(r.notes or "{}")
                if notes.get("hidden"):
                    continue
                notes["hidden"] = now
                r.notes = json.dumps(notes)
                n += 1
        return n

    def _earlier_runs(self, s: Any, row: PaperSession) -> list[int]:
        """The runs a Kairos desk carried on from, newest first: same market and timeframe,
        stopped before this one started, ending with the money this one started with (the
        chain D-146 counts the total return along)."""
        version = strategies.get_version(s, row.strategy_version_id)
        if version is None or version.definition.kind != "kairos":
            return []
        key = (version.definition.market, version.definition.timeframe)
        earlier = []
        for r in s.scalars(
            select(PaperSession)
            .where(PaperSession.state == "stopped", PaperSession.stopped_at <= row.started_at)
            .order_by(PaperSession.stopped_at.desc())
        ):
            v = strategies.get_version(s, r.strategy_version_id)
            d = v.definition if v is not None else None
            if d is not None and d.kind == "kairos" and (d.market, d.timeframe) == key:
                earlier.append(r)
        out: list[int] = []
        cur = row
        while True:
            acct = s.get(PaperAccount, cur.account_id)
            if acct is None:
                break
            start = float(acct.starting_capital)
            prev = None
            for r in earlier:
                if r.stopped_at is None or r.stopped_at > cur.started_at or r.id in out:
                    continue
                last = s.scalar(
                    select(PaperEquity.equity)
                    .where(PaperEquity.session_id == r.id)
                    .order_by(PaperEquity.ts.desc())
                    .limit(1)
                )
                if last is not None and abs(float(last) - start) <= 1e-4 * max(1.0, abs(start)):
                    prev = r  # the latest run that ended with this run's money
                    break
            if prev is None:
                break
            out.append(prev.id)
            cur = prev
        return out

    def detail(self, sid: int) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            row = s.get(PaperSession, sid)
            if row is None:
                raise _err("NOT_FOUND", "That paper session doesn't exist.", "Go back.", 404)
            out = self._summary(s, row)
            names = _symbols(s, sid)
            runner = self.runner(sid)
            if runner is not None and runner.engine is not None:
                with runner.lock:
                    positions = runner.positions()
            else:
                positions = [
                    {
                        "instrument_id": p.instrument_id,
                        "symbol": names.get(p.instrument_id, "?"),
                        "side": "long" if p.qty > 0 else "short",
                        "qty": abs(p.qty),
                        "entry_price": p.avg_price,
                        "entry_ts": p.opened_ts,
                        "last_price": None,
                        "unrealized": None,
                        "unrealized_pct": None,
                        "stop": None,
                        "target": None,
                        "reason": "",
                    }
                    for p in s.scalars(select(PaperPosition).where(PaperPosition.session_id == sid))
                ]
            # a Kairos desk's earlier runs too: the autopilot restarts a desk with the money its
            # last run ended with, so its history is all its runs together (D-207: a desk
            # restarted this morning showed only today's flat line)
            runs = [sid, *self._earlier_runs(s, row)]
            points = s.execute(
                select(PaperEquity.ts, PaperEquity.equity, PaperEquity.cash)
                .where(PaperEquity.session_id.in_(runs))
                .order_by(PaperEquity.ts)
            ).all()
            step = max(1, len(points) // MAX_EQUITY_POINTS)
            equity = [
                {"ts": p[0], "equity": p[1], "cash": p[2]}
                for i, p in enumerate(points)
                if i % step == 0 or i == len(points) - 1
            ]
            fills = s.execute(
                select(PaperOrder, PaperFill)
                .join(PaperFill, PaperFill.order_id == PaperOrder.id)
                .where(PaperOrder.session_id == sid)
                .order_by(PaperFill.ts.desc(), PaperFill.id.desc())
                .limit(200)
            ).all()
            rejected = s.scalars(
                select(PaperOrder)
                .where(PaperOrder.session_id == sid, PaperOrder.status == "rejected")
                .order_by(PaperOrder.id.desc())
                .limit(100)
            ).all()
            # every closed trade of the desk's runs (D-209: a restarted desk showed none)
            every = s.scalars(
                select(PaperTrade)
                .where(PaperTrade.session_id.in_(runs))
                .order_by(PaperTrade.exit_ts.desc(), PaperTrade.id.desc())
            ).all()
            trades = every[:MAX_CLOSED_TRADES]
            missing = {t.instrument_id for t in trades} - set(names)
            if missing:
                for inst in s.scalars(select(Instrument).where(Instrument.id.in_(missing))):
                    names[inst.id] = inst.symbol
            events = s.scalars(
                select(PaperEvent)
                .where(PaperEvent.session_id == sid)
                .order_by(PaperEvent.id.desc())
                .limit(200)
            ).all()
            out.update(
                {
                    "positions": positions,
                    "equity_curve": equity,
                    "fills": [
                        {
                            "id": f.id,
                            "ts": f.ts,
                            "symbol": names.get(o.instrument_id, "?"),
                            "instrument_id": o.instrument_id,
                            "side": o.side,
                            "type": o.type,
                            "qty": f.qty,
                            "price": f.price,
                            "charges": f.charges,
                            "reason": o.reason,
                        }
                        for o, f in fills
                    ],
                    "rejected": [
                        {
                            "id": o.id,
                            "ts": o.created_ts,
                            "symbol": names.get(o.instrument_id, "?"),
                            "side": o.side,
                            "reason": o.reason,
                        }
                        for o in rejected
                    ],
                    "stats": summarize(every),
                    "runs": len(runs),
                    "closed_trades": [
                        {
                            "id": t.id,
                            "symbol": names.get(t.instrument_id, "?"),
                            "instrument_id": t.instrument_id,
                            "side": t.side,
                            "qty": t.qty,
                            "entry_ts": t.entry_ts,
                            "entry_price": t.entry_price,
                            "exit_ts": t.exit_ts,
                            "exit_price": t.exit_price,
                            "net_pnl": t.net_pnl,
                            "return_pct": t.return_pct,
                            "charges": t.charges,
                            "entry_reason": t.entry_reason,
                            "exit_reason": t.exit_reason,
                        }
                        for t in trades
                    ],
                    "events": [
                        {
                            "id": e.id,
                            "ts": e.ts,
                            "level": e.level,
                            "kind": e.kind,
                            "message_plain": e.message_plain,
                        }
                        for e in events
                    ],
                    "instruments": [
                        {"id": iid, "symbol": sym}
                        for iid, sym in sorted(names.items(), key=lambda x: x[1])
                    ],
                }
            )
        return out


def _account(r: PaperAccount) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "market": r.market_code,
        "starting_capital": r.starting_capital,
        "brokerage_profile_id": r.brokerage_profile_id,
        "slippage_bps": r.slippage_bps,
        "created_at": r.created_at,
    }


def _symbols(s: Any, sid: int) -> dict[int, str]:
    """instrument id → symbol for everything this session traded or holds, plus the
    strategy's own list."""

    row = s.get(PaperSession, sid)
    version = strategies.get_version(s, row.strategy_version_id)
    ids: set[int] = set(
        s.scalars(select(PaperOrder.instrument_id).where(PaperOrder.session_id == sid).distinct())
    )
    d = version.definition if version else None
    names: dict[int, str] = {}
    if d is not None and d.universe.kind == "symbols":
        for inst in s.scalars(
            select(Instrument).where(
                Instrument.market_code == d.market, Instrument.symbol.in_(d.universe.symbols)
            )
        ):
            names[inst.id] = inst.symbol
    for inst in s.scalars(select(Instrument).where(Instrument.id.in_(ids))):
        names[inst.id] = inst.symbol
    return names
