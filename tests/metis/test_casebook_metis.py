"""Metis uses the casebook (D-128), rests strategies that give nothing, tops up stock lists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.metis import diagnose
from backend.strategy import templates


@dataclass
class _Base:
    definition: Any
    strategy_id: int = 5
    study: dict[str, Any] = field(
        default_factory=lambda: {"trades": 5, "win_rate": 0.6, "avg_win": 100.0, "avg_loss": 80.0}
    )


def test_the_first_look_fixes_what_the_losers_shared() -> None:
    d = templates.template_definition("ma_crossover", "IN", ["TCS", "INFY"])
    review = {
        "casebook": {
            "patterns": [
                {
                    "key": "long_trend",
                    "text": "3 of 3 losing trades were taken against the 200-candle trend.",
                    "fix": "trade only with the 200-candle average (a trend filter)",
                }
            ]
        }
    }
    found = {f.key: f for f in diagnose.first_look(_Base(d), review=review, characters={})}
    book = found["casebook"]
    assert "one by one" in book.text
    (seed,) = book.seeds
    assert seed["kind"] == "filter" and seed["conditions"][0]["params"] == {"period": 200.0}
