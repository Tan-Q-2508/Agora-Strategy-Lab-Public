"""Kairos's trade judge (D-145): learns combinations, proves itself on unseen trades, and only
then may pass on a desk's entries."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.indicators.series import from_arrays
from backend.kairos import brain, judge
from tests.kairos.test_brain import load

DAY = 86_400_000


def _lessons(n: int, edge: bool, seed: int = 1) -> list[judge.Lesson]:
    """Synthetic lessons: with ``edge`` a trade wins mostly when two readings are *both* high
    (a combination no single reading shows on its own)."""
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        x = rng.normal(0, 1, len(judge.FEATURES))
        both = x[2] > 0 and x[3] > 0
        p = (0.75 if both else 0.35) if edge else 0.45
        r = 1.5 if rng.random() < p else -1.0
        out.append(judge.Lesson(ts=k * DAY, x=[float(v) for v in x], r=r))
    return out


def test_the_trees_find_a_combination() -> None:
    ls = _lessons(3000, edge=True)
    X = np.asarray([x.x for x in ls[:2000]])
    y = np.asarray([1.0 if x.won else 0.0 for x in ls[:2000]])
    m = judge.boost(X, y)
    Xt = np.asarray([x.x for x in ls[2000:]])
    yt = np.asarray([1.0 if x.won else 0.0 for x in ls[2000:]])
    a = judge.auc(m.chances(Xt), yt)
    assert a is not None and a > 0.65


def test_with_an_edge_it_switches_on_and_without_one_it_only_watches() -> None:
    on = judge.learn(_lessons(3000, edge=True), embargo_ms=10 * DAY)
    assert on is not None and on.active and on.threshold > 0
    assert on.report["exam_kept_r"] > on.report["exam_all_r"] + judge.MIN_GAIN_R
    assert "On: takes the best" in judge.words(on)
    noise = judge.learn(_lessons(3000, edge=False, seed=5), embargo_ms=10 * DAY)
    assert noise is not None and not noise.active
    assert judge.words(noise).startswith("Watching only")
    assert all(noise.take([0.0] * len(judge.FEATURES)) for _ in range(3))  # never blocks
    assert judge.learn(_lessons(100, edge=True), embargo_ms=0) is None  # too few lessons


def test_the_exam_is_after_the_study_with_a_gap() -> None:
    ls = _lessons(2000, edge=True)
    m = judge.learn(ls, embargo_ms=50 * DAY)
    assert m is not None
    r = m.report
    assert r["study"] + r["exam"] < r["lessons"]  # the gap left some out


def test_saved_and_loaded(tmp_path: Path) -> None:
    m = judge.learn(_lessons(2000, edge=True), embargo_ms=DAY)
    assert m is not None
    judge.save(tmp_path, "IN", "1d", m)
    back = judge.load(tmp_path, "IN", "1d")
    assert back is not None and back.active == m.active
    x = _lessons(1, edge=True, seed=9)[0].x
    assert math.isclose(back.chance(x), m.chance(x))
    judge.save(tmp_path, "IN", "1d", None)
    assert judge.load(tmp_path, "IN", "1d") is None


def test_missing_readings_never_break_it() -> None:
    m = judge.learn(_lessons(2000, edge=True), embargo_ms=DAY)
    assert m is not None
    x = [math.nan] * len(judge.FEATURES)
    assert 0.0 < m.chance(x) < 1.0


def test_the_study_teaches_the_judge_and_the_card_says_so(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["RELIANCE", "TCS", "INFY"])
    ctx.learning.train(Market.IN, Timeframe.D1)
    card = ctx.learning.learned(Market.IN, Timeframe.D1)["judge"]
    assert card["text"]  # on, watching, or not enough trades yet: always said plainly
    m = ctx.learning.trade_judge(Market.IN, Timeframe.D1)
    if m is not None:
        assert judge.path(ctx.paths.data_dir, "IN", "1d").exists()
        assert m.report["lessons"] >= judge.MIN_LESSONS


def test_a_desk_skips_an_entry_its_judge_rejects() -> None:
    rng = np.random.default_rng(2)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    series = from_arrays(close, high=close * 1.01, low=close * 0.99)
    b = brain.Brain.__new__(brain.Brain)
    b.passed = 0
    d = brain.Decision(55.0, {c: 0.5 for c in judge.COMPONENTS})
    ctx = SimpleNamespace(_provider=SimpleNamespace(series=series))
    b.judge_model = None
    assert not b.judge_says_no(ctx, 250, 1, d)  # type: ignore[arg-type]
    b.judge_model = SimpleNamespace(active=True, take=lambda x: False)
    assert b.judge_says_no(ctx, 250, 1, d) and b.passed == 1  # type: ignore[arg-type]
    b.judge_model = SimpleNamespace(active=False, take=lambda x: False)
    assert not b.judge_says_no(ctx, 250, 1, d)  # type: ignore[arg-type]
    reader = judge.Reader(series)
    x = reader.at(250, 1, d)
    assert len(x) == len(judge.FEATURES) and x[0] == 1.0 and x[1] == 55.0


def test_a_chart_whose_entries_lose_stands_aside_and_one_that_earns_does_not() -> None:
    """D-147, D-215: when the entries the desk would take lost clearly on unseen past trades,
    after costs, the card warns; a small or noisy loss isn't enough."""
    losing = [judge.Lesson(x.ts, x.x, x.r - 0.6) for x in _lessons(3000, edge=False)]
    m = judge.learn(losing, embargo_ms=10 * DAY)
    assert m is not None and m.stand_aside
    assert "Warning" in judge.words(m) and "keeps trading at full size" in judge.words(m)
    earning = judge.learn(_lessons(3000, edge=False), embargo_ms=10 * DAY)
    assert earning is not None and not earning.stand_aside
    # a loss inside the noise (mean about −0.01R) never stands aside
    flat = [judge.Lesson(x.ts, x.x, x.r - 0.135) for x in _lessons(3000, edge=False, seed=4)]
    f = judge.learn(flat, embargo_ms=10 * DAY)
    assert f is not None and not f.stand_aside
    back = judge.Model.from_json(m.to_json())
    assert back is not None and back.stand_aside


def test_a_desk_whose_entries_lost_still_enters() -> None:
    """D-215: losing entries never bench a desk; a judge that proved itself can still pass on
    one entry."""
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    series = from_arrays(close, high=close * 1.01, low=close * 0.99)
    b = brain.Brain.__new__(brain.Brain)
    b.passed = 0
    d = brain.Decision(55.0, {c: 0.5 for c in judge.COMPONENTS})
    ctx = SimpleNamespace(_provider=SimpleNamespace(series=series))
    b.judge_model = SimpleNamespace(active=False, stand_aside=True, take=lambda x: False)
    assert not b.judge_says_no(ctx, 250, 1, d) and b.passed == 0  # type: ignore[arg-type]
    b.judge_model = SimpleNamespace(active=True, stand_aside=True, take=lambda x: False)
    assert b.judge_says_no(ctx, 250, 1, d) and b.passed == 1  # type: ignore[arg-type]
