"""Backtests: start, follow, read results, export, compare (API_CONTRACT → Backtests)."""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.backtest.manager import BacktestRequest
from backend.backtest.run import _clean
from backend.context import AppContext, get_ctx
from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market
from backend.db.models import (
    BacktestEquity,
    BacktestOrder,
    BacktestRun,
    BacktestTrade,
    Instrument,
    StrategyVersion,
)
from backend.errors import AgoraError
from backend.metrics import tearsheet

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _run(ctx: AppContext, run_id: int) -> BacktestRun:
    with ctx.db.session() as s:
        row = s.get(BacktestRun, run_id)
    if row is None:
        raise AgoraError(
            "BACKTEST_NOT_FOUND",
            "That backtest doesn't exist.",
            "Pick one from your backtests.",
            status=404,
        )
    return row


def _brief(row: BacktestRun, strategy_id: int | None = None) -> dict[str, Any]:
    params = json.loads(row.params)
    metrics = json.loads(row.metrics) if row.metrics else {}
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "progress": row.progress,
        "starred": bool(row.starred),
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "strategy_id": params.get("strategy_id", strategy_id),
        "strategy_name": params.get("strategy_name"),
        "version": params.get("version"),
        "strategy_version_id": row.strategy_version_id,
        "mode": params.get("mode", "single"),
        "market": params.get("market"),
        "timeframe": params.get("timeframe"),
        "symbols": params.get("symbols", []),
        "start": params.get("start"),
        "end": params.get("end"),
        "capital": params.get("capital"),
        "headline": {
            k: metrics.get(k)
            for k in (
                "total_return",
                "cagr",
                "max_drawdown",
                "sharpe",
                "win_rate",
                "trades",
                "vs_benchmark",
                "final_equity",
            )
        },
        "error": row.error_plain,
        "parent_run_id": row.parent_run_id,
        "overrides": params.get("overrides", {}),
    }


@router.post("/backtests", status_code=202)
def start_backtest(ctx: Ctx, body: BacktestRequest) -> dict[str, Any]:
    run_id = ctx.backtests.submit(body)
    return {"run_id": run_id, "job_id": f"backtest-{run_id}"}


@router.get("/backtests")
def list_backtests(
    ctx: Ctx,
    strategy_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    starred: bool | None = None,
) -> dict[str, Any]:
    with ctx.db.session() as s:
        stmt = select(BacktestRun).where(BacktestRun.parent_run_id.is_(None))
        if strategy_id is not None:
            stmt = stmt.join(
                StrategyVersion, StrategyVersion.id == BacktestRun.strategy_version_id
            ).where(StrategyVersion.strategy_id == strategy_id)
        if starred is not None:
            stmt = stmt.where(BacktestRun.starred == int(starred))
        rows = s.scalars(
            stmt.order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc()).limit(limit)
        ).all()
    return {"backtests": [_brief(r) for r in rows]}


@router.get("/backtests/{run_id}")
def get_backtest(ctx: Ctx, run_id: int) -> dict[str, Any]:
    row = _run(ctx, run_id)
    job = ctx.jobs.get(f"backtest-{run_id}")
    repro = json.loads(row.repro) if row.repro else None
    return {
        **_brief(row),
        "params": json.loads(row.params),
        "metrics": json.loads(row.metrics) if row.metrics else None,
        "warnings": json.loads(row.warnings) if row.warnings else [],
        "summary": row.summary_text,
        "error_detail": row.error_detail,
        "repro": repro,
        "job": job.public() if job else None,
    }


@router.post("/backtests/{run_id}/cancel")
def cancel_backtest(ctx: Ctx, run_id: int) -> dict[str, Any]:
    _run(ctx, run_id)
    return {"cancelling": ctx.backtests.cancel(run_id)}


class PatchRun(BaseModel):
    starred: bool | None = None
    name: str | None = Field(None, max_length=120)


@router.patch("/backtests/{run_id}")
def patch_backtest(ctx: Ctx, run_id: int, body: PatchRun) -> dict[str, Any]:
    _run(ctx, run_id)
    with ctx.db.session() as s:
        row = s.get(BacktestRun, run_id)
        assert row is not None
        if body.starred is not None:
            row.starred = int(body.starred)
        if body.name is not None:
            row.name = body.name.strip() or None
        return _brief(row)


@router.get("/backtests/{run_id}/equity")
def equity(ctx: Ctx, run_id: int) -> dict[str, Any]:
    row = _run(ctx, run_id)
    with ctx.db.session() as s:
        pts = s.scalars(
            select(BacktestEquity)
            .where(BacktestEquity.run_id == run_id)
            .order_by(BacktestEquity.ts)
        ).all()
    metrics = json.loads(row.metrics) if row.metrics else {}
    return {
        "points": [
            {
                "ts": p.ts,
                "equity": round(p.equity, 2),
                "cash": round(p.cash, 2),
                "exposure": round(p.exposure, 4),
                "drawdown": round(p.drawdown, 6),
            }
            for p in pts
        ],
        "benchmark": [
            {"ts": int(t), "value": round(float(v), 2)}
            for t, v in metrics.get("benchmark_curve", [])
        ],
        "capital": json.loads(row.params).get("capital"),
    }


@router.get("/backtests/{run_id}/tearsheet")
def tear_sheet(ctx: Ctx, run_id: int) -> dict[str, Any]:
    """The tear sheet (D-89). Saved with every run since Phase 16; worked out from the saved
    equity and trades for older runs."""
    row = _run(ctx, run_id)
    metrics = json.loads(row.metrics) if row.metrics else {}
    if metrics.get("tear_sheet"):
        return dict(metrics["tear_sheet"])
    if row.status != "done":
        raise AgoraError("NOT_FINISHED", "This backtest hasn't finished.", "Wait for it to finish.")
    params = json.loads(row.params)
    with ctx.db.session() as s:
        pts = s.execute(
            select(BacktestEquity.ts, BacktestEquity.equity)
            .where(BacktestEquity.run_id == run_id)
            .order_by(BacktestEquity.ts)
        ).all()
        pnls = s.scalars(
            select(BacktestTrade.net_pnl).where(
                BacktestTrade.run_id == run_id, BacktestTrade.exit_reason != "end_of_test"
            )
        ).all()
    trials = len((metrics.get("sweep") or {}).get("cells") or []) or 1
    return dict(
        _clean(
            tearsheet.compute(
                [(int(t), float(v)) for t, v in pts],
                [float(x) for x in pnls],
                float(params.get("capital") or (pts[0][1] if pts else 1.0)),
                ZoneInfo(MARKET_TZ[Market(params.get("market", "IN"))]),
                n_trials=trials,
            )
        )
    )


SORTABLE = {
    "entry_ts": BacktestTrade.entry_ts,
    "exit_ts": BacktestTrade.exit_ts,
    "net_pnl": BacktestTrade.net_pnl,
    "return_pct": BacktestTrade.return_pct,
    "charges": BacktestTrade.charges,
    "bars_held": BacktestTrade.bars_held,
}


def _trade_rows(
    ctx: AppContext, run_id: int, sort: str, order: str, symbol: str | None, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    with ctx.db.session() as s:
        stmt = (
            select(BacktestTrade, Instrument.symbol)
            .join(Instrument, Instrument.id == BacktestTrade.instrument_id)
            .where(BacktestTrade.run_id == run_id)
        )
        if symbol:
            stmt = stmt.where(Instrument.symbol == symbol.upper())
        total = len(s.execute(stmt).all())
        col = SORTABLE.get(sort, BacktestTrade.entry_ts)
        stmt = (
            stmt.order_by(col.desc() if order == "desc" else col.asc(), BacktestTrade.id)
            .offset(offset)
            .limit(limit)
        )
        rows = [
            {
                "id": t.id,
                "symbol": sym,
                "side": t.side,
                "qty": t.qty,
                "entry_ts": t.entry_ts,
                "entry_price": t.entry_price,
                "exit_ts": t.exit_ts,
                "exit_price": t.exit_price,
                "gross_pnl": t.gross_pnl,
                "charges": t.charges,
                "net_pnl": t.net_pnl,
                "return_pct": t.return_pct,
                "bars_held": t.bars_held,
                "entry_reason": t.entry_reason,
                "exit_reason": t.exit_reason,
            }
            for t, sym in s.execute(stmt).all()
        ]
    return rows, total


@router.get("/backtests/{run_id}/trades")
def trades(
    ctx: Ctx,
    run_id: int,
    sort: str = "entry_ts",
    order: Literal["asc", "desc"] = "asc",
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=5000),
    cursor: int = Query(0, ge=0),
) -> dict[str, Any]:
    _run(ctx, run_id)
    rows, total = _trade_rows(ctx, run_id, sort, order, symbol, limit, cursor)
    nxt = cursor + len(rows)
    return {"trades": rows, "total": total, "next_cursor": nxt if nxt < total else None}


EXIT_WORDS = {
    "signal": "Exit rule",
    "stop": "Stop-loss",
    "target": "Take-profit",
    "trailing": "Trailing stop",
    "time": "Time exit",
    "square_off": "Intraday square-off",
    "end_of_test": "Still open at the end",
}


@router.get("/backtests/{run_id}/trades.csv")
def trades_csv(ctx: Ctx, run_id: int) -> Response:
    row = _run(ctx, run_id)
    market = Market(json.loads(row.params).get("market", "IN"))
    tz = ZoneInfo(MARKET_TZ[market])
    rows, _ = _trade_rows(ctx, run_id, "entry_ts", "asc", None, 1_000_000, 0)

    def fmt(ms: int | None) -> str:
        return ms_to_dt(ms, tz).strftime("%Y-%m-%d %H:%M") if ms else ""

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Symbol",
            "Side",
            "Quantity",
            "Entry time",
            "Entry price",
            "Exit time",
            "Exit price",
            "Gross P&L",
            "Charges",
            "Net P&L",
            "Return %",
            "Candles held",
            "Entry reason",
            "Exit reason",
        ]
    )
    for t in rows:
        w.writerow(
            [
                t["symbol"],
                t["side"],
                f"{t['qty']:g}",
                fmt(t["entry_ts"]),
                f"{t['entry_price']:.2f}",
                fmt(t["exit_ts"]),
                f"{t['exit_price']:.2f}" if t["exit_price"] is not None else "",
                f"{t['gross_pnl']:.2f}",
                f"{t['charges']:.2f}",
                f"{t['net_pnl']:.2f}",
                f"{t['return_pct']:.2f}",
                t["bars_held"],
                t["entry_reason"],
                EXIT_WORDS.get(t["exit_reason"] or "", ""),
            ]
        )
    name = f"agora-backtest-{run_id}-trades.csv"
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/backtests/{run_id}/orders")
def orders(
    ctx: Ctx, run_id: int, status: str | None = "rejected", limit: int = Query(200, ge=1, le=5000)
) -> dict[str, Any]:
    _run(ctx, run_id)
    with ctx.db.session() as s:
        stmt = (
            select(BacktestOrder, Instrument.symbol)
            .join(Instrument, Instrument.id == BacktestOrder.instrument_id)
            .where(BacktestOrder.run_id == run_id)
        )
        if status:
            stmt = stmt.where(BacktestOrder.status == status)
        rows = s.execute(stmt.order_by(BacktestOrder.ts).limit(limit)).all()
    return {
        "orders": [
            {
                "ts": o.ts,
                "symbol": sym,
                "type": o.type,
                "side": o.side,
                "qty": o.qty,
                "status": o.status,
                "reason": o.reason,
            }
            for o, sym in rows
        ]
    }


@router.get("/backtests/{run_id}/children")
def children(ctx: Ctx, run_id: int) -> dict[str, Any]:
    _run(ctx, run_id)
    with ctx.db.session() as s:
        rows = s.scalars(
            select(BacktestRun).where(BacktestRun.parent_run_id == run_id).order_by(BacktestRun.id)
        ).all()
    return {"children": [_brief(r) for r in rows]}


class CompareBody(BaseModel):
    run_ids: list[int] = Field(min_length=1, max_length=4)


@router.post("/backtests/compare")
def compare(ctx: Ctx, body: CompareBody) -> dict[str, Any]:
    series = []
    table = []
    for rid in body.run_ids:
        row = _run(ctx, rid)
        if row.status != "done":
            raise AgoraError(
                "NOT_FINISHED",
                f"Backtest #{rid} hasn't finished.",
                "Pick finished backtests to compare.",
            )
        brief = _brief(row)
        with ctx.db.session() as s:
            pts = s.execute(
                select(BacktestEquity.ts, BacktestEquity.equity)
                .where(BacktestEquity.run_id == rid)
                .order_by(BacktestEquity.ts)
            ).all()
        capital = brief["capital"] or (pts[0][1] if pts else 1.0)
        series.append(
            {
                "run_id": rid,
                "label": f"{brief['strategy_name']} v{brief['version']} (#{rid})",
                "points": [{"ts": t, "value": round(100.0 * v / capital, 3)} for t, v in pts],
            }
        )
        metrics = json.loads(row.metrics or "{}")
        table.append(
            {
                "run_id": rid,
                "label": series[-1]["label"],
                "market": brief["market"],
                **{
                    k: metrics.get(k)
                    for k in (
                        "total_return",
                        "cagr",
                        "max_drawdown",
                        "sharpe",
                        "sortino",
                        "win_rate",
                        "trades",
                        "profit_factor",
                        "charges_total",
                    )
                },
            }
        )
    return {"series": series, "metrics": table}
