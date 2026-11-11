"""The "no invented numbers" check."""

from __future__ import annotations

from backend.ai.numbers import unverified

CONTEXT = {
    "results": {"total_return": 0.4237, "max_drawdown": 0.1812, "sharpe": 1.34, "trades": 31},
    "settings": {"starting_money": 1000000, "from": "2016-01-04"},
    "best": [{"net_profit": 23456.78}],
}


def test_numbers_from_the_data_pass_in_any_usual_form() -> None:
    reply = (
        "It returned 42.4% (worst drop 18.1%) with a Sharpe ratio of 1.34 over 31 trades, "
        "starting from ₹10,00,000 in 2016. The best trade made ₹23,457. Try 2–3 changes."
    )
    assert unverified(reply, CONTEXT) == []


def test_invented_numbers_are_flagged() -> None:
    reply = "It returned 55% and the win rate was 64%, Sharpe 1.34."
    assert unverified(reply, CONTEXT) == ["55", "64"]
