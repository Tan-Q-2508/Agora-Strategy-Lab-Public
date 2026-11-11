"""``/api/metis``: Metis, Kairos's AI researcher (docs/METIS.md, API_CONTRACT).

Switching Metis on, its pace and its focus are ordinary settings (``/api/settings``); these
endpoints show what it is doing and has found, run a round now, and save an idea that held up.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.context import AppContext, get_ctx
from backend.errors import AgoraError
from backend.metis import apply, notebook

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/metis")
def metis_status(ctx: Ctx) -> dict[str, Any]:
    """What Metis is doing now, its totals, its latest rounds and ideas."""
    out: dict[str, Any] = ctx.services["metis"].status()
    out["rounds"] = notebook.rounds(ctx, limit=10)
    out["ideas"] = notebook.ideas(ctx, limit=30)
    return out


@router.get("/metis/ideas")
def metis_ideas(ctx: Ctx, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"ideas": notebook.ideas(ctx, status=status, limit=max(1, min(limit, 200)))}


@router.get("/metis/ideas/{idea_id}")
def metis_idea(ctx: Ctx, idea_id: int) -> dict[str, Any]:
    idea = notebook.get_idea(ctx, idea_id)
    if idea is None:
        raise AgoraError("NOT_FOUND", "That idea isn't in Metis's notebook.", "", status=404)
    return {"idea": idea}


@router.get("/metis/rounds/{round_id}")
def metis_round(ctx: Ctx, round_id: int) -> dict[str, Any]:
    """One round with what Metis was shown (the brief), how it thought, and its ideas."""
    r = notebook.get_round(ctx, round_id)
    if r is None:
        raise AgoraError("NOT_FOUND", "That round isn't in Metis's notebook.", "", status=404)
    return {"round": r, "ideas": notebook.ideas(ctx, round_id=round_id, limit=10)}


@router.post("/metis/round")
def metis_round_now(ctx: Ctx) -> dict[str, Any]:
    """Research now (a job), even when the switch is off. Without the AI helper the round
    works from the playbook (D-81)."""
    metis = ctx.services["metis"]
    if metis.working:
        raise AgoraError(
            "BUSY", "Metis is already researching.", "Watch this page: it updates by itself."
        )
    job = ctx.jobs.submit("metis_round", "Metis is researching", lambda jc: metis.round("user"))
    return {"job_id": job.id}


@router.post("/metis/ideas/{idea_id}/save")
def metis_save(ctx: Ctx, idea_id: int) -> dict[str, Any]:
    """Save an idea that held up (when Metis isn't set to save them by itself)."""
    return {"idea": apply.save(ctx, idea_id)}


@router.get("/metis/library")
def metis_library(ctx: Ctx) -> dict[str, Any]:
    """What Metis knows: its quant library by area (METIS §11), for the Metis screen."""
    from backend.metis import library

    areas: dict[str, dict[str, Any]] = {}
    for s in library.sections():
        a = areas.setdefault(
            s.doc, {"key": s.doc, "title": AREA_TITLE.get(s.doc, s.doc), "sections": []}
        )
        a["sections"].append(s.title)
    out = sorted(
        areas.values(),
        key=lambda a: list(AREA_TITLE).index(a["key"]) if a["key"] in AREA_TITLE else 99,
    )
    return {"areas": out, "total": sum(len(a["sections"]) for a in out)}


AREA_TITLE = {
    "method": "The research method",
    "statistics": "Backtest statistics and luck",
    "anomalies": "Documented anomalies and factors",
    "technical": "Technical strategies, researched",
    "volatility": "Volatility and regimes",
    "meanreversion": "Random walks, mean reversion and pairs",
    "portfolio": "Portfolio construction",
    "risk": "Risk, drawdowns and survival",
    "costs": "Costs, fills and turnover",
    "ml": "Machine learning and AI research",
    "markets": "Market structure: India and the US",
    "playbook": "The expert's playbook",
}


class CombineBody(BaseModel):
    version_ids: list[int] = Field(min_length=2, max_length=5)
    mode: str = "all"
    min_votes: int = 2


@router.post("/metis/combine")
def combine(ctx: Ctx, body: CombineBody) -> dict[str, Any]:
    """Test strategies together, as a background job (it runs several backtests)."""
    from backend.metis import combine as c

    c.build(ctx, body.version_ids, body.mode, body.min_votes)  # refuse bad choices at once
    job = ctx.jobs.submit(
        "strategy_combine",
        "Testing strategies together",
        lambda _jc: c.judge(ctx, body.version_ids, body.mode, body.min_votes),
    )
    return {"job_id": job.id}


@router.post("/metis/combine/repair/{version_id}")
def combine_repair(ctx: Ctx, version_id: int) -> dict[str, Any]:
    """Find what would have blocked a strategy's bad trades and test the combination."""
    from backend.metis import combine as c

    job = ctx.jobs.submit(
        "strategy_repair",
        "Looking for what would have blocked the bad trades",
        lambda jc: c.repair(ctx, version_id, tell=lambda t: jc.progress(50, t)),
    )
    return {"job_id": job.id}
