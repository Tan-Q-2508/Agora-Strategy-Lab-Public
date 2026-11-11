"""``/api/paper``: paper accounts and live paper-trading sessions (API_CONTRACT → Paper
trading). Sessions run on their own threads; these endpoints start, control and read them.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from backend.context import AppContext, get_ctx
from backend.core.types import Timeframe
from backend.data import store
from backend.data.adjust import adjusted
from backend.db.models import PaperFill, PaperOrder, PaperSession
from backend.errors import AgoraError
from backend.paper.compare import vs_backtest
from backend.paper.service import AccountIn, SessionIn
from backend.paper.timing import bar_end_ms
from backend.strategy import service as strategies

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/paper/accounts")
def list_accounts(ctx: Ctx, include_kairos: bool = False) -> dict[str, Any]:
    return {"accounts": ctx.paper.accounts(include_kairos=include_kairos)}


@router.post("/paper/accounts", status_code=201)
def create_account(ctx: Ctx, body: AccountIn) -> dict[str, Any]:
    return {"account": ctx.paper.create_account(body)}


@router.get("/paper/sessions")
def list_sessions(ctx: Ctx) -> dict[str, Any]:
    return {"sessions": ctx.paper.sessions(), "mode": "replay" if ctx.paper.replay else "live"}


@router.post("/paper/sessions/clear-stopped")
def clear_stopped(ctx: Ctx) -> dict[str, Any]:
    """Take every stopped session off the Paper page (D-206); nothing is deleted."""
    return {"hidden": ctx.paper.clear_stopped()}


@router.post("/paper/sessions", status_code=201)
def start_session(ctx: Ctx, body: SessionIn) -> dict[str, Any]:
    sid = ctx.paper.start_session(body)
    return {"session_id": sid, "session": ctx.paper.detail(sid)}


@router.get("/paper/sessions/{sid}")
def session_detail(ctx: Ctx, sid: int) -> dict[str, Any]:
    return {"session": ctx.paper.detail(sid)}


@router.post("/paper/sessions/{sid}/stop")
def stop_session(ctx: Ctx, sid: int) -> dict[str, Any]:
    ctx.paper.stop(sid)
    return {"session": ctx.paper.detail(sid)}


@router.post("/paper/sessions/{sid}/pause")
def pause_session(ctx: Ctx, sid: int) -> dict[str, Any]:
    ctx.paper.pause(sid)
    return {"session": ctx.paper.detail(sid)}


@router.post("/paper/sessions/{sid}/resume")
def resume_session(ctx: Ctx, sid: int) -> dict[str, Any]:
    ctx.paper.resume(sid)
    return {"session": ctx.paper.detail(sid)}


@router.get("/paper/sessions/{sid}/vs-backtest")
def session_vs_backtest(ctx: Ctx, sid: int) -> dict[str, Any]:
    return vs_backtest(ctx, sid)


@router.get("/paper/trades/{trade_id}/story")
def trade_story(ctx: Ctx, trade_id: int) -> dict[str, Any]:
    """Why a trade happened and what did or didn't work (27.11)."""
    from backend.kairos import story

    told = story.story(ctx, trade_id)
    if told is None:
        raise AgoraError("NOT_FOUND", "That trade isn't closed yet.", "Go back.", status=404)
    return told


@router.get("/paper/sessions/{sid}/candles")
def session_candles(
    ctx: Ctx, sid: int, instrument_id: int, limit: int = Query(300, ge=10, le=5000)
) -> dict[str, Any]:
    """Candles for the live chart, only up to the session's own "now" (a replay must not
    show the future), with the session's fills as markers."""
    with ctx.db.session() as s:
        row = s.get(PaperSession, sid)
        if row is None:
            raise AgoraError(
                "NOT_FOUND", "That paper session doesn't exist.", "Go back.", status=404
            )
        version = strategies.get_version(s, row.strategy_version_id)
        assert version is not None
        inst = store.get_instrument(s, instrument_id)
        if inst is None:
            raise AgoraError("NOT_FOUND", "That stock isn't known.", "Pick another.", status=404)
        notes = json.loads(row.notes or "{}")
        fills = s.execute(
            select(PaperOrder.side, PaperOrder.reason, PaperFill.ts, PaperFill.price, PaperFill.qty)
            .join(PaperFill, PaperFill.order_id == PaperOrder.id)
            .where(PaperOrder.session_id == sid, PaperOrder.instrument_id == instrument_id)
            .order_by(PaperFill.ts)
        ).all()
        last_bar = row.last_bar_ts
    tf = Timeframe(version.definition.timeframe)
    runner = ctx.paper.runner(sid)
    if runner is not None and runner.state != "starting":
        now = runner.clock.now_ms()
    elif notes.get("mode") == "replay":
        now = int(notes.get("now", last_bar or 0))
    else:
        now = ctx.clock.now_ms()
    bars = [
        b
        for b in ctx.cache.bars(inst, tf, 0, now + 1)
        if bar_end_ms(ctx.calendar, inst.market, tf, b.ts) <= now
    ][-limit:]
    factor = {b.ts: b.split_factor for b in bars}
    first = bars[0].ts if bars else now
    return {
        "instrument": {"id": inst.id, "symbol": inst.symbol, "market": inst.market.value},
        "timeframe": tf.value,
        "bars": [
            {
                "ts": a.ts,
                "open": round(a.open, 4),
                "high": round(a.high, 4),
                "low": round(a.low, 4),
                "close": round(a.close, 4),
                "volume": a.volume,
            }
            for a in (adjusted(b) for b in bars)
        ],
        "markers": [
            {
                "ts": ts,
                "side": side,
                "price": round(price * factor.get(ts, 1.0), 4),
                "qty": qty,
                "reason": reason,
            }
            for side, reason, ts, price, qty in fills
            if ts >= first
        ],
    }
