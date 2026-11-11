"""Reading several timeframes of one stock at once (SPEC §18.1, D-97).

Traders call it *multiple timeframe analysis* or *top-down analysis* (Alexander Elder's
"triple screen", 1985; John Murphy's "Technical Analysis of the Financial Markets"): the
bigger chart sets the direction, the chart you trade on finds the setup, a smaller one times
the entry. A buy signal on the daily chart while the weekly chart is falling is a "bounce in
a downtrend", and such signals fail more often; requiring the bigger chart to agree is the
classic way to fend off false alarms.

Two uses, both causal (only finished candles):

1. **Strategies and the Kairos brain** (``resample`` + ``Frame``): a bigger chart is built from
   the strategy's own candles (5-minute candles into hours or days; days into weeks or
   months), so backtests, paper trading and replays all see exactly the same thing. At each
   candle the bigger chart's value is the one of its **last finished candle**: the period
   before the one the current candle is in. Nothing from an unfinished week or hour leaks in.
2. **Kairos's chart reading** (``reading`` + ``confluence``): each timeframe's trend and
   momentum, from its own saved candles, and one verdict over all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.analysis.trend import MomentumArrays, TrendArrays, regime_of
from backend.core.clock import ms_to_dt
from backend.core.types import Timeframe
from backend.indicators.series import F64, I64, BarSeries

# Bigger charts a strategy on each timeframe may read.
BIGGER: dict[str, tuple[str, ...]] = {
    "1d": ("1w", "1mo"),
    "1h": ("1d", "1w"),
    "15m": ("1h", "1d"),
    "5m": ("15m", "1h", "1d"),
    "1m": ("5m", "15m", "1h"),
}
LABEL = {
    "1m": "1-minute",
    "5m": "5-minute",
    "15m": "15-minute",
    "1h": "hourly",
    "1d": "daily",
    "1w": "weekly",
    "1mo": "monthly",
}
MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
# Roughly how many smaller candles make one bigger candle (for warm-up lengths).
PER_SESSION = {"1m": 375, "5m": 75, "15m": 25, "1h": 7}


def candles_per(bigger: str, smaller: str) -> int:
    if smaller == "1d":
        return {"1w": 5, "1mo": 21}[bigger]
    if bigger in MINUTES:
        return MINUTES[bigger] // MINUTES[smaller]
    per_day = PER_SESSION[smaller]
    return per_day * {"1d": 1, "1w": 5, "1mo": 21}[bigger]


def allowed(base: str, bigger: str) -> bool:
    return bigger in BIGGER.get(base, ())


def _period_keys(series: BarSeries, bigger: str, zone: ZoneInfo) -> I64:
    """A number per candle that changes exactly when a new ``bigger`` period starts."""
    n = len(series)
    if bigger in MINUTES:  # intraday buckets anchored to the session open
        step = MINUTES[bigger] * 60_000
        within = (series.ts - series.session_open) // step
        out: I64 = series.session * 100_000 + within
        return out
    if bigger == "1d" and series.timeframe.is_intraday:
        return series.session.copy()
    # Weeks and months: by the local date of each session (one conversion per session).
    keys = np.zeros(n, dtype=np.int64)
    cache: dict[int, int] = {}
    for i in range(n):
        sid = int(series.session[i])
        k = cache.get(sid)
        if k is None:
            d = ms_to_dt(int(series.ts[i]), zone).date()
            k = d.toordinal() - d.weekday() if bigger == "1w" else d.year * 12 + d.month
            cache[sid] = k
        keys[i] = k
    return keys


def resample(series: BarSeries, bigger: str, zone: ZoneInfo) -> tuple[BarSeries, I64]:
    """(the bigger chart, for each candle the index of the bigger candle it belongs to)."""
    n = len(series)
    if n == 0:
        empty = series.upto(0)
        return empty, np.zeros(0, dtype=np.int64)
    keys = _period_keys(series, bigger, zone)
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:] - 1, n - 1]
    group = np.cumsum(np.r_[True, keys[1:] != keys[:-1]]).astype(np.int64) - 1
    intraday_out = bigger in MINUTES
    m = len(starts)
    out = BarSeries(
        ts=series.ts[starts].copy(),
        open=series.open[starts].copy(),
        high=np.maximum.reduceat(series.high, starts),
        low=np.minimum.reduceat(series.low, starts),
        close=series.close[ends].copy(),
        volume=np.add.reduceat(series.volume, starts),
        session=series.session[starts].copy() if intraday_out else np.arange(m, dtype=np.int64),
        session_open=series.session_open[starts].copy()
        if intraday_out
        else series.ts[starts].copy(),
        timeframe=Timeframe(bigger) if intraday_out else Timeframe.D1,
    )
    return out, group


def finished(values: F64, group: I64) -> F64:
    """Line each candle up with the bigger chart's **last finished** candle: the one before
    the bigger candle it is in. Earlier than the first finished candle: NaN."""
    prev = group - 1
    out = np.full(len(group), np.nan)
    ok = prev >= 0
    out[ok] = values[prev[ok]]
    return out


@dataclass
class Frame:
    """One bigger chart of a strategy's candles, with its values lined up to the candles."""

    series: BarSeries
    group: I64
    _mapped: dict[Any, F64] = field(default_factory=dict)

    @classmethod
    def build(cls, base: BarSeries, bigger: str, zone: ZoneInfo) -> Frame:
        s, g = resample(base, bigger, zone)
        return cls(s, g)

    def line(self, key: Any, values: F64) -> F64:
        hit = self._mapped.get(key)
        if hit is None:
            hit = self._mapped[key] = finished(values, self.group)
        return hit


# The bigger chart a Kairos desk checks before trading, by the desk's timeframe.
DESK_BIGGER = {"1d": "1w", "1h": "1d", "15m": "1h", "5m": "1h", "1m": "15m"}
TREND_LINE = 25.0  # a trend score this far against the trade means "the bigger chart says no"


def trend_line(series: BarSeries) -> F64:
    """The trend score (−100 … +100, ``trend.py``) on every candle of a chart, with a
    causal swing-structure read, so value ``i`` uses candles ``0..i`` only."""
    n = len(series)
    out = np.full(n, np.nan)
    if n < 30:
        return out
    ta = TrendArrays(series.high, series.low, series.close)
    for i in range(29, n):
        out[i] = ta.score(i, _structure(series.close[: i + 1]))
    return out


# ---------------------------------------------------------------- Kairos's reading


@dataclass(frozen=True)
class Reading:
    timeframe: str
    candles: int
    last_ts: int
    trend: float  # −100 … +100
    regime: str
    momentum: float  # −1 … +1
    rsi: float
    above_sma50: bool | None
    above_sma200: bool | None

    @property
    def direction(self) -> int:
        return 1 if self.trend >= 25 else -1 if self.trend <= -25 else 0

    def to_json(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "label": LABEL[self.timeframe],
            "candles": self.candles,
            "last_ts": self.last_ts,
            "trend": self.trend,
            "regime": self.regime,
            "momentum": round(self.momentum, 2),
            "rsi": self.rsi,
            "above_sma50": self.above_sma50,
            "above_sma200": self.above_sma200,
            "direction": self.direction,
        }


def reading(series: BarSeries, timeframe: str) -> Reading | None:
    """Trend and momentum of a chart on its latest finished candle (None if too short)."""
    n = len(series)
    if n < 30:
        return None
    ta = TrendArrays(series.high, series.low, series.close)
    ma = MomentumArrays(series.high, series.low, series.close)
    i = n - 1
    score = ta.score(i, _structure(series.close))
    rsi = float(ma.rsi[i]) if np.isfinite(ma.rsi[i]) else 50.0
    c = float(series.close[i])
    s50, s200 = ta.sma50[i], ta.sma200[i]
    return Reading(
        timeframe=timeframe,
        candles=n,
        last_ts=int(series.ts[i]),
        trend=score,
        regime=regime_of(score),
        momentum=ma.score(i),
        rsi=round(rsi, 1),
        above_sma50=bool(c > s50) if np.isfinite(s50) else None,
        above_sma200=bool(c > s200) if np.isfinite(s200) else None,
    )


def _structure(close: F64, look: int = 60) -> int:
    """Higher highs and higher lows over the last two halves of ``look`` candles (+1), lower
    and lower (−1), else 0: a quick swing-structure read that needs no zig-zag."""
    c = close[-look:]
    if len(c) < 20:
        return 0
    a, b = c[: len(c) // 2], c[len(c) // 2 :]
    if b.max() > a.max() and b.min() > a.min():
        return 1
    if b.max() < a.max() and b.min() < a.min():
        return -1
    return 0


ORDER = ("1mo", "1w", "1d", "1h", "15m", "5m", "1m")


def confluence(readings: list[Reading], chart: str) -> dict[str, Any]:
    """One verdict over several timeframes, biggest first.

    Weights: the biggest chart 0.45, the next 0.35, the chart traded on 0.2 (re-scaled when
    fewer are available). Long trades are "with the bigger trend" when the biggest chart
    isn't falling; short trades the mirror image."""
    rs = sorted(readings, key=lambda r: ORDER.index(r.timeframe))
    if not rs:
        return {"timeframes": [], "score": 0.0, "verdict": "unknown", "headline": "", "text": ""}
    weights = [0.45, 0.35, 0.2][: len(rs)] if len(rs) <= 3 else [0.4, 0.3, 0.2, 0.1][: len(rs)]
    total = sum(weights)
    score = round(sum(w * r.trend for w, r in zip(weights, rs, strict=False)) / total, 1)
    big = rs[0]
    small = next((r for r in rs if r.timeframe == chart), rs[-1])
    dirs = [r.direction for r in rs]
    names = {r.timeframe: LABEL[r.timeframe] for r in rs}
    if all(d == 1 for d in dirs):
        verdict, headline = "aligned_up", "Every timeframe agrees: up"
        text = (
            "The bigger and smaller charts all point up. Buy signals that agree with every "
            "timeframe have the best odds; short trades go against the tide."
        )
    elif all(d == -1 for d in dirs):
        verdict, headline = "aligned_down", "Every timeframe agrees: down"
        text = (
            "The bigger and smaller charts all point down. Rallies tend to fail here; buy "
            "signals on the small chart are likely false alarms."
        )
    elif big.direction == 1 and small.direction == -1:
        verdict, headline = "pullback_in_uptrend", f"A dip inside a {names[big.timeframe]} uptrend"
        text = (
            f"The {names[big.timeframe]} trend is up while the {names[small.timeframe]} chart "
            "is falling: a pullback. Trend followers wait for the small chart to turn up again "
            "before buying."
        )
    elif big.direction == -1 and small.direction == 1:
        verdict, headline = (
            "bounce_in_downtrend",
            f"A bounce inside a {names[big.timeframe]} downtrend",
        )
        text = (
            f"The {names[small.timeframe]} chart is rising but the {names[big.timeframe]} trend "
            "is down: rallies like this often fail. Buy signals here are the classic false alarm."
        )
    elif all(d == 0 for d in dirs):
        verdict, headline = "sideways", "No timeframe is trending"
        text = "Every chart is moving sideways: breakouts are less reliable; ranges more so."
    else:
        verdict, headline = "mixed", "The timeframes disagree"
        text = "Some charts point up and some down. Signals are less reliable until they line up."
    return {
        "chart": chart,
        "timeframes": [r.to_json() for r in rs],
        "score": score,
        "verdict": verdict,
        "headline": headline,
        "text": text,
        "long_ok": big.direction >= 0,
        "short_ok": big.direction <= 0,
    }
