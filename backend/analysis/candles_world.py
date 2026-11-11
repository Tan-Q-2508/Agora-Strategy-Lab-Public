"""The rest of the candlestick dictionary (Phase 10.2).

Together with ``candles.py`` this covers every pattern in TA-Lib's 61 candlestick
functions (the reference list most charting platforms use), plus the few common ones it
lacks (rising/falling windows, above/below the stomach, two black gapping, matching high).
TA-Lib's "kicking by length" is the same shape as "kicking" (it only decides the colour by
the longer candle), so it isn't a separate entry.

Shape words, measured like ``candles.py`` (ATR and the previous 14 candles' average body):
long body ≥ the average body; short body ≤ 0.6 × the average; doji body ≤ 10% of the range;
two prices are "equal" within 0.1 × ATR; a gap is a candle whose whole body (or, for
windows and kicks, whole range) clears the previous one. Context "after a fall/rise" is
the move into the pattern's first candle, as in ``candles.py``. Every value at candle
``i`` uses candles up to ``i`` only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backend.indicators.series import F64

B = NDArray[np.bool_]


@dataclass(frozen=True)
class Measures:
    o: F64
    h: F64
    lo: F64
    c: F64
    body: F64
    rng: F64
    upper: F64
    lower: F64
    up: B
    down: B
    atr: F64
    avg: F64  # average body of the previous 14 candles
    avg_rng: F64  # average range of the previous 14 candles
    fell: B
    rose: B
    safe: F64  # the range, NaN when zero


def S(x: F64, k: int) -> F64:
    """``x`` moved ``k`` candles later (index i holds candle i − k)."""
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def SB(x: B, k: int) -> B:
    out = np.zeros(len(x), dtype=bool)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


# (key, name, bias, candles, meaning)
WORLD: tuple[tuple[str, str, str, int, str], ...] = (
    (
        "breakaway_bull",
        "Bullish breakaway",
        "bullish",
        5,
        "A gap down that runs out of steam over three candles, then a strong up candle closing into the gap: the selling climax is over.",
    ),
    (
        "breakaway_bear",
        "Bearish breakaway",
        "bearish",
        5,
        "A gap up that stalls over three candles, then a strong down candle closing into the gap: the buying climax is over.",
    ),
    (
        "ladder_bottom",
        "Ladder bottom",
        "bullish",
        5,
        "Four falling down candles, the last with a long upper wick, then an up candle opening above it: a falling ladder that buyers finally climb.",
    ),
    (
        "mat_hold",
        "Mat hold",
        "bullish",
        5,
        "A strong up candle, a gap up, three small pullback candles that hold high, then a new high: the uptrend only paused.",
    ),
    (
        "rising_three_methods",
        "Rising three methods",
        "bullish",
        5,
        "A strong up candle, three small candles drifting inside its range, then a strong up candle to a new close: a rest in an uptrend.",
    ),
    (
        "falling_three_methods",
        "Falling three methods",
        "bearish",
        5,
        "A strong down candle, three small candles drifting inside its range, then a strong down candle to a new close: a rest in a downtrend.",
    ),
    (
        "concealing_baby_swallow",
        "Concealing baby swallow",
        "bullish",
        4,
        "Two big down candles, a gap down with a wick back up, then a down candle that swallows it: sellers exhausted (rare).",
    ),
    (
        "three_line_strike_bull",
        "Bullish three-line strike",
        "bullish",
        4,
        "Three rising up candles, then one long down candle that wipes them out. Traditionally bullish; Bulkowski's tests found it more often reverses down, so Kairos checks its own history.",
    ),
    (
        "three_line_strike_bear",
        "Bearish three-line strike",
        "bearish",
        4,
        "Three falling down candles, then one long up candle that wipes them out. Traditionally bearish; Bulkowski's tests found it reverses up about 84% of the time, the best of all candles.",
    ),
    (
        "hikkake_mod_bull",
        "Modified hikkake (bullish)",
        "bullish",
        5,
        "Two shrinking inside candles, a fake break lower, then a close back above the inside candle: the breakdown trapped sellers.",
    ),
    (
        "hikkake_mod_bear",
        "Modified hikkake (bearish)",
        "bearish",
        5,
        "Two shrinking inside candles, a fake break higher, then a close back below the inside candle: the breakout trapped buyers.",
    ),
    (
        "hikkake_bull",
        "Hikkake (bullish)",
        "bullish",
        3,
        "An inside candle, a fake break below it, then a close back above its high within three candles: a failed breakdown.",
    ),
    (
        "hikkake_bear",
        "Hikkake (bearish)",
        "bearish",
        3,
        "An inside candle, a fake break above it, then a close back below its low within three candles: a failed breakout.",
    ),
    (
        "abandoned_baby_bull",
        "Bullish abandoned baby",
        "bullish",
        3,
        "A big down candle, a doji left alone below a gap, then a gap up into a strong up candle: a sharp bottom (rare, reliable).",
    ),
    (
        "abandoned_baby_bear",
        "Bearish abandoned baby",
        "bearish",
        3,
        "A big up candle, a doji alone above a gap, then a gap down into a strong down candle: a sharp top (rare, reliable).",
    ),
    (
        "morning_doji_star",
        "Morning doji star",
        "bullish",
        3,
        "A big down candle, a doji that gaps lower, then a strong up candle: indecision at the low, then buyers.",
    ),
    (
        "evening_doji_star",
        "Evening doji star",
        "bearish",
        3,
        "A big up candle, a doji that gaps higher, then a strong down candle: indecision at the high, then sellers.",
    ),
    (
        "tristar_bull",
        "Bullish tri-star",
        "bullish",
        3,
        "Three dojis with the middle one gapping lower: extreme indecision at a low.",
    ),
    (
        "tristar_bear",
        "Bearish tri-star",
        "bearish",
        3,
        "Three dojis with the middle one gapping higher: extreme indecision at a high.",
    ),
    (
        "identical_three_crows",
        "Identical three crows",
        "bearish",
        3,
        "Three long down candles, each opening at the previous close: relentless, panicky selling.",
    ),
    (
        "three_stars_in_south",
        "Three stars in the south",
        "bullish",
        3,
        "Three down candles, each smaller with a higher low, the last tiny and wickless: selling drying up (rare).",
    ),
    (
        "unique_three_river",
        "Unique three river",
        "bullish",
        3,
        "A big down candle, a lower low that closes back up inside it, then a small up candle: a slow-forming bottom (rare).",
    ),
    (
        "three_inside_up",
        "Three inside up",
        "bullish",
        3,
        "A bullish harami confirmed by a third candle closing above the first candle's open.",
    ),
    (
        "three_inside_down",
        "Three inside down",
        "bearish",
        3,
        "A bearish harami confirmed by a third candle closing below the first candle's open.",
    ),
    (
        "three_outside_up",
        "Three outside up",
        "bullish",
        3,
        "A bullish engulfing confirmed by a third up candle closing higher.",
    ),
    (
        "three_outside_down",
        "Three outside down",
        "bearish",
        3,
        "A bearish engulfing confirmed by a third down candle closing lower.",
    ),
    (
        "two_crows",
        "Two crows",
        "bearish",
        3,
        "After a strong up candle, a gap up that fails into two down candles, the second closing inside the first candle's body.",
    ),
    (
        "upside_gap_two_crows",
        "Upside gap two crows",
        "bearish",
        3,
        "A strong up candle, a small down candle above a gap, then a bigger down candle engulfing it: the gap is about to fail.",
    ),
    (
        "advance_block",
        "Advance block",
        "bearish",
        3,
        "Three up candles with shrinking bodies and a growing upper wick: the rally is tiring.",
    ),
    (
        "stalled_pattern",
        "Stalled pattern (deliberation)",
        "bearish",
        3,
        "Two strong up candles, then a small one riding on the second's close: the advance is stalling.",
    ),
    (
        "stick_sandwich",
        "Stick sandwich",
        "bullish",
        3,
        "Two down candles closing at the same price with an up candle between them: a floor at that close.",
    ),
    (
        "tasuki_gap_up",
        "Upside tasuki gap",
        "bullish",
        3,
        "Two up candles with a gap between, then a down candle that dips into the gap but doesn't close it: the uptrend continues (Bulkowski: 57% continuation).",
    ),
    (
        "tasuki_gap_down",
        "Downside tasuki gap",
        "bearish",
        3,
        "Two down candles with a gap between, then an up candle into the gap that doesn't close it: the downtrend continues.",
    ),
    (
        "gap_three_methods_up",
        "Upside gap three methods",
        "bullish",
        3,
        "Two up candles with a gap between, then a down candle that fills the gap: a quick reset in an uptrend.",
    ),
    (
        "gap_three_methods_down",
        "Downside gap three methods",
        "bearish",
        3,
        "Two down candles with a gap between, then an up candle that fills the gap: a quick reset in a downtrend.",
    ),
    (
        "side_by_side_white_up",
        "Upside side-by-side white lines",
        "bullish",
        3,
        "A gap up followed by two similar up candles opening at the same price: the gap holds, the trend continues.",
    ),
    (
        "side_by_side_white_down",
        "Downside side-by-side white lines",
        "bearish",
        3,
        "A gap down followed by two similar up candles below it: weak bounces, the downtrend continues.",
    ),
    (
        "two_black_gapping",
        "Two black gapping candles",
        "bearish",
        2,
        "A gap down followed by two down candles: sellers pressing (Bulkowski: 68% bearish continuation).",
    ),
    (
        "kicking_bull",
        "Bullish kicker",
        "bullish",
        2,
        "A full down candle followed by a full up candle that gaps above it: a violent change of mind (rare, strong).",
    ),
    (
        "kicking_bear",
        "Bearish kicker",
        "bearish",
        2,
        "A full up candle followed by a full down candle that gaps below it: a violent change of mind (rare, strong).",
    ),
    (
        "harami_cross_bull",
        "Bullish harami cross",
        "bullish",
        2,
        "A doji inside the previous big down candle: the selling stopped dead.",
    ),
    (
        "harami_cross_bear",
        "Bearish harami cross",
        "bearish",
        2,
        "A doji inside the previous big up candle: the buying stopped dead.",
    ),
    (
        "doji_star_bull",
        "Bullish doji star",
        "bullish",
        2,
        "A doji that gaps below a big down candle: the fall hesitates (needs a confirming up candle).",
    ),
    (
        "doji_star_bear",
        "Bearish doji star",
        "bearish",
        2,
        "A doji that gaps above a big up candle: the rise hesitates (needs a confirming down candle).",
    ),
    (
        "counterattack_bull",
        "Bullish counterattack",
        "bullish",
        2,
        "After a big down candle, a big up candle that opens lower but closes right at the previous close.",
    ),
    (
        "counterattack_bear",
        "Bearish counterattack",
        "bearish",
        2,
        "After a big up candle, a big down candle that opens higher but closes right at the previous close.",
    ),
    (
        "separating_lines_bull",
        "Bullish separating lines",
        "bullish",
        2,
        "In an uptrend, a down candle then an up candle opening at the same price: buyers reassert the trend.",
    ),
    (
        "separating_lines_bear",
        "Bearish separating lines",
        "bearish",
        2,
        "In a downtrend, an up candle then a down candle opening at the same price: sellers reassert the trend.",
    ),
    (
        "homing_pigeon",
        "Homing pigeon",
        "bullish",
        2,
        "A small down candle inside a big down candle: the selling is shrinking.",
    ),
    (
        "matching_low",
        "Matching low",
        "bullish",
        2,
        "Two down candles closing at the same price: a floor (Bulkowski: often continues down instead, 61%).",
    ),
    (
        "matching_high",
        "Matching high",
        "bearish",
        2,
        "Two up candles closing at the same price: a ceiling.",
    ),
    (
        "in_neck",
        "In-neck line",
        "bearish",
        2,
        "After a big down candle, an up candle opening below its low that closes just inside it: a weak bounce, the fall continues.",
    ),
    (
        "on_neck",
        "On-neck line",
        "bearish",
        2,
        "After a big down candle, an up candle opening lower that closes right at its low: a weak bounce, the fall continues.",
    ),
    (
        "thrusting",
        "Thrusting line",
        "bearish",
        2,
        "After a big down candle, an up candle opening below its low that closes inside it but below its middle: not enough to turn.",
    ),
    (
        "above_the_stomach",
        "Above the stomach",
        "bullish",
        2,
        "After a down candle, an up candle that opens and closes above its middle: buyers took over overnight.",
    ),
    (
        "below_the_stomach",
        "Below the stomach",
        "bearish",
        2,
        "After an up candle, a down candle that opens and closes below its middle: sellers took over overnight.",
    ),
    (
        "rising_window",
        "Rising window (gap up)",
        "bullish",
        2,
        "The whole candle trades above the previous high: a gap that often becomes support.",
    ),
    (
        "falling_window",
        "Falling window (gap down)",
        "bearish",
        2,
        "The whole candle trades below the previous low: a gap that often becomes resistance.",
    ),
    (
        "takuri",
        "Takuri line",
        "bullish",
        1,
        "A doji with a very long lower wick (over 80% of the range) after a fall: a deep dip completely bought back.",
    ),
    (
        "rickshaw_man",
        "Rickshaw man",
        "neutral",
        1,
        "A long-legged doji with the open and close right in the middle: perfect indecision.",
    ),
    (
        "high_wave",
        "High-wave candle",
        "neutral",
        1,
        "A small body with very long wicks on both sides: the market has lost its sense of direction.",
    ),
    (
        "belt_hold_bull",
        "Bullish belt hold",
        "bullish",
        1,
        "After a fall, a long up candle opening at its low: buyers from the first trade.",
    ),
    (
        "belt_hold_bear",
        "Bearish belt hold",
        "bearish",
        1,
        "After a rise, a long down candle opening at its high: sellers from the first trade.",
    ),
    (
        "closing_marubozu_bull",
        "Bullish closing marubozu",
        "bullish",
        1,
        "A long up candle that closes at its high: buyers held control to the bell.",
    ),
    (
        "closing_marubozu_bear",
        "Bearish closing marubozu",
        "bearish",
        1,
        "A long down candle that closes at its low: sellers held control to the bell.",
    ),
    (
        "long_white_candle",
        "Long up candle",
        "bullish",
        1,
        "An up candle at least 1.5× the usual body with short wicks: strong buying.",
    ),
    (
        "long_black_candle",
        "Long down candle",
        "bearish",
        1,
        "A down candle at least 1.5× the usual body with short wicks: strong selling.",
    ),
    (
        "short_line",
        "Short candle",
        "neutral",
        1,
        "A small body and a small range: a quiet, undecided session.",
    ),
)


def detect_world(m: Measures) -> dict[str, B]:
    o, h, lo, c = m.o, m.h, m.lo, m.c
    body, upper, lower, safe = m.body, m.upper, m.lower, m.safe
    up, down, atr, avg = m.up, m.down, m.atr, m.avg
    with np.errstate(invalid="ignore"):
        eq = 0.1 * atr
        doji = body <= 0.1 * safe
        long_ = body >= avg
        short = body <= 0.6 * avg
        full = body >= 0.9 * safe  # marubozu shape
        top, bot = np.maximum(o, c), np.minimum(o, c)

        def o_(k: int) -> F64:
            return S(o, k)

        def h_(k: int) -> F64:
            return S(h, k)

        def l_(k: int) -> F64:
            return S(lo, k)

        def c_(k: int) -> F64:
            return S(c, k)

        def b_(k: int) -> F64:
            return S(body, k)

        def u_(k: int) -> B:
            return SB(up, k)

        def d_(k: int) -> B:
            return SB(down, k)

        def big(k: int) -> B:
            return SB(long_, k)

        def sh(k: int) -> B:
            return SB(short, k)

        def dj(k: int) -> B:
            return SB(doji, k)

        def top_(k: int) -> F64:
            return S(top, k)

        def bot_(k: int) -> F64:
            return S(bot, k)

        fell, rose = m.fell, m.rose
        f2, r2 = SB(fell, 2), SB(rose, 2)
        f3 = SB(fell, 3)
        f4, r4 = SB(fell, 4), SB(rose, 4)
        mid1 = (o_(1) + c_(1)) / 2.0
        mid2 = (o_(2) + c_(2)) / 2.0
        hi3 = np.maximum.reduce([h_(3), h_(2), h_(1)])
        lo3 = np.minimum.reduce([l_(3), l_(2), l_(1)])

        out: dict[str, B] = {
            # ---- five candles
            "breakaway_bull": f4
            & d_(4)
            & big(4)
            & d_(3)
            & (top_(3) < c_(4))
            & (c_(2) < c_(3))
            & (c_(1) < c_(2))
            & d_(1)
            & up
            & (c > top_(3))
            & (c < c_(4)),
            "breakaway_bear": r4
            & u_(4)
            & big(4)
            & u_(3)
            & (bot_(3) > c_(4))
            & (c_(2) > c_(3))
            & (c_(1) > c_(2))
            & u_(1)
            & down
            & (c < bot_(3))
            & (c > c_(4)),
            "ladder_bottom": f4
            & d_(4)
            & d_(3)
            & d_(2)
            & (o_(3) < o_(4))
            & (c_(3) < c_(4))
            & (o_(2) < o_(3))
            & (c_(2) < c_(3))
            & d_(1)
            & (S(upper, 1) >= b_(1))
            & up
            & (o > o_(1))
            & (c > h_(1)),
            "mat_hold": u_(4)
            & big(4)
            & (bot_(3) > c_(4))
            & sh(3)
            & sh(2)
            & sh(1)
            & (lo3 > (o_(4) + c_(4)) / 2.0)
            & (c_(2) < c_(3))
            & (c_(1) < c_(2))
            & up
            & long_
            & (o > c_(1))
            & (c > hi3),
            "rising_three_methods": u_(4)
            & big(4)
            & sh(3)
            & sh(2)
            & sh(1)
            & (hi3 <= h_(4))
            & (lo3 >= l_(4))
            & (c_(1) < c_(4))
            & up
            & long_
            & (o > c_(1))
            & (c > c_(4)),
            "falling_three_methods": d_(4)
            & big(4)
            & sh(3)
            & sh(2)
            & sh(1)
            & (hi3 <= h_(4))
            & (lo3 >= l_(4))
            & (c_(1) > c_(4))
            & down
            & long_
            & (o < c_(1))
            & (c < c_(4)),
            # ---- four candles
            "concealing_baby_swallow": f3
            & d_(3)
            & SB(full, 3)
            & d_(2)
            & SB(full, 2)
            & d_(1)
            & (o_(1) < c_(2))
            & (h_(1) > c_(2))
            & down
            & (o > h_(1))
            & (c < l_(1)),
            "three_line_strike_bull": u_(3)
            & u_(2)
            & u_(1)
            & (c_(2) > c_(3))
            & (c_(1) > c_(2))
            & down
            & (o >= c_(1))
            & (c <= o_(3)),
            "three_line_strike_bear": d_(3)
            & d_(2)
            & d_(1)
            & (c_(2) < c_(3))
            & (c_(1) < c_(2))
            & up
            & (o <= c_(1))
            & (c >= o_(3)),
            # ---- three candles
            "abandoned_baby_bull": f2
            & d_(2)
            & big(2)
            & dj(1)
            & (h_(1) < l_(2))
            & up
            & (lo > h_(1))
            & (c > c_(2) + 0.3 * b_(2)),
            "abandoned_baby_bear": r2
            & u_(2)
            & big(2)
            & dj(1)
            & (l_(1) > h_(2))
            & down
            & (h < l_(1))
            & (c < c_(2) - 0.3 * b_(2)),
            "morning_doji_star": f2 & d_(2) & big(2) & dj(1) & (top_(1) < c_(2)) & up & (c >= mid2),
            "evening_doji_star": r2
            & u_(2)
            & big(2)
            & dj(1)
            & (bot_(1) > c_(2))
            & down
            & (c <= mid2),
            "tristar_bull": f2 & dj(2) & dj(1) & doji & (top_(1) < bot_(2)) & (top_(1) < bot),
            "tristar_bear": r2 & dj(2) & dj(1) & doji & (bot_(1) > top_(2)) & (bot_(1) > top),
            "identical_three_crows": r2
            & d_(2)
            & d_(1)
            & down
            & big(2)
            & big(1)
            & long_
            & (np.abs(o_(1) - c_(2)) <= eq)
            & (np.abs(o - c_(1)) <= eq)
            & (c_(1) < c_(2))
            & (c < c_(1)),
            "three_stars_in_south": f2
            & d_(2)
            & big(2)
            & (S(lower, 2) >= 0.5 * b_(2))
            & d_(1)
            & (b_(1) < b_(2))
            & (l_(1) > l_(2))
            & (o_(1) < h_(2))
            & down
            & (upper <= 0.1 * safe)
            & (lower <= 0.1 * safe)
            & (h <= h_(1))
            & (lo >= l_(1))
            & (body <= b_(1)),
            "unique_three_river": f2
            & d_(2)
            & big(2)
            & d_(1)
            & (top_(1) <= o_(2))
            & (bot_(1) >= c_(2))
            & (l_(1) < l_(2))
            & up
            & short
            & (c < c_(1))
            & (o > l_(1)),
            "three_inside_up": f2
            & d_(2)
            & big(2)
            & u_(1)
            & (top_(1) <= o_(2))
            & (bot_(1) >= c_(2))
            & (b_(1) <= 0.6 * b_(2))
            & up
            & (c > o_(2)),
            "three_inside_down": r2
            & u_(2)
            & big(2)
            & d_(1)
            & (top_(1) <= c_(2))
            & (bot_(1) >= o_(2))
            & (b_(1) <= 0.6 * b_(2))
            & down
            & (c < o_(2)),
            "three_outside_up": f2
            & d_(2)
            & u_(1)
            & (o_(1) <= c_(2))
            & (c_(1) >= o_(2))
            & (b_(1) > b_(2))
            & up
            & (c > c_(1)),
            "three_outside_down": r2
            & u_(2)
            & d_(1)
            & (o_(1) >= c_(2))
            & (c_(1) <= o_(2))
            & (b_(1) > b_(2))
            & down
            & (c < c_(1)),
            "two_crows": r2
            & u_(2)
            & big(2)
            & d_(1)
            & (bot_(1) > c_(2))
            & down
            & (o < o_(1))
            & (o > c_(1))
            & (c > o_(2))
            & (c < c_(2)),
            "upside_gap_two_crows": r2
            & u_(2)
            & big(2)
            & d_(1)
            & (bot_(1) > c_(2))
            & down
            & (o > o_(1))
            & (c < c_(1))
            & (c > c_(2)),
            "advance_block": r2
            & u_(2)
            & big(2)
            & u_(1)
            & up
            & (c > c_(1))
            & (c_(1) > c_(2))
            & (o_(1) > o_(2))
            & (o_(1) <= c_(2))
            & (o > o_(1))
            & (o <= c_(1))
            & (b_(1) < b_(2))
            & (body < b_(1))
            & (upper >= 0.5 * body),
            "stalled_pattern": r2
            & u_(2)
            & u_(1)
            & big(2)
            & big(1)
            & (c_(1) > c_(2))
            & up
            & short
            & (o >= c_(1) - eq)
            & (c > c_(1)),
            "stick_sandwich": f2
            & d_(2)
            & u_(1)
            & (l_(1) > c_(2))
            & down
            & (o > c_(1))
            & (np.abs(c - c_(2)) <= eq),
            "tasuki_gap_up": u_(2)
            & u_(1)
            & (l_(1) > h_(2))
            & down
            & (o < c_(1))
            & (o > o_(1))
            & (c < o_(1))
            & (c > h_(2)),
            "tasuki_gap_down": d_(2)
            & d_(1)
            & (h_(1) < l_(2))
            & up
            & (o > c_(1))
            & (o < o_(1))
            & (c > o_(1))
            & (c < l_(2)),
            "gap_three_methods_up": u_(2)
            & u_(1)
            & (l_(1) > h_(2))
            & down
            & (o < c_(1))
            & (o > o_(1))
            & (c < c_(2))
            & (c > o_(2)),
            "gap_three_methods_down": d_(2)
            & d_(1)
            & (h_(1) < l_(2))
            & up
            & (o > c_(1))
            & (o < o_(1))
            & (c > c_(2))
            & (c < o_(2)),
            "side_by_side_white_up": u_(2)
            & u_(1)
            & (bot_(1) > top_(2))
            & up
            & (bot > top_(2))
            & (np.abs(o - o_(1)) <= eq)
            & (body >= 0.7 * b_(1))
            & (body <= 1.3 * b_(1)),
            "side_by_side_white_down": d_(2)
            & u_(1)
            & (top_(1) < bot_(2))
            & up
            & (top < bot_(2))
            & (np.abs(o - o_(1)) <= eq)
            & (body >= 0.7 * b_(1))
            & (body <= 1.3 * b_(1)),
            # ---- two candles
            "two_black_gapping": d_(1) & (h_(1) < l_(2)) & down & (h < h_(1)),
            "kicking_bull": d_(1) & SB(full, 1) & big(1) & up & full & long_ & (lo > h_(1)),
            "kicking_bear": u_(1) & SB(full, 1) & big(1) & down & full & long_ & (h < l_(1)),
            "harami_cross_bull": fell & d_(1) & big(1) & doji & (top <= o_(1)) & (bot >= c_(1)),
            "harami_cross_bear": rose & u_(1) & big(1) & doji & (top <= c_(1)) & (bot >= o_(1)),
            "doji_star_bull": fell & d_(1) & big(1) & doji & (top < c_(1)),
            "doji_star_bear": rose & u_(1) & big(1) & doji & (bot > c_(1)),
            "counterattack_bull": fell
            & d_(1)
            & big(1)
            & up
            & long_
            & (o < c_(1))
            & (np.abs(c - c_(1)) <= eq),
            "counterattack_bear": rose
            & u_(1)
            & big(1)
            & down
            & long_
            & (o > c_(1))
            & (np.abs(c - c_(1)) <= eq),
            "separating_lines_bull": rose & d_(1) & up & long_ & (np.abs(o - o_(1)) <= eq),
            "separating_lines_bear": fell & u_(1) & down & long_ & (np.abs(o - o_(1)) <= eq),
            "homing_pigeon": fell
            & d_(1)
            & big(1)
            & down
            & (o < o_(1))
            & (c > c_(1))
            & (body <= 0.6 * b_(1)),
            "matching_low": fell & d_(1) & big(1) & down & (np.abs(c - c_(1)) <= eq),
            "matching_high": rose & u_(1) & big(1) & up & (np.abs(c - c_(1)) <= eq),
            "in_neck": fell
            & d_(1)
            & big(1)
            & up
            & (o < l_(1))
            & (c >= c_(1) + 0.25 * eq)
            & (c <= c_(1) + 0.15 * b_(1)),
            "on_neck": fell & d_(1) & big(1) & up & (o < l_(1)) & (np.abs(c - l_(1)) <= eq),
            "thrusting": fell
            & d_(1)
            & big(1)
            & up
            & (o < l_(1))
            & (c > c_(1) + 0.15 * b_(1))
            & (c < mid1),
            "above_the_stomach": fell & d_(1) & big(1) & up & (o >= mid1) & (c >= mid1),
            "below_the_stomach": rose & u_(1) & big(1) & down & (o <= mid1) & (c <= mid1),
            "rising_window": lo > h_(1),
            "falling_window": h < l_(1),
            # ---- one candle
            "takuri": fell & doji & (upper <= 0.05 * safe) & (lower >= 0.8 * safe),
            "rickshaw_man": doji
            & (upper >= 0.35 * safe)
            & (lower >= 0.35 * safe)
            & (np.abs((o + c) / 2.0 - (h + lo) / 2.0) <= 0.1 * safe),
            "high_wave": (body > 0.1 * safe) & (upper >= 3 * body) & (lower >= 3 * body),
            "belt_hold_bull": fell & up & long_ & (lower <= 0.05 * safe),
            "belt_hold_bear": rose & down & long_ & (upper <= 0.05 * safe),
            "closing_marubozu_bull": up & long_ & (upper <= 0.05 * safe) & (lower > 0.05 * safe),
            "closing_marubozu_bear": down & long_ & (lower <= 0.05 * safe) & (upper > 0.05 * safe),
            "long_white_candle": up
            & (body >= 1.5 * avg)
            & (upper <= 0.25 * body)
            & (lower <= 0.25 * body),
            "long_black_candle": down
            & (body >= 1.5 * avg)
            & (upper <= 0.25 * body)
            & (lower <= 0.25 * body),
            "short_line": (body <= 0.5 * avg) & (body > 0.1 * safe) & (m.rng <= 0.75 * m.avg_rng),
        }
    out.update(_hikkake(h, lo, c))
    return {k: np.asarray(v, dtype=bool) for k, v in out.items()}


def _hikkake(h: F64, lo: F64, c: F64) -> dict[str, B]:
    """Hikkake: an inside candle (``ib``) inside its mother, then a candle that breaks one
    way (lower high and lower low, or the mirror), then, within three candles, the first
    close back beyond the inside candle's other side. The modified version needs two
    nested inside candles, the second closing near its low (high) for the bullish (bearish)
    case. Flagged on the confirming close."""
    n = len(c)
    out = {
        k: np.zeros(n, dtype=bool)
        for k in ("hikkake_bull", "hikkake_bear", "hikkake_mod_bull", "hikkake_mod_bear")
    }

    def inside(a: int, b: int) -> bool:
        return bool(h[b] < h[a] and lo[b] > lo[a])

    for i in range(3, n):
        for k in (1, 2, 3):
            s = i - k  # the false-break candle
            ib = s - 1
            if ib < 1 or not inside(ib - 1, ib):
                continue
            between = c[s:i]
            if h[s] < h[ib] and lo[s] < lo[ib] and c[i] > h[ib] and (between <= h[ib]).all():
                out["hikkake_bull"][i] = True
                rng = h[ib] - lo[ib]
                if ib >= 2 and inside(ib - 2, ib - 1) and rng > 0 and c[ib] <= lo[ib] + 0.25 * rng:
                    out["hikkake_mod_bull"][i] = True
            if h[s] > h[ib] and lo[s] > lo[ib] and c[i] < lo[ib] and (between >= lo[ib]).all():
                out["hikkake_bear"][i] = True
                rng = h[ib] - lo[ib]
                if ib >= 2 and inside(ib - 2, ib - 1) and rng > 0 and c[ib] >= h[ib] - 0.25 * rng:
                    out["hikkake_mod_bear"][i] = True
    return out
