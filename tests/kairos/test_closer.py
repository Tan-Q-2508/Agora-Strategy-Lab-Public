"""The closer look at the smaller chart before an entry (D-177)."""

from __future__ import annotations

from backend.kairos import closer


def test_the_smaller_chart_says_no_when_it_turned_against_the_trade() -> None:
    up = [100 + k * 0.5 for k in range(40)]
    faded = up + [up[-1] - 1.5 * k for k in range(1, 8)]  # the last candles fell through
    assert not closer.says_no(up, +1)  # rising: a buy is fine
    assert closer.says_no(faded, +1)  # below a falling average: pass on the buy
    assert closer.says_no(up, -1)  # rising: pass on a short
    assert not closer.says_no(faded, -1)


def test_without_enough_candles_it_never_blocks() -> None:
    assert not closer.says_no([100.0, 99.0, 98.0], +1)
    assert not closer.says_no([], +1)
    assert not closer.says_no([100.0] * 30 + [float("nan")], +1)


def test_which_chart_each_desk_consults() -> None:
    """The user's request (2026-11-05): daily consults hourly, hourly and 15-minute the
    5-minute chart."""
    assert closer.SMALLER == {"1d": "1h", "1h": "5m", "15m": "5m"}
