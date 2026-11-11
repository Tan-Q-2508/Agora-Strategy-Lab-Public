"""A closer look before an entry (D-177): the desk consults a smaller chart.

The user asked (2026-11-05) for the daily desk to consult the hourly chart and the hourly and
15-minute desks the 5-minute chart. A trader who likes a daily setup still looks at how the day
ended before buying: a stock that closed the day well but fell through its last hours is losing
buyers. So when a live desk is about to enter, it reads the smaller chart's candles that closed
inside the desk's own candle and passes on the entry when that chart has turned against it: the
last close below (for a buy) its 20-candle exponential average while that average is falling.

Only for the stocks the desk is about to trade (a handful a candle), never all 250: Yahoo answers
about one request a second, and polling a 5-minute chart for every stock wouldn't fit. Live only,
like the judge and the forecast nudge (D-145, D-175), so backtests stay reproducible (D-04).
Without enough candles, or when they can't be fetched, the check never blocks a trade.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

SMALLER = {"1d": "1h", "1h": "5m", "15m": "5m"}
EMA = 20
SLOPE_BARS = 3  # the average "falling" = lower than it was this many candles ago
LOOKBACK_DAYS = {"1h": 10, "5m": 4}  # calendar days of smaller candles to read (weekends too)


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1.0)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def says_no(closes: Sequence[float], side: int) -> bool:
    """True when the smaller chart has turned against an entry on ``side`` (+1 buy, −1 short)."""
    c = np.asarray(closes, dtype=np.float64)
    if len(c) < EMA + SLOPE_BARS or not np.all(np.isfinite(c)):
        return False
    e = _ema(c, EMA)
    falling = e[-1] < e[-1 - SLOPE_BARS]
    if side > 0:
        return bool(c[-1] < e[-1] and falling)
    rising = e[-1] > e[-1 - SLOPE_BARS]
    return bool(c[-1] > e[-1] and rising)
