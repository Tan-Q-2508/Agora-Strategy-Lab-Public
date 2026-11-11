"""Candlestick patterns (KAIROS §3).

One-, two- and three-candle shapes from Japanese candlestick charting. Most only mean
something in context: a hammer is a hammer only after a fall (the same shape after a rise
is a hanging man). "Before a fall/rise" is the move from 6 candles ago to the previous
candle: at least 0.5 × ATR down (or up).

Shape measures: body = |close − open|, range = high − low, upper/lower shadow = the wicks.
"Long" bodies are at least the average body of the previous 14 candles. Every array value
at candle ``i`` uses candles ``i − 2 … i`` and earlier only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from backend.analysis import candles_world as cw
from backend.indicators import vector as vx
from backend.indicators.series import F64

Bias = Literal["bullish", "bearish", "neutral"]
B = NDArray[np.bool_]


@dataclass(frozen=True)
class CandleInfo:
    key: str
    name: str
    bias: Bias
    candles: int  # how many candles make the pattern
    meaning: str


INFO: dict[str, CandleInfo] = {
    i.key: i
    for i in (
        CandleInfo(
            "morning_star",
            "Morning star",
            "bullish",
            3,
            "A big down candle, a small pause, then a strong up candle: sellers ran out.",
        ),
        CandleInfo(
            "evening_star",
            "Evening star",
            "bearish",
            3,
            "A big up candle, a small pause, then a strong down candle: buyers ran out.",
        ),
        CandleInfo(
            "three_white_soldiers",
            "Three white soldiers",
            "bullish",
            3,
            "Three strong up candles in a row: steady buying.",
        ),
        CandleInfo(
            "three_black_crows",
            "Three black crows",
            "bearish",
            3,
            "Three strong down candles in a row: steady selling.",
        ),
        CandleInfo(
            "bullish_engulfing",
            "Bullish engulfing",
            "bullish",
            2,
            "An up candle whose body swallows the previous down candle after a fall.",
        ),
        CandleInfo(
            "bearish_engulfing",
            "Bearish engulfing",
            "bearish",
            2,
            "A down candle whose body swallows the previous up candle after a rise.",
        ),
        CandleInfo(
            "piercing_line",
            "Piercing line",
            "bullish",
            2,
            "After a big down candle, the next opens lower but closes above its middle.",
        ),
        CandleInfo(
            "dark_cloud_cover",
            "Dark cloud cover",
            "bearish",
            2,
            "After a big up candle, the next opens higher but closes below its middle.",
        ),
        CandleInfo(
            "bullish_harami",
            "Bullish harami",
            "bullish",
            2,
            "A small candle inside the previous big down candle: the selling paused.",
        ),
        CandleInfo(
            "bearish_harami",
            "Bearish harami",
            "bearish",
            2,
            "A small candle inside the previous big up candle: the buying paused.",
        ),
        CandleInfo(
            "tweezer_bottom",
            "Tweezer bottom",
            "bullish",
            2,
            "Two candles with the same low after a fall: a floor held twice.",
        ),
        CandleInfo(
            "tweezer_top",
            "Tweezer top",
            "bearish",
            2,
            "Two candles with the same high after a rise: a ceiling held twice.",
        ),
        CandleInfo(
            "hammer",
            "Hammer",
            "bullish",
            1,
            "A long lower wick after a fall: sellers pushed down, buyers pushed back.",
        ),
        CandleInfo(
            "hanging_man",
            "Hanging man",
            "bearish",
            1,
            "A hammer shape after a rise: a warning that selling is appearing.",
        ),
        CandleInfo(
            "inverted_hammer",
            "Inverted hammer",
            "bullish",
            1,
            "A long upper wick after a fall: buyers are starting to test higher.",
        ),
        CandleInfo(
            "shooting_star",
            "Shooting star",
            "bearish",
            1,
            "A long upper wick after a rise: buyers were pushed back down.",
        ),
        CandleInfo(
            "bullish_marubozu",
            "Bullish marubozu",
            "bullish",
            1,
            "A big up candle with almost no wicks: buyers in control all session.",
        ),
        CandleInfo(
            "bearish_marubozu",
            "Bearish marubozu",
            "bearish",
            1,
            "A big down candle with almost no wicks: sellers in control all session.",
        ),
        CandleInfo(
            "dragonfly_doji",
            "Dragonfly doji",
            "bullish",
            1,
            "Opened and closed at the high after a deep dip: the dip was bought.",
        ),
        CandleInfo(
            "gravestone_doji",
            "Gravestone doji",
            "bearish",
            1,
            "Opened and closed at the low after a rally: the rally was sold.",
        ),
        CandleInfo(
            "long_legged_doji",
            "Long-legged doji",
            "neutral",
            1,
            "Big swings both ways but no change: strong indecision.",
        ),
        CandleInfo(
            "doji",
            "Doji",
            "neutral",
            1,
            "Open and close almost equal: buyers and sellers are balanced.",
        ),
        CandleInfo(
            "spinning_top",
            "Spinning top",
            "neutral",
            1,
            "A small body with wicks on both sides: indecision.",
        ),
        CandleInfo(
            "inside_bar",
            "Inside bar",
            "neutral",
            2,
            "A candle inside the previous one's range: the market is coiling.",
        ),
        CandleInfo(
            "outside_bar",
            "Outside bar",
            "neutral",
            2,
            "A candle that takes out both the previous high and low: a volatile turn.",
        ),
    )
}
INFO.update(
    {key: CandleInfo(key, name, bias, n, meaning) for key, name, bias, n, meaning in cw.WORLD}  # type: ignore[arg-type]
)
# Earlier = more specific; each candle gets one label. Longer patterns first, then rarer
# shapes before the common ones they contain (a takuri is also a dragonfly doji).
PRIORITY = [
    *[w[0] for w in cw.WORLD if w[3] >= 4],
    "hikkake_bull",
    "hikkake_bear",
    "abandoned_baby_bull",
    "abandoned_baby_bear",
    "morning_doji_star",
    "evening_doji_star",
    "tristar_bull",
    "tristar_bear",
    "identical_three_crows",
    "morning_star",
    "evening_star",
    "three_white_soldiers",
    "three_black_crows",
    *[
        w[0]
        for w in cw.WORLD
        if w[3] == 3
        and not w[0].startswith(
            ("hikkake", "abandoned", "morning", "evening", "tristar", "identical")
        )
    ],
    "kicking_bull",
    "kicking_bear",
    "bullish_engulfing",
    "bearish_engulfing",
    "two_black_gapping",
    "harami_cross_bull",
    "harami_cross_bear",
    "piercing_line",
    "dark_cloud_cover",
    "bullish_harami",
    "bearish_harami",
    *[
        w[0]
        for w in cw.WORLD
        if w[3] == 2
        and not w[0].startswith(("kicking", "harami", "two_black", "rising_w", "falling_w"))
    ],
    "tweezer_bottom",
    "tweezer_top",
    "hammer",
    "hanging_man",
    "inverted_hammer",
    "shooting_star",
    "takuri",
    "bullish_marubozu",
    "bearish_marubozu",
    "closing_marubozu_bull",
    "closing_marubozu_bear",
    "belt_hold_bull",
    "belt_hold_bear",
    "dragonfly_doji",
    "gravestone_doji",
    "rickshaw_man",
    "long_legged_doji",
    "doji",
    "high_wave",
    "spinning_top",
    "long_white_candle",
    "long_black_candle",
    "inside_bar",
    "outside_bar",
    "rising_window",
    "falling_window",
    "short_line",
]
assert sorted(PRIORITY) == sorted(INFO), "every pattern needs a place in PRIORITY"


def _sf(x: F64, k: int = 1) -> F64:
    """``x`` moved ``k`` candles later (so index i holds the value of candle i − k)."""
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    return out


def _sb(x: B, k: int = 1) -> B:
    out = np.zeros(len(x), dtype=bool)
    out[k:] = x[:-k]
    return out


def detect(o: F64, h: F64, lo: F64, c: F64) -> dict[str, B]:
    """A boolean array per pattern: True on the candle that completes it."""
    n = len(c)
    body = np.abs(c - o)
    rng = h - lo
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - lo
    up, down = c > o, c < o
    atr = vx.atr(h, lo, c, 14)
    atr = np.where(np.isnan(atr), np.nan_to_num(np.cumsum(rng) / np.arange(1, n + 1)), atr)
    avg = _sf(vx.sma(body, 14))
    avg = np.where(np.isnan(avg), np.cumsum(body) / np.arange(1, n + 1), avg)
    move = _sf(c, 1) - _sf(c, 6)
    fell = move <= -0.5 * atr
    rose = move >= 0.5 * atr
    big = body >= avg
    safe = np.where(rng > 0, rng, np.nan)
    with np.errstate(invalid="ignore"):
        doji = body <= 0.1 * safe
        small = (body <= 0.35 * safe) & (body > 0.05 * safe)
        hammer_shape = small & (lower >= 2 * body) & (upper <= 0.15 * safe)
        inv_shape = small & (upper >= 2 * body) & (lower <= 0.15 * safe)

    pb, pu, pd = _sb(big), _sb(up), _sb(down)
    po, pc, ph, pl, pbody = _sf(o), _sf(c), _sf(h), _sf(lo), _sf(body)
    fell2, rose2 = _sb(fell, 2), _sb(rose, 2)
    with np.errstate(invalid="ignore"):
        mid_prev = (po + pc) / 2.0
        out: dict[str, B] = {
            "doji": doji,
            "dragonfly_doji": doji & (upper <= 0.1 * safe) & (lower >= 0.6 * safe),
            "gravestone_doji": doji & (lower <= 0.1 * safe) & (upper >= 0.6 * safe),
            "long_legged_doji": doji & (upper >= 0.35 * safe) & (lower >= 0.35 * safe),
            "hammer": hammer_shape & fell,
            "hanging_man": hammer_shape & rose,
            "inverted_hammer": inv_shape & fell,
            "shooting_star": inv_shape & rose,
            "bullish_engulfing": fell & pd & up & (o <= pc) & (c >= po) & (body > pbody),
            "bearish_engulfing": rose & pu & down & (o >= pc) & (c <= po) & (body > pbody),
            "bullish_harami": fell
            & pd
            & pb
            & (np.maximum(o, c) <= po)
            & (np.minimum(o, c) >= pc)
            & (body <= 0.5 * pbody),
            "bearish_harami": rose
            & pu
            & pb
            & (np.maximum(o, c) <= pc)
            & (np.minimum(o, c) >= po)
            & (body <= 0.5 * pbody),
            "piercing_line": fell & pd & pb & up & (o < pc) & (c > mid_prev) & (c < po),
            "dark_cloud_cover": rose & pu & pb & down & (o > pc) & (c < mid_prev) & (c > po),
            "morning_star": fell2
            & _sb(down, 2)
            & _sb(big, 2)
            & (pbody <= 0.5 * _sf(body, 2))
            & (np.maximum(po, pc) <= _sf(c, 2) + 0.1 * atr)
            & up
            & (c >= (_sf(o, 2) + _sf(c, 2)) / 2.0),
            "evening_star": rose2
            & _sb(up, 2)
            & _sb(big, 2)
            & (pbody <= 0.5 * _sf(body, 2))
            & (np.minimum(po, pc) >= _sf(c, 2) - 0.1 * atr)
            & down
            & (c <= (_sf(o, 2) + _sf(c, 2)) / 2.0),
            "three_white_soldiers": up
            & pu
            & _sb(up, 2)
            & (body >= 0.8 * avg)
            & (pbody >= 0.8 * avg)
            & (_sf(body, 2) >= 0.8 * avg)
            & (c > pc)
            & (pc > _sf(c, 2))
            & (o >= po)
            & (o <= pc)
            & (po >= _sf(o, 2))
            & (po <= _sf(c, 2))
            & (upper <= 0.3 * body),
            "three_black_crows": down
            & pd
            & _sb(down, 2)
            & (body >= 0.8 * avg)
            & (pbody >= 0.8 * avg)
            & (_sf(body, 2) >= 0.8 * avg)
            & (c < pc)
            & (pc < _sf(c, 2))
            & (o <= po)
            & (o >= pc)
            & (po <= _sf(o, 2))
            & (po >= _sf(c, 2))
            & (lower <= 0.3 * body),
            "bullish_marubozu": up & (body >= 0.9 * safe) & (body >= 1.2 * avg),
            "bearish_marubozu": down & (body >= 0.9 * safe) & (body >= 1.2 * avg),
            "spinning_top": (body <= 0.3 * safe)
            & (body > 0.1 * safe)
            & (upper >= body)
            & (lower >= body),
            "tweezer_bottom": fell & pd & up & (np.abs(lo - pl) <= 0.1 * atr),
            "tweezer_top": rose & pu & down & (np.abs(h - ph) <= 0.1 * atr),
            "inside_bar": (h <= ph) & (lo >= pl) & (rng < _sf(rng)),
            "outside_bar": (h > ph) & (lo < pl),
        }
    avg_rng = _sf(vx.sma(rng, 14))
    avg_rng = np.where(np.isnan(avg_rng), np.cumsum(rng) / np.arange(1, n + 1), avg_rng)
    m = cw.Measures(
        o, h, lo, c, body, rng, upper, lower, up, down, atr, avg, avg_rng, fell, rose, safe
    )
    out.update(cw.detect_world(m))
    for k in out:
        arr = np.asarray(out[k], dtype=bool)
        arr[:1] = False
        out[k] = arr
    return out


@dataclass(frozen=True)
class CandleHit:
    index: int
    key: str

    @property
    def info(self) -> CandleInfo:
        return INFO[self.key]


def label_candles(flags: dict[str, B], start: int, end: int) -> list[CandleHit]:
    """The most specific pattern on each candle from ``start`` to ``end`` (inclusive)."""
    hits: list[CandleHit] = []
    for i in range(max(0, start), end + 1):
        for key in PRIORITY:
            if bool(flags[key][i]):
                hits.append(CandleHit(i, key))
                break
    return hits
