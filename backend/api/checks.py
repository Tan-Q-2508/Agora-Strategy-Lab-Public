"""Checks of strategy revisions (API_CONTRACT → Checks): the look-ahead check (D-88) and
forward checks on new candles (D-90)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from backend.checks import forward, lookahead, store
from backend.context import AppContext, get_ctx
from backend.db.models import Strategy
from backend.errors import AgoraError
from backend.settings_store import read_all

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.post("/strategies/{strategy_id}/lookahead", status_code=202)
def start_lookahead(
    ctx: Ctx, strategy_id: int, body: lookahead.LookaheadRequest | None = None
) -> dict[str, Any]:
    """Start the look-ahead check on a saved version (default: the newest)."""
    job_id = lookahead.submit(ctx, strategy_id, body or lookahead.LookaheadRequest())
    return {"job_id": job_id}


@router.get("/strategies/{strategy_id}/checks")
def strategy_checks(
    ctx: Ctx,
    strategy_id: int,
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    with ctx.db.session() as s:
        if s.get(Strategy, strategy_id) is None:
            raise AgoraError(
                "STRATEGY_NOT_FOUND",
                "That strategy doesn't exist.",
                "Pick a strategy from the list.",
                status=404,
            )
        return {"checks": store.for_strategy(s, strategy_id, kind, limit)}


@router.get("/checks/forward")
def forward_checks(ctx: Ctx) -> dict[str, Any]:
    """Every revision Kairos or Metis saved (still in use) and every portfolio sleeve, with its
    latest forward check on candles formed since (D-90)."""
    with ctx.db.session() as s:
        auto = bool(read_all(s)["revisions.auto_undo"])
    return {"items": forward.overview(ctx), "auto_undo": auto}


@router.post("/checks/forward/run", status_code=202)
def run_forward_checks(ctx: Ctx) -> dict[str, Any]:
    """Check now: every subject with enough new candles, as a background job."""

    def work(jc: Any) -> dict[str, Any]:
        jc.progress(5, "Re-testing on the newest candles…")
        done = forward.run_due(ctx, limit=50, force=True)
        jc.progress(100, f"Checked {len(done)}.")
        return {"checked": len(done), "checks": done}

    job = ctx.jobs.submit("forward_check", "Forward checks", work, single=True)
    return {"job_id": job.id}


@router.post("/checks/{check_id}/undo")
def undo_check(ctx: Ctx, check_id: int) -> dict[str, Any]:
    """Undo what stopped holding up: the earlier version back, or the sleeve wound down."""
    return {"check": forward.undo(ctx, check_id)}
