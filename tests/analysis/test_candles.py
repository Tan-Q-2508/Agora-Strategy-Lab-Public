"""Every candlestick pattern on hand-built candles.

Context candles: ``falling()`` ends with a down candle open 106, high 106.5, low 104.5,
close 105 (bodies 1, true range 2, so ATR ≈ 2); ``rising()`` ends with open 114, high
115.5, low 113.5, close 115. "After a fall/rise" means the close moved ≥ 1 (0.5 × ATR)
over the previous 5 candles; both contexts move 5.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.analysis import candles as cdl
from tests.analysis.helpers import candles, falling, rising
from tests.golden.test_indicators import DAILY

Row = tuple[float, float, float, float]

CASES: dict[str, tuple[str, list[Row]]] = {
    # body 0.4 (≤ 0.35 × range 2.05), lower wick 1.6 ≥ 2 × body, upper 0.05
    "hammer": ("fall", [(104.6, 105.05, 103.0, 105.0)]),
    # opens below the last close; upper wick 1.6, lower 0.05
    "inverted_hammer": ("fall", [(104.0, 106.0, 103.95, 104.4)]),
    # opens ≤ 105 (last close), closes ≥ 106 (last open), bigger body
    "bullish_engulfing": ("fall", [(104.8, 106.6, 104.6, 106.4)]),
    # opens below 105, closes above the middle 105.5 but below 106
    "piercing_line": ("fall", [(104.5, 105.9, 104.3, 105.8)]),
    # small body inside the last body (105–106)
    "bullish_harami": ("fall", [(105.2, 105.6, 105.0, 105.5)]),
    # same low as the last candle (104.5), closes up
    "tweezer_bottom": ("fall", [(104.6, 105.4, 104.5, 105.2)]),
    # big down, small pause near its close, up past its middle (104)
    "morning_star": (
        "fall",
        [(105, 105.5, 102.9, 103), (102.8, 103.1, 102.3, 102.7), (102.9, 104.6, 102.8, 104.5)],
    ),
    "three_white_soldiers": (
        "fall",
        [(105, 106.3, 104.9, 106.2), (106.0, 107.3, 105.9, 107.2), (107.0, 108.3, 106.9, 108.2)],
    ),
    "dragonfly_doji": ("fall", [(105, 105.05, 103.0, 105.0)]),
    "bullish_marubozu": ("fall", [(105, 107.05, 104.95, 107)]),
    "hanging_man": ("rise", [(115.4, 115.85, 113.8, 115.8)]),
    "shooting_star": ("rise", [(115.2, 117.2, 115.0, 115.6)]),
    "bearish_engulfing": ("rise", [(115.2, 115.4, 113.4, 113.6)]),
    "dark_cloud_cover": ("rise", [(115.5, 115.7, 114.1, 114.3)]),
    "bearish_harami": ("rise", [(114.8, 115.0, 114.3, 114.5)]),
    "tweezer_top": ("rise", [(115.2, 115.5, 114.0, 114.4)]),
    "evening_star": (
        "rise",
        [(115, 117.1, 114.9, 117), (117.2, 117.6, 116.9, 117.3), (117.1, 117.2, 115.4, 115.5)],
    ),
    "three_black_crows": (
        "rise",
        [(115, 115.1, 113.7, 113.8), (113.9, 114.0, 112.6, 112.7), (112.8, 112.9, 111.5, 111.6)],
    ),
    "gravestone_doji": ("rise", [(115, 117, 114.95, 115.0)]),
    "bearish_marubozu": ("rise", [(115, 115.05, 112.95, 113)]),
    "doji": ("fall", [(105, 105.5, 104.5, 105.05)]),
    "long_legged_doji": ("fall", [(105, 106, 104, 105.05)]),
    "spinning_top": ("fall", [(105, 105.9, 104.1, 105.4)]),
    "inside_bar": ("fall", [(105.5, 106, 105, 105.6)]),
    "outside_bar": ("fall", [(105, 107, 104, 106)]),
    # ---- Phase 10.2 (candles_world.py). Fall context ends (106, 106.5, 104.5, 105),
    # rise context (114, 115.5, 113.5, 115); average body 1, ATR ≈ 2, "equal" = ± 0.2.
    # 5 candles: long down, gap down, two lower closes, then an up close inside the gap
    "breakaway_bull": (
        "fall",
        [
            (105, 105.2, 102.8, 103),
            (102.5, 102.7, 101.6, 101.8),
            (101.8, 102.0, 100.9, 101.1),
            (101.1, 101.3, 100.3, 100.5),
            (100.6, 102.9, 100.5, 102.8),
        ],
    ),
    "breakaway_bear": (
        "rise",
        [
            (115, 117.2, 114.8, 117),
            (117.5, 118.4, 117.3, 118.2),
            (118.2, 119.1, 118.0, 118.9),
            (118.9, 119.8, 118.7, 119.6),
            (119.5, 119.6, 117.1, 117.2),
        ],
    ),
    # four falling down candles (the last with an upper wick ≥ its body), then a close above it
    "ladder_bottom": (
        "fall",
        [
            (105, 105.2, 103.8, 104),
            (104, 104.2, 102.8, 103),
            (103, 103.2, 101.8, 102),
            (101.8, 103.0, 101.0, 101.2),
            (102.0, 103.8, 101.9, 103.5),
        ],
    ),
    # long up, gap up, three small falling candles above its middle (116), a new high
    "mat_hold": (
        "rise",
        [
            (115, 117.2, 114.8, 117),
            (117.6, 117.8, 117.2, 117.4),
            (117.4, 117.5, 116.9, 117.1),
            (117.1, 117.2, 116.6, 116.8),
            (116.9, 118.6, 116.8, 118.5),
        ],
    ),
    # long up, three small candles inside its range, then a close above its close
    "rising_three_methods": (
        "rise",
        [
            (115, 117.2, 114.8, 117),
            (116.8, 117.0, 116.2, 116.4),
            (116.4, 116.6, 115.8, 116.0),
            (116.0, 116.2, 115.4, 115.6),
            (115.7, 117.8, 115.6, 117.6),
        ],
    ),
    "falling_three_methods": (
        "fall",
        [
            (105, 105.2, 102.8, 103),
            (103.2, 103.8, 103.0, 103.6),
            (103.6, 104.2, 103.4, 104.0),
            (104.0, 104.6, 103.8, 104.4),
            (104.3, 104.4, 102.2, 102.4),
        ],
    ),
    # 4 candles: two full down candles, a gap down with a wick into the second, then a swallow
    "concealing_baby_swallow": (
        "fall",
        [
            (105, 105.0, 103.0, 103.0),
            (103.0, 103.0, 101.0, 101.0),
            (100.6, 101.4, 99.8, 100.0),
            (101.6, 101.7, 99.4, 99.5),
        ],
    ),
    "three_line_strike_bull": (
        "rise",
        [
            (115, 116.2, 114.9, 116),
            (116, 117.2, 115.9, 117),
            (117, 118.2, 116.9, 118),
            (118.1, 118.2, 114.6, 114.8),
        ],
    ),
    "three_line_strike_bear": (
        "fall",
        [
            (105, 105.1, 103.8, 104),
            (104, 104.1, 102.8, 103),
            (103, 103.1, 101.8, 102),
            (101.9, 105.4, 101.8, 105.2),
        ],
    ),
    # mother, two nested inside candles (the 2nd closes near its low), a fake break, a close above
    "hikkake_mod_bull": (
        "fall",
        [
            (105, 106.0, 103.0, 104.0),
            (104.0, 105.5, 103.5, 104.5),
            (104.5, 105.0, 104.0, 104.1),
            (104.1, 104.6, 103.6, 103.8),
            (103.9, 105.4, 103.8, 105.2),
        ],
    ),
    "hikkake_mod_bear": (
        "rise",
        [
            (115, 117.0, 114.0, 116.0),
            (116.0, 116.5, 114.5, 115.5),
            (115.5, 116.0, 115.0, 115.9),
            (115.9, 116.4, 115.4, 116.2),
            (116.1, 116.2, 114.6, 114.8),
        ],
    ),
    "hikkake_bull": (
        "fall",
        [
            (105, 106, 103, 104),
            (104, 105, 103.5, 104.5),
            (104.5, 104.8, 103.2, 103.4),
            (103.5, 105.3, 103.4, 105.2),
        ],
    ),
    "hikkake_bear": (
        "rise",
        [
            (115, 117, 114, 116),
            (116, 116.5, 114.5, 115.5),
            (115.5, 116.8, 114.8, 116.6),
            (116.5, 116.6, 114.2, 114.3),
        ],
    ),
    # 3 candles: long down, a doji alone below a gap, then a gap up past 103 + 0.3 × 2
    "abandoned_baby_bull": (
        "fall",
        [(105, 105.2, 102.8, 103), (102.0, 102.5, 101.5, 102.02), (102.8, 104.6, 102.7, 104.5)],
    ),
    "abandoned_baby_bear": (
        "rise",
        [(115, 117.2, 114.8, 117), (118.0, 118.5, 117.5, 118.02), (117.2, 117.3, 115.4, 115.5)],
    ),
    "morning_doji_star": (
        "fall",
        [(105, 105.2, 102.8, 103), (102.6, 103.0, 102.2, 102.62), (102.8, 104.4, 102.7, 104.3)],
    ),
    "evening_doji_star": (
        "rise",
        [(115, 117.2, 114.8, 117), (117.4, 117.8, 117.0, 117.42), (117.2, 117.3, 115.6, 115.7)],
    ),
    "tristar_bull": (
        "fall",
        [(105, 105.5, 104.5, 105.02), (104.3, 104.7, 103.9, 104.32), (104.8, 105.3, 104.3, 104.82)],
    ),
    "tristar_bear": (
        "rise",
        [(115, 115.5, 114.5, 115.02), (115.7, 116.1, 115.3, 115.72), (115.2, 115.7, 114.8, 115.22)],
    ),
    # three long down candles, each opening at the previous close
    "identical_three_crows": (
        "rise",
        [(115, 115.1, 112.9, 113), (113.0, 113.1, 110.9, 111), (111.0, 111.1, 108.9, 109)],
    ),
    "three_stars_in_south": (
        "fall",
        [(106, 106.2, 102.0, 104.0), (105.0, 105.2, 102.8, 103.8), (103.6, 103.6, 103.0, 103.0)],
    ),
    "unique_three_river": (
        "fall",
        [(105, 105.2, 102.8, 103), (104.4, 104.5, 102.2, 103.4), (102.9, 103.4, 102.8, 103.2)],
    ),
    "three_inside_up": (
        "fall",
        [(105, 105.2, 102.8, 103), (103.4, 104.2, 103.3, 104.0), (104.0, 105.6, 103.9, 105.4)],
    ),
    "three_inside_down": (
        "rise",
        [(115, 117.2, 114.8, 117), (116.6, 116.7, 115.7, 116.0), (116.0, 116.1, 114.4, 114.6)],
    ),
    "three_outside_up": (
        "fall",
        [(105, 105.2, 103.8, 104), (103.8, 105.6, 103.7, 105.4), (105.4, 106.4, 105.3, 106.2)],
    ),
    "three_outside_down": (
        "rise",
        [(115, 116.2, 114.9, 116), (116.2, 116.3, 114.4, 114.6), (114.6, 114.7, 113.5, 113.7)],
    ),
    "two_crows": (
        "rise",
        [(115, 117.2, 114.8, 117), (118.0, 118.3, 117.3, 117.5), (117.8, 117.9, 115.8, 116.0)],
    ),
    "upside_gap_two_crows": (
        "rise",
        [(115, 117.2, 114.8, 117), (117.8, 118.0, 117.4, 117.5), (118.2, 118.3, 117.1, 117.2)],
    ),
    # bodies 2, 1.3, 0.7 and a growing upper wick
    "advance_block": (
        "rise",
        [(115, 117.2, 114.9, 117), (116.5, 117.9, 116.4, 117.8), (117.5, 118.9, 117.4, 118.2)],
    ),
    "stalled_pattern": (
        "rise",
        [(115, 117.2, 114.9, 117), (116.9, 119.1, 116.8, 119), (119.0, 119.5, 118.9, 119.3)],
    ),
    "stick_sandwich": (
        "fall",
        [(105, 105.2, 103.8, 104), (104.2, 105.4, 104.1, 105.2), (105.4, 105.5, 103.9, 104.05)],
    ),
    # gap (116.2 → 116.5), then a down candle into the gap that stays above 116.2
    "tasuki_gap_up": (
        "rise",
        [(115, 116.2, 114.9, 116), (116.6, 117.8, 116.5, 117.6), (117.2, 117.3, 116.3, 116.4)],
    ),
    "tasuki_gap_down": (
        "fall",
        [(105, 105.1, 103.8, 104), (103.4, 103.5, 102.2, 102.4), (102.8, 103.7, 102.7, 103.6)],
    ),
    # … or a candle that closes into the first body (fills the gap)
    "gap_three_methods_up": (
        "rise",
        [(115, 116.2, 114.9, 116), (116.6, 117.8, 116.5, 117.6), (117.2, 117.3, 115.4, 115.5)],
    ),
    "gap_three_methods_down": (
        "fall",
        [(105, 105.1, 103.8, 104), (103.4, 103.5, 102.2, 102.4), (102.8, 104.7, 102.7, 104.5)],
    ),
    "side_by_side_white_up": (
        "rise",
        [(115, 116.2, 114.9, 116), (116.6, 117.5, 116.5, 117.4), (116.7, 117.6, 116.6, 117.5)],
    ),
    "side_by_side_white_down": (
        "fall",
        [(105, 105.1, 103.8, 104), (102.6, 103.5, 102.5, 103.4), (102.7, 103.6, 102.6, 103.5)],
    ),
    # 2 candles (the first may be the context's last candle)
    "two_black_gapping": ("fall", [(104.0, 104.2, 102.8, 103.0), (103.0, 103.1, 101.8, 102.0)]),
    "kicking_bull": ("fall", [(105, 105, 103, 103), (105.5, 107.5, 105.5, 107.5)]),
    "kicking_bear": ("rise", [(115, 117, 115, 117), (114.5, 114.5, 112.5, 112.5)]),
    "harami_cross_bull": ("fall", [(105, 105.2, 102.8, 103), (104.0, 104.5, 103.5, 104.02)]),
    "harami_cross_bear": ("rise", [(115, 117.2, 114.8, 117), (116.0, 116.5, 115.5, 116.02)]),
    "doji_star_bull": ("fall", [(105, 105.2, 102.8, 103), (102.5, 102.9, 102.1, 102.52)]),
    "doji_star_bear": ("rise", [(115, 117.2, 114.8, 117), (117.5, 117.9, 117.1, 117.52)]),
    "counterattack_bull": ("fall", [(105, 105.2, 102.8, 103), (101.0, 103.1, 100.9, 103.0)]),
    "counterattack_bear": ("rise", [(115, 117.2, 114.8, 117), (119.0, 119.1, 116.9, 117.0)]),
    "separating_lines_bull": ("rise", [(115, 115.1, 113.8, 114), (115.0, 117.2, 114.9, 117)]),
    "separating_lines_bear": ("fall", [(105, 106.2, 104.9, 106), (105.0, 105.1, 102.8, 103)]),
    "homing_pigeon": ("fall", [(105, 105.2, 102.8, 103), (104.5, 104.7, 103.6, 103.8)]),
    "matching_low": ("fall", [(105, 105.2, 102.8, 103), (104.0, 104.2, 102.9, 103.05)]),
    "matching_high": ("rise", [(115, 117.2, 114.8, 117), (116.0, 117.3, 115.9, 117.05)]),
    # after a long down candle (low 102.8, close 103), an up candle opening below its low …
    "in_neck": (
        "fall",
        [(105, 105.2, 102.8, 103), (102.4, 103.3, 102.3, 103.2)],
    ),  # … closing just inside
    "on_neck": (
        "fall",
        [(105, 105.2, 102.8, 103), (102.0, 102.9, 101.9, 102.8)],
    ),  # … closing at its low
    "thrusting": (
        "fall",
        [(105, 105.2, 102.8, 103), (102.4, 103.8, 102.3, 103.7)],
    ),  # … below its middle
    "above_the_stomach": ("fall", [(105, 105.2, 102.8, 103), (104.1, 105.3, 104.0, 105.2)]),
    "below_the_stomach": ("rise", [(115, 117.2, 114.8, 117), (115.9, 116.0, 114.8, 115.0)]),
    "rising_window": ("fall", [(106.8, 107.6, 106.7, 107.4)]),  # whole candle above 106.5
    "falling_window": ("fall", [(104.2, 104.3, 103.0, 103.2)]),  # whole candle below 104.5
    # 1 candle
    "takuri": ("fall", [(105.0, 105.02, 103.0, 104.98)]),  # lower wick 1.98 of 2.02
    "rickshaw_man": ("fall", [(105.0, 106.0, 104.0, 105.02)]),
    "high_wave": ("fall", [(105.0, 106.8, 103.3, 105.4)]),  # body 0.4, wicks 1.4 and 1.7
    "belt_hold_bull": ("fall", [(103.5, 105.8, 103.5, 105.5)]),
    "belt_hold_bear": ("rise", [(116.5, 116.5, 114.2, 114.5)]),
    "closing_marubozu_bull": ("fall", [(104.0, 106.0, 103.4, 106.0)]),
    "closing_marubozu_bear": ("rise", [(115.0, 115.6, 113.0, 113.0)]),
    "long_white_candle": ("fall", [(104.0, 106.2, 103.8, 106.0)]),
    "long_black_candle": ("fall", [(106.0, 106.2, 103.8, 104.0)]),
    "short_line": ("fall", [(105.0, 105.5, 104.6, 105.3)]),
}


def _flags(context: str, rows: list[Row]) -> dict[str, np.ndarray]:
    base = falling() if context == "fall" else rising()
    s = candles([*base, *rows])
    return cdl.detect(s.open, s.high, s.low, s.close)


def test_every_pattern_has_a_case() -> None:
    assert set(CASES) == set(cdl.INFO)


@pytest.mark.parametrize("key", sorted(CASES))
def test_pattern_fires_on_its_candle(key: str) -> None:
    context, rows = CASES[key]
    flags = _flags(context, rows)
    assert flags[key][-1], key
    assert not flags[key][-1 - len(rows)], f"{key} fired on the context candle"


def test_context_decides_hammer_or_hanging_man() -> None:
    shape = (104.6, 105.05, 103.0, 105.0)
    after_fall = _flags("fall", [shape])
    assert after_fall["hammer"][-1] and not after_fall["hanging_man"][-1]
    # the same shape after a rise (shifted to the rising context's prices)
    after_rise = _flags("rise", [(115.4, 115.85, 113.8, 115.8)])
    assert after_rise["hanging_man"][-1] and not after_rise["hammer"][-1]


def test_label_prefers_the_most_specific_pattern() -> None:
    # This candle is both a bullish engulfing and a tweezer bottom: engulfing wins.
    flags = _flags("fall", [(104.8, 106.6, 104.6, 106.4)])
    assert flags["tweezer_bottom"][-1]
    n = len(flags["doji"])
    [hit] = cdl.label_candles(flags, n - 1, n - 1)
    assert hit.key == "bullish_engulfing" and hit.info.bias == "bullish"


def test_every_pattern_is_ranked_once() -> None:
    assert len(cdl.PRIORITY) == len(set(cdl.PRIORITY)) == len(cdl.INFO)
    assert len(cdl.INFO) >= 90  # all 61 TA-Lib shapes plus the common extras


def test_three_line_strike_and_hikkake_are_specific() -> None:
    # A modified hikkake is also a plain hikkake; the label prefers the modified one.
    context, rows = CASES["hikkake_mod_bull"]
    flags = _flags(context, rows)
    n = len(flags["doji"])
    assert flags["hikkake_bull"][-1]
    [hit] = cdl.label_candles(flags, n - 1, n - 1)
    assert hit.key == "hikkake_mod_bull"


def test_candles_never_look_ahead() -> None:
    s = DAILY
    full = cdl.detect(s.open, s.high, s.low, s.close)
    for cut in (50, 700, len(s) - 3):
        part = cdl.detect(s.open[:cut], s.high[:cut], s.low[:cut], s.close[:cut])
        for k in full:
            assert (part[k] == full[k][:cut]).all(), (k, cut)
