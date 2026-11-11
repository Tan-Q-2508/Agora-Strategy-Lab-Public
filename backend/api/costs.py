"""Brokerage and slippage profiles (for the backtest setup and paper accounts)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend.context import AppContext, get_ctx
from backend.core.types import Market
from backend.db.models import BrokerageProfile, SlippageProfile

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/costs/profiles")
def profiles(ctx: Ctx, market: Market | None = None) -> dict[str, Any]:
    with ctx.db.session() as s:
        b = select(BrokerageProfile).order_by(BrokerageProfile.id)
        sl = select(SlippageProfile).order_by(SlippageProfile.id)
        if market is not None:
            b = b.where(BrokerageProfile.market_code == market.value)
            sl = sl.where(SlippageProfile.market_code == market.value)
        brokerage = [
            {
                "id": r.id,
                "market": r.market_code,
                "name": r.name,
                "rules": json.loads(r.rules),
                "is_default": bool(r.is_default),
            }
            for r in s.scalars(b)
        ]
        slippage = [
            {
                "id": r.id,
                "market": r.market_code,
                "name": r.name,
                "bps": r.bps,
                "is_default": bool(r.is_default),
            }
            for r in s.scalars(sl)
        ]
    return {"brokerage": brokerage, "slippage": slippage}
