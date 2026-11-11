"""Ideas that can't work are caught before a backtest, with the real range (D-142)."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.indicators.series import from_arrays
from backend.metis import brief, precheck, trial
from backend.strategy.definition import (
    AllOf,
    Compare,
    IndicatorOperand,
    NumberOperand,
    PriceOperand,
)
from tests.metis.test_metis import _strategy


def _series() -> list:
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    s = from_arrays(close, high=close * 1.01, low=close * 0.99)
    return [(s, int(s.ts[0]), int(s.ts[-1]) + 1)]


def _rsi(op: str, value: float) -> Compare:
    return Compare(
        left=IndicatorOperand(name="rsi", params={"period": 14}),
        op=op,
        right=NumberOperand(value=value),
    )


def test_never_always_and_fine() -> None:
    s = _series()
    never = precheck.reach(_rsi("above", 101), s, {})
    assert never is not None and never.never
    msg = never.problem()
    assert msg and "never true" in msg and "mostly between" in msg
    always = precheck.reach(_rsi("at_least", 0), s, {})
    assert always is not None and always.always and "changes nothing" in (always.problem() or "")
    fine = precheck.reach(_rsi("below", 40), s, {})
    assert fine is not None and fine.problem() is None
    # an oscillator against the price: different scales, never true
    flag = Compare(
        left=IndicatorOperand(name="rsi", params={"period": 14}),
        op="above",
        right=PriceOperand(field="close"),
    )
    r = precheck.reach(flag, s, {})
    assert r is not None and r.never


def test_a_cross_is_rare_by_nature_not_never() -> None:
    s = _series()
    cross = Compare(
        left=IndicatorOperand(name="sma", params={"period": 10}),
        op="crosses_above",
        right=IndicatorOperand(name="sma", params={"period": 50}),
    )
    r = precheck.reach(cross, s, {})
    assert r is not None and 0 < max(r.shares) < 0.05 and r.problem() is None
    impossible = precheck.reach(_rsi("crosses_above", 101), s, {})
    assert impossible is not None and impossible.never


def test_leaves_only_counts_must_hold_conditions() -> None:
    a, b = _rsi("below", 30), _rsi("above", 70)
    assert list(precheck.leaves(AllOf(conditions=[a, AllOf(conditions=[b])]))) == [a, b]
    assert list(precheck.leaves(None)) == []


def test_a_filter_that_is_never_true_is_not_backtested(client: TestClient, ctx: AppContext) -> None:
    sid, _vid = _strategy(client)
    b = brief.build(ctx, "", ["IN"]).baselines[sid]
    idea = {
        "kind": "filter",
        "strategy_id": sid,
        "title": "Only very strong trends",
        "why": "",
        "conditions": [
            {
                "indicator": "adx",
                "params": {"period": 14},
                "output": None,
                "op": "at_least",
                "value": 99.0,
            }
        ],
        "side": "long",
        "changes": {},
    }
    calls = []
    real = trial.judge_against
    trial.judge_against = lambda *a, **k: calls.append(1) or real(*a, **k)  # type: ignore
    try:
        out = trial.try_change(ctx, idea, b, "fp-adx-99")
    finally:
        trial.judge_against = real  # type: ignore
    assert out.status == "untestable" and "never true" in out.verdict
    assert "mostly between" in out.verdict and calls == []
