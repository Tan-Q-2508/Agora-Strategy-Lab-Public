"""Keeping what held up (METIS §5, D-76).

A change becomes a new version of the strategy (every earlier version is kept); a new strategy
is saved as "Metis · …". Either way a full backtest is started so the user can open it, and
Kairos gets a lesson written by code from the test's numbers, so Kairos knows what Metis found.
"""

from __future__ import annotations

from typing import Any

from backend.backtest.manager import BacktestRequest
from backend.core.types import Market
from backend.db.models import MetisIdea, Strategy
from backend.errors import AgoraError
from backend.kairos import memory
from backend.metis import notebook
from backend.metrics.summary import money
from backend.settings_store import read_all
from backend.strategy import revisions
from backend.strategy import service as strategies
from backend.strategy.validator import validate


def _lesson(idea: dict[str, Any], name: str) -> str:
    r = idea["result"]
    market = Market(idea["market"] or "IN")
    exam = r["candidate"]["exam"]
    if r.get("baseline"):
        base = r["baseline"]["exam"]
        return (
            f"Metis found that “{idea['title']}” improves {name}: on years it hadn't seen it made "
            f"{money(exam['net'] - base['net'], market)} more after costs and won "
            f"{(exam['win_rate'] or 0) * 100:.0f}% of trades against "
            f"{(base['win_rate'] or 0) * 100:.0f}%."
        )
    return (
        f"Metis found a new strategy, {name}: on years it hadn't seen it made "
        f"{money(exam['net'], market)} after costs over {exam['trades']} trades, winning "
        f"{(exam['win_rate'] or 0) * 100:.0f}%."
    )


def _evidence(idea: dict[str, Any]) -> dict[str, Any]:
    """What a revision records about the test that justified it (docs/REVISIONS.md §1)."""
    r = idea["result"]
    return {
        "test": "Metis: study and exam years",
        "verdict": idea["verdict"],
        "split": r.get("split"),
        "baseline": r.get("baseline"),
        "candidate": r.get("candidate"),
        "luck": r.get("luck"),
    }


def save(ctx: Any, idea_id: int, *, auto: bool = False) -> dict[str, Any]:
    """Save an idea that held up. Safe to call twice (the second call changes nothing).

    Through the revision gateway (D-79): a change, or a "new" strategy that is really one the
    user has, becomes that strategy's next revision; a genuinely new strategy is created, at
    most ``metis.new_per_day`` a day when Metis saves on its own (``auto``)."""
    idea = notebook.get_idea(ctx, idea_id)
    if idea is None:
        raise AgoraError("NOT_FOUND", "That idea isn't in Metis's notebook.", "", status=404)
    if idea["status"] == "saved":
        return idea
    if idea["status"] != "held_up":
        raise AgoraError(
            "NOT_KEPT",
            "Metis only saves ideas that held up on the exam years.",
            "Pick an idea marked “Held up”.",
            status=409,
        )
    res = validate(idea["rules"]["definition"])
    if not res.ok or res.definition is None:
        raise AgoraError("BAD_RULES", "The saved rules no longer pass Agora's checks.", "")
    d = res.definition
    now = ctx.clock.now_ms()
    note = f"Metis: {idea['title']}"[:500]
    family = (idea["result"] or {}).get("family")
    with ctx.db.session() as s:
        if idea["kind"] == "new_strategy" and not family:
            if revisions.match(s, d, template_key=idea["rules"].get("template")) is not None:
                raise AgoraError(
                    "CHANGED",
                    "A strategy with the same logic appeared since Metis tested this idea, so "
                    "it wasn't saved as a new one.",
                    "Metis will test it against that strategy in a later round.",
                    status=409,
                )
            limit = int(read_all(s)["metis.new_per_day"]) if auto else None
            try:
                saved = revisions.save(
                    s,
                    definition=d,
                    author="metis",
                    name=f"Metis · {idea['title']}"[:120],
                    description=f"Found by Metis. {idea['why']}"[:2000],
                    now=now,
                    note=note,
                    template_key=idea["rules"].get("template"),
                    evidence=_evidence(idea),
                    source=f"metis-idea:{idea_id}",
                    new_per_day=limit,
                )
            except revisions.NewStrategyLimit as exc:
                raise AgoraError(
                    "DAILY_LIMIT",
                    f"{exc} The idea waits in the notebook.",
                    "Save it yourself with its Save button, or let Metis save it tomorrow.",
                    status=409,
                ) from exc
        else:
            target = family["strategy_id"] if family else idea["strategy_id"]
            tested = family["version_id"] if family else idea["strategy_version_id"]
            strat_row = s.get(Strategy, target)
            latest = strategies.latest_version(s, target)
            if strat_row is None or strat_row.archived_at is not None or latest is None:
                raise AgoraError(
                    "GONE",
                    "That strategy was deleted or archived, so nothing was saved.",
                    "",
                    status=409,
                )
            if latest.id != tested:
                raise AgoraError(
                    "CHANGED",
                    "That strategy has changed since Metis tested this idea, so it wasn't saved.",
                    "Metis will test its ideas on the new version in a later round.",
                    status=409,
                )
            saved = revisions.revise(
                s,
                target,
                d,
                now,
                author="metis",
                note=note,
                evidence=_evidence(idea),
                source=f"metis-idea:{idea_id}",
                why=family["why"] if family else "an improved version",
            )
        sid, vid, name = saved.strategy_id, saved.version_id, saved.name
    run_id = None
    r = idea["result"]
    try:
        run_id = ctx.backtests.submit(
            BacktestRequest(
                strategy_version_id=vid,
                symbols=r.get("symbols") or None,
                start=r.get("start"),
                end=r.get("end"),
                capital=r.get("capital"),
                name=f"Metis: {idea['title']}"[:120],
            )
        )
    except AgoraError:
        run_id = None  # the version is saved; the backtest can be run from its page
    with ctx.db.session() as s:
        row = s.get(MetisIdea, idea_id)
        assert row is not None
        row.status = "saved"
        row.saved_strategy_id = sid
        row.saved_version_id = vid
        row.run_id = run_id
    memory.note(ctx, f"metis-{idea_id}", _lesson(idea, name), idea["market"])
    out = notebook.get_idea(ctx, idea_id)
    assert out is not None
    out.pop("rules", None)
    return {**out, "strategy_name": name, "saved_as": saved.outcome}
