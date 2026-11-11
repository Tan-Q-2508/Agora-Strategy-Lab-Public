"""Putting strategies together, under the same honest tests as everything else (§5, D-227).

``compare`` answers the screen: the combination against each member alone, and which trades it
removed and added. ``repair`` is for Metis and Kairos: find a strategy's bad trades, look for
strategies that would have blocked them without blocking the good ones, and test the combination.

The guard against luck, which is the whole point:

- Candidates are chosen on the **study years only**; the exam years are only ever read in the
  final judgement, through the same ``trial.judge_against`` every change passes: exam gain after
  costs, study not worse, trades kept, the overfitting check and the luck check.
- **Only strategies that already passed a real test may join**, so two lucky things can't
  excuse each other. (``proven`` lists them.)
- Every combination judged is written in the notebook as a tested idea, so it counts as a try
  and raises the bar for the next one (D-162). At most ``MAX_JUDGED`` are judged per strategy.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from backend.backtest.run import RunOutput
from backend.db.models import MetisIdea, Strategy, StrategyVersion
from backend.engine.types import Trade
from backend.errors import AgoraError
from backend.lab.measure import part
from backend.metis import brief, notebook, trial
from backend.strategy import service as strategies
from backend.strategy.definition import AnyDefinition, CombinedDefinition

MAX_JUDGED = 3
MIN_BAD_BLOCKED = 0.3  # a blocker must stop at least this share of the study's bad trades
MAX_GOOD_LOST = 0.3  # and at most this share of its good ones
MODES = ("all", "any", "veto", "vote")


def build(
    ctx: Any, version_ids: list[int], mode: str, min_votes: int = 2, window: int = 5
) -> AnyDefinition:
    """The combined definition of saved versions; the first one sets market, size and limits."""
    if len(set(version_ids)) < 2:
        raise AgoraError("TOO_FEW", "Pick at least two different strategies.", "Add another.")
    if mode not in MODES:
        raise AgoraError("BAD_MODE", "That way of combining isn't known.", "Pick another.")
    members = []
    with ctx.db.session() as s:
        for vid in version_ids:
            v = strategies.get_version(s, vid)
            if v is None:
                raise AgoraError("NOT_FOUND", "One of those strategies is gone.", "Pick again.")
            d = v.definition
            if d.kind not in ("visual", "code"):
                raise AgoraError(
                    "CANT_COMBINE",
                    "Only strategies made of rules or code can be combined yet.",
                    "Kairos's desks and monthly rankings work differently; pick another.",
                )
            name = s.scalar(select(Strategy.name).where(Strategy.id == v.strategy_id))
            members.append((str(name), vid, d))
    first = members[0][2]
    for _, _, d in members[1:]:
        if d.market != first.market or d.timeframe != first.timeframe:
            raise AgoraError(
                "MIXED",
                "Combined strategies must share a market and a timeframe.",
                "Pick strategies on the same market and chart.",
            )
    common = {
        k: getattr(first, k)
        for k in (
            "schema_version",
            "market",
            "universe",
            "sizing",
            "limits",
            "timeframe",
            "product",
        )
    }
    return CombinedDefinition.model_validate(
        {
            **{k: v.model_dump() if hasattr(v, "model_dump") else v for k, v in common.items()},
            "kind": "combined",
            "parameters": [],
            "combine": {"mode": mode, "min_votes": min_votes, "window": window},
            "members": [
                {"name": n, "version_id": vid, "definition": json.loads(d.model_dump_json())}
                for n, vid, d in members
            ],
        }
    )


def _key(t: Trade) -> tuple[str, int]:
    return (t.symbol, t.entry_ts)


def _row(t: Trade) -> dict[str, Any]:
    return {
        "symbol": t.symbol,
        "side": t.side,
        "entry_ts": t.entry_ts,
        "net": round(t.net_pnl, 2),
        "return_pct": round(t.return_pct, 2),
    }


def trade_changes(base: RunOutput, combo: RunOutput, limit: int = 200) -> dict[str, Any]:
    """Which trades the combination removed and added, against the first strategy alone."""
    old = {_key(t): t for t in base.trades}
    new = {_key(t): t for t in combo.trades}
    removed = [t for k, t in old.items() if k not in new]
    added = [t for k, t in new.items() if k not in old]
    return {
        "removed": [_row(t) for t in sorted(removed, key=lambda t: t.net_pnl)[:limit]],
        "added": [_row(t) for t in sorted(added, key=lambda t: -t.net_pnl)[:limit]],
        "removed_n": len(removed),
        "removed_net": round(sum(t.net_pnl for t in removed), 2),
        "removed_losers": sum(1 for t in removed if t.net_pnl <= 0),
        "added_n": len(added),
        "added_net": round(sum(t.net_pnl for t in added), 2),
        "added_winners": sum(1 for t in added if t.net_pnl > 0),
    }


def _strategy_of(ctx: Any, version_id: int) -> int:
    with ctx.db.session() as s:
        sid = s.scalar(select(StrategyVersion.strategy_id).where(StrategyVersion.id == version_id))
    if sid is None:
        raise AgoraError("NOT_FOUND", "That strategy is gone.", "Pick another.")
    return int(sid)


def _name(ctx: Any, strategy_id: int) -> str:
    with ctx.db.session() as s:
        return str(s.scalar(select(Strategy.name).where(Strategy.id == strategy_id)))


def judge(ctx: Any, version_ids: list[int], mode: str, min_votes: int = 2) -> dict[str, Any]:
    """Run the combination through the fixed tests, against its first strategy alone; the attempt
    goes into the notebook, so it counts as a try whatever comes out."""
    d = build(ctx, version_ids, mode, min_votes)
    base = brief.baseline(ctx, _strategy_of(ctx, version_ids[0]))
    if base is None:
        raise AgoraError(
            "NO_BASE", "The first strategy has no prices to test on.", "Download its stocks."
        )
    held, verdict, result, spec = trial.judge_against(ctx, base, d, "filter")
    combo_run = trial._parts(spec, d, ctx)[3]  # the same run again, for its trades
    alone = []
    for vid in version_ids:
        with ctx.db.session() as s:
            v = strategies.get_version(s, vid)
        assert v is not None
        _, parts, _, _ = trial._parts(spec, v.definition, ctx)
        alone.append(
            {
                "name": _name(ctx, v.strategy_id),
                "study": parts["study"],
                "exam": parts["exam"],
            }
        )
    split = int(result.get("split") or base.split_ms)
    combined = {
        "study": part(combo_run.trades, spec.start_ms, split),
        "exam": part(combo_run.trades, split, spec.end_ms + 1),
    }
    fp = notebook.fingerprint("combine", version_ids[0], {"v": version_ids, "m": mode})
    if not notebook.seen(ctx, fp):  # a repeat is the same test, not another try
        rid = notebook.start_round(ctx, "user", "", "rules", "improve")
        notebook.add_idea(
            ctx,
            rid,
            kind="filter",  # a combination is a filter on its first strategy
            title=f"Combine ({mode}): " + " + ".join(a["name"] for a in alone)[:180],
            why="The strategy combiner",
            market_code=base.market.value,
            strategy_id=base.strategy_id,
            strategy_version_id=base.version_id,
            spec=json.dumps({"definition": json.loads(d.model_dump_json())}),
            fingerprint=fp,
            status="held_up" if held else "rejected",
            verdict=verdict,
            result=json.dumps(trial_public(result), default=str),
            origin="playbook",
        )
        notebook.update_round(
            ctx,
            rid,
            status="done",
            finished_at=ctx.clock.now_ms(),
            note=verdict[:300],
            ideas=1,
            kept=int(held),
        )
    return {
        "held_up": held,
        "verdict": verdict,
        "checks": result.get("checks", []),
        "alone": alone,
        "combined": combined,
        "changes": trade_changes(base.out, combo_run),
        "tries": notebook.tries(ctx, strategy_id=base.strategy_id),
        "definition": json.loads(d.model_dump_json()),
    }


def trial_public(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if k not in ("daily", "base_daily")}


def proven(ctx: Any, market: str, timeframe: str) -> list[int]:
    """Latest versions of strategies that passed a real test: only these may join a repair."""
    with ctx.db.session() as s:
        ids = list(
            s.scalars(
                select(MetisIdea.saved_strategy_id).where(
                    MetisIdea.status == "saved",
                    MetisIdea.market_code == market,
                    MetisIdea.saved_strategy_id.is_not(None),
                )
            )
        )
        out = []
        for sid in dict.fromkeys(ids):
            row = s.get(Strategy, sid)
            if row is None or row.archived_at is not None:
                continue
            v = strategies.latest_version(s, sid)
            if (
                v is not None
                and v.definition.timeframe == timeframe
                and v.definition.kind
                in (
                    "visual",
                    "code",
                )
            ):
                out.append(v.id)
    return out


def repair(ctx: Any, version_id: int, *, tell: Any = None) -> dict[str, Any]:
    """Find what would have blocked this strategy's bad trades, on study years only, then judge
    the best few combinations by the fixed tests."""
    sid = _strategy_of(ctx, version_id)
    base = brief.baseline(ctx, sid)
    if base is None:
        return {"status": "no_data", "note": "This strategy has no prices to test on."}
    study = [t for t in base.out.trades if t.entry_ts < base.split_ms]
    bad = {_key(t) for t in study if t.net_pnl <= 0}
    good = {_key(t) for t in study if t.net_pnl > 0}
    if len(bad) < 5:
        return {"status": "too_few", "note": "Too few bad trades in the study years to learn from."}
    d = base.definition
    candidates = [v for v in proven(ctx, d.market, d.timeframe) if v != base.version_id]
    scored = []
    for vid in candidates:
        for mode in ("all", "veto"):
            combo = build(ctx, [base.version_id, vid], mode)
            out = trial._parts(base.spec, combo, ctx)[3]
            kept = {_key(t) for t in out.trades if t.entry_ts < base.split_ms}
            blocked = len(bad - kept) / max(1, len(bad))
            lost = len(good - kept) / max(1, len(good))
            if tell:
                tell(
                    f"Study years: {mode} with #{vid} blocks {blocked:.0%} of bad, {lost:.0%} good"
                )
            if blocked >= MIN_BAD_BLOCKED and lost <= MAX_GOOD_LOST:
                scored.append((blocked - lost, vid, mode))
    scored.sort(reverse=True)
    judged = [judge(ctx, [base.version_id, vid], mode) for _, vid, mode in scored[:MAX_JUDGED]]
    return {
        "status": "done",
        "bad_trades": len(bad),
        "good_trades": len(good),
        "candidates": len(candidates),
        "passed_study": len(scored),
        "judged": [
            {k: j[k] for k in ("held_up", "verdict", "alone", "combined", "tries")} for j in judged
        ],
    }
