"""The Kairos desk: Kairos paper trading on its own, and keeping a diary (KAIROS §9).

A desk is an ordinary paper session (D-06: started and stopped by the user, nothing runs
while Agora is closed) whose strategy is the Kairos brain over a watchlist, with its own
paper account. Any paper session running a ``kairos`` strategy counts as a desk.

After every save, the paper runner hands the desk what happened (``after_save``):

- a position just opened → a **thesis**: the signals behind it, the score, the stop and
  the target, and the plan;
- a trade just closed → a **review**: what happened against the plan; the signals in play
  at entry learn from the outcome (``LearningService.record_trade``) and the lessons are
  rewritten (``memory.update_lessons``).

The decisions are recomputed from the brain's cached signals for that stock, so the diary
says exactly what the brain saw.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from backend import actions
from backend.analysis import mtf
from backend.analysis.report import price
from backend.core.types import Market, Timeframe
from backend.data.store import InstrumentRef
from backend.db.models import KairosJournal, PaperSession, Strategy, StrategyVersion
from backend.errors import AgoraError
from backend.kairos import brain, exits, memory, story
from backend.logging_setup import get_logger
from backend.paper.service import AccountIn, SessionIn
from backend.settings_store import read_all
from backend.strategy import service as strategies

log = get_logger("kairos.desk")

DESK_NAME = {"IN": "Kairos desk · India", "US": "Kairos desk · US"}
TF_WORD = {"1h": "hourly", "15m": "15-minute", "5m": "5-minute", "1m": "1-minute"}


def desk_name(market: str, timeframe: str) -> str:
    """The daily desk keeps its old name; others say their timeframe (D-118)."""
    base = DESK_NAME[market]
    return base if timeframe == "1d" else f"{base} · {TF_WORD.get(timeframe, timeframe)}"


# As many stocks as Kairos picks for a desk (D-191: this stayed 30 when D-177 widened the desks
# to the 250 most traded stocks, so every desk silently followed only the first 30).
MAX_SYMBOLS = 250


class DeskService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._lock = threading.Lock()
        self._theses: dict[int, set[tuple[int, int]]] = {}  # session → {(instrument, entry ts)}

    # ------------------------------------------------------------ start / stop / read

    def launch(
        self,
        instruments: list[InstrumentRef],
        timeframe: Timeframe = Timeframe.D1,
        capital: float | None = None,
        first_capital: float | None = None,
    ) -> dict[str, Any]:
        if not instruments:
            raise AgoraError(
                "NO_STOCKS",
                "Kairos needs at least one stock to watch.",
                "Name the stocks for the desk, e.g. “watch TCS, Infosys and HDFC Bank”.",
            )
        markets = {i.market for i in instruments}
        if len(markets) > 1:
            raise AgoraError(
                "MIXED_MARKETS",
                "A desk trades one market at a time.",
                "Start one desk for Indian stocks and another for US stocks.",
            )
        market = markets.pop()
        insts = instruments[:MAX_SYMBOLS]
        learning = self.ctx.learning
        if learning.trained(market, timeframe) is None:
            learning.train(market, timeframe)  # first desk: study the history first
        weights = learning.weights(market, timeframe)
        info = learning.trained(market, timeframe)
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            settings = read_all(s)
        d = brain.definition(
            market.value,
            [i.symbol for i in insts],
            timeframe=timeframe.value,
            weights=weights,
            trained_at=info["at"] if info else None,
            risk_pct=float(settings["kairos.risk_pct"]),
            max_positions=int(settings["kairos.max_positions"]),
            daily_loss_pct=float(settings["kairos.daily_loss_pct"]),
            bigger_chart=(
                mtf.DESK_BIGGER.get(timeframe.value) if settings["kairos.bigger_chart"] else None
            ),
            # every bigger chart read together (D-132)
            bigger_charts=(
                list(mtf.BIGGER.get(timeframe.value, ()))
                if settings["kairos.bigger_chart"]
                else None
            ),
            trail_atr=float(settings["kairos.trail_atr"]) or None,
            partial_r=float(settings["kairos.partial_r"]) or None,
        )
        entry = float(settings["kairos.entry_score"])
        d.parameters[0] = d.parameters[0].model_copy(update={"default": entry})
        name = desk_name(market.value, timeframe.value)
        with self.ctx.db.session() as s:
            row = s.scalars(
                select(Strategy).where(
                    Strategy.kind == "kairos",
                    Strategy.name == name,
                    Strategy.archived_at.is_(None),
                )
            ).first()
            if row is None:
                row, version = strategies.create(
                    s,
                    name=name,
                    description="Kairos trading on its own: the brain over a watchlist, "
                    "weighted by what has worked.",
                    definition=d,
                    now=now,
                    created_by="kairos",
                    note="Desk started",
                )
            else:
                version = strategies.add_version(
                    s, row, d, now, note="Desk started", created_by="kairos"
                )
            version_id = version.id
        what = "India" if market is Market.IN else "US"
        tf_note = "" if timeframe is Timeframe.D1 else f", {TF_WORD.get(timeframe.value)}"
        sid = self.ctx.paper.start_session(
            SessionIn(
                strategy_version_id=version_id,
                account=AccountIn(
                    name=f"Kairos desk ({what}{tf_note})",
                    market=market,
                    starting_capital=capital,
                ),
                trade_check=settings["kairos.trade_check"],
                first_capital=first_capital,
            )
        )
        return self.desk(sid)

    def rules_outdated(self, sid: int) -> bool:
        """The desk's rules differ from Settings → Kairos (risk, limits, trailing stop, partial
        exit): a desk keeps the rules it started with, so a change only reaches a running desk
        when it is started again (the autopilot does that once it holds no trades, D-128)."""
        with self.ctx.db.session() as s:
            raw = s.scalar(
                select(StrategyVersion.definition)
                .join(PaperSession, PaperSession.strategy_version_id == StrategyVersion.id)
                .where(PaperSession.id == sid)
            )
            settings = read_all(s)
        if raw is None:
            return False
        d = json.loads(raw)
        k = d.get("kairos") or {}
        limits = d.get("limits") or {}
        charts = list(mtf.BIGGER.get(d.get("timeframe", "1d"), ()))
        if (k.get("bigger_charts") or []) != (charts if settings["kairos.bigger_chart"] else []):
            return True  # the bigger charts changed (D-132)
        want: dict[str, float | None] = {
            "trail_atr": float(settings["kairos.trail_atr"]) or None,
            "partial_r": float(settings["kairos.partial_r"]) or None,
            "risk_pct": float(settings["kairos.risk_pct"]),
            "max_positions": int(settings["kairos.max_positions"]),
            "daily_loss_pct": float(settings["kairos.daily_loss_pct"]),
            "max_position_pct": round(100.0 / int(settings["kairos.max_positions"]), 2),
            "max_per_group": float(brain.MAX_PER_SECTOR),  # D-168
        }
        have = {
            "trail_atr": k.get("trail_atr"),
            "partial_r": k.get("partial_r"),
            "risk_pct": (d.get("sizing") or {}).get("value"),
            "max_positions": limits.get("max_open_positions"),
            "daily_loss_pct": limits.get("max_daily_loss_pct"),
            "max_position_pct": limits.get("max_position_pct"),
            "max_per_group": limits.get("max_per_group"),
        }

        def differs(a: float | None, b: Any) -> bool:
            if a is None or b is None:
                return (a is None) != (b is None)
            return abs(a - float(b)) > 1e-9

        return any(differs(want[x], have[x]) for x in want)

    def is_desk(self, sid: int) -> bool:
        with self.ctx.db.session() as s:
            kind = s.scalar(
                select(Strategy.kind)
                .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
                .join(PaperSession, PaperSession.strategy_version_id == StrategyVersion.id)
                .where(PaperSession.id == sid)
            )
        return bool(kind == "kairos")

    def desks(self) -> list[dict[str, Any]]:
        return [x for x in self.ctx.paper.sessions() if x.get("kind") == "kairos"]

    def desk(self, sid: int) -> dict[str, Any]:
        if not self.is_desk(sid):
            raise AgoraError(
                "NOT_A_DESK", "That paper session isn't a Kairos desk.", "Go back.", status=404
            )
        out: dict[str, Any] = dict(self.ctx.paper.detail(sid))
        out["journal"] = self.journal(sid)
        market, tf = Market(out["market"]), Timeframe(out["timeframe"])
        out["learned"] = self.ctx.learning.learned(market, tf)
        out["lessons"] = memory.lessons(self.ctx, market, limit=8)
        theses = {
            (j["instrument_id"], j["entry_ts"]): j for j in out["journal"] if j["kind"] == "thesis"
        }
        for p in out.get("positions", []):
            t = theses.get((p["instrument_id"], p["entry_ts"]))
            p["thesis"] = t["text"] if t else None
        return out

    def stop(self, sid: int, message: str | None = None) -> None:
        if not self.is_desk(sid):
            raise AgoraError(
                "NOT_A_DESK", "That paper session isn't a Kairos desk.", "Go back.", status=404
            )
        self.ctx.paper.stop(sid, message)

    def journal(self, sid: int, limit: int = 100) -> list[dict[str, Any]]:
        from backend.db.models import Instrument

        with self.ctx.db.session() as s:
            rows = s.execute(
                select(KairosJournal, Instrument.symbol)
                .outerjoin(Instrument, Instrument.id == KairosJournal.instrument_id)
                .where(KairosJournal.session_id == sid)
                .order_by(KairosJournal.id.desc())
                .limit(limit)
            ).all()
            out = []
            for j, symbol in rows:
                data = json.loads(j.signals or "{}")
                out.append(
                    {
                        "id": j.id,
                        "kind": j.kind,
                        "symbol": symbol,
                        "instrument_id": j.instrument_id,
                        "trade_id": j.trade_id,
                        "entry_ts": data.get("entry_ts"),
                        "score": j.score,
                        "text": j.text,
                        "won": data.get("won"),
                        "return_pct": data.get("return_pct"),
                        "at": j.created_at,
                    }
                )
            return out

    # ------------------------------------------------------------ the paper runner's hook

    def after_save(self, runner: Any, closed: list[dict[str, Any]]) -> None:
        """Write theses for new positions and reviews for closed trades (then learn)."""
        engine = runner.engine
        program = engine.program if engine is not None else None
        if program is None or program.brain is None:
            return
        with self._lock:
            known = self._theses.get(runner.id)
            if known is None:
                known = self._load_theses(runner.id)
                self._theses[runner.id] = known
        b: brain.Brain = program.brain
        market, tf = runner.market, runner.tf
        for st in engine.symbols:
            pos = st.position
            if pos is None or (st.inst.id, pos.entry_ts) in known or st.ctx is None:
                continue
            known.add((st.inst.id, pos.entry_ts))
            d = self._decision(b, st, pos.entry_index - 1)
            if pos.partials or pos.start_qty > pos.qty:
                # a partial sale before this save moved the stop to the entry and sold shares:
                # the thesis tells the trade as it was opened
                side = 1 if pos.side == "long" else -1
                stop, target = _planned(b, st, pos.entry_index - 1, d, side, pos.entry_price)
                pos = SimpleNamespace(
                    side=pos.side,
                    qty=pos.start_qty or pos.qty,
                    entry_price=pos.entry_price,
                    entry_ts=pos.entry_ts,
                    stop=stop if stop is not None else pos.stop,
                    target=target if target is not None else pos.target,
                )
            self._thesis(runner.id, st.inst, market, pos, d, b)
        if not closed:
            return
        for t in closed:
            if (t["instrument_id"], t["entry_ts"]) not in known and "entry_price" in t:
                # opened and closed between two saves (e.g. stopped out on its first
                # candle): it still gets its thesis, written from the entry candle
                st = next((x for x in engine.symbols if x.inst.id == t["instrument_id"]), None)
                idx = _index_of(st, t["entry_ts"]) if st is not None else None
                if st is not None and idx:
                    known.add((t["instrument_id"], t["entry_ts"]))
                    d = self._decision(b, st, idx - 1)
                    side = 1 if t["side"] == "long" else -1
                    px = float(t["entry_price"])
                    stop, target = _planned(b, st, idx - 1, d, side, px)
                    pos = SimpleNamespace(
                        side=t["side"],
                        qty=t["qty"],
                        entry_price=px,
                        entry_ts=t["entry_ts"],
                        stop=stop,
                        target=target,
                    )
                    self._thesis(runner.id, st.inst, market, pos, d, b)
            keys = self._entry_keys(runner.id, t)
            if keys is None:
                st = next((x for x in engine.symbols if x.inst.id == t["instrument_id"]), None)
                idx = _index_of(st, t["entry_ts"]) if st is not None else None
                d = self._decision(b, st, idx - 1) if st is not None and idx else None
                keys = d.signal_keys() if d is not None else []
            side = 1 if t["side"] == "long" else -1
            self.ctx.learning.record_trade(market, tf, keys, side, float(t["return_pct"]))
            self._exits_lesson(b, engine, market, tf, t, side)
            review = self._review(runner.id, market, t, keys)
            self._reflect(runner.id, t, review)
        memory.update_lessons(self.ctx, market)
        actions.note("kairos_lessons", f"Lessons rewritten for {market}", who="kairos")

    def _exits_lesson(
        self, b: brain.Brain, engine: Any, market: Market, tf: Any, t: dict[str, Any], side: int
    ) -> None:
        """How every exit plan would have done on this trade (D-140), so Kairos's choice of
        stops, targets, trailing and partial sales learns from its own trades too."""
        try:
            st = next((x for x in engine.symbols if x.inst.id == t["instrument_id"]), None)
            idx = _index_of(st, t["entry_ts"]) if st is not None else None
            if st is None or not idx or st.ctx is None:
                return
            d = self._decision(b, st, idx - 1)
            if d is None:
                return
            series = st.ctx._provider.series
            results = exits.replay_trade(
                series,
                b.signals(st.ctx),
                idx - 1,
                side,
                d,
                market.value,
                b.max_bars or 30,
                self.ctx.learning.default_exits(),
            )
            self.ctx.learning.record_exits(market, tf, results)
        except Exception:
            log.exception("Couldn't learn exits from a closed trade")

    def _load_theses(self, sid: int) -> set[tuple[int, int]]:
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(KairosJournal).where(
                    KairosJournal.session_id == sid, KairosJournal.kind == "thesis"
                )
            ).all()
            return {
                (int(r.instrument_id or 0), int(json.loads(r.signals or "{}").get("entry_ts", 0)))
                for r in rows
            }

    def _decision(self, b: brain.Brain, st: Any, i: int) -> brain.Decision | None:
        if st is None or st.ctx is None or i is None or i < 1:
            return None
        ss = b.signals(st.ctx)
        if i >= ss.n:
            return None
        return brain.decide(ss, i, b.weights)

    def _thesis(
        self,
        sid: int,
        inst: InstrumentRef,
        market: Market,
        pos: Any,
        d: brain.Decision | None,
        b: brain.Brain,
    ) -> None:
        side = 1 if pos.side == "long" else -1
        verb = "Bought" if side > 0 else "Short-sold"
        qty = f"{pos.qty:g}"
        text = f"{verb} {qty} {inst.symbol} at {price_in(market, pos.entry_price)}."
        keys: list[tuple[str, int]] = []
        score = None
        if d is not None:
            reasons = [a.event.label for a in d.reasons(side, 4)]
            keys = d.signal_keys()
            score = d.score
            why = ", ".join(dict.fromkeys(reasons)) if reasons else "the overall picture"
            trend = d.components["trend"] * 100
            text += f" Why: {why} (score {d.score:+.0f}, trend {trend:+.0f})."
            against = [a.event.label for a in d.active if a.contribution * side < 0]
            if against:
                text += f" Against it: {', '.join(dict.fromkeys(against[:3]))}."
        if pos.stop is not None:
            risk = abs(pos.entry_price - pos.stop) / pos.entry_price * 100
            text += f" Stop {price_in(market, pos.stop)} (risking {risk:.1f}%)"
            if pos.target is not None:
                reward = abs(pos.target - pos.entry_price) / pos.entry_price * 100
                rr = reward / risk if risk else 0.0
                text += (
                    f", target {price_in(market, pos.target)} (+{reward:.1f}%, {rr:.1f}× the risk)."
                )
            else:
                text += "."
        if b.exit_words:
            text += f" Exits: {b.exit_words}."
        limit = f" or after {b.max_bars} candles" if b.max_bars else ""
        text += f" Plan: get out if the score turns {b.exit:.0f} points against the trade{limit}."
        data = {
            "entry_ts": pos.entry_ts,
            "side": side,
            "keys": keys,
            "market": market.value,
            "entry_price": pos.entry_price,
        }
        self._write(sid, inst.id, None, "thesis", data, score, text, at=pos.entry_ts)

    def _entry_keys(self, sid: int, t: dict[str, Any]) -> list[tuple[str, int]] | None:
        with self.ctx.db.session() as s:
            rows = s.scalars(
                select(KairosJournal).where(
                    KairosJournal.session_id == sid,
                    KairosJournal.kind == "thesis",
                    KairosJournal.instrument_id == t["instrument_id"],
                )
            ).all()
            for r in rows:
                data = json.loads(r.signals or "{}")
                if data.get("entry_ts") == t["entry_ts"]:
                    return [(str(k), int(v)) for k, v in data.get("keys", [])]
        return None

    def _review(
        self, sid: int, market: Market, t: dict[str, Any], keys: list[tuple[str, int]]
    ) -> str:
        ret = float(t["return_pct"])
        won = float(t["net_pnl"]) > 0
        how = {
            "target": "it reached its target",
            "stop": "the stop was hit",
            "trailing": "the trailing stop was hit",
            "signal": "Kairos's reading turned against it",
            "time": "it ran out of time",
            "square_off": "intraday trades close before the end of the day",
        }.get(str(t["exit_reason"]), "it was closed")
        verdict = "It worked" if won else "It didn't work"
        text = (
            f"Closed {t['symbol']} ({t['side']}): {ret:+.2f}% after {t['bars_held']} candles, "
            f"because {how}. {verdict}"
        )
        from backend.kairos.learning import label_of

        labels = [label_of(k) for k, d in keys if d == (1 if t["side"] == "long" else -1)]
        if labels:
            text += f": the thesis was {', '.join(dict.fromkeys(labels[:3])).lower()}."
        else:
            text += "."
        net = price(float(t["net_pnl"]), market)
        text += f" Net result after charges: {net}."
        if t.get("id"):  # the whole story: best and worst point, and what it teaches (27.11)
            told = story.story(self.ctx, int(t["id"]))
            if told is not None:
                text += story.sentence(told)
        data = {
            "entry_ts": t["entry_ts"],
            "side": 1 if t["side"] == "long" else -1,
            "keys": keys,
            "market": market.value,
            "won": won,
            "return_pct": ret,
            "exit_reason": t["exit_reason"],
        }
        self._write(
            sid, t["instrument_id"], t.get("id"), "review", data, None, text, at=t["exit_ts"]
        )
        return text

    def _reflect(self, sid: int, t: dict[str, Any], review: str) -> None:
        """With the AI model ready, Kairos adds one sentence of its own about the trade, on a
        side thread. The sentence may only use numbers from the review (D-52), and it goes
        in the diary only, never into the lessons that steer later prompts."""
        kairos = self.ctx.services.get("kairos")
        if kairos is None or kairos.mode() != "ai":
            return
        thesis = ""
        with self.ctx.db.session() as s:
            for r in s.scalars(
                select(KairosJournal).where(
                    KairosJournal.session_id == sid,
                    KairosJournal.kind == "thesis",
                    KairosJournal.instrument_id == t["instrument_id"],
                )
            ):
                if json.loads(r.signals or "{}").get("entry_ts") == t["entry_ts"]:
                    thesis = r.text

        def work() -> None:
            from backend.ai.numbers import unverified
            from backend.core.ai_provider import ChatMessage, ChatOptions

            try:
                settings = self.ctx.ai_service._settings()
                reply = self.ctx.ai.chat(
                    [
                        ChatMessage(
                            "system",
                            "You are Kairos, a disciplined trader reviewing your own paper trade. "
                            "In one plain sentence (under 40 words), say what this trade teaches. "
                            "Use only facts given. No advice, no new numbers.",
                        ),
                        ChatMessage("user", f"Thesis: {thesis}\nResult: {review}"),
                    ],
                    model=settings["model"],
                    stream=False,
                    options=ChatOptions(num_ctx=settings["num_ctx"], temperature=0.3),
                )
                text = str(reply).strip().split("\n")[0][:300]
                if text and not unverified(text, thesis + " " + review):
                    self._write(
                        sid,
                        t["instrument_id"],
                        t.get("id"),
                        "note",
                        {"entry_ts": t["entry_ts"], "reflection": True},
                        None,
                        f"Reflection: {text}",
                        at=t["exit_ts"],
                    )
            except Exception:
                log.info("Kairos couldn't reflect on trade %s", t.get("id"), exc_info=True)

        threading.Thread(target=work, name="kairos-reflect", daemon=True).start()

    def _write(
        self,
        sid: int,
        instrument_id: int | None,
        trade_id: int | None,
        kind: str,
        data: dict[str, Any],
        score: float | None,
        text: str,
        at: int | None = None,
    ) -> None:
        """``at``: when it happened on the market's clock (the fill), so a practice replay's
        diary reads in replay time."""
        with self.ctx.db.session() as s:
            s.add(
                KairosJournal(
                    session_id=sid,
                    trade_id=trade_id,
                    instrument_id=instrument_id,
                    kind=kind,
                    signals=json.dumps(data),
                    score=score,
                    text=text,
                    created_at=at if at is not None else self.ctx.clock.now_ms(),
                )
            )


def price_in(market: Market, value: float) -> str:
    return price(value, market)


def write_note(
    ctx: Any, sid: int, instrument_id: int | None, text: str, data: dict[str, Any]
) -> None:
    """A diary note that isn't a thesis or a review (e.g. the news guard acting, D-69)."""
    with ctx.db.session() as s:
        s.add(
            KairosJournal(
                session_id=sid,
                trade_id=None,
                instrument_id=instrument_id,
                kind="note",
                signals=json.dumps(data),
                score=None,
                text=text,
                created_at=ctx.clock.now_ms(),
            )
        )


def _planned(
    b: brain.Brain, st: Any, i: int, d: brain.Decision | None, side: int, px: float
) -> tuple[float | None, float | None]:
    """The stop and target the brain planned on candle ``i`` for a trade opened at ``px``."""
    if d is None or st.ctx is None:
        return None, None
    p = brain.plan(b.signals(st.ctx), i, d, side, b.stop_atr, b.target_r)
    return px * (1 - side * p.stop_pct / 100), px * (1 + side * p.target_pct / 100)


def _index_of(st: Any, ts: int) -> int | None:
    for k in range(len(st.raw) - 1, -1, -1):
        if st.raw[k].ts == ts:
            return k
        if st.raw[k].ts < ts:
            break
    return None
