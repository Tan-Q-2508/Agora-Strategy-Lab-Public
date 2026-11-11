"""The Phase 10.3 chart patterns: harmonics, AB=CD, three drives, rounding top, channels.

Ratio tests use exact turning points (``Swing`` objects) so each Fibonacci rule is pinned
by hand; path tests draw the shape candle by candle and check the full analyst finds it
and follows it to its target.
"""

from __future__ import annotations

import pytest

from backend.analysis import chart_patterns as cp
from backend.analysis import chart_patterns_world as cw
from backend.analysis.report import Analysis
from backend.analysis.swings import Swing
from backend.core.types import Market
from tests.analysis.helpers import path

ATR = 1.0


def zig(prices: list[float], first: str = "L", step: int = 10) -> list[Swing]:
    """Alternating swings ``step`` candles apart, each confirmed 3 candles later."""
    kinds = ("L", "H") if first == "L" else ("H", "L")
    return [
        Swing(k * step, p, kinds[k % 2], k * step + 3)  # type: ignore[arg-type]
        for k, p in enumerate(prices)
    ]


# X, A, B, C, D for bullish shapes (X a low); bearish shapes mirror them around 200.
# Each comment gives B/XA, C/AB, D (of XA, or of XC), CD/BC.
XABCD: dict[str, list[float]] = {
    # B 18.54/30 = .618, C 11.46/18.54 = .618, D 23.58/30 = .786, CD 16.5/11.46 = 1.44
    "gartley": [100, 130, 111.46, 122.92, 106.42],
    # B 13.5/30 = .45, C 10.8/13.5 = .8, D 26.58/30 = .886, CD 23.88/10.8 = 2.21
    "bat": [100, 130, 116.5, 127.3, 103.42],
    # B 10.5/30 = .35, C 9.3/10.5 = .886, D 33.9/30 = 1.13, CD 32.7/9.3 = 3.52
    "alt_bat": [100, 130, 119.5, 128.8, 96.1],
    # B 23.58/30 = .786, C 11.79/23.58 = .5, D 42/30 = 1.4, CD 30.21/11.79 = 2.56
    "butterfly": [100, 130, 106.42, 118.21, 88.0],
    # B 12.5/25 = .5, C 11.1/12.5 = .888, D 40.45/25 = 1.618, CD 39.05/11.1 = 3.52
    "crab": [100, 125, 112.5, 123.6, 84.55],
    # B 22.15/25 = .886, C 10/22.15 = .45, D 40.45/25 = 1.618, CD 33/10 = 3.3
    "deep_crab": [100, 125, 102.85, 112.85, 84.55],
    # B 10/20 = .5, C beyond A: XC 27/20 = 1.35, D 21.22/27 = .786 of XC
    "cypher": [100, 120, 110, 127, 105.78],
}


def mirror(ps: list[float]) -> list[float]:
    return [200 - p for p in ps]


@pytest.mark.parametrize("name", sorted(XABCD))
def test_harmonic_ratios(name: str) -> None:
    bull = cw.harmonic(zig(XABCD[name], "L"), ATR, 60)
    assert bull is not None and bull.key == f"{name}_bull", name
    bear = cw.harmonic(zig(mirror(XABCD[name]), "H"), ATR, 60)
    assert bear is not None and bear.key == f"{name}_bear", name
    assert [p.label for p in bull.points] == ["X", "A", "B", "C", "D"]


def test_shark() -> None:
    # Bearish: X 130, A 110 (XA 20), B 122 (.6), C 106.2 beyond A (BC 15.8 = 1.32 × AB 12),
    # XC 23.8, D 132.38 → CD 26.18 = 1.1 × XC, and 26.18 / 15.8 = 1.66 × BC
    p = cw.harmonic(zig([130, 110, 122, 106.2, 132.38], "H"), ATR, 60)
    assert p is not None and p.key == "shark_bear"


def test_gartley_trade_levels_hand_calculated() -> None:
    # D 106.42; CD 16.5 → confirm 1 ATR or 23.6% of CD (3.894) above D = 110.314;
    # fail 1 ATR below D = 105.42; target 61.8% of AD (23.58) above D = 120.99244
    p = cw.harmonic(zig(XABCD["gartley"], "L"), ATR, 60)
    assert p is not None and p.upper is not None and p.lower is not None
    assert p.upper.price == pytest.approx(110.314)
    assert p.lower.price == pytest.approx(105.42)
    assert p.height == pytest.approx(120.99244 - 110.314)
    assert p.allowed == frozenset({1})


def test_near_misses_are_not_harmonics() -> None:
    # a Gartley whose D stops at 70% instead of 78.6%
    assert cw.harmonic(zig([100, 130, 111.46, 122.92, 109.0], "L"), ATR, 60) is None
    # legs too small for the volatility (XA 30 < 3 ATR of 12)
    assert cw.harmonic(zig(XABCD["gartley"], "L"), 12.0, 60) is None


def test_abcd() -> None:
    # AB 20, BC 12.36 (.618), CD 20 (= AB) → bullish; D beyond B
    p = cw.abcd(zig([130, 110, 122.36, 102.36], "H"), ATR, 40)
    assert p is not None and p.key == "abcd_bull"
    # 1.618 extension: CD 32.36
    assert cw.abcd(zig([130, 110, 122.36, 90.0], "H"), ATR, 40) is not None
    # CD 1.45 × AB fits none of 1, 1.272, 1.618
    assert cw.abcd(zig([130, 110, 122.36, 93.36], "H"), ATR, 40) is None
    # bearish mirror
    p = cw.abcd(zig([70, 90, 77.64, 97.64], "L"), ATR, 40)
    assert p is not None and p.key == "abcd_bear"


def test_three_drives() -> None:
    # drives down: 130 → 115 (15), back 9.27 (.618), push 11.79 (1.272 × 9.27) to 112.48,
    # back 8.25 (.7), push 10.5 (1.272 × 8.25) to 110.23 → a bottom; target the last high
    ps = [130, 115, 124.27, 112.48, 120.73, 110.23]
    p = cw.three_drives(zig(ps, "H"), ATR, 70)
    assert p is not None and p.key == "three_drives_bull"
    assert [q.label for q in p.points][::2] == ["Drive 1", "Drive 2", "Drive 3"]
    top = cw.three_drives(zig(mirror(ps), "L"), ATR, 70)
    assert top is not None and top.key == "three_drives_bear"
    # pushes that don't extend (1.0×) aren't drives
    assert cw.three_drives(zig([130, 115, 124.27, 115.0, 120.73, 116.0], "H"), ATR, 70) is None


PATHS: dict[str, tuple[list[tuple[int, float]], str]] = {
    # the XABCD prices above, drawn with 0.5 wicks (ratios move slightly but stay in range)
    "gartley_bull": (
        [(0, 112), (8, 100), (20, 130), (28, 111.46), (34, 122.92), (42, 106.42), (55, 125)],
        "target",
    ),
    "bat_bear": (
        [(0, 118), (8, 130), (20, 100), (28, 113.5), (36, 102.7), (46, 126.58), (60, 108)],
        "target",
    ),
    "cypher_bull": (
        [(0, 108), (8, 100), (18, 120), (24, 110), (32, 127), (44, 105.78), (58, 125)],
        "target",
    ),
    "rounding_top": (
        [
            (0, 108),
            (6, 100),
            (14, 112),
            (22, 119),
            (30, 122),
            (38, 119),
            (46, 112),
            (54, 100),
            (58, 104),
            (70, 90),
        ],
        "confirmed",
    ),
    "ascending_channel": (
        [
            (0, 100),
            (6, 110),
            (12, 106),
            (18, 116),
            (24, 112),
            (30, 122),
            (36, 118),
            (42, 128),
            (60, 105),
        ],
        "target",
    ),
}


@pytest.mark.parametrize("key", sorted(PATHS))
def test_found_on_a_drawn_chart(key: str) -> None:
    pts, status = PATHS[key]
    found = Analysis(path(pts), Market.US, "X").patterns()
    assert found, key
    p = next((x for x in found if x.key == key), None)
    assert p is not None, [x.key for x in found]
    assert p.status == status
    assert abs(p.target - p.trigger) == pytest.approx(p.height, rel=1e-3)


def test_every_new_pattern_has_a_name_rank_and_explanation() -> None:
    for key in cw.NAMES:
        assert key in cp.NAMES and key in cp.RANK
        assert cw.explain(key)
