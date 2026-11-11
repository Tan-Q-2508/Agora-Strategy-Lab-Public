"""The regime map (D-143): hand-built markets get the obvious labels, and no look-ahead."""

from __future__ import annotations

import numpy as np

from backend.analysis import regime_map as rm
from backend.indicators.series import from_arrays


def _series(close: np.ndarray, spread: np.ndarray | float = 0.01):
    return from_arrays(close, high=close * (1 + spread), low=close * (1 - spread))


def test_steady_markets_get_the_obvious_trend() -> None:
    n = 400
    up = 100 * 1.002 ** np.arange(n)
    down = 100 * 0.998 ** np.arange(n)
    flat = 100 + np.sin(np.arange(n) / 3.0)
    for close, want in ((up, "up"), (down, "down"), (flat, "sideways")):
        s = _series(close, 0.005)
        assert rm.trend_axis(s.close, s.high, s.low)[-1] == want
    assert rm.trend_axis(up)[150] is None  # no 200-candle average yet


def test_volatility_is_relative_to_the_stocks_own_past() -> None:
    n = 400
    close = 100 * 1.003 ** np.arange(n)  # a clear trend: it survives the wider swings
    spread = np.full(n, 0.005)
    spread[-20:] = 0.03  # the last month swings six times wider
    s = _series(close, spread)
    v = rm.vol_axis(s.high, s.low, s.close)
    assert v[300] == "calm" and v[-1] == "volatile"
    assert rm.regimes(s)[-1] == "up-volatile" and rm.regimes(s)[300] == "up-calm"


def test_no_look_ahead() -> None:
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, 600)))
    s = _series(close, 0.01 + rng.uniform(0, 0.01, 600))
    full = rm.regimes(s)
    for k in (260, 333, 480, 599):
        assert rm.regimes(s.upto(k + 1))[k] == full[k]
    assert rm.at(s, int(s.ts[400])) == full[400]
    assert rm.at(s, int(s.ts[0]) - 1) is None
    assert set(x for x in full if x) <= set(rm.REGIMES)
