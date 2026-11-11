"""``/api/kairos``: talk to Kairos (KAIROS §11). Replies stream as Server-Sent Events, so
steps and words appear as they happen; the page can stop listening at any time."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.data import _timeframe
from backend.context import AppContext, get_ctx
from backend.core.types import Market
from backend.kairos import memory, resolve, threads
from backend.kairos.agent import FOOTER

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]

SUGGESTIONS = [
    "Analyse RELIANCE",
    "Which Nifty 50 stocks look oversold right now?",
    "How is the US market doing today?",
    "What is a bear flag?",
    "Backtest RSI mean reversion on TCS and Infosys over 5 years",
    "Find the best strategy for HDFCBANK and ICICIBANK",
]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: int | None = None
    page: dict[str, Any] = Field(default_factory=dict)


def _sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    for e in events:
        yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"


@router.get("/kairos/status")
def kairos_status(ctx: Ctx) -> dict[str, Any]:
    mode = ctx.kairos.mode()
    ai = ctx.ai_service.status()
    return {
        "mode": mode,
        "ai_state": ai.get("state"),
        "model": ai.get("model"),
        "suggestions": SUGGESTIONS,
        "footer": FOOTER,
    }


@router.post("/kairos/chat")
def kairos_chat(ctx: Ctx, body: ChatIn) -> StreamingResponse:
    page = {
        k: v for k, v in body.page.items() if isinstance(v, str | int | float) and len(str(v)) < 200
    }
    events = ctx.kairos.chat(body.thread_id, body.message.strip(), page)
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/kairos/threads")
def kairos_threads(ctx: Ctx) -> dict[str, Any]:
    return {"threads": threads.listing(ctx.db)}


@router.get("/kairos/threads/{thread_id}")
def kairos_thread(ctx: Ctx, thread_id: int) -> dict[str, Any]:
    return {"id": thread_id, "messages": threads.messages(ctx.db, thread_id)}


@router.delete("/kairos/threads/{thread_id}")
def kairos_thread_delete(ctx: Ctx, thread_id: int) -> dict[str, Any]:
    threads.remove(ctx.db, thread_id)
    return {"deleted": thread_id}


# ---------------------------------------------------------------- training and learning


class TrainIn(BaseModel):
    market: Market
    timeframe: str = "1d"


@router.post("/kairos/train")
def kairos_train(ctx: Ctx, body: TrainIn) -> dict[str, Any]:
    """Study the market's history now (a job), even if the stats look current."""
    jid = ctx.learning.start_training(body.market, _timeframe(body.timeframe))
    return {"job_id": jid}


@router.get("/kairos/stats")
def kairos_stats(ctx: Ctx, market: Market, timeframe: str = "1d") -> dict[str, Any]:
    """What Kairos learned: its best and worst signals, with their records."""
    out: dict[str, Any] = ctx.learning.learned(market, _timeframe(timeframe))
    return out


@router.get("/kairos/lessons")
def kairos_lessons(ctx: Ctx, market: Market | None = None) -> dict[str, Any]:
    return {"lessons": memory.lessons(ctx, market)}


# ---------------------------------------------------------------- the desk


class DeskIn(BaseModel):
    market: Market
    symbols: list[str] = Field(min_length=1, max_length=30)
    timeframe: str = "1d"
    capital: float | None = Field(None, gt=0, le=1e12)


@router.post("/kairos/desk")
def kairos_desk_start(ctx: Ctx, body: DeskIn) -> dict[str, Any]:
    """Start a desk (a job: the first desk on a market studies its history first)."""
    insts = [resolve.stock(ctx, sym, body.market) for sym in body.symbols]
    tf = _timeframe(body.timeframe)
    job = ctx.jobs.submit(
        "kairos_desk",
        "Starting the Kairos desk",
        lambda jc: {"session_id": ctx.desk.launch(insts, tf, body.capital)["id"]},
    )
    return {"job_id": job.id}


@router.get("/kairos/desk")
def kairos_desks(ctx: Ctx) -> dict[str, Any]:
    return {"desks": ctx.desk.desks()}


@router.get("/kairos/desk/{session_id}")
def kairos_desk(ctx: Ctx, session_id: int) -> dict[str, Any]:
    out: dict[str, Any] = ctx.desk.desk(session_id)
    return out


@router.post("/kairos/desk/{session_id}/stop")
def kairos_desk_stop(ctx: Ctx, session_id: int) -> dict[str, Any]:
    ctx.desk.stop(session_id)
    return {"stopped": session_id}


# ---------------------------------------------------------------- reviews, the trade check,
# improvements and the always-on learner (KAIROS §16–18)


@router.get("/kairos/review/{kind}/{ref_id}")
def kairos_review(ctx: Ctx, kind: str, ref_id: int) -> dict[str, Any]:
    """The latest saved review of a backtest or paper session (``review: null`` if none)."""
    if kind not in ("backtest", "paper"):
        from backend.errors import AgoraError

        raise AgoraError("BAD_KIND", "Kairos reviews backtests and paper sessions.", "", status=404)
    return {"review": ctx.services["kairos_coach"].latest(kind, ref_id)}


@router.post("/kairos/review/{kind}/{ref_id}")
def kairos_review_now(ctx: Ctx, kind: str, ref_id: int) -> dict[str, Any]:
    """Review now (a job: reading the candles around every trade takes a few seconds)."""
    coach = ctx.services["kairos_coach"]
    if kind not in ("backtest", "paper"):
        from backend.errors import AgoraError

        raise AgoraError("BAD_KIND", "Kairos reviews backtests and paper sessions.", "", status=404)
    fn = coach.review_backtest if kind == "backtest" else coach.review_paper
    job = ctx.jobs.submit(
        "kairos_review",
        "Kairos is reviewing the trades",
        lambda jc: fn(ref_id),
        key=f"{kind}:{ref_id}",
    )
    return {"job_id": job.id}


@router.get("/kairos/trade-check/{strategy_id}")
def kairos_trade_check(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    """What Kairos's trade check has learned about one strategy."""
    out: dict[str, Any] = ctx.services["kairos_coach"].picture(strategy_id)
    return out


@router.post("/kairos/improve/{strategy_id}")
def kairos_improve(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    from backend.kairos.improve import improve

    job = ctx.jobs.submit(
        "kairos_improve",
        "Kairos is testing an improvement",
        lambda jc: improve(ctx, strategy_id, jc.progress),
        key=f"strategy:{strategy_id}",
    )
    return {"job_id": job.id}


@router.get("/kairos/improvements")
def kairos_improvements(ctx: Ctx, strategy_id: int | None = None) -> dict[str, Any]:
    from backend.kairos.improve import history

    return {"improvements": history(ctx, strategy_id)}


@router.get("/kairos/learner")
def kairos_learner(ctx: Ctx) -> dict[str, Any]:
    """What the always-on learner is doing and has learned."""
    out: dict[str, Any] = ctx.services["kairos_learner"].status()
    from backend.kairos.autolearn import strategies_with_samples

    out["strategies"] = strategies_with_samples(ctx)
    return out


@router.post("/kairos/learner/round")
def kairos_learner_round(ctx: Ctx) -> dict[str, Any]:
    """Study now instead of waiting for the next round (a job)."""
    learner = ctx.services["kairos_learner"]
    job = ctx.jobs.submit("kairos_learn", "Kairos is studying", lambda jc: learner.round())
    return {"job_id": job.id}
