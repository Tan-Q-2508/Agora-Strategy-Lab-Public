"""``/api/portfolios`` and ``/api/opportunities`` (docs/PORTFOLIO.md, API_CONTRACT).

A portfolio is one budget in one market split into sleeves by the allocator (tested code);
opportunities are strategy-and-stocks pairings that held up on unseen years. Planning,
backtesting and scanning are jobs (poll ``/api/jobs/{id}``).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.backtest.manager import BacktestRequest
from backend.context import AppContext, get_ctx
from backend.db.models import Opportunity
from backend.errors import AgoraError
from backend.portfolio import live
from backend.portfolio import service as svc
from backend.settings_store import read_all

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


class NewPortfolio(BaseModel):
    market: Literal["IN", "US"]
    budget: float | None = Field(None, gt=0, le=1e12)
    risk: Literal["careful", "balanced", "bold"] = "balanced"
    name: str = Field("", max_length=80)
    # the best of your strategies (mix), or a monthly ranking of the index (D-91)
    method: Literal["mix", "momentum", "low_volatility"] = "mix"


class PatchPortfolio(BaseModel):
    name: str | None = Field(None, max_length=80)
    budget: float | None = Field(None, gt=0, le=1e12)
    risk: Literal["careful", "balanced", "bold"] | None = None
    manage: bool | None = None


@router.get("/portfolios")
def list_portfolios(ctx: Ctx) -> dict[str, Any]:
    return {"portfolios": svc.portfolios(ctx)}


@router.post("/portfolios", status_code=201)
def create_portfolio(ctx: Ctx, body: NewPortfolio) -> dict[str, Any]:
    """Create a portfolio and start planning it (finding opportunities first if needed)."""
    p = svc.create(
        ctx,
        market=body.market,
        budget=body.budget,
        risk=body.risk,
        name=body.name,
        method=body.method,
    )
    return {"portfolio": p, "job_id": svc.submit_plan(ctx, p["id"])}


@router.get("/portfolios/{pid}")
def get_portfolio(ctx: Ctx, pid: int) -> dict[str, Any]:
    return {"portfolio": svc.detail(ctx, pid)}


@router.patch("/portfolios/{pid}")
def patch_portfolio(ctx: Ctx, pid: int, body: PatchPortfolio) -> dict[str, Any]:
    return {"portfolio": svc.update(ctx, pid, **body.model_dump())}


@router.delete("/portfolios/{pid}")
def delete_portfolio(ctx: Ctx, pid: int) -> dict[str, Any]:
    svc.archive(ctx, pid)
    return {"ok": True}


@router.post("/portfolios/{pid}/plan")
def plan_portfolio(ctx: Ctx, pid: int) -> dict[str, Any]:
    return {"job_id": svc.submit_plan(ctx, pid)}


@router.post("/portfolios/{pid}/backtest")
def backtest_portfolio(ctx: Ctx, pid: int) -> dict[str, Any]:
    return {"job_id": svc.submit_backtest(ctx, pid)}


@router.post("/portfolios/{pid}/paper/start")
def start_paper(ctx: Ctx, pid: int) -> dict[str, Any]:
    return {"portfolio": svc.start_paper(ctx, pid)}


@router.post("/portfolios/{pid}/paper/stop")
def stop_paper(ctx: Ctx, pid: int) -> dict[str, Any]:
    return {"portfolio": svc.stop_paper(ctx, pid)}


@router.get("/portfolios/{pid}/rebalance")
def preview_rebalance(ctx: Ctx, pid: int) -> dict[str, Any]:
    """What a rebalance would move now, before anything moves."""
    p = svc.detail(ctx, pid)
    if p["status"] != "paper":
        raise AgoraError(
            "NOT_PAPER",
            "Rebalancing applies while the portfolio is paper trading.",
            "",
            status=409,
        )
    return live.preview(ctx, pid)


@router.post("/portfolios/{pid}/rebalance")
def rebalance_now(ctx: Ctx, pid: int) -> dict[str, Any]:
    p = svc.detail(ctx, pid)
    if p["status"] != "paper":
        raise AgoraError(
            "NOT_PAPER",
            "Rebalancing applies while the portfolio is paper trading.",
            "",
            status=409,
        )
    return live.rebalance(ctx, pid, "Rebalance you asked for")


@router.get("/opportunities")
def list_opportunities(
    ctx: Ctx, market: Literal["IN", "US"] | None = None, status: str | None = None
) -> dict[str, Any]:
    return {"opportunities": svc.opportunities(ctx, market, status=status)}


class ScanIn(BaseModel):
    markets: list[Literal["IN", "US"]] | None = None


@router.post("/opportunities/scan")
def scan_opportunities(ctx: Ctx, body: ScanIn | None = None) -> dict[str, Any]:
    markets = (body.markets if body else None) or None
    if not markets:
        with ctx.db.session() as s:
            markets = list(read_all(s)["markets"])
    return {"job_id": svc.start_scan(ctx, list(markets))}


@router.post("/opportunities/{oid}/dismiss")
def dismiss_opportunity(ctx: Ctx, oid: int) -> dict[str, Any]:
    return {"opportunity": svc.dismiss(ctx, oid)}


@router.post("/opportunities/{oid}/backtest", status_code=202)
def backtest_opportunity(ctx: Ctx, oid: int) -> dict[str, Any]:
    """Backtest the strategy revision on the opportunity's stocks and settings (D-80)."""
    with ctx.db.session() as s:
        row = s.get(Opportunity, oid)
        if row is None:
            raise AgoraError("NOT_FOUND", "That opportunity doesn't exist.", "", status=404)
        req = BacktestRequest(
            strategy_version_id=row.version_id,
            symbols=json.loads(row.symbols),
            overrides=json.loads(row.overrides),
            name=f"Opportunity #{oid}",
        )
    return {"run_id": ctx.backtests.submit(req)}
