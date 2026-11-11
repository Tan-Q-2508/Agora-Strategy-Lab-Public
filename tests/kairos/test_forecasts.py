"""Live forecast scoring (KAIROS §5, D-58): shown forecasts are kept and checked later."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from backend.context import AppContext
from backend.core.types import Bar, Market, Timeframe
from backend.db.models import KairosForecast
from backend.kairos import forecasts, resolve
from tests.kairos.test_brain import load

DAY = 86_400_000


def bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(ts=k * DAY, open=c, high=c, low=c, close=c, volume=1.0, source="fake")
        for k, c in enumerate(closes)
    ]


def fc(
    origin: float, p10: float, p50: float, p90: float, up: float = 0.6, horizon: int = 3
) -> dict:
    return {
        "horizon": horizon,
        "origin": origin,
        "up_probability": up,
        "path": [{"p10": p10, "median": p50, "p90": p90}],
    }


def test_forecasts_are_scored_by_hand(ctx: AppContext) -> None:
    inst = resolve.stock(ctx, "RELIANCE", Market.IN)
    tf = Timeframe.D1
    forecasts.record(
        ctx, inst, tf, 1 * DAY, fc(100, 90, 105, 115)
    )  # said up; went to 108: hit, inside
    forecasts.record(
        ctx, inst, tf, 2 * DAY, fc(100, 96, 98, 101)
    )  # said down; went to 108: miss, outside
    forecasts.record(
        ctx, inst, tf, 2 * DAY, fc(100, 96, 98, 101)
    )  # the same forecast again: kept once
    forecasts.record(ctx, inst, tf, 6 * DAY, fc(100, 90, 100, 110))  # horizon not passed yet
    history = bars([100, 100, 100, 101, 108, 108, 100, 100])
    assert forecasts.score(ctx, inst, tf, history) == 2
    rec = forecasts.live_record(ctx, tf, inst=inst)
    assert rec == {"n": 2, "direction_hits": 1, "inside80": 1, "pending": 1}
    assert forecasts.live_record(ctx, tf, market=Market.IN)["n"] == 2
    assert forecasts.live_record(ctx, tf, market=Market.US)["n"] == 0


def test_shown_forecasts_are_kept(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["TCS"])
    inst = resolve.stock(ctx, "TCS", Market.IN)
    out = ctx.analysis.forecast(inst, Timeframe.D1)
    assert out["live"] == {"n": 0, "direction_hits": 0, "inside80": 0, "pending": 1}
    with ctx.db.session() as s:
        [row] = s.scalars(select(KairosForecast)).all()
    assert row.instrument_id == inst.id and row.horizon == out["horizon"]
    assert row.p10 <= row.p50 <= row.p90 and row.origin == out["origin"]


def test_predicted_candles_are_compared_with_what_formed() -> None:
    detail = {
        "candles": [
            {"open": 100, "high": 102, "low": 99, "close": 101, "direction": 1},
            {"open": 101, "high": 103, "low": 100, "close": 102, "direction": 1},
            {"open": 102, "high": 103, "low": 101, "close": 102, "direction": 0},
        ],
        "path": [{"p10": 98, "p90": 104}, {"p10": 97, "p90": 105}, {"p10": 96, "p90": 106}],
    }
    actual = [
        Bar(ts=1, open=100, high=101, low=98, close=99, volume=1, source="x"),  # down: wrong
        Bar(ts=2, open=99, high=104, low=99, close=103, volume=1, source="x"),  # up: right
    ]
    c = forecasts.compare(detail, 100.0, actual)
    assert c["formed"] == 2 and c["horizon"] == 3
    assert (c["direction_hits"], c["direction_scored"], c["inside80"]) == (1, 2, 2)
    assert c["predicted_change_pct"] == 2.0 and c["actual_change_pct"] == 3.0
    assert c["end_error_pct"] == pytest.approx(0.98)
    assert c["text"].startswith("2 of 3 predicted candles have formed")


def test_forecasts_remember_and_show_the_last_prediction(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["TCS"])
    inst = resolve.stock(ctx, "TCS", Market.IN)
    first = ctx.analysis.forecast(inst, Timeframe.D1)
    assert len(first["candles"]) == first["horizon"] == 10
    assert first["previous"]["kind"] == "re-created" and first["previous"]["formed"] == 10
    assert first["calibration"]["text"]
    # pretend the same prediction had been shown twelve candles ago: it has now formed
    bars = ctx.cache.bars(inst, Timeframe.D1, 0, ctx.clock.now_ms() + 1, adjusted_prices=True)
    old = {
        **first,
        "raw": {"median": 0.0, "half": 0.05},
        "models_q": {"volatility": [-0.05, -0.02, 0, 0.02, 0.05]},
    }
    forecasts.record(ctx, inst, Timeframe.D1, bars[-13].ts, old)
    ctx.analysis.clear_cache()
    later = ctx.analysis.forecast(inst, Timeframe.D1)
    assert later["calibration"]["checked"] == 1
    prev = later["previous"]
    assert prev["kind"] == "live" and prev["made_at"] == bars[-13].ts and prev["formed"] == 10
    assert prev["candles"][0]["predicted"] and "inside80" in prev["candles"][0]
    with ctx.db.session() as s:
        row = s.scalars(select(KairosForecast).where(KairosForecast.made_at == bars[-13].ts)).one()
    review = json.loads(row.review or "{}")
    assert review["formed"] == 10 and "miss" in review and review["model_loss"]["volatility"] >= 0
    mem = forecasts.memory(ctx, inst, Timeframe.D1)
    assert len(mem.misses) == 1 and set(mem.model_losses) == {"volatility"}
