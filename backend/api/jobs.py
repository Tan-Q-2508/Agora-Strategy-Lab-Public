"""``/api/jobs``: progress and cancellation for any long-running job."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend.context import AppContext, get_ctx
from backend.errors import AgoraError

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _missing(job_id: str) -> AgoraError:
    return AgoraError(
        "JOB_NOT_FOUND",
        "That task isn't running any more.",
        "Refresh the page to see the latest state.",
        detail=job_id,
        status=404,
    )


@router.get("/jobs")
def list_jobs(
    ctx: Ctx, kind: str | None = None, active: bool = False, key: str | None = None
) -> dict[str, Any]:
    """``kind`` may list several kinds separated by commas; ``active`` keeps unfinished jobs."""
    return {"jobs": [j.public() for j in ctx.jobs.list(kind, active=active, key=key)]}


@router.get("/jobs/{job_id}")
def get_job(ctx: Ctx, job_id: str) -> dict[str, Any]:
    job = ctx.jobs.get(job_id)
    if job is None:
        raise _missing(job_id)
    return job.public()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(ctx: Ctx, job_id: str) -> dict[str, Any]:
    job = ctx.jobs.get(job_id)
    if job is None:
        raise _missing(job_id)
    ctx.jobs.cancel(job_id)
    return job.public()
