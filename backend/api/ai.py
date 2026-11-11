"""``/api/ai``: the optional AI helper (API_CONTRACT → AI helper). Explanations stream as
Server-Sent Events so words appear as they're written; the page can stop them any time."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.context import AppContext, get_ctx

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


class PullIn(BaseModel):
    model: str | None = Field(None, max_length=120)


class ExplainIn(BaseModel):
    kind: Literal["backtest", "trade", "metric", "paper_day"]
    id: int | None = None
    question: str | None = Field(None, max_length=500)


class DraftIn(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)
    market: Literal["IN", "US"]


@router.get("/ai/status")
def ai_status(ctx: Ctx, fresh: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = ctx.ai_service.status(fresh=fresh)
    return result


@router.post("/ai/pull", status_code=202)
def ai_pull(ctx: Ctx, body: PullIn) -> dict[str, Any]:
    return {"job_id": ctx.ai_service.pull(body.model)}


def _sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    for e in events:
        yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"


@router.post("/ai/explain")
def ai_explain(ctx: Ctx, body: ExplainIn) -> StreamingResponse:
    events = ctx.ai_service.explain(body.kind, body.id, body.question)
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/ai/draft-strategy")
def ai_draft(ctx: Ctx, body: DraftIn) -> dict[str, Any]:
    result: dict[str, Any] = ctx.ai_service.draft(body.idea, body.market)
    return result


@router.get("/ai/conversations/{conv_id}")
def ai_conversation(ctx: Ctx, conv_id: int) -> dict[str, Any]:
    result: dict[str, Any] = ctx.ai_service.conversation(conv_id)
    return result
