"""Improve a strategy with what Kairos learned (KAIROS §16, D-72).

For a visual strategy, Kairos:

1. backtests the latest version (both halves of the period: the trades are later split 60/40
   by time),
2. reviews it (``review.py``): filters are chosen on the first 60% of the trades only,
3. adds up to two filters that kept their promise on the last 40% as ordinary entry
   conditions ("ADX (14) at least 18.4"), turned round for short trades where the reading
   has a direction,
4. backtests the candidate over the same period and compares the part after the 60% point
   (which the filters never saw while being chosen): it must make at least as much money
   after costs, win at least 2 points more often and keep at least 30% of the trades,
5. only then saves it as a new version ("Kairos: skip choppy markets …"). Earlier versions
   are always kept; one click on the old version brings it back.

Code strategies can't be rewritten safely, and the Kairos brain is improved by its own
learning; for both, Kairos turns on its trade check instead (``quality.py``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sqlalchemy import select

from backend.backtest.manager import BacktestRequest
from backend.backtest.run import RunOutput, run
from backend.core.types import Market
from backend.db.models import KairosReview, Strategy
from backend.engine.types import Trade
from backend.errors import AgoraError
from backend.kairos import review as rv
from backend.kairos.coach import Coach, _clean
from backend.kairos.quality import score_reader
from backend.metrics.summary import money
from backend.strategy import service as strategies
from backend.strategy.definition import (
    AllOf,
    Compare,
    Condition,
    IndicatorOperand,
    NumberOperand,
    StopSpec,
    VisualDefinition,
)
from backend.strategy.validator import validate

Progress = Callable[[float, str], None]
MIN_KEEP = 0.3
MIN_WIN_GAIN = 0.02


def _flip(cond: dict[str, Any]) -> tuple[str, float]:
    """The same condition for a short trade (readings with a direction turn round)."""
    op, v = str(cond["op"]), float(cond["value"])
    if not cond.get("directional"):
        return op, v
    other = "at_most" if op == "at_least" else "at_least"
    return other, (100.0 - v) if cond.get("flip") == "mirror100" else -v


def to_condition(cond: dict[str, Any], side: int) -> Compare:
    op, v = (str(cond["op"]), float(cond["value"])) if side > 0 else _flip(cond)
    return Compare(
        left=IndicatorOperand(
            name=str(cond["indicator"]),
            params={k: float(x) for k, x in dict(cond["params"]).items()},
            output=cond.get("output"),
        ),
        op=op,
        right=NumberOperand(value=round(v, 4)),
    )


def _add(rule: Condition | None, extra: list[Compare]) -> Condition | None:
    if rule is None or not extra:
        return rule
    if isinstance(rule, AllOf) and len(rule.conditions) + len(extra) <= 20:
        return AllOf(conditions=[*rule.conditions, *extra])
    return AllOf(conditions=[rule, *extra])


def with_filters(d: VisualDefinition, conds: list[dict[str, Any]]) -> VisualDefinition:
    entry = d.entry.model_copy(
        update={
            "long": _add(d.entry.long, [to_condition(c, 1) for c in conds]),
            "short": _add(d.entry.short, [to_condition(c, -1) for c in conds]),
        }
    )
    return d.model_copy(update={"entry": entry})


def _part(trades: list[Trade], after: int) -> dict[str, Any]:
    closed = [t for t in trades if t.closed and t.entry_ts >= after]
    n = len(closed)
    wins = sum(1 for t in closed if t.net_pnl > 0)
    return {
        "trades": n,
        "win_rate": round(wins / n, 3) if n else None,
        "net": round(sum(t.net_pnl for t in closed), 2),
        "charges": round(sum(t.charges for t in closed), 2),
    }


def _trades_in(out: RunOutput) -> list[rv.TradeIn]:
    return [
        rv.TradeIn(
            t.symbol,
            1 if t.side == "long" else -1,
            t.entry_ts,
            t.exit_ts,
            t.gross_pnl,
            t.charges,
            t.net_pnl,
            t.return_pct,
            t.bars_held,
            t.exit_reason,
        )
        for t in out.trades
    ]


def improve(ctx: Any, strategy_id: int, progress: Progress | None = None) -> dict[str, Any]:
    say = progress or (lambda _p, _m: None)
    with ctx.db.session() as s:
        strat = s.get(Strategy, strategy_id)
        if strat is None:
            raise AgoraError("NOT_FOUND", "That strategy doesn't exist.", "Pick one from the list.")
        version = strategies.latest_version(s, strategy_id)
        assert version is not None
        name = strat.name
    d = version.definition
    if not isinstance(d, VisualDefinition):
        return {
            "strategy_id": strategy_id,
            "changed": False,
            "headline": "Kairos can't rewrite this kind of strategy safely.",
            "lines": [
                "For code strategies and the Kairos brain, turn on Kairos's trade check when "
                "you backtest or paper trade: it learns which signals to skip without "
                "changing the strategy itself."
            ],
        }
    say(5, "Backtesting the current version…")
    prep = ctx.backtests._prepare(
        BacktestRequest(strategy_version_id=version.id, name="Kairos's check (current version)")
    )
    ctx.backtests._ensure_data(prep, lambda _p, _m: None, lambda: None)
    spec = prep.spec
    base = run(ctx.cache, spec)
    ctx.backtests._save(prep.run_id, prep, base, full=True)
    ctx.backtests._set(prep.run_id, status="done", progress=100.0, finished_at=ctx.clock.now_ms())
    market = Market(d.market)
    say(45, "Reviewing the trades…")
    trades = _trades_in(base)
    closed = sorted((t for t in trades if t.exit_reason != "end_of_test"), key=lambda t: t.exit_ts)
    coach = Coach(ctx)
    series = coach._series(
        {i.symbol: i for i in spec.instruments}, spec.timeframe, spec.start_ms, spec.end_ms
    )
    scorer = score_reader() if len(series) <= 15 else None
    result = rv.review(trades, series, market, score_for=scorer)
    result.pop("features", None)
    result.pop("closed", None)
    good = [r for r in result.get("filters", {}).get("rules", []) if r.get("held_up")]
    out: dict[str, Any] = {
        "strategy_id": strategy_id,
        "strategy": name,
        "from_version": version.version,
        "baseline_run_id": prep.run_id,
        "review": result,
        "changed": False,
    }
    if not good or len(closed) < rv.MIN_FOR_FILTERS:
        trailed = _try_trailing(ctx, out, d, spec, base, closed, version, say)
        if trailed is None:
            trailed = _try_partials(ctx, out, d, spec, base, closed, version, say)
        if trailed is not None:
            return trailed
        out["headline"] = f"Kairos kept {name} as it is: no filter held up on unseen trades."
        out["lines"] = [result.get("filters", {}).get("note", ""), *result.get("lines", [])[:3]]
        _log(ctx, out)
        return out
    split = closed[int(len(closed) * rv.TRAIN_SHARE)].entry_ts
    picked = good[:2]
    candidate = with_filters(d, [r["condition"] for r in picked])
    check = validate(candidate)
    if not check.ok:
        out["headline"] = "Kairos's filter didn't fit this strategy's rules, so nothing changed."
        out["lines"] = [i.message for i in check.errors[:3]]
        _log(ctx, out)
        return out
    say(60, "Backtesting the improved version…")
    trial = run(ctx.cache, replace(spec, definition=candidate))
    before, after = _part(base.trades, split), _part(trial.trades, split)
    better = (
        after["trades"] >= max(5, MIN_KEEP * before["trades"])
        and after["net"] >= before["net"]
        and (after["win_rate"] or 0) >= (before["win_rate"] or 0) + MIN_WIN_GAIN
    )
    words = "; ".join(r["text"].rstrip(".") for r in picked)
    out["filters"] = [{"text": r["text"], "condition": r["condition"]} for r in picked]
    out["compare"] = {"split_ts": split, "before": before, "after": after}
    if not better:
        trailed = _try_trailing(ctx, out, d, spec, base, closed, version, say)
        if trailed is None:
            trailed = _try_partials(ctx, out, d, spec, base, closed, version, say)
        if trailed is not None:
            return trailed
        out["headline"] = (
            f"Kairos tested “{words}” on {name} but it didn't do better on the unseen part of the "
            f"period, so the strategy stays as it is."
        )
        out["lines"] = [_compare_line(before, after, market)]
        _log(ctx, out)
        return out
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        strat_row = s.get(Strategy, strategy_id)
        assert strat_row is not None
        saved = strategies.add_version(
            s,
            strat_row,
            candidate,
            now,
            note=f"Kairos: {words}"[:500],
            created_by="kairos",
            evidence={"test": "unseen trades", "split_ts": split, "before": before, "after": after},
            source=f"kairos-improve:{version.id}",
        )
        new_version = saved.version
        new_version_id = saved.id
    out.update(
        {
            "changed": True,
            "to_version": new_version,
            "to_version_id": new_version_id,
            "headline": f"Kairos saved version {new_version} of {name}: {words}.",
            "lines": [
                _compare_line(before, after, market),
                f"Version {version.version} is kept; open the strategy's history to go back.",
            ],
        }
    )
    _log(ctx, out)
    say(100, "Done.")
    return out


TRAIL_WIDTHS = (2.0, 3.0, 4.0)  # × ATR(14)


PARTIAL_TRIES = ("partial_half_r", "partial_thirds_r")


def _try_partials(
    ctx: Any,
    out: dict[str, Any],
    d: VisualDefinition,
    spec: Any,
    base: RunOutput,
    closed: list[rv.TradeIn],
    version: Any,
    say: Progress,
) -> dict[str, Any] | None:
    """When neither a filter nor a trailing stop helps: partial exits (D-125), half at 1R or
    thirds at 1R and 2R, with the stop moved to the entry after the first. Chosen on the
    first 60% of the trades, kept only if it also makes more after costs on the last 40%."""
    from backend.metis.trial import partial_spec

    if d.exit.scale_out is not None or len(closed) < rv.MIN_FOR_FILTERS:
        return None
    split = closed[int(len(closed) * rv.TRAIN_SHARE)].entry_ts
    say(80, "Trying partial exits…")
    stop = d.exit.stop_loss or StopSpec(kind="percent", value=PARTIAL_STOP.get(d.timeframe, 5.0))
    tried = []
    for name in PARTIAL_TRIES:
        exit_ = d.exit.model_copy(update={"stop_loss": stop, "scale_out": partial_spec(name, 1.0)})
        cand = d.model_copy(update={"exit": exit_})
        res = run(ctx.cache, replace(spec, definition=cand))
        early = [t for t in res.trades if t.closed and t.entry_ts < split]
        tried.append((sum(t.net_pnl for t in early), name, cand, res))
    _net, name, cand, res = max(tried, key=lambda x: x[0])
    before, after = _part(base.trades, split), _part(res.trades, split)
    enough = after["trades"] >= max(5, MIN_KEEP * before["trades"])
    if not (enough and after["net"] > before["net"]):
        out["partials"] = {"plan": name, "before": before, "after": after, "kept": False}
        return None
    words = (
        "sell half at 1R, then the stop moves to the entry"
        if name == "partial_half_r"
        else "sell a third at 1R and a third at 2R, then the stop moves to the entry"
    )
    if d.exit.stop_loss is None:
        words += f" (with a {stop.value:g}% stop-loss)"
    with ctx.db.session() as s:
        row = s.get(Strategy, out["strategy_id"])
        assert row is not None
        saved = strategies.add_version(
            s,
            row,
            cand,
            ctx.clock.now_ms(),
            note=f"Kairos: {words}",
            created_by="kairos",
            evidence={"test": "unseen trades", "split_ts": split, "before": before, "after": after},
            source=f"kairos-improve:{version.id}",
        )
        new_version, new_id = saved.version, saved.id
    market = Market(d.market)
    out.update(
        {
            "changed": True,
            "to_version": new_version,
            "to_version_id": new_id,
            "partials": {"plan": name, "before": before, "after": after, "kept": True},
            "compare": {"split_ts": split, "before": before, "after": after},
            "headline": f"Kairos saved version {new_version} of {out['strategy']}: {words}.",
            "lines": [
                _compare_line(before, after, market),
                "No entry filter or trailing stop helped, but booking part of the profit early "
                "did: trades that were ahead no longer turn into full losses.",
                f"Version {version.version} is kept; open the strategy's history to go back.",
            ],
        }
    )
    _log(ctx, out)
    say(100, "Done.")
    return out


PARTIAL_STOP = {"1d": 6.0, "1h": 3.0, "15m": 1.5, "5m": 1.0, "1m": 0.6}


def _try_trailing(
    ctx: Any,
    out: dict[str, Any],
    d: VisualDefinition,
    spec: Any,
    base: RunOutput,
    closed: list[rv.TradeIn],
    version: Any,
    say: Progress,
) -> dict[str, Any] | None:
    """When no entry filter helps: a trailing stop (D-119). The width is chosen on the first
    60% of the trades and kept only if it also makes more after costs on the last 40%, which it
    never saw. ``None`` when the strategy already trails, there are too few trades, or it
    didn't help."""
    if d.exit.trailing_stop is not None or len(closed) < rv.MIN_FOR_FILTERS:
        return None
    split = closed[int(len(closed) * rv.TRAIN_SHARE)].entry_ts
    say(70, "Trying a trailing stop…")
    tried = []
    for w in TRAIL_WIDTHS:
        trail = StopSpec(kind="atr", value=w)
        cand = d.model_copy(update={"exit": d.exit.model_copy(update={"trailing_stop": trail})})
        res = run(ctx.cache, replace(spec, definition=cand))
        early = [t for t in res.trades if t.closed and t.entry_ts < split]
        tried.append((sum(t.net_pnl for t in early), w, cand, res))
    _net, w, cand, res = max(tried, key=lambda x: x[0])
    before, after = _part(base.trades, split), _part(res.trades, split)
    enough = after["trades"] >= max(5, MIN_KEEP * before["trades"])
    if not (enough and after["net"] > before["net"]):
        out["trailing"] = {"atr": w, "before": before, "after": after, "kept": False}
        return None
    words = f"a trailing stop {w:g} ATRs behind the best price"
    with ctx.db.session() as s:
        row = s.get(Strategy, out["strategy_id"])
        assert row is not None
        saved = strategies.add_version(
            s,
            row,
            cand,
            ctx.clock.now_ms(),
            note=f"Kairos: {words}",
            created_by="kairos",
            evidence={"test": "unseen trades", "split_ts": split, "before": before, "after": after},
            source=f"kairos-improve:{version.id}",
        )
        new_version, new_id = saved.version, saved.id
    market = Market(d.market)
    out.update(
        {
            "changed": True,
            "to_version": new_version,
            "to_version_id": new_id,
            "trailing": {"atr": w, "before": before, "after": after, "kept": True},
            "compare": {"split_ts": split, "before": before, "after": after},
            "headline": f"Kairos saved version {new_version} of {out['strategy']}: {words}.",
            "lines": [
                _compare_line(before, after, market),
                "No entry filter helped, but locking in gains did: winners now keep most of "
                "their gain when the move ends.",
                f"Version {version.version} is kept; open the strategy's history to go back.",
            ],
        }
    )
    _log(ctx, out)
    say(100, "Done.")
    return out


def _compare_line(before: dict[str, Any], after: dict[str, Any], market: Market) -> str:
    def wr(x: dict[str, Any]) -> str:
        return "–" if x["win_rate"] is None else f"{x['win_rate'] * 100:.0f}%"

    return (
        f"On the part of the period the filter never saw: {before['trades']} trades winning "
        f"{wr(before)} and making {money(before['net'], market)} after costs, against "
        f"{after['trades']} trades winning {wr(after)} and making "
        f"{money(after['net'], market)} with the filter."
    )


def _log(ctx: Any, out: dict[str, Any]) -> None:
    with ctx.db.session() as s:
        s.add(
            KairosReview(
                kind="improvement",
                ref_id=out.get("baseline_run_id"),
                strategy_id=out["strategy_id"],
                trades_seen=int(out.get("review", {}).get("trades", 0)),
                headline=str(out.get("headline", ""))[:500],
                payload=json.dumps(_clean(out)),
                created_at=ctx.clock.now_ms(),
            )
        )


def history(ctx: Any, strategy_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        q = select(KairosReview).where(KairosReview.kind == "improvement")
        if strategy_id is not None:
            q = q.where(KairosReview.strategy_id == strategy_id)
        rows = s.scalars(q.order_by(KairosReview.id.desc()).limit(limit)).all()
        out = []
        for r in rows:
            p = json.loads(r.payload)
            out.append(
                {
                    "id": r.id,
                    "strategy_id": r.strategy_id,
                    "created_at": r.created_at,
                    "headline": r.headline,
                    "changed": bool(p.get("changed")),
                    "to_version": p.get("to_version"),
                    "compare": p.get("compare"),
                    "lines": p.get("lines", []),
                }
            )
        return out
