"""The casebook (D-128): why each losing trade lost, from as few as three trades."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.kairos.casebook import casebook, causes_of


def _row(
    net: float, exit_reason: str = "signal", bars: int = 5, mfe: float | None = 0.2, **f: float
) -> Any:
    t = SimpleNamespace(net=net, exit_reason=exit_reason, bars_held=bars)
    return SimpleNamespace(t=t, features=dict(f), mfe_atr=mfe, mae_atr=None)


def test_one_trade_gets_its_textbook_causes() -> None:
    r = _row(-100, "stop", 1, long_trend=-3.0, rvol=0.5, market=-1.0)
    assert causes_of(r) == ["market", "long_trend", "rvol", "noise_stop"]


def test_shared_causes_are_named_only_when_winners_lacked_them() -> None:
    rows = [
        _row(-100, long_trend=-2.0, rvol=0.5),
        _row(-80, long_trend=-1.0, rvol=0.6),
        _row(-50, long_trend=-4.0),
        _row(120, long_trend=3.0, rvol=0.5),
        _row(90, long_trend=2.0, rvol=0.6),
    ]
    book = casebook(rows)
    keys = [p["key"] for p in book["patterns"]]
    assert keys == ["long_trend"]  # thin volume was there for the winners too
    assert book["patterns"][0]["text"].startswith(
        "3 of 3 losing trades were taken against the 200-candle trend; 0 of 2 winners."
    )
    assert len(book["cases"]) == 3


def test_gains_given_back_point_at_partial_exits() -> None:
    rows = [_row(-50, mfe=1.5), _row(-40, mfe=2.0), _row(60, mfe=3.0)]
    (p,) = casebook(rows)["patterns"]
    assert p["key"] == "gave_back" and "partial exits" in p["fix"]
