"""``/api/world`` (SPEC §18, D-95, D-96): world events and what they mean for each market,
sector and stock; sudden moves and their most likely cause; what the world map learned."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends

from backend.context import AppContext, get_ctx
from backend.world.scenarios import SCENARIOS

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/world")
def world(ctx: Ctx, refresh: bool = False) -> dict[str, Any]:
    """Both markets' view of today's world events, the events, and the latest moves."""
    return {
        "IN": ctx.world.view("IN", refresh=refresh),
        "US": ctx.world.view("US"),
        "events": ctx.world.events(limit=20),
        "moves": ctx.world.investigations(limit=10),
    }


@router.get("/world/events")
def world_events(ctx: Ctx, limit: int = 30) -> dict[str, Any]:
    return {"events": ctx.world.events(limit=min(limit, 200))}


@router.get("/world/moves")
def world_moves(ctx: Ctx, market: Literal["IN", "US"] | None = None) -> dict[str, Any]:
    return {"moves": ctx.world.investigations(market)}


@router.post("/world/investigate")
def world_investigate(ctx: Ctx, market: Literal["IN", "US"] = "IN") -> dict[str, Any]:
    """Look for an unusual move on the latest candle now (investigated once each)."""
    return {"moves": ctx.world.investigate(market)}


@router.get("/world/lessons")
def world_lessons(ctx: Ctx, scenario: str | None = None) -> dict[str, Any]:
    return {"lessons": ctx.world.lessons(scenario)}


@router.post("/world/learn")
def world_learn(ctx: Ctx) -> dict[str, Any]:
    """Re-measure past events and measure live ones now (a job)."""

    def run(job: Any) -> dict[str, Any]:
        job.progress(10, "Measuring past world events on saved prices…")
        trained = ctx.world.train_history(force=True)
        job.progress(70, "Measuring live events whose days have passed…")
        return {"trained": trained, "live": ctx.world.learn_live()}

    job = ctx.jobs.submit("world_learn", "Learning from world events", run, single=True)
    return {"job_id": job.id}


@router.get("/world/stock/{iid}")
def world_stock(ctx: Ctx, iid: int) -> dict[str, Any]:
    return {"stock": ctx.world.stock(iid)}


@router.get("/world/map")
def world_map() -> dict[str, Any]:
    """Every kind of event Agora recognises and how it usually ripples."""
    return {
        "scenarios": [
            {
                "key": s.key,
                "title": s.title,
                "group": s.group,
                "chain": list(s.chain),
                "effects": s.effects,
                "assets": s.assets,
            }
            for s in SCENARIOS
        ]
    }
