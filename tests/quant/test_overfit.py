"""The probability of backtest overfitting (CSCV, D-89), worked by hand."""

from __future__ import annotations

import numpy as np
import pytest

from backend.quant import overfit


def blocks(*cols: list[float], size: int = 5) -> np.ndarray:
    """A T × N matrix whose rows repeat each block's value ``size`` times."""
    return np.array([[v for v in col for _ in range(size)] for col in cols]).T


def test_the_in_sample_winner_always_ends_last() -> None:
    # Blocks 1–4. A = [4, 2, 0, 0], B = [0, 0, 1, 5], C = [1.1] × 4, by mean return. The six
    # halves (in-sample mean → winner; out-of-sample means → its rank of 3):
    #   {1,2}: A 3, B 0, C 1.1 → A; {3,4}: A 0, B 3, C 1.1 → A last
    #   {3,4}: B 3 → B;             {1,2}: B 0 → last
    #   {1,3}: A 2, B .5, C 1.1 → A; {2,4}: A 1, B 2.5, C 1.1 → A last
    #   {1,4}: A 2, B 2.5 → B;       {2,3}: A 1, B .5, C 1.1 → B last
    #   {2,3}: A 1, B .5, C 1.1 → C; {1,4}: A 2, B 2.5 → C last
    #   {2,4}: A 1, B 2.5 → B;       {1,3}: A 2, B .5 → B last
    # Every ω = 1/4 ≤ ½, so PBO = 6/6 = 1, and the winner always lost relative to the others.
    m = blocks([4, 2, 0, 0], [0, 0, 1, 5], [1.1] * 4)
    r = overfit.pbo(m, s=4, metric="mean")
    assert r["combinations"] == 6 and r["blocks"] == 4 and r["tries"] == 3
    assert r["pbo"] == 1.0
    assert r["median_logit"] == pytest.approx(np.log(0.25 / 0.75), abs=1e-4)
    assert r["oos_loss"] == 0.0  # it lost to the others, not money


def test_a_try_that_wins_everywhere_is_not_overfit() -> None:
    m = blocks([3, 2, 4, 3], [1, 1, 1, 1], [0, 2, -1, 1])
    r = overfit.pbo(m, s=4, metric="mean")
    # A wins every half and ranks first (3 of 3) on the other half: ω = 3/4 > ½.
    assert r["pbo"] == 0.0
    assert r["median_logit"] == pytest.approx(np.log(0.75 / 0.25), abs=1e-4)


def test_ties_share_their_rank() -> None:
    # Two identical tries tie everywhere: the winner's shared rank is 1.5 of 2, so
    # ω = 1.5 / 3 = ½ and the logit is 0, which counts as overfit (ω ≤ ½): picking between
    # identical tries shows no skill.
    m = blocks([1, 2, 3, 4], [1, 2, 3, 4])
    assert overfit.pbo(m, s=4, metric="mean")["pbo"] == 1.0


def test_pure_noise_is_a_coin_toss() -> None:
    """One noise table's PBO varies a lot; on average over tables it is about ½."""
    values = []
    for seed in range(8):
        r = overfit.pbo(np.random.default_rng(seed).normal(0, 0.01, (800, 20)))
        assert r["combinations"] == 12_870 and r["blocks"] == 16
        values.append(r["pbo"])
    assert 0.4 < float(np.mean(values)) < 0.65


def test_real_skill_shows_low_pbo() -> None:
    rng = np.random.default_rng(3)
    m = rng.normal(0, 0.01, (800, 10))
    m[:, 4] += 0.004  # one try with a real edge
    r = overfit.pbo(m)
    assert r["pbo"] < 0.1 and r["oos_loss"] < 0.05


def test_short_histories_use_fewer_blocks_or_give_up() -> None:
    rng = np.random.default_rng(1)
    assert overfit.pbo(rng.normal(0, 1, (40, 5)))["blocks"] == 10
    assert overfit.pbo(rng.normal(0, 1, (3, 5)))["pbo"] is None
    assert overfit.pbo(rng.normal(0, 1, (300, 1)))["pbo"] is None


def test_aligned_keeps_common_days() -> None:
    days, m = overfit.aligned(
        [[("d1", 0.1), ("d2", 0.2), ("d3", 0.3)], [("d2", 1.0), ("d3", 2.0), ("d4", 3.0)]]
    )
    assert days == ["d2", "d3"] and m.tolist() == [[0.2, 1.0], [0.3, 2.0]]


def test_words() -> None:
    assert "classic overfitting" in overfit.words(
        {"pbo": 0.9, "tries": 12, "blocks": 16}, "settings"
    )
    assert "worked well" in overfit.words({"pbo": 0.05, "tries": 12, "blocks": 16})
    assert overfit.words({"pbo": None}).startswith("Too few")
