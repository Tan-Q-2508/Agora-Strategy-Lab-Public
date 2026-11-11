"""``GET /api/markets/status``: open/closed and countdown for each market."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend.context import AppContext, get_ctx
from backend.core.types import Market
from backend.markets.status import describe, market_status

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/markets/status")
def status(ctx: Ctx) -> dict[str, Any]:
    ctx.refresh_overrides()
    now = ctx.clock.now_ms()
    markets = [describe(market_status(ctx.calendar, m, now), now) for m in Market]
    return {"markets": markets, "server_time": now}
