"""Partial exits in strategy definitions (D-125): checked, compiled and converted to code
exactly like the rest of the exits; the code version trades identically."""

from __future__ import annotations

from backend.core.types import Market, Timeframe
from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.engine.core import Engine, EngineConfig, SymbolState
from backend.strategy.codegen import to_code
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import CodeDefinition, ScaleOutSpec, ScaleStepSpec, StopSpec
from backend.strategy.diff import changes_json
from backend.strategy.templates import template_definition
from backend.strategy.validator import validate
from tests.golden.test_engine import inst
from tests.strategy.test_compiler import SRC


def _with_partials(stop: bool = True, pct: float = 50.0):  # type: ignore[no-untyped-def]
    d = template_definition("ma_crossover", "IN", ["RELIANCE"])
    scale = ScaleOutSpec(steps=[ScaleStepSpec(kind="r", value=1, sell_pct=pct)])
    update = {"scale_out": scale, "stop_loss": StopSpec(kind="percent", value=4) if stop else None}
    return d.model_copy(update={"exit": d.exit.model_copy(update=update)})


def test_partials_need_a_stop_when_measured_in_r() -> None:
    assert validate(_with_partials()).ok
    bad = validate(_with_partials(stop=False))
    assert not bad.ok and any("no stop-loss" in i.message for i in bad.issues)
    assert not validate(_with_partials(pct=100)).ok


def _trades(defn):  # type: ignore[no-untyped-def]
    raw = SRC._all("RELIANCE", Timeframe.D1)
    cfg = EngineConfig(
        market=Market.IN, product="delivery", timeframe=Timeframe.D1, capital=1e6, slippage_bps=5
    )
    costs = CostModel("IN", "delivery", {}, ChargeTable([]))
    engine = Engine(cfg, compile_definition(defn), costs, [SymbolState(inst("RELIANCE"), raw)])
    for i, b in enumerate(engine.symbols[0].raw):
        engine.step(b.ts, [(engine.symbols[0], i)])
    engine.finish()
    return engine.trades


def test_the_code_version_takes_the_same_partials() -> None:
    visual = _with_partials()
    code = CodeDefinition(
        market=visual.market,
        universe=visual.universe,
        timeframe=visual.timeframe,
        product=visual.product,
        sizing=visual.sizing,
        limits=visual.limits,
        parameters=visual.parameters,
        code=to_code(visual, "With partials"),
    )
    a, b = _trades(visual), _trades(code)
    assert a == b
    assert any(t.partials for t in a), "no trade reached its first target on the fixture"


def test_revisions_describe_partials_in_words() -> None:
    before = template_definition("ma_crossover", "IN", ["RELIANCE"]).model_dump(mode="json")
    lines = changes_json(before, _with_partials().model_dump(mode="json"))
    want = "Partial exits: none → sell 50% at 1R; stop to entry after the first."
    assert want in lines
