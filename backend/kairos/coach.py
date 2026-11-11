"""Kairos's coach: reviews finished backtests and paper sessions and keeps what it learns
(KAIROS §16, D-72).

``review_backtest`` / ``review_paper`` load the trades and the candles around them, run
``review.review`` and save the result in ``kairos_reviews``; the trades and the market's
condition at each signal go into ``kairos_trade_samples`` so the trade check (and every
later review) learns from them. ``picture`` is what the trade check currently believes about
a strategy.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from sqlalchemy import select

from backend.backtest.run import warmup_ms
from backend.core.types import Market, Timeframe
from backend.data.store import InstrumentRef
from backend.db.models import (
    BacktestRun,
    BacktestTrade,
    Instrument,
    KairosReview,
    PaperSession,
    PaperTrade,
    Strategy,
    StrategyVersion,
)
from backend.errors import AgoraError
from backend.indicators.series import BarSeries, from_bars
from backend.kairos import review as rv
from backend.kairos import samples as smp
from backend.kairos.quality import (
    PROOF_MIN,
    PROOF_SKILL,
    PROOF_WINDOW,
    brier_skill,
    fit,
    prequential,
    score_reader,
)
from backend.logging_setup import get_logger

log = get_logger("kairos.coach")
MAX_SCORED_SYMBOLS = 15  # Kairos's score costs ~1 s a stock; beyond this the readings suffice


def _not_found(what: str) -> AgoraError:
    return AgoraError(
        "NOT_FOUND", f"That {what} doesn't exist.", "Pick one from the list.", status=404
    )


class Coach:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------ loading

    def _series(
        self, insts: dict[str, InstrumentRef], tf: Timeframe, lo: int, hi: int
    ) -> dict[str, BarSeries]:
        out: dict[str, BarSeries] = {}
        for sym, inst in insts.items():
            bars = self.ctx.cache.bars(
                inst, tf, lo - warmup_ms(tf, 260), hi + 1, adjusted_prices=True
            )
            if bars:
                out[sym] = from_bars(bars, tf, inst.market)
        return out

    def _insts(self, ids: set[int]) -> dict[int, InstrumentRef]:
        from backend.data.store import ref

        with self.ctx.db.session() as s:
            rows = s.scalars(select(Instrument).where(Instrument.id.in_(ids))).all()
            return {r.id: ref(r) for r in rows}

    def _run(
        self,
        kind: str,
        ref_id: int,
        strategy_id: int,
        strategy_kind: str,
        market: Market,
        tf: Timeframe,
        rows: list[Any],
    ) -> dict[str, Any]:
        insts = self._insts({r.instrument_id for r in rows})
        trades = [
            rv.TradeIn(
                symbol=insts[r.instrument_id].symbol if r.instrument_id in insts else "?",
                side=-1 if r.side == "short" else 1,
                entry_ts=int(r.entry_ts),
                exit_ts=int(r.exit_ts or r.entry_ts),
                gross=float(r.gross_pnl),
                charges=float(r.charges),
                net=float(r.net_pnl),
                return_pct=float(r.return_pct),
                bars_held=int(r.bars_held),
                exit_reason=str(r.exit_reason or "signal"),
            )
            for r in rows
        ]
        closed = [t for t in trades if t.exit_reason != "end_of_test"]
        series: dict[str, BarSeries] = {}
        if closed:
            lo = min(t.entry_ts for t in closed)
            hi = max(t.exit_ts for t in closed)
            by_symbol = {i.symbol: i for i in insts.values()}
            series = self._series(by_symbol, tf, lo, hi)
        scorer = score_reader() if len(series) <= MAX_SCORED_SYMBOLS else None
        result = rv.review(trades, series, market, score_for=scorer)
        feats = result.pop("features", [])
        order = result.pop("closed", [])
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            if feats:
                by_key = {(t.symbol, t.side, t.entry_ts): t for t in closed}
                matched = [
                    (by_key[(o["symbol"], o["side"], o["entry_ts"])], f, o)
                    for o, f in zip(order, feats, strict=True)
                    if (o["symbol"], o["side"], o["entry_ts"]) in by_key
                ]
                if matched:
                    samples = rv.to_samples([m[0] for m in matched], [m[1] for m in matched])
                    for x, (_, _, o) in zip(samples, matched, strict=True):
                        # keyed by the signal candle, like the trade check's own samples
                        x.ts = int(o.get("signal_ts") or x.ts)
                    smp.save(
                        s,
                        strategy_id=strategy_id,
                        strategy_kind=strategy_kind,
                        market=market.value,
                        timeframe=tf.value,
                        source="paper" if kind == "paper" else "backtest",
                        ref_id=ref_id,
                        samples=samples,
                        now=now,
                    )
            for old in s.scalars(
                select(KairosReview).where(KairosReview.kind == kind, KairosReview.ref_id == ref_id)
            ):
                s.delete(old)
            s.add(
                KairosReview(
                    kind=kind,
                    ref_id=ref_id,
                    strategy_id=strategy_id,
                    trades_seen=len(trades),
                    headline=str(result.get("headline", ""))[:500],
                    payload=json.dumps(_clean(result)),
                    created_at=now,
                )
            )
        result["created_at"] = now
        result["kind"] = kind
        result["ref_id"] = ref_id
        result["strategy_id"] = strategy_id
        return result

    # ------------------------------------------------------------ public

    def review_backtest(self, run_id: int) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            run = s.get(BacktestRun, run_id)
            if run is None:
                raise _not_found("backtest")
            params = json.loads(run.params or "{}")
            strat = s.scalar(
                select(Strategy)
                .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
                .where(StrategyVersion.id == run.strategy_version_id)
            )
            assert strat is not None
            rows = s.scalars(
                select(BacktestTrade)
                .where(BacktestTrade.run_id == run_id)
                .order_by(BacktestTrade.id)
            ).all()
            s.expunge_all()
        market = Market(params.get("market") or strat.market_code)
        tf = Timeframe(params.get("timeframe") or "1d")
        return self._run("backtest", run_id, strat.id, strat.kind, market, tf, list(rows))

    def review_paper(self, session_id: int) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            row = s.get(PaperSession, session_id)
            if row is None:
                raise _not_found("paper session")
            version = s.get(StrategyVersion, row.strategy_version_id)
            assert version is not None
            strat = s.get(Strategy, version.strategy_id)
            assert strat is not None
            d = json.loads(version.definition)
            rows = s.scalars(
                select(PaperTrade)
                .where(PaperTrade.session_id == session_id)
                .order_by(PaperTrade.id)
            ).all()
            s.expunge_all()
        market = Market(d["market"])
        tf = Timeframe(d.get("timeframe", "1d"))
        return self._run("paper", session_id, strat.id, strat.kind, market, tf, list(rows))

    def latest(self, kind: str, ref_id: int) -> dict[str, Any] | None:
        with self.ctx.db.session() as s:
            row = s.scalars(
                select(KairosReview)
                .where(KairosReview.kind == kind, KairosReview.ref_id == ref_id)
                .order_by(KairosReview.id.desc())
            ).first()
            if row is None:
                return None
            out: dict[str, Any] = json.loads(row.payload)
            out.update(
                {
                    "created_at": row.created_at,
                    "kind": row.kind,
                    "ref_id": row.ref_id,
                    "strategy_id": row.strategy_id,
                }
            )
            return out

    def picture(self, strategy_id: int) -> dict[str, Any]:
        """What the trade check has learned about one strategy so far."""
        with self.ctx.db.session() as s:
            samples = smp.for_strategy(s, strategy_id)
        model = fit(samples)
        trades = [x for x in samples if x.source == "trade"]
        scored = prequential(samples)[-PROOF_WINDOW:]
        skill = brier_skill(scored)
        out: dict[str, Any] = {
            "strategy_id": strategy_id,
            "judged": len(scored),
            "skill": round(skill, 3),
            "proven": len(scored) >= PROOF_MIN and skill > PROOF_SKILL,
            "samples": len(samples),
            "trades": len(trades),
            "followed_skips": len(samples) - len(trades),
            "model": model.public() if model else None,
        }
        if model is not None and trades:
            chances = np.array([model.chance(x.features) for x in trades])
            wins = np.array([x.win for x in trades])
            hi = chances >= model.threshold_strict
            out["strict_preview"] = {
                "threshold": round(model.threshold_strict, 3),
                "kept": int(hi.sum()),
                "kept_win_rate": round(float(wins[hi].mean()), 3) if hi.any() else None,
                "all_win_rate": round(float(wins.mean()), 3),
                "note": "Measured on the same trades the check learned from, so it flatters; "
                "the backtest with the check on is the honest test.",
            }
        return out


def _clean(x: Any) -> Any:
    if isinstance(x, float):
        return None if x != x or x in (float("inf"), float("-inf")) else x
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        return _clean(x.item())
    return x
