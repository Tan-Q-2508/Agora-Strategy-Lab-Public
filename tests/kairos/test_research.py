"""Strategy research (KAIROS §7.3): character, honest tuning, out-of-sample and walk-forward."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.indicators.series import from_arrays
from backend.kairos import research, resolve
from backend.strategy.definition import ParameterDef
from tests.kairos.test_agent import chat, steps
from tests.kairos.test_brain import load


def series_with(phi: float, seed: int = 3, n: int = 1500) -> Any:
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    for k in range(1, n):
        r[k] = phi * r[k - 1] + rng.normal(0, 0.01)
    c = 100 * np.exp(np.cumsum(r))
    return from_arrays(c, open_=c, high=c * 1.005, low=c * 0.995, volume=np.full(n, 1e6))


def test_character_tells_trending_from_reverting() -> None:
    trend = research.character("UP", series_with(0.6))
    revert = research.character("CHOP", series_with(-0.6))
    assert trend.variance_ratio > 1.3 and trend.label == "trending"
    assert revert.variance_ratio < 0.7 and revert.label == "mean-reverting"
    assert 0 <= revert.efficiency < trend.efficiency <= 1


def test_grid_stays_inside_each_setting() -> None:
    p = ParameterDef(name="period", label="Period", type="int", default=14, min=10, max=50, step=4)
    assert research._values(p, 1) == [10.0, 14.0, 18.0]
    edge = ParameterDef(name="x", label="X", type="float", default=1.0, min=1.0, max=2.0, step=0.5)
    assert research._values(edge, 1) == [1.0, 1.5]


def test_tuning_prefers_a_steady_neighbourhood_over_a_lone_peak() -> None:
    p = ParameterDef(name="n", label="N", type="int", default=3, min=1, max=5, step=1)
    cand = research.Candidate("x", "X", None, [{"n": float(v)} for v in research._values(p, 2)])  # type: ignore[arg-type]
    # A steady plateau at 1–3 and a lone spike at 5 next to a loser. Neighbourhood means:
    # 1: (1.0 + 1.1)/2 = 1.05 · 2: 1.033 · 3: 0.367 · 4: 1.0 · 5: (3.0 − 1.0)/2 = 1.0
    surface = {1.0: 1.0, 2.0: 1.1, 3.0: 1.0, 4.0: -1.0, 5.0: 3.0}

    def fake(_d: Any, g: dict[str, float], _lo: int, _hi: int) -> dict[str, Any]:
        return {"sharpe": surface[g["n"]], "trades": 30}

    params, sharpe, trades, isolated = research.tune(cand, fake, 0, 1)  # type: ignore[arg-type]
    assert isolated  # the raw best (5) sits next to a loser
    assert params == {"n": 1.0} and sharpe == 1.0 and trades == 30
    few = {1.0: 3.0, 2.0: 3.0, 3.0: 3.0, 4.0: 3.0, 5.0: 3.0}

    def thin(_d: Any, g: dict[str, float], _lo: int, _hi: int) -> dict[str, Any]:
        return {"sharpe": few[g["n"]], "trades": 2}

    assert math.isinf(research.tune(cand, thin, 0, 1)[1])  # type: ignore[arg-type]


def test_research_on_the_practice_data(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["RELIANCE", "TCS", "INFY"])
    insts = [resolve.stock(ctx, s, Market.IN) for s in ("RELIANCE", "TCS", "INFY")]
    out = research.research(ctx, insts, Timeframe.D1, 5, cfg=research.QUICK)
    assert [c["symbol"] for c in out["character"]] == ["RELIANCE", "TCS", "INFY"]
    keys = [c["key"] for c in out["candidates"]]
    assert "kairos" in keys and len(keys) == research.QUICK.max_candidates
    assert out["runs"] >= len(keys) * 3
    assert out["period"]["start"] < out["period"]["split"] < out["period"]["end"]
    verdicts = {c["verdict"] for c in out["candidates"]}
    assert verdicts <= {
        "winner",
        "runner-up",
        "finalist",
        "too few trades to judge",
        "no edge even on the years it was tuned on",
        "too few trades in the unseen years",
        "lost money in the unseen years",
        "fell apart in the unseen years",
        "failed the walk-forward test",
    }
    assert out["cautions"]
    if out["winner"] is not None:
        w = out["winner"]
        winner = next(c for c in out["candidates"] if c["verdict"] == "winner")
        assert winner["out_of_sample_sharpe"] > 0 and winner["walk_forward_sharpe"] > 0
        detail = ctx.backtests  # the full backtest of the winner was queued
        assert w["run_id"] > 0 and detail is not None
    else:
        assert "Nothing held up" in out["cautions"][0]
    json.dumps(out, allow_nan=False)


def test_kairos_researches_from_the_chat(client: TestClient, ctx: AppContext) -> None:
    load(ctx, Market.IN, ["HDFCBANK", "ICICIBANK"])
    ctx.services["kairos_research_config"] = research.QUICK
    ev = chat(client, "Find the best strategy for HDFCBANK and ICICIBANK")
    [step] = steps(ev)
    assert step["tool"] == "research_strategy", [
        (e.get("tool"), e.get("status"), e.get("detail")) for e in ev if e["type"] == "step"
    ]
    assert step["card"]["title"] == "Strategy research" and step["card"]["items"]
    text = "".join(e["delta"] for e in ev if e["type"] == "text")
    assert "Tried" in text and "Caution" in text


@pytest.mark.parametrize("label", ["trending", "mean-reverting"])
def test_candidates_put_the_fitting_family_first(label: str) -> None:
    ch = research.Character("X", 0.5, 1.2 if label == "trending" else 0.8, 30, 2, label)
    cands = research.candidates(Market.IN, Timeframe.D1, ["TCS"], [ch], research.Config())
    assert cands[0].key == "kairos"
    first = research.TREND_KEYS if label == "trending" else research.REVERSION_KEYS
    assert cands[1].key in first
    assert all(c.definition.timeframe == "1d" for c in cands)
