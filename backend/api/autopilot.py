"""``/api/autopilot`` (SPEC §18, D-99): what Kairos and Metis are doing on their own."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend.context import AppContext, get_ctx

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/autopilot")
def autopilot_status(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = ctx.services["autopilot"].status()
    return out


@router.post("/autopilot/run")
def autopilot_run(ctx: Ctx) -> dict[str, Any]:
    """Run a round now (a job): prices, factor lists, Kairos's picks and desks."""
    ap = ctx.services["autopilot"]

    def run(job: Any) -> dict[str, Any]:
        job.progress(5, "Kairos and Metis are getting to work…")
        out: dict[str, Any] = ap.round()
        return out

    return {"job_id": ctx.jobs.submit("autopilot", "Autopilot round", run, single=True).id}
