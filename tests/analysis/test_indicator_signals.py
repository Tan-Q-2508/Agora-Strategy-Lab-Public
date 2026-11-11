"""Every indicator's signal, classic strategy entries and quant signals (D-138)."""

from __future__ import annotations

import time

import numpy as np

from backend.analysis import indicator_signals as ind
from backend.analysis import signals as sig
from backend.kairos import brain, learning
from tests.analysis.helpers import path
from tests.golden.test_indicators import DAILY, INTRA

INTRADAY_ONLY = {"strategy:vwap", "strategy:opening_range"}


def test_crossing_by_hand() -> None:
    a = np.array([1.0, 2.0, 3.0, 2.0, 1.0, np.nan, 3.0])
    assert list(ind._up(a, 2.0)) == [2]  # 2 → 3 crosses; nan never counts
    assert list(ind._down(a, 2.0)) == [4]
    assert list(ind._up(a, np.array([0, 0, 0, 5, 0, 0, 0.0]))) == [4]


def test_turtle_breakout_by_hand() -> None:
    # flat at 100 (highs 100.5) for 30 candles, then a close of 102 on candle 31
    s = path([(0, 100.0), (30, 100.0), (31, 102.0)])
    up, down = ind._turtle(s)
    assert list(up) == [31] and list(down) == []


def test_every_signal_fires_on_real_prices() -> None:
    daily = {k for k, _, _ in ind.detect(DAILY)}
    intra = {k for k, _, _ in ind.detect(INTRA)}
    for key in ind.RULES:
        seen = intra if key in INTRADAY_ONLY else daily
        assert f"{key}:up" in seen and f"{key}:down" in seen, key
    assert not any(k.startswith(tuple(INTRADAY_ONLY)) for k in daily)  # no VWAP on daily


def test_the_brain_and_its_learning_know_every_new_signal() -> None:
    for key, (label, d) in ind.INFO.items():
        family = key.split(":", 1)[0]
        assert sig.LABELS[key] == label and learning.direction_of(key) == d
        assert family in brain.BUCKET and family in sig.WINDOW
        assert family in learning.FAMILY_WORDS and learning.label_of(key) == label


def test_signals_stay_fast_enough_for_live_desks() -> None:
    t0 = time.perf_counter()
    ind.detect(DAILY)
    assert time.perf_counter() - t0 < 2.0  # ten years of candles, every rule
