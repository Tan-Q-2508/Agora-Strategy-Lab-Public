"""Every chart pattern on a hand-drawn price path, plus the breakout/target/failure rules."""

from __future__ import annotations

import pytest

from backend.analysis import chart_patterns as cp
from backend.analysis.report import Analysis
from backend.analysis.swings import find_swings, reversal_size
from backend.core.types import Market
from tests.analysis.helpers import path

SHAPES: dict[str, tuple[list[tuple[int, float]], str]] = {
    "double_top": ([(0, 100), (15, 120), (25, 110), (35, 120), (50, 95)], "target"),
    "double_bottom": ([(0, 120), (15, 100), (25, 110), (35, 100), (50, 125)], "target"),
    "triple_top": (
        [(0, 95), (12, 120), (20, 108), (28, 120), (36, 112), (44, 120), (58, 95)],
        "target",
    ),
    "triple_bottom": (
        [(0, 125), (12, 100), (20, 112), (28, 100), (36, 108), (44, 100), (58, 125)],
        "target",
    ),
    "head_shoulders": (
        [(0, 100), (10, 115), (18, 108), (28, 125), (36, 108), (44, 115), (60, 90)],
        "target",
    ),
    "inverse_head_shoulders": (
        [(0, 125), (10, 110), (18, 117), (28, 100), (36, 117), (44, 110), (60, 135)],
        "target",
    ),
    "ascending_triangle": (
        [
            (0, 90),
            (10, 120),
            (18, 105),
            (26, 120),
            (32, 110),
            (38, 120),
            (42, 114),
            (46, 121),
            (55, 135),
        ],
        "confirmed",
    ),
    "descending_triangle": (
        [
            (0, 130),
            (10, 100),
            (18, 115),
            (26, 100),
            (32, 110),
            (38, 100),
            (42, 106),
            (46, 99),
            (55, 85),
        ],
        "confirmed",
    ),
    "symmetrical_triangle": (
        [(0, 90), (10, 130), (18, 100), (26, 124), (32, 106), (38, 119), (42, 110), (52, 135)],
        "confirmed",
    ),
    "rising_wedge": (
        [(0, 90), (8, 120), (14, 104), (22, 126), (28, 113), (36, 130), (40, 121), (52, 100)],
        "target",
    ),
    "falling_wedge": (
        [(0, 130), (8, 100), (14, 118), (22, 95), (28, 108), (36, 91), (40, 99), (50, 120)],
        "confirmed",
    ),
    "rectangle": (
        [(0, 90), (10, 120), (18, 105), (26, 120), (32, 105), (38, 120), (44, 105), (56, 130)],
        "confirmed",
    ),
    "bull_flag": ([(0, 100), (5, 100), (13, 125), (22, 120), (23, 121), (30, 140)], "confirmed"),
    "bear_flag": ([(0, 130), (5, 130), (13, 105), (22, 110), (30, 90)], "confirmed"),
    "cup_handle": (
        [
            (0, 100),
            (5, 130),
            (15, 112),
            (25, 104),
            (35, 112),
            (45, 130),
            (50, 124),
            (53, 126),
            (60, 145),
        ],
        "confirmed",
    ),
}


@pytest.mark.parametrize("key", sorted(SHAPES))
def test_each_pattern_is_recognised(key: str) -> None:
    pts, status = SHAPES[key]
    found = Analysis(path(pts), Market.US, "X").patterns()
    assert found, key
    assert (found[0].key, found[0].status) == (key, status)
    p = found[0]
    want = cp.NAMES[key][1]
    if want != "neutral":
        assert p.bias == want
    # the target is the pattern's height projected from the breakout
    assert abs(p.target - p.trigger) == pytest.approx(p.height, rel=1e-3)


def test_double_top_breakout_and_target_hand_calculated() -> None:
    # Neckline = the dip's low 109.5; the higher top 120.5 → height 11 → target 98.5.
    # Falling from 120 (candle 35) to 95 (candle 50): close = 120 − (5/3)(k − 35).
    # Breakout needs a close below 109.5 − 0.1 × ATR (~0.24): first at k = 42.
    # Target: the low (close − 0.5) reaches 98.5 when close ≤ 99 → k = 48.
    p = Analysis(path(SHAPES["double_top"][0]), Market.US, "X").patterns()[0]
    assert p.trigger == pytest.approx(109.5)
    assert p.target == pytest.approx(98.5)
    assert p.stop == pytest.approx(120.5)
    assert (p.event, p.resolved) == (42, 48)


def test_forming_pattern_shows_where_it_would_break() -> None:
    # A double bottom whose bounce hasn't broken the neckline yet.
    s = path([(0, 120), (15, 100), (25, 110), (35, 100), (40, 106)])
    p = Analysis(s, Market.US, "X").patterns()[0]
    assert p.key == "double_bottom" and p.status == "forming"
    assert p.trigger == pytest.approx(110.5)


def test_failed_pattern() -> None:
    # A double bottom that breaks out, then collapses through its lows.
    s = path([(0, 120), (15, 100), (25, 110), (35, 100), (45, 114), (60, 92)])
    found = Analysis(s, Market.US, "X").patterns()
    p = next(x for x in found if x.key == "double_bottom")
    assert p.status == "failed" and p.direction == 1


def test_a_straight_line_has_no_patterns() -> None:
    assert Analysis(path([(0, 100), (120, 160)]), Market.US, "X").patterns() == []


def test_patterns_are_found_only_from_the_past() -> None:
    """Swing-based shapes use confirmed swings; the shape found on a truncated history is
    the same shape, with the same trigger, as on the full history."""
    pts, _ = SHAPES["head_shoulders"]
    full = path(pts)
    cut = 47  # after the right shoulder is confirmed (46), before the breakout (49)
    part = full.upto(cut)
    sw = find_swings(part.high, part.low, part.close)
    atr = reversal_size(part.high, part.low, part.close)
    found = cp.from_swings(list(sw.swings), part.close, float(atr[-1]), cut - 1)
    hs = next(p for p in found if p.key == "head_shoulders")
    tracked = cp.track(hs, part.high, part.low, part.close, None, cut - 1)
    assert tracked.status == "forming"
    whole = Analysis(full, Market.US, "X").patterns()[0]
    assert whole.key == "head_shoulders" and whole.trigger == pytest.approx(
        tracked.trigger, abs=0.6
    )


def test_select_keeps_one_reading_per_stretch() -> None:
    a = cp.ChartPattern(
        key="double_top",
        points=(),
        upper=None,
        lower=None,
        allowed=frozenset({-1}),
        height=1,
        stop_up=0,
        stop_down=0,
        start=0,
        end=20,
        formed=20,
        confidence=0.9,
        atr=1,
        status="failed",
    )
    b = cp.ChartPattern(
        key="ascending_triangle",
        points=(),
        upper=None,
        lower=None,
        allowed=frozenset({1}),
        height=1,
        stop_up=0,
        stop_down=0,
        start=2,
        end=22,
        formed=22,
        confidence=0.6,
        atr=1,
        status="confirmed",
    )
    assert [p.key for p in cp.select([a, b])] == ["ascending_triangle"]
