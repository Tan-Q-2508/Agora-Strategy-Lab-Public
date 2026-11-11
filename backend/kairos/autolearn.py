"""Kairos keeps learning on its own while Agora is open (KAIROS §18, D-73).

A background thread wakes every two minutes (never while Agora is closed: it lives and dies
with the app, D-06) and does one bounded round of study, in this order:

1. **Review finished backtests** it hasn't read yet: costs, win rate, why trades failed,
   filters that held up (``coach.py``). Their trades become trade-check experience.
2. **Review paper sessions** that closed new trades since its last look.
3. **Improve strategies** (setting ``kairos.auto_improve``): when a review found a filter
   that held up on unseen trades, test it as a new version and keep it only if it did
   better after costs (``improve.py``). At most one strategy a round, each at most once a
   week.
   Then **forward checks** (D-90, ``backend/checks/forward.py``): what Kairos and Metis saved,
   and portfolio sleeves, re-tested on the candles formed since; undone when they stopped
   holding up.
4. **Predict and check**: a fresh forecast with predicted candles for a few watchlist
   stocks (one per stock per candle). Older predictions whose candles have now formed are
   scored and compared candle by candle; the calibration this feeds is used by every later
   forecast (``forecast.py``, KAIROS §17).
5. **Re-study signals** when a market's history grew or new signals were added
   (``learning.ensure_trained``), on every timeframe a desk trades, one study a round.

Each round writes what it learned as short lessons (memory) and as one ``learner`` review,
so the Kairos panel can show "what I learned today". A round yields to the user: it is
skipped while a backtest, research or training job is running. All of it is ordinary,
deterministic code (D-56): it never places an order.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Any

from sqlalchemy import func, select

from backend import actions
from backend.core.heavy import background_turn
from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.db.models import (
    BacktestRun,
    KairosReview,
    PaperTrade,
    Strategy,
)
from backend.kairos import memory
from backend.kairos.coach import Coach
from backend.logging_setup import get_logger
from backend.settings_store import read_all

# every timeframe Kairos runs a desk on (D-132)
DESK_TIMEFRAMES = (Timeframe.D1, Timeframe.H1, Timeframe.M15, Timeframe.M5, Timeframe.M1)
log = get_logger("kairos.learner")
FIRST_WAIT_S = 60.0
CYCLE_S = 120.0  # Kairos studies all the time while Agora is open (the user's request 2026-10-24)
REVIEWS_PER_ROUND = 3
FORECASTS_PER_ROUND = 6
FORWARD_PER_ROUND = 2
IMPROVE_EVERY_MS = 7 * 86_400_000
BUSY_KINDS = ("backtest", "kairos_research", "kairos_train", "kairos_desk", "kairos_improve")


class AutoLearner:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.coach = Coach(ctx)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.running = False
        self.last_round_at: int | None = None
        self.next_round_at: int | None = None
        self.activity: deque[dict[str, Any]] = deque(maxlen=60)
        self._cursor: dict[str, int] = {"IN": 0, "US": 0}

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """App start. Practice-data sessions (tests, the cloud) don't run the thread unless
        asked; the laptop always does (when the setting is on)."""
        if self.ctx.data_mode != "real" and not os.environ.get("AGORA_AUTOLEARN"):
            return
        self._thread = threading.Thread(target=self._loop, name="kairos-learner", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def poke(self) -> None:
        """Run a round soon (the user asked, or a backtest just finished)."""
        self._wake.set()

    def _loop(self) -> None:
        wait = FIRST_WAIT_S
        while not self._stop.is_set():
            self.next_round_at = self.ctx.clock.now_ms() + int(wait * 1000)
            self._wake.wait(wait)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                if self.enabled() and not self.busy():
                    with background_turn("Kairos's learner"):
                        self.round()
            except Exception:  # a bad round must never take the app down
                log.exception("Kairos's learning round failed")
            wait = CYCLE_S

    def enabled(self) -> bool:
        with self.ctx.db.session() as s:
            st = read_all(s)
        return bool(st["kairos.enabled"]) and bool(st["kairos.keep_learning"])

    def busy(self) -> bool:
        return any(
            j.status in ("queued", "running") and j.kind in BUSY_KINDS for j in self.ctx.jobs.list()
        )

    def status(self) -> dict[str, Any]:
        return {
            "on": self.enabled(),
            "thread": self._thread is not None and self._thread.is_alive(),
            "running": self.running,
            "last_round_at": self.last_round_at,
            "next_round_at": self.next_round_at,
            "activity": list(self.activity)[::-1][:30],
            "history": self.history(),
        }

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(KairosReview)
                .where(KairosReview.kind == "learner")
                .order_by(KairosReview.id.desc())
                .limit(limit)
            ).all()
            return [
                {"at": r.created_at, "headline": r.headline, **json.loads(r.payload)} for r in rows
            ]

    # ------------------------------------------------------------ one round

    def _note(self, kind: str, text: str, **extra: Any) -> dict[str, Any]:
        item = {"at": self.ctx.clock.now_ms(), "kind": kind, "text": text, **extra}
        self.activity.append(item)
        actions.note("kairos_learning", text, who="kairos", why=kind)
        return item

    def round(self) -> dict[str, Any]:
        """One round of study. Safe to call directly (tests, "Learn now")."""
        with self._lock:
            self.running = True
            t0 = time.perf_counter()
            done: list[dict[str, Any]] = []
            act = actions.track("kairos_learning_round", "Kairos's study round", who="kairos")
            try:
                for step in (
                    self._review_backtests,
                    self._review_paper,
                    self._improve,
                    self._forward,
                    self._predict,
                    self._restudy,
                    self._trade_kinds,
                ):
                    try:
                        done.extend(step())
                    except Exception as exc:
                        log.exception("Learning step %s failed", step.__name__)
                        actions.note(
                            "kairos_learning",
                            f"Learning step {step.__name__}",
                            repr(exc),
                            who="kairos",
                            status="failed",
                        )
            finally:
                self.running = False
            now = self.ctx.clock.now_ms()
            self.last_round_at = now
            headline = (
                f"Studied {len(done)} thing{'s' if len(done) != 1 else ''}."
                if done
                else "Nothing new to study."
            )
            out = {"items": done, "seconds": round(time.perf_counter() - t0, 1)}
            act.done(headline)
            if done:
                with self.ctx.db.session() as s:
                    s.add(
                        KairosReview(
                            kind="learner",
                            ref_id=None,
                            strategy_id=None,
                            trades_seen=0,
                            headline=headline,
                            payload=json.dumps(out),
                            created_at=now,
                        )
                    )
            return {"headline": headline, **out}

    def _trade_kinds(self) -> list[dict[str, Any]]:
        """What the record of real trades teaches, by kind, into the lessons (27.11)."""
        from backend.core.types import Market
        from backend.kairos import story

        out = []
        for market in (Market.IN, Market.US):
            text = story.teach(self.ctx, market)
            if text:
                out.append(self._note("lesson", text))
        return out

    def _review_backtests(self) -> list[dict[str, Any]]:
        with self.ctx.db.session() as s:
            reviewed = select(KairosReview.ref_id).where(KairosReview.kind == "backtest")
            ids = s.scalars(
                select(BacktestRun.id)
                .where(
                    BacktestRun.status == "done",
                    BacktestRun.parent_run_id.is_(None),
                    BacktestRun.id.not_in(reviewed),
                )
                .order_by(BacktestRun.id.desc())
                .limit(REVIEWS_PER_ROUND)
            ).all()
        out = []
        for rid in ids:
            r = self.coach.review_backtest(int(rid))
            text = f"Reviewed backtest #{rid}: {r.get('headline', '')}"
            out.append(self._note("review", text, run_id=rid))
            for line in r.get("failure_reasons", [])[:1]:
                memory.note(
                    self.ctx,
                    f"bt-{r.get('strategy_id')}-why",
                    f"Strategy #{r.get('strategy_id')}: {line['text']}",
                )
        return out

    def _review_paper(self) -> list[dict[str, Any]]:
        with self.ctx.db.session() as s:
            counts = dict(
                s.execute(
                    select(PaperTrade.session_id, func.count(PaperTrade.id)).group_by(
                        PaperTrade.session_id
                    )
                ).all()
            )
            seen = dict(
                s.execute(
                    select(KairosReview.ref_id, func.max(KairosReview.trades_seen))
                    .where(KairosReview.kind == "paper")
                    .group_by(KairosReview.ref_id)
                ).all()
            )
        todo = [sid for sid, n in counts.items() if n > int(seen.get(sid) or 0)]
        out = []
        for sid in sorted(todo, reverse=True)[:REVIEWS_PER_ROUND]:
            r = self.coach.review_paper(int(sid))
            out.append(
                self._note(
                    "review",
                    f"Reviewed paper session #{sid}: {r.get('headline', '')}",
                    session_id=sid,
                )
            )
        return out

    def _improve(self) -> list[dict[str, Any]]:
        with self.ctx.db.session() as s:
            if not read_all(s)["kairos.auto_improve"]:
                return []
            now = self.ctx.clock.now_ms()
            recent = {
                int(x)
                for x in s.scalars(
                    select(KairosReview.strategy_id).where(
                        KairosReview.kind == "improvement",
                        KairosReview.created_at >= now - IMPROVE_EVERY_MS,
                    )
                )
                if x is not None
            }
            rows = s.execute(
                select(KairosReview.strategy_id, KairosReview.payload)
                .join(Strategy, Strategy.id == KairosReview.strategy_id)
                .where(
                    KairosReview.kind == "backtest",
                    Strategy.kind == "visual",
                    Strategy.archived_at.is_(None),
                )
                .order_by(KairosReview.id.desc())
                .limit(50)
            ).all()
        for sid, payload in rows:
            if sid is None or int(sid) in recent:
                continue
            rules = json.loads(payload).get("filters", {}).get("rules", [])
            if not any(r.get("held_up") for r in rules):
                continue
            from backend.kairos.improve import improve

            res = improve(self.ctx, int(sid))
            return [
                self._note(
                    "improve",
                    res.get("headline", ""),
                    strategy_id=sid,
                    changed=bool(res.get("changed")),
                )
            ]
        return []

    def _forward(self) -> list[dict[str, Any]]:
        """Re-test what Kairos and Metis saved, and portfolio sleeves, on the candles formed
        since (D-90): each at most once a day; undo what stopped holding up."""
        from backend.checks import forward

        return [
            self._note(
                "forward",
                f"{c['result'].get('name', c['strategy_name'])}: {c['title']}"
                + (f" {c['action']}" if c["action"] else ""),
                strategy_id=c["strategy_id"],
                verdict=c["verdict"],
            )
            for c in forward.run_due(self.ctx, limit=FORWARD_PER_ROUND)
            if c["verdict"] != "waiting"
        ]

    def _predict(self) -> list[dict[str, Any]]:
        out = []
        for market in Market:
            with self.ctx.db.session() as s:
                insts = [i for i in data_service.default_symbols(s, market) if not i.is_index]
            if not insts:
                continue
            k = self._cursor[market.value] % len(insts)
            batch = (insts[k:] + insts[:k])[: FORECASTS_PER_ROUND // 2]
            self._cursor[market.value] = k + len(batch)
            for inst in batch:
                try:
                    f = self.ctx.analysis.forecast(inst, Timeframe.D1)
                except Exception:
                    continue  # no prices yet for this stock
                cal = f.get("calibration") or {}
                if cal.get("checked"):
                    out.append(
                        self._note(
                            "predict",
                            f"Checked {cal['checked']} of my earlier predictions for "
                            f"{inst.symbol}; {cal.get('text', '')}",
                            symbol=inst.symbol,
                        )
                    )
                    memory.note(
                        self.ctx,
                        f"fc-{inst.id}",
                        f"{inst.symbol}: {cal.get('text', '')}",
                        market.value,
                    )
        return out

    def _restudy(self) -> list[dict[str, Any]]:
        for market in Market:
            for tf in DESK_TIMEFRAMES:
                try:
                    if not self.ctx.learning.needs_training(market, tf):
                        continue
                    job = self.ctx.learning.ensure_trained(market, tf)
                except Exception:
                    continue
                if job:  # one study a round
                    note = f"Re-studied {market.value} {tf.value} signal history."
                    return [self._note("train", note)]
        return []


def strategies_with_samples(ctx: Any) -> list[dict[str, Any]]:
    """Strategies Kairos has trade experience for (for the panels)."""
    from backend.db.models import KairosTradeSample

    with ctx.db.session() as s:
        rows = s.execute(
            select(
                KairosTradeSample.strategy_id,
                Strategy.name,
                func.count(KairosTradeSample.id),
                func.sum(KairosTradeSample.win),
            )
            .join(Strategy, Strategy.id == KairosTradeSample.strategy_id)
            .where(KairosTradeSample.origin == "trade")
            .group_by(KairosTradeSample.strategy_id, Strategy.name)
            .order_by(func.count(KairosTradeSample.id).desc())
        ).all()
    return [
        {"strategy_id": sid, "name": name, "trades": int(n), "win_rate": round(int(w or 0) / n, 3)}
        for sid, name, n, w in rows
        if n
    ]
