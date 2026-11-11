"""Options arithmetic (KAIROS §19, D-74): golden values from the textbook case S = K = 100,
one year, r = 5%, σ = 20% (Hull's tables), parity, implied volatility and strategy payoffs
worked out by hand."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from backend.analysis import options as opt
from tests.kairos.test_agent import chat, load, steps


def test_black_scholes_textbook_values() -> None:
    c = opt.bsm("call", 100, 100, 1.0, 0.05, 0.2)
    p = opt.bsm("put", 100, 100, 1.0, 0.05, 0.2)
    assert c.price == pytest.approx(10.4506, abs=1e-4)
    assert p.price == pytest.approx(5.5735, abs=1e-4)
    assert c.delta == pytest.approx(0.6368, abs=1e-4) and p.delta == pytest.approx(
        -0.3632, abs=1e-4
    )
    assert c.gamma == pytest.approx(0.018762, abs=1e-6) == p.gamma
    assert c.vega == pytest.approx(0.37524, abs=1e-5)  # per volatility point
    assert c.theta * 365 == pytest.approx(-6.4140, abs=1e-3)  # per year
    # put-call parity: C − P = S − K·e^(−rT)
    assert c.price - p.price == pytest.approx(100 - 100 * math.exp(-0.05), abs=1e-9)


def test_dividends_lower_calls_and_raise_puts() -> None:
    plain, paying = (
        opt.bsm("call", 100, 100, 1, 0.05, 0.2),
        opt.bsm("call", 100, 100, 1, 0.05, 0.2, 0.03),
    )
    assert paying.price < plain.price
    assert (
        opt.bsm("put", 100, 100, 1, 0.05, 0.2, 0.03).price
        > opt.bsm("put", 100, 100, 1, 0.05, 0.2).price
    )


def test_american_put_is_worth_more_than_european() -> None:
    am = opt.american("put", 100, 100, 1.0, 0.05, 0.2)
    assert am == pytest.approx(6.09, abs=0.01)  # the binomial-tree value (≈ 6.0824 at the limit)
    assert am > opt.bsm("put", 100, 100, 1.0, 0.05, 0.2).price
    # without dividends an American call is never exercised early: equal to European
    assert opt.american("call", 100, 100, 1.0, 0.05, 0.2) == pytest.approx(10.4506, abs=0.01)


def test_implied_volatility_recovers_the_input() -> None:
    for vol in (0.08, 0.2, 0.65):
        price = opt.bsm("put", 100, 90, 0.25, 0.05, vol).price
        assert opt.implied_vol(price, "put", 100, 90, 0.25, 0.05) == pytest.approx(vol, abs=1e-6)
    assert opt.implied_vol(0.0001, "call", 100, 100, 1.0, 0.05) is None  # below any volatility


def test_expected_move() -> None:
    # Nifty 25,000, IV 13%, 7 days: 25,000 × 0.13 × √(7/365) ≈ 450
    assert opt.expected_move(25_000, 0.13, 7) == pytest.approx(450.06, abs=0.1)


def test_bull_call_spread_by_hand() -> None:
    legs = [opt.Leg("call", 1, 100, premium=5.0), opt.Leg("call", -1, 110, premium=2.0)]
    a = opt.analyze(legs, 100, 30, 0.2)
    # debit 3; max profit 10 − 3 = 7 above 110; max loss 3 below 100; break-even 103
    assert a.net_premium == pytest.approx(3.0)
    assert a.max_profit == pytest.approx(7.0, abs=1e-6) and a.max_loss == pytest.approx(
        3.0, abs=1e-6
    )
    assert a.breakevens == [pytest.approx(103.0, abs=0.05)]


def test_iron_condor_by_hand() -> None:
    legs = [
        opt.Leg("put", 1, 80, premium=0.5),
        opt.Leg("put", -1, 90, premium=1.5),
        opt.Leg("call", -1, 110, premium=1.5),
        opt.Leg("call", 1, 120, premium=0.5),
    ]
    a = opt.analyze(legs, 100, 30, 0.2)
    # credit 2; max loss 10 − 2 = 8; break-evens 90 − 2 and 110 + 2
    assert a.net_premium == pytest.approx(-2.0)
    assert a.max_profit == pytest.approx(2.0, abs=1e-6) and a.max_loss == pytest.approx(
        8.0, abs=1e-6
    )
    assert a.breakevens == [pytest.approx(88.0, abs=0.05), pytest.approx(112.0, abs=0.05)]
    assert 0.5 < a.pop < 1.0 and a.greeks["theta"] > 0 and a.greeks["vega"] < 0


def test_unlimited_risk_and_reward_are_called_unlimited() -> None:
    straddle = opt.analyze(opt.STRATEGIES["short_straddle"].build(100, 2.5), 100, 30, 0.2)
    assert straddle.max_loss is None and straddle.max_profit is not None
    call = opt.analyze(opt.STRATEGIES["long_call"].build(100, 2.5), 100, 30, 0.2)
    assert call.max_profit is None and call.max_loss == pytest.approx(call.net_premium, abs=1e-6)
    put = opt.analyze(opt.STRATEGIES["long_put"].build(100, 2.5), 100, 30, 0.2)
    assert put.max_profit == pytest.approx(
        100 - put.net_premium, abs=0.01
    )  # the price can't go below 0


@pytest.mark.parametrize("key", list(opt.STRATEGIES))
def test_every_strategy_is_sound(key: str) -> None:
    info = opt.STRATEGIES[key]
    a = opt.analyze(info.build(100.0, 2.5), 100.0, 30, 0.25)
    assert a.legs and 0.0 <= a.pop <= 1.0
    assert len(a.grid) == len(a.at_expiry) == len(a.today)
    assert a.max_loss is None or a.max_loss >= 0
    assert opt.find_strategy(info.name) is info


def test_strategy_names_are_found_in_sentences() -> None:
    assert opt.find_strategy("can you set up an iron condor on nifty").key == "iron_condor"  # type: ignore[union-attr]
    assert opt.find_strategy("what about a put credit spread").key == "bull_put_spread"  # type: ignore[union-attr]
    assert opt.find_strategy("poor man's covered call").key == "diagonal_spread"  # type: ignore[union-attr]
    assert opt.find_strategy("buy some shares") is None


def test_kairos_works_out_a_strategy(client: TestClient) -> None:
    load(client, ["TCS"])
    ev = chat(client, "iron condor on TCS for 30 days")
    [step] = steps(ev)
    assert step["tool"] == "option_strategy"
    card = step["card"]
    assert card["type"] == "options" and len(card["legs"]) == 4 and len(card["breakevens"]) == 2
    assert card["max_loss"] > 0 and card["net"] < 0 and card["days"] == 30
    done = ev[-1]
    assert done["type"] == "done"
