"""Every setup on hand-built candles, plus the no-look-ahead rule."""

from __future__ import annotations

import numpy as np
import pytest

from backend.analysis import setups as st
from backend.indicators import vector as vx
from backend.indicators.series import from_arrays
from tests.golden.test_indicators import DAILY

Row = tuple[float, float, float, float, float]  # open, high, low, close, volume


def flat(n: int = 25, price: float = 100.0) -> list[Row]:
    return [(price, price + 1, price - 1, price, 1000.0)] * n


def flags(rows: list[Row]) -> dict[str, np.ndarray]:
    o, h, lo, c, v = (np.array(col, dtype=np.float64) for col in zip(*rows, strict=True))
    return st.detect(o, h, lo, c, v)


CASES: dict[str, list[Row]] = {
    # whole candle above yesterday's high 101, close above the 20-candle high, 2× volume
    "breakaway_gap_up": [*flat(), (103, 104, 102.5, 103.8, 2000)],
    "breakaway_gap_down": [*flat(), (97, 97.5, 96, 96.2, 2000)],
    # gap up over 101, two candles stranded above, then a gap down below their low 102.5
    "island_top": [
        *flat(),
        (103, 104, 102.5, 103.5, 1000),
        (103.5, 104.5, 103, 104, 1000),
        (101.8, 102, 100.5, 100.8, 1000),
    ],
    "island_bottom": [
        *flat(),
        (97, 97.5, 96, 96.5, 1000),
        (96.5, 97, 95.5, 96, 1000),
        (98.2, 99.5, 98, 99.2, 1000),
    ],
    # ranges 2, then the week's narrowest (0.5), then a close beyond it
    "nr7_up": [*flat(10), (100, 100.3, 99.8, 100.1, 1000), (100.2, 101, 100.1, 100.8, 1000)],
    "nr7_down": [*flat(10), (100, 100.3, 99.8, 100.1, 1000), (100, 100.1, 99, 99.4, 1000)],
    # a mother candle 98–102, an inside candle, then a close above (below) the mother
    "inside_break_up": [
        *flat(5),
        (100, 102, 98, 101, 1000),
        (101, 101.5, 99, 100.5, 1000),
        (100.6, 102.6, 100.4, 102.4, 1000),
    ],
    "inside_break_down": [
        *flat(5),
        (100, 102, 98, 99, 1000),
        (99, 101, 98.5, 99.5, 1000),
        (99.4, 99.6, 97.4, 97.6, 1000),
    ],
    # the 20-candle low 98.5 was set 10 candles ago; today dips to 98 and closes 99.5
    "spring": [*flat(14), (100, 101, 98.5, 100, 1000), *flat(9), (99.5, 100, 98, 99.5, 1000)],
    "upthrust": [*flat(14), (100, 101.5, 99, 100, 1000), *flat(9), (100.5, 102, 100, 100.5, 1000)],
    # a new 10-candle low (high), then a close past yesterday's close in the top (bottom) half
    "key_reversal_up": [*flat(12), (100, 100.5, 98.5, 99, 1000), (99, 100.6, 98, 100.4, 1000)],
    "key_reversal_down": [*flat(12), (100, 101.5, 99.5, 101, 1000), (101, 102, 99.4, 99.6, 1000)],
    # down days on 1,000, up days on 800; then an up day on 1,200 above its 10-day average
    "pocket_pivot": [
        *[
            (
                100 + k * 0.1,
                101 + k * 0.1,
                99 + k * 0.1,
                100 + k * 0.1 + (0.3 if k % 2 else -0.3),
                800.0 if k % 2 else 1000.0,
            )
            for k in range(14)
        ],
        (101.5, 103, 101.4, 102.8, 1200),
    ],
    # a year of 99–101, then a close of 102 above the 52-week high
    "new_high_52w": [*flat(260), (101, 102.5, 100.8, 102, 1000)],
    "new_low_52w": [*flat(260), (99, 99.2, 97.5, 98, 1000)],
    # a quiet coil (closes 100 / 100.1, ATR ≈ 2 → bands far inside the Keltner Channel)
    "squeeze_up": [
        *[(100, 101, 99, 100 + 0.1 * (k % 2), 1000.0) for k in range(40)],
        (100.1, 101.6, 100, 101.5, 1000),
    ],
    "squeeze_down": [
        *[(100, 101, 99, 100 + 0.1 * (k % 2), 1000.0) for k in range(40)],
        (100, 100.1, 98.4, 98.5, 1000),
    ],
}


def test_every_setup_has_a_case_or_a_relation_test() -> None:
    assert set(CASES) | {"golden_cross", "death_cross"} == set(st.INFO)


@pytest.mark.parametrize("key", sorted(CASES))
def test_setup_fires_on_its_candle(key: str) -> None:
    f = flags(CASES[key])
    assert f[key][-1], key
    assert not f[key][:-1].any(), f"{key} fired early at {np.flatnonzero(f[key][:-1])}"


def test_breakaway_gap_needs_volume() -> None:
    rows = [*flat(), (103, 104, 102.5, 103.8, 1100)]
    assert not flags(rows)["breakaway_gap_up"][-1]


def test_spring_needs_an_old_low() -> None:
    # the low was set 2 candles ago: a running fall, not a false break
    rows = [*flat(22), (100, 101, 98.5, 100, 1000), *flat(1), (99.5, 100, 98, 99.5, 1000)]
    assert not flags(rows)["spring"][-1]


def test_new_highs_are_one_event_a_month() -> None:
    rows = [*flat(260)] + [(100 + k, 102 + k, 100 + k, 101.5 + k, 1000.0) for k in range(10)]
    f = flags(rows)["new_high_52w"]
    assert f.sum() == 1 and f[260]


def test_golden_and_death_crosses_follow_the_averages() -> None:
    c = DAILY.close
    f = st.detect(DAILY.open, DAILY.high, DAILY.low, c, DAILY.volume)
    d = vx.sma(c, 50) - vx.sma(c, 200)
    up = np.flatnonzero((d[1:] > 0) & (d[:-1] <= 0)) + 1
    down = np.flatnonzero((d[1:] < 0) & (d[:-1] >= 0)) + 1
    assert list(np.flatnonzero(f["golden_cross"])) == list(up)
    assert list(np.flatnonzero(f["death_cross"])) == list(down)
    assert len(up) and len(down)


def test_setups_never_look_ahead() -> None:
    s = DAILY
    full = st.detect(s.open, s.high, s.low, s.close, s.volume)
    for cut in (60, 700, len(s) - 3):
        part = st.detect(s.open[:cut], s.high[:cut], s.low[:cut], s.close[:cut], s.volume[:cut])
        for k in full:
            assert (part[k] == full[k][:cut]).all(), (k, cut)


def test_without_volume_gaps_still_count_and_pivots_do_not() -> None:
    rows = [(r[0], r[1], r[2], r[3], 0.0) for r in CASES["breakaway_gap_up"]]
    f = flags(rows)
    assert f["breakaway_gap_up"][-1] and not f["pocket_pivot"].any()
    series = from_arrays([1.0, 2.0])
    assert st.detect(series.open, series.high, series.low, series.close, series.volume)
