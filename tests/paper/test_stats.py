"""D-209: a paper strategy's whole record in numbers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.paper.stats import summarize


@dataclass
class T:
    net_pnl: float
    return_pct: float
    exit_ts: int
    charges: float = 10.0
    bars_held: int = 2
    exit_reason: str = "stop"
    side: str = "long"


def test_no_trades() -> None:
    assert summarize([]) == {"trades": 0}


def test_hand_counted_record() -> None:
    trades = [
        T(100, 1.0, 1, exit_reason="target"),
        T(-50, -0.5, 2),
        T(-30, -0.3, 3),
        T(200, 2.0, 4, exit_reason="trailing", side="short"),
        T(40, 0.4, 5, exit_reason="target"),
    ]
    s = summarize(list(reversed(trades)))  # order doesn't matter: sorted by exit time
    assert s["trades"] == 5 and s["wins"] == 3 and s["losses"] == 2
    assert s["win_rate"] == pytest.approx(60.0)
    assert s["net_pnl"] == pytest.approx(260.0)
    assert s["charges"] == pytest.approx(50.0)
    assert s["avg_win"] == pytest.approx(340 / 3) and s["avg_loss"] == pytest.approx(-40.0)
    assert s["profit_factor"] == pytest.approx(340 / 80)
    assert s["biggest_win"] == 200 and s["biggest_win_pct"] == 2.0
    assert s["biggest_loss"] == -50 and s["biggest_loss_pct"] == -0.5
    assert s["median_return_pct"] == pytest.approx(0.4)
    # sorted returns -0.5 -0.3 0.4 1.0 2.0: 90th percentile at index 3.6 → 1.0 + 0.6 × 1.0
    assert s["top10_return_pct"] == pytest.approx(1.6)
    assert s["bottom10_return_pct"] == pytest.approx(-0.5 + 0.4 * 0.2)
    assert s["best_streak"] == 2 and s["worst_streak"] == 2
    assert s["longs"] == 4 and s["shorts"] == 1
    assert s["exits"] == {"target": 2, "stop": 2, "trailing": 1}
    assert (s["first_ts"], s["last_ts"]) == (1, 5)


def test_all_losers_have_no_profit_factor_or_biggest_win() -> None:
    s = summarize([T(-10, -0.1, 1), T(-20, -0.2, 2)])
    assert s["win_rate"] == 0 and s["biggest_win"] is None and s["profit_factor"] == 0.0
