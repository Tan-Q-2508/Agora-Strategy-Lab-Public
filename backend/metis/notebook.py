"""Metis's notebook: its rounds of research and every idea it had (METIS §8, §9).

Every idea is kept, the ones that failed included: the full record is what lets the user judge
Metis, and what lets Metis learn (the latest verdicts go into the next round's brief).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select

from backend.db.models import MetisIdea, MetisRound

THINKING_LIMIT = 8000


def fingerprint(kind: str, version_id: int | None, rules: dict[str, Any]) -> str:
    """The same idea on the same strategy version is tested once (a repeat is skipped)."""
    key = json.dumps({"k": kind, "v": version_id, "r": rules}, sort_keys=True, default=str)
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def seen(ctx: Any, fp: str) -> bool:
    with ctx.db.session() as s:
        return (
            s.scalar(select(MetisIdea.id).where(MetisIdea.fingerprint == fp).limit(1)) is not None
        )


TESTED = ("held_up", "rejected", "saved")


def tries(
    ctx: Any,
    *,
    strategy_id: int | None = None,
    market: str | None = None,
    kind: str | None = None,
) -> int:
    """Ideas already tested on a strategy (or of a kind in a market): the N of the luck
    check (D-82). Ideas that couldn't be tested don't count; they never saw the exam."""
    with ctx.db.session() as s:
        q = select(func.count(MetisIdea.id)).where(MetisIdea.status.in_(TESTED))
        if strategy_id is not None:
            q = q.where(MetisIdea.strategy_id == strategy_id)
        if market is not None:
            q = q.where(MetisIdea.market_code == market)
        if kind is not None:
            q = q.where(MetisIdea.kind == kind)
        return int(s.scalar(q) or 0)


def record(ctx: Any) -> dict[str, tuple[int, int]]:
    """Each direction's record: (ideas kept, ideas that didn't hold up), for the agenda."""
    with ctx.db.session() as s:
        rows = s.execute(
            select(MetisRound.direction, MetisIdea.status, func.count(MetisIdea.id))
            .join(MetisRound, MetisRound.id == MetisIdea.round_id)
            .where(MetisIdea.status.in_(TESTED))
            .group_by(MetisRound.direction, MetisIdea.status)
        ).all()
    out: dict[str, list[int]] = {}
    for direction, status, n in rows:
        pair = out.setdefault(str(direction), [0, 0])
        pair[0 if status in ("held_up", "saved") else 1] += int(n)
    return {k: (v[0], v[1]) for k, v in out.items()}


def playbook_tries(ctx: Any, market: str) -> int:
    """Playbook entries (D-144) already tested on the user's stocks in this market."""
    with ctx.db.session() as s:
        rows = s.scalars(
            select(MetisIdea.spec).where(
                MetisIdea.status.in_(TESTED),
                MetisIdea.market_code == market,
                MetisIdea.kind == "new_strategy",
            )
        )
        return sum(1 for r in rows if '"playbook"' in (r or ""))


def recent_directions(ctx: Any, limit: int = 4) -> list[str]:
    """The directions of the latest rounds, newest first."""
    with ctx.db.session() as s:
        return [
            str(d)
            for d in s.scalars(
                select(MetisRound.direction)
                .where(MetisRound.status.in_(("done", "running")))
                .order_by(MetisRound.id.desc())
                .limit(limit)
            )
        ]


def close_unfinished(ctx: Any) -> int:
    """Rounds left "running" when Agora closed mid-round never finish: mark them failed, so
    the Metis page doesn't show them running for ever and the choice of the next direction
    doesn't count them as done. Returns how many were closed."""
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        rows = list(s.scalars(select(MetisRound).where(MetisRound.status == "running")))
        for r in rows:
            r.status = "failed"
            r.finished_at = now
            r.note = r.note or "Agora closed during this round."
        s.commit()
    return len(rows)


def start_round(ctx: Any, trigger: str, focus: str, model: str, direction: str = "improve") -> int:
    with ctx.db.session() as s:
        row = MetisRound(
            started_at=ctx.clock.now_ms(),
            status="running",
            trigger=trigger,
            focus=focus,
            model=model,
            direction=direction,
            noticed="",
            thinking="",
            note="",
            ideas=0,
            kept=0,
            brief="",
        )
        s.add(row)
        s.flush()
        return int(row.id)


def update_round(ctx: Any, round_id: int, **values: Any) -> None:
    if "thinking" in values:
        values["thinking"] = str(values["thinking"])[-THINKING_LIMIT:]
    with ctx.db.session() as s:
        row = s.get(MetisRound, round_id)
        if row is not None:
            for k, v in values.items():
                setattr(row, k, v)


def add_idea(ctx: Any, round_id: int, **values: Any) -> int:
    with ctx.db.session() as s:
        row = MetisIdea(round_id=round_id, created_at=ctx.clock.now_ms(), **values)
        s.add(row)
        s.flush()
        return int(row.id)


def set_idea(ctx: Any, idea_id: int, **values: Any) -> None:
    with ctx.db.session() as s:
        row = s.get(MetisIdea, idea_id)
        if row is not None:
            for k, v in values.items():
                setattr(row, k, v)


def _without_daily(result: dict[str, Any]) -> dict[str, Any]:
    """The daily returns kept for the overfitting check (D-89) are for code, not screens."""
    result.pop("daily", None)
    result.pop("base_daily", None)
    return result


def idea_public(r: MetisIdea, *, full: bool = False) -> dict[str, Any]:
    spec = json.loads(r.spec or "{}")
    if not full:
        spec.pop("definition", None)
    return {
        "id": r.id,
        "round_id": r.round_id,
        "created_at": r.created_at,
        "kind": r.kind,
        "title": r.title,
        "why": r.why,
        "market": r.market_code,
        "strategy_id": r.strategy_id,
        "strategy_version_id": r.strategy_version_id,
        "rules": spec,
        "status": r.status,
        "verdict": r.verdict,
        "result": _without_daily(json.loads(r.result or "{}")),
        "saved_strategy_id": r.saved_strategy_id,
        "saved_version_id": r.saved_version_id,
        "run_id": r.run_id,
        "origin": r.origin,
    }


def round_public(r: MetisRound, *, full: bool = False) -> dict[str, Any]:
    out = {
        "id": r.id,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "status": r.status,
        "trigger": r.trigger,
        "focus": r.focus,
        "model": r.model,
        "noticed": r.noticed,
        "note": r.note,
        "ideas": r.ideas,
        "kept": r.kept,
        "thinking": r.thinking,
        "direction": r.direction,
        "autopsy": autopsy_of(r.brief or ""),
    }
    if full:
        out["brief"] = r.brief
    return out


AUTOPSY_STARTS = (
    "Trade autopsy of",
    "Second opinions from",
    "Win rate when another strategy agreed",
    "The market's mood",
    "What separated its losers",
    "What past autopsies taught",
    "No single reading separated",
)


def autopsy_of(brief: str) -> list[dict[str, Any]]:
    """The trade autopsy's lines from a round's brief, by strategy (D-109), for the screen."""
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in brief.splitlines():
        if line.startswith("STRATEGY #"):
            head = line.split(" (", 1)[0]
            current = {"strategy": head.removeprefix("STRATEGY "), "lines": []}
        elif current is not None and line.startswith(AUTOPSY_STARTS):
            if not current["lines"]:
                out.append(current)
            current["lines"].append(line)
    return out


def ideas(
    ctx: Any, *, limit: int = 30, status: str | None = None, round_id: int | None = None
) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        q = select(MetisIdea)
        if status:
            q = q.where(MetisIdea.status == status)
        if round_id is not None:
            q = q.where(MetisIdea.round_id == round_id)
        rows = s.scalars(q.order_by(MetisIdea.id.desc()).limit(limit)).all()
        return [idea_public(r) for r in rows]


def get_idea(ctx: Any, idea_id: int) -> dict[str, Any] | None:
    with ctx.db.session() as s:
        row = s.get(MetisIdea, idea_id)
        return idea_public(row, full=True) if row is not None else None


def rounds(ctx: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        rows = s.scalars(select(MetisRound).order_by(MetisRound.id.desc()).limit(limit)).all()
        return [round_public(r) for r in rows]


def get_round(ctx: Any, round_id: int) -> dict[str, Any] | None:
    with ctx.db.session() as s:
        row = s.get(MetisRound, round_id)
        return round_public(row, full=True) if row is not None else None


def totals(ctx: Any) -> dict[str, int]:
    with ctx.db.session() as s:
        by = dict(
            s.execute(
                select(MetisIdea.status, func.count(MetisIdea.id)).group_by(MetisIdea.status)
            ).all()
        )
        n_rounds = s.scalar(select(func.count(MetisRound.id)).where(MetisRound.status == "done"))
    tested = int(by.get("held_up", 0)) + int(by.get("rejected", 0)) + int(by.get("saved", 0))
    return {
        "rounds": int(n_rounds or 0),
        "ideas": sum(int(v) for v in by.values()),
        "tested": tested,
        "held_up": int(by.get("held_up", 0)) + int(by.get("saved", 0)),
        "saved": int(by.get("saved", 0)),
    }


def memory_lines(ctx: Any, limit: int = 15) -> list[str]:
    """The notebook as Metis reads it in its next brief: what it tried and how it went.

    Only the verdict and the *study-year* numbers are shown, never the exam-year numbers:
    re-reading the exam's numbers round after round would slowly teach Metis the exam
    (D-76). The verdict alone is a much smaller hint."""
    words = {
        "held_up": "HELD UP",
        "saved": "HELD UP, saved",
        "rejected": "did not hold up",
        "untestable": "could not be tested",
    }
    out = []
    for i in ideas(ctx, limit=limit):
        where = f"strategy #{i['strategy_id']}" if i["strategy_id"] else "new strategy"
        study = str(i["result"].get("study_line", "")) if i["status"] != "untestable" else ""
        reason = i["verdict"] if i["status"] == "untestable" else study
        by = " (from the playbook)" if i.get("origin") == "playbook" else ""
        out.append(
            f"- [{words.get(i['status'], i['status'])}] {i['kind']}{by} on {where}: "
            f"{i['title']}. {reason}".rstrip()
        )
    return out
