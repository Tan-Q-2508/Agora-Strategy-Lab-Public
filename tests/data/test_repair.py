"""Half-adjusted candles around a split (D-228), on hand-worked series."""

from __future__ import annotations

from backend.data.repair import find


def fixed(closes: list[float], factors: list[float]) -> list[float]:
    out = list(closes)
    for f in find(closes, factors):
        out[f.index] *= f.multiply
    return [round(x, 4) for x in out]


def test_amtd_rows_divided_twice_are_put_back() -> None:
    # before a 60-for-1 reverse split: 0.77 is right, 0.0126 was over-corrected; after it, 28.5
    closes = [0.0126, 0.0128, 0.767, 0.73, 0.0123, 0.0119, 0.726, 0.011, 0.585, 28.5]
    factors = [60.0] * 9 + [1.0]
    assert fixed(closes, factors) == [0.756, 0.768, 0.767, 0.73, 0.738, 0.714, 0.726, 0.66, 0.585, 28.5]


def test_a_clean_series_is_left_alone() -> None:
    assert find([10, 11, 10.5, 9.9, 300, 310], [30, 30, 30, 30, 1, 1]) == []


def test_a_small_split_is_never_touched() -> None:
    # a real halving looks like a 2-for-1, so 2-for-1s are left out
    assert find([10, 5, 10, 5, 22, 21], [2, 2, 2, 2, 1, 1]) == []


def test_when_nothing_lands_on_the_next_price_it_is_left_for_a_person() -> None:
    assert find([1.0, 0.03, 1.0, 90000.0], [30.0, 30.0, 30.0, 1.0]) == []


def test_a_forward_split_works_the_same_way() -> None:
    # 1-for-10 forward split: factor 0.1, adjusted = raw × 0.1; the true raw is 100
    closes = [100.0, 1000.0, 99.0, 10.1]
    factors = [0.1, 0.1, 0.1, 1.0]
    assert fixed(closes, factors) == [100.0, 100.0, 99.0, 10.1]
