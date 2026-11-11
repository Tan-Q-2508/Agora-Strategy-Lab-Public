"""``/api/analysis``: Kairos's chart reading and forecasts (KAIROS §11)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from backend.api.data import _instrument, _timeframe
from backend.context import AppContext, get_ctx

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/analysis/chart")
def analysis_chart(
    ctx: Ctx,
    instrument_id: int,
    timeframe: str = "1d",
    start: int | None = None,
    forecast: bool = True,
) -> dict[str, Any]:
    inst = _instrument(ctx, instrument_id)
    tf = _timeframe(timeframe)
    result: dict[str, Any] = dict(ctx.analysis.chart(inst, tf, start, with_forecast=forecast))
    # The first reading on a market starts Kairos's study of its history (KAIROS §8.1),
    # so the findings can say how often each signal worked.
    result["training_job"] = (
        ctx.learning.ensure_trained(inst.market, tf) if ctx.learning.auto else None
    )
    return result


@router.get("/analysis/forecast")
def analysis_forecast(
    ctx: Ctx,
    instrument_id: int,
    timeframe: str = "1d",
    horizon: int | None = Query(None, ge=1, le=30),
) -> dict[str, Any]:
    inst = _instrument(ctx, instrument_id)
    result: dict[str, Any] = ctx.analysis.forecast(inst, _timeframe(timeframe), horizon)
    return result
