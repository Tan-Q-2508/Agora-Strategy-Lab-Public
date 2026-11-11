"""``/api/news``: headlines for a market or a stock, with sentiment (KAIROS §6); the live
world-news feed and the news risk gauge (Phase 10.5, D-68)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.api.data import _instrument
from backend.context import AppContext, get_ctx
from backend.core.types import Market
from backend.settings_store import read_setting

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/news")
def news(
    ctx: Ctx,
    market: Literal["IN", "US"] | None = None,
    instrument_id: int | None = None,
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(30, ge=1, le=200),
) -> dict[str, Any]:
    svc = ctx.news
    inst = _instrument(ctx, instrument_id) if instrument_id is not None else None
    m = Market(market) if market else None
    feeds = svc.feeds(m, inst)
    if inst is None:
        feeds += svc.world_feeds(m)
    refreshing = svc.ensure_fresh(feeds)
    out: dict[str, Any] = {
        "enabled": svc.enabled(),
        "refreshing": refreshing,
        "sources": sorted({f.label for f in feeds}),
        "items": svc.latest(m, inst.id if inst else None, hours, limit),
    }
    if inst is not None:
        out["mood"] = svc.mood(inst.id, hours)
        out["alert"] = svc.alert(inst.id)
    elif m is not None:
        out["risk"] = svc.risk(m)
    return out


Region = Literal["ALL", "IN", "US", "WORLD"]


@router.get("/news/live")
def news_live(
    ctx: Ctx,
    region: Region = "ALL",
    group: str | None = None,
    topic: str | None = None,
    q: str | None = Query(None, max_length=80),
    min_severity: int = Query(0, ge=0, le=5),
    hours: int = Query(48, ge=1, le=168),
    limit: int = Query(120, ge=1, le=300),
) -> dict[str, Any]:
    """Everything the News screen shows: every feed (world, both markets) kept fresh while
    the screen is open, the filtered headlines, and the three risk gauges."""
    from backend.news import topics

    svc = ctx.news
    feeds = [*svc.feeds(None), *svc.world_feeds(None)]
    refreshing = svc.ensure_fresh(feeds)
    scope = None if region == "ALL" else region
    items = svc.latest(
        None,
        hours=hours,
        limit=limit,
        world=None,
        scope=scope,
        group=group,
        topic=topic,
        q=q,
        min_severity=min_severity,
    )
    return {
        "enabled": svc.enabled(),
        "refreshing": refreshing,
        "sources": sorted({f.label for f in feeds}),
        "items": items,
        "risk": {
            "IN": svc.risk(Market.IN),
            "US": svc.risk(Market.US),
            "WORLD": svc.risk(None),
        },
        "guard": read_setting(ctx.db, "kairos.news_guard"),
        "groups": list(topics.GROUPS),
        "topics": [{"key": t.key, "label": t.label, "group": t.group} for t in topics.TOPICS],
        "as_of": ctx.clock.now_ms(),
    }


@router.get("/news/risk")
def news_risk(ctx: Ctx, market: Literal["IN", "US", "WORLD"] = "WORLD") -> dict[str, Any]:
    out: dict[str, Any] = ctx.news.risk(None if market == "WORLD" else Market(market))
    return out


class RefreshIn(BaseModel):
    market: Literal["IN", "US"] | None = None
    instrument_id: int | None = None
    world: bool = False


@router.post("/news/refresh")
def news_refresh(ctx: Ctx, body: RefreshIn) -> dict[str, Any]:
    inst = _instrument(ctx, body.instrument_id) if body.instrument_id is not None else None
    m = Market(body.market) if body.market else None
    feeds = ctx.news.feeds(m, inst)
    if body.world:
        feeds += ctx.news.world_feeds(m)
    r = ctx.news.refresh(feeds, force=True)
    return {"feeds": r.feeds, "new": r.new, "errors": r.errors}
