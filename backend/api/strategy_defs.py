"""Indicator catalog, starter templates and definition validation (Phase 3 endpoints)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from backend.context import AppContext, get_ctx
from backend.core.types import Market
from backend.data import store
from backend.errors import AgoraError
from backend.indicators import catalog as indicator_catalog
from backend.strategy import ranking, templates
from backend.strategy.validator import validate

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("/indicators")
def indicators() -> dict[str, Any]:
    return {
        "indicators": indicator_catalog.catalog(),
        "price_fields": list(indicator_catalog.PRICE_FIELDS),
    }


@router.get("/templates")
def list_templates() -> dict[str, Any]:
    """The 28 rule-based starters, then the ranking ones (D-91)."""
    visual = [{**t, "kind": "visual"} for t in templates.catalog()]
    return {"templates": visual + [t.public() for t in ranking.RANKING_TEMPLATES.values()]}


@router.get("/templates/{key}")
def get_template(key: str, market: Market = Market.IN) -> dict[str, Any]:
    if key in ranking.RANKING_TEMPLATES:
        r = ranking.RANKING_TEMPLATES[key]
        d = ranking.ranking_definition(key, market.value)
        return {**r.public(), "definition": d.model_dump(mode="json")}
    if key not in templates.TEMPLATES:
        raise AgoraError(
            "TEMPLATE_NOT_FOUND",
            "That starter strategy doesn't exist.",
            "Pick one from the list.",
            status=404,
        )
    t = templates.TEMPLATES[key]
    return {
        **t.public(),
        "definition": templates.template_definition(key, market.value).model_dump(mode="json"),
    }


def known_symbol_checker(ctx: AppContext, market: str) -> Any:
    def known(symbol: str) -> bool:
        with ctx.db.session() as s:
            return store.find_instrument(s, Market(market), symbol) is not None

    return known


class ValidateBody(BaseModel):
    definition: dict[str, Any]


@router.post("/strategies/validate")
def validate_definition(ctx: Ctx, body: Annotated[ValidateBody, Body()]) -> dict[str, Any]:
    market = body.definition.get("market")
    known = known_symbol_checker(ctx, market) if market in ("IN", "US") else None
    result = validate(body.definition, known_symbol=known)
    return {
        "ok": result.ok,
        "issues": [i.public() for i in result.issues],
        "definition": result.definition.model_dump(mode="json") if result.definition else None,
    }


@router.get("/indicators/{key}/values")
def indicator_values(
    ctx: Ctx,
    key: str,
    instrument_id: int,
    timeframe: str = "1d",
    start: int | None = None,
    params: str = "{}",
) -> dict[str, Any]:
    """An overlay indicator over saved prices, for the Charts screen. Computed from enough
    earlier candles that the first value shown is already warmed up."""
    import json
    import math

    from backend.backtest.run import warmup_ms
    from backend.core.types import Timeframe
    from backend.data.adjust import adjusted
    from backend.indicators.series import from_bars

    if key not in indicator_catalog.INDICATORS:
        raise AgoraError(
            "UNKNOWN_INDICATOR",
            "Agora doesn't know that indicator.",
            "Pick one from the list.",
            status=404,
        )
    ind = indicator_catalog.get(key)
    try:
        p = indicator_catalog.resolve_params(ind, json.loads(params))
        tf = Timeframe(timeframe)
    except (ValueError, TypeError) as exc:
        raise AgoraError(
            "BAD_PARAMS", "Those indicator settings aren't valid.", str(exc), status=422
        ) from exc
    with ctx.db.session() as s:
        inst = store.get_instrument(s, instrument_id)
    if inst is None:
        raise AgoraError(
            "INSTRUMENT_NOT_FOUND",
            "Agora doesn't know that stock.",
            "Pick a stock from the list.",
            status=404,
        )
    now = ctx.clock.now_ms()
    show_from = start if start is not None else now - 730 * 86_400_000
    lo = show_from - warmup_ms(tf, int(ind.warmup(p)) + 5)
    bars = [adjusted(b) for b in ctx.cache.bars(inst, tf, lo, now + 1)]
    if not bars:
        return {"key": key, "label": ind.label, "params": p, "outputs": {}}
    series = from_bars(bars, tf, inst.market)
    out = indicator_catalog.compute(key, series, p)
    return {
        "key": key,
        "label": ind.label,
        "params": p,
        "outputs": {
            name: [
                {"ts": int(series.ts[i]), "value": round(float(v), 4)}
                for i, v in enumerate(arr)
                if series.ts[i] >= show_from and math.isfinite(float(v))
            ]
            for name, arr in out.items()
        },
    }
