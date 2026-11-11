"""Strategies: library, versions, preview and "open as code" (API_CONTRACT → Strategies)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.api.strategy_defs import known_symbol_checker
from backend.backtest.manager import latest_run_for
from backend.context import AppContext, get_ctx
from backend.core.types import Market, Timeframe
from backend.data import store
from backend.data.adjust import adjusted
from backend.db.models import BacktestEquity, Strategy, StrategyVersion
from backend.errors import AgoraError
from backend.indicators.series import from_bars
from backend.strategy import diff, lineage, ranking, templates
from backend.strategy import service as svc
from backend.strategy.codegen import to_code
from backend.strategy.compiler import CompileError, compile_definition
from backend.strategy.definition import AnyDefinition, CodeDefinition, VisualDefinition
from backend.strategy.sandbox import SandboxError
from backend.strategy.signals import trace
from backend.strategy.validator import Result, validate

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _invalid(result: Result) -> AgoraError:
    first = result.errors[0] if result.errors else None
    detail = "; ".join(i.sentence() for i in result.errors)
    return AgoraError(
        "INVALID_STRATEGY",
        f"The strategy has {len(result.errors)} problem"
        f"{'s' if len(result.errors) != 1 else ''} to fix.",
        first.sentence() if first else "Check the highlighted blocks.",
        detail=detail,
        status=422,
    )


def _checked(ctx: AppContext, raw: dict[str, Any]) -> AnyDefinition:
    market = raw.get("market")
    known = known_symbol_checker(ctx, market) if market in ("IN", "US") else None
    result = validate(raw, known_symbol=known)
    if not result.ok or result.definition is None:
        raise _invalid(result)
    return result.definition


def _get(ctx: AppContext, strategy_id: int) -> Strategy:
    with ctx.db.session() as s:
        row = s.get(Strategy, strategy_id)
    if row is None:
        raise AgoraError(
            "STRATEGY_NOT_FOUND",
            "That strategy doesn't exist.",
            "Pick one from your strategies.",
            status=404,
        )
    return row


def _sparkline(ctx: AppContext, strategy_id: int) -> dict[str, Any] | None:
    with ctx.db.session() as s:
        run = latest_run_for(s, strategy_id)
        if run is None:
            return None
        pts = s.execute(
            select(BacktestEquity.ts, BacktestEquity.equity)
            .where(BacktestEquity.run_id == run.id)
            .order_by(BacktestEquity.ts)
        ).all()
        metrics = json.loads(run.metrics or "{}")
    step = max(1, len(pts) // 40)
    return {
        "run_id": run.id,
        "total_return": metrics.get("total_return"),
        "max_drawdown": metrics.get("max_drawdown"),
        "trades": metrics.get("trades"),
        "created_at": run.created_at,
        "points": [round(float(p[1]), 2) for p in pts[::step]],
    }


@router.get("/strategies")
def list_strategies(ctx: Ctx, archived: bool = False) -> dict[str, Any]:
    with ctx.db.session() as s:
        stmt = select(Strategy).order_by(Strategy.updated_at.desc())
        stmt = stmt.where(
            Strategy.archived_at.is_not(None) if archived else Strategy.archived_at.is_(None)
        )
        rows = s.scalars(stmt).all()
        out = []
        for r in rows:
            # the columns, not the whole definition: reading every Kairos desk's weights took 3 s
            latest = s.execute(
                select(
                    StrategyVersion.version,
                    StrategyVersion.id,
                    func.json_extract(StrategyVersion.definition, "$.timeframe"),
                    StrategyVersion.created_by,
                    StrategyVersion.created_at,
                )
                .where(StrategyVersion.strategy_id == r.id)
                .order_by(StrategyVersion.version.desc())
                .limit(1)
            ).first()
            out.append(
                {
                    **svc.strategy_json(r),
                    "version": latest[0] if latest else None,
                    "version_id": latest[1] if latest else None,
                    "timeframe": latest[2] if latest else None,
                    "version_author": latest[3] if latest else None,
                    "version_at": latest[4] if latest else None,
                }
            )
    for item in out:
        item["last_backtest"] = _sparkline(ctx, item["id"])
    return {"strategies": out}


class CreateStrategy(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=2000)
    market: Literal["IN", "US"] | None = None
    template_key: str | None = None
    definition: dict[str, Any] | None = None
    created_by: Literal["user", "ai_draft"] = "user"


@router.post("/strategies", status_code=201)
def create_strategy(ctx: Ctx, body: CreateStrategy) -> dict[str, Any]:
    definition: AnyDefinition
    if body.template_key and body.template_key in ranking.RANKING_TEMPLATES:
        if body.market is None:
            raise AgoraError(
                "TEMPLATE_NOT_FOUND",
                "Pick a market for the starter strategy.",
                "Choose India or the US.",
            )
        definition = ranking.ranking_definition(body.template_key, body.market)
        description = body.description or ranking.RANKING_TEMPLATES[body.template_key].description
    elif body.template_key:
        if body.template_key not in templates.TEMPLATES or body.market is None:
            raise AgoraError(
                "TEMPLATE_NOT_FOUND",
                "That starter strategy doesn't exist.",
                "Pick one from the list.",
                status=404,
            )
        definition = templates.template_definition(body.template_key, body.market)
        description = body.description or templates.TEMPLATES[body.template_key].description
    elif body.definition is not None:
        definition = _checked(ctx, body.definition)
        description = body.description
    else:
        raise AgoraError(
            "NO_DEFINITION",
            "A new strategy needs rules or a template.",
            "Start from a template or build the rules first.",
        )
    with ctx.db.session() as s:
        row, version = svc.create(
            s,
            name=body.name,
            description=description,
            definition=definition,
            now=ctx.clock.now_ms(),
            template_key=body.template_key,
            created_by=body.created_by,
        )
        return {"strategy": svc.strategy_json(row), "version": version.public()}


@router.get("/strategies/{strategy_id}")
def get_strategy(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    row = _get(ctx, strategy_id)
    with ctx.db.session() as s:
        latest = svc.latest_version(s, strategy_id)
        count = len(svc.versions(s, strategy_id))
    return {
        "strategy": svc.strategy_json(row),
        "version": latest.public() if latest else None,
        "versions": count,
        "last_backtest": _sparkline(ctx, strategy_id),
    }


class PatchStrategy(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    archived: bool | None = None


@router.patch("/strategies/{strategy_id}")
def patch_strategy(ctx: Ctx, strategy_id: int, body: PatchStrategy) -> dict[str, Any]:
    _get(ctx, strategy_id)
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.get(Strategy, strategy_id)
        assert row is not None
        if body.name is not None:
            row.name = body.name.strip()
        if body.description is not None:
            row.description = body.description.strip()
        if body.archived is not None:
            row.archived_at = now if body.archived else None
        row.updated_at = now
        return {"strategy": svc.strategy_json(row)}


@router.delete("/strategies/{strategy_id}")
def archive_strategy(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    return patch_strategy(ctx, strategy_id, PatchStrategy(archived=True))


@router.post("/strategies/{strategy_id}/duplicate", status_code=201)
def duplicate_strategy(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    row = _get(ctx, strategy_id)
    with ctx.db.session() as s:
        latest = svc.latest_version(s, strategy_id)
        assert latest is not None
        new, version = svc.create(
            s,
            name=f"{row.name} (copy)",
            description=row.description,
            definition=latest.definition,
            now=ctx.clock.now_ms(),
        )
        return {"strategy": svc.strategy_json(new), "version": version.public()}


@router.get("/strategies/{strategy_id}/versions")
def list_versions(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    _get(ctx, strategy_id)
    with ctx.db.session() as s:
        return {"versions": [v.public() for v in svc.versions(s, strategy_id)]}


class SaveVersion(BaseModel):
    definition: dict[str, Any]
    note: str = Field("", max_length=500)
    created_by: Literal["user", "ai_draft"] = "user"


@router.post("/strategies/{strategy_id}/versions", status_code=201)
def save_version(ctx: Ctx, strategy_id: int, body: SaveVersion) -> dict[str, Any]:
    _get(ctx, strategy_id)
    definition = _checked(ctx, body.definition)
    with ctx.db.session() as s:
        row = s.get(Strategy, strategy_id)
        assert row is not None
        version = svc.add_version(
            s, row, definition, ctx.clock.now_ms(), note=body.note, created_by=body.created_by
        )
        return {"strategy": svc.strategy_json(row), "version": version.public()}


@router.get("/strategies/{strategy_id}/diff")
def version_diff(
    ctx: Ctx, strategy_id: int, to: int, from_: Annotated[int | None, Query(alias="from")] = None
) -> dict[str, Any]:
    """What changed between two versions (``from`` defaults to the one ``to`` came from)."""
    _get(ctx, strategy_id)
    with ctx.db.session() as s:
        new = svc.get_version(s, to)
        if new is None or new.strategy_id != strategy_id:
            raise AgoraError("VERSION_NOT_FOUND", "That version doesn't exist.", "", status=404)
        ref = from_ if from_ is not None else new.parent_version_id
        old = svc.get_version(s, ref) if ref is not None else None
        if old is not None and old.strategy_id != strategy_id:
            raise AgoraError("VERSION_NOT_FOUND", "That version doesn't exist.", "", status=404)
        return {
            "from": old.public() if old else None,
            "to": new.public(),
            "changes": diff.changes(old.definition if old else None, new.definition),
        }


@router.post("/strategies/{strategy_id}/versions/{version_id}/restore", status_code=201)
def restore_version(ctx: Ctx, strategy_id: int, version_id: int) -> dict[str, Any]:
    """Bring an old version back as the newest one; nothing is ever overwritten (D-79)."""
    _get(ctx, strategy_id)
    with ctx.db.session() as s:
        row = s.get(Strategy, strategy_id)
        assert row is not None
        try:
            version = svc.restore(s, row, version_id, ctx.clock.now_ms())
        except ValueError as exc:
            raise AgoraError(
                "VERSION_NOT_FOUND", str(exc), "Pick a version from the history.", status=404
            ) from exc
        return {"strategy": svc.strategy_json(row), "version": version.public()}


@router.get("/strategies/{strategy_id}/family")
def strategy_family(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    """Other strategies with the same logic (copies saved before revision control)."""
    _get(ctx, strategy_id)
    with ctx.db.session() as s:
        return {
            "same_logic": [
                {
                    "strategy_id": f.strategy_id,
                    "name": f.name,
                    "similarity": f.similarity,
                    "why": f.why,
                }
                for f in lineage.families(s, strategy_id)
            ]
        }


@router.post("/strategies/{strategy_id}/to-code", status_code=201)
def open_as_code(ctx: Ctx, strategy_id: int) -> dict[str, Any]:
    row = _get(ctx, strategy_id)
    with ctx.db.session() as s:
        latest = svc.latest_version(s, strategy_id)
        assert latest is not None
        d = latest.definition
        if not isinstance(d, VisualDefinition):
            raise AgoraError(
                "ALREADY_CODE", "This strategy is already code.", "Open it in the code editor."
            )
        code = CodeDefinition(
            market=d.market,
            universe=d.universe,
            timeframe=d.timeframe,
            product=d.product,
            sizing=d.sizing,
            limits=d.limits,
            parameters=d.parameters,
            code=to_code(d, row.name),
        )
        new, version = svc.create(
            s,
            name=f"{row.name} (code)",
            description=row.description,
            definition=code,
            now=ctx.clock.now_ms(),
            note=f"Converted from visual strategy “{row.name}”",
        )
        return {"strategy": svc.strategy_json(new), "version": version.public()}


class PreviewBody(BaseModel):
    definition: dict[str, Any]
    instrument_id: int
    days: int = Field(180, ge=5, le=3650)


@router.post("/strategies/preview")
def preview(ctx: Ctx, body: PreviewBody) -> dict[str, Any]:
    """Where the rules would have fired on one stock recently (the builder's preview)."""
    result = validate(body.definition)
    if not result.ok or result.definition is None:
        return {
            "ok": False,
            "issues": [i.public() for i in result.issues],
            "bars": [],
            "signals": [],
        }
    d = result.definition
    with ctx.db.session() as s:
        inst = store.get_instrument(s, body.instrument_id)
    if inst is None:
        raise AgoraError(
            "INSTRUMENT_NOT_FOUND",
            "Agora doesn't know that stock.",
            "Pick a stock from the list.",
            status=404,
        )
    if inst.market.value != d.market:
        raise AgoraError(
            "WRONG_MARKET",
            "That stock is in a different market from the strategy.",
            "Pick a stock from the strategy's market.",
        )
    tf = Timeframe(d.timeframe)
    try:
        program = compile_definition(d)
    except (CompileError, SandboxError, ValueError) as exc:
        msg = exc.sentence() if isinstance(exc, SandboxError) else str(exc)
        raise AgoraError("STRATEGY_ERROR", "The strategy couldn't run.", msg, status=422) from exc
    now = ctx.clock.now_ms()
    show_from = now - body.days * 86_400_000
    from backend.backtest.run import warmup_ms

    load_from = show_from - warmup_ms(tf, program.warmup)
    ctx.cache.ensure(inst, tf, load_from, now + 1)
    bars = [adjusted(b) for b in ctx.cache.bars(inst, tf, load_from, now + 1)]
    if not bars:
        return {
            "ok": True,
            "issues": [i.public() for i in result.issues],
            "bars": [],
            "signals": [],
            "note": "No saved prices for this stock yet.",
        }
    series = from_bars(bars, tf, Market(d.market))
    try:
        signals = trace(program, series, Market(d.market), inst.symbol)
    except SandboxError as exc:
        raise AgoraError(
            "STRATEGY_ERROR", "Your strategy code stopped.", exc.sentence(), status=422
        ) from exc
    shown = [b for b in bars if b.ts >= show_from] or bars[-120:]
    first_ts = shown[0].ts
    return {
        "ok": True,
        "issues": [i.public() for i in result.issues],
        "bars": [
            {
                "ts": b.ts,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in shown
        ],
        "signals": [
            {"ts": x.ts, "action": x.action, "reason": x.reason, "price": x.price}
            for x in signals
            if x.ts >= first_ts
        ],
        "timeframe": tf.value,
    }
