"""``/api/watchlists`` (SPEC §18, D-94): yours, ready-made, and the ones Kairos and Metis made."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.context import AppContext, get_ctx

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


class NewList(BaseModel):
    market: Literal["IN", "US"]
    name: str = Field(min_length=1, max_length=80)
    symbols: list[str] = Field(default_factory=list, max_length=500)
    description: str = Field("", max_length=500)


class PatchList(BaseModel):
    name: str | None = Field(None, max_length=80)
    description: str | None = Field(None, max_length=500)
    add: list[str] | None = Field(None, max_length=500)
    remove: list[str] | None = Field(None, max_length=500)


class CopyList(BaseModel):
    name: str | None = Field(None, max_length=80)


@router.get("/watchlists")
def list_watchlists(
    ctx: Ctx, market: str | None = None, category: str | None = None, kind: str | None = None
) -> dict[str, Any]:
    return {"watchlists": ctx.watchlists.lists(market, category, kind)}


@router.post("/watchlists", status_code=201)
def create_watchlist(ctx: Ctx, body: NewList) -> dict[str, Any]:
    return {
        "watchlist": ctx.watchlists.create(body.market, body.name, body.symbols, body.description)
    }


@router.get("/watchlists/{wid}")
def get_watchlist(ctx: Ctx, wid: int) -> dict[str, Any]:
    return {"watchlist": ctx.watchlists.detail(wid)}


@router.patch("/watchlists/{wid}")
def patch_watchlist(ctx: Ctx, wid: int, body: PatchList) -> dict[str, Any]:
    return {"watchlist": ctx.watchlists.update(wid, **body.model_dump())}


@router.delete("/watchlists/{wid}")
def delete_watchlist(ctx: Ctx, wid: int) -> dict[str, Any]:
    ctx.watchlists.delete(wid)
    return {"ok": True}


@router.post("/watchlists/{wid}/copy", status_code=201)
def copy_watchlist(ctx: Ctx, wid: int, body: CopyList) -> dict[str, Any]:
    return {"watchlist": ctx.watchlists.copy(wid, body.name)}


@router.post("/watchlists/refresh-factors")
def refresh_factors(ctx: Ctx, market: Literal["IN", "US"] | None = None) -> dict[str, Any]:
    """Rebuild the price-based factor lists now from saved daily candles."""
    return {"refreshed": ctx.watchlists.refresh_factors(market, force=True)}


@router.get("/instruments/{iid}/profile")
def instrument_profile(ctx: Ctx, iid: int) -> dict[str, Any]:
    """A stock's sector, industry, size, exposure tags and the lists it is in."""
    ctx.watchlists.ensure()
    return {"profile": ctx.watchlists.profile(iid), "lists": ctx.watchlists.lists_with(iid)}


@router.get("/sectors")
def sectors(ctx: Ctx, market: Literal["IN", "US"] = "IN") -> dict[str, Any]:
    """Every sector and industry: returns, rotation, breadth, booms and slumps (D-98)."""
    out: dict[str, Any] = ctx.sectors.overview(market)
    return out
