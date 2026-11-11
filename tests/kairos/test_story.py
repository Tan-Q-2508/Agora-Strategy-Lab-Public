"""What a trade teaches, by hand-worked cases (27.11)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.kairos.story import Path, _path, lesson_kind


def path(best: float, worst: float = -1.0, after: float | None = None) -> Path:
    return Path(best, 1, worst, 2, after)


def test_a_winner_worked() -> None:
    assert lesson_kind(2.0, 2.0, path(3.0), "target") == "worked"


def test_a_winner_sold_before_the_move_was_early() -> None:
    assert lesson_kind(0.5, 2.0, path(1.0, after=4.5), "signal") == "early"


def test_a_loss_far_past_the_stop_is_a_gap_not_a_bad_entry() -> None:
    # IOVA, 29 Oct: risk 3%, closed −41% by the stop
    assert lesson_kind(-41.0, 3.0, path(1.0), "trailing") == "gap"


def test_a_loser_that_was_well_ahead_gave_it_back() -> None:
    assert lesson_kind(-1.0, 2.0, path(2.5), "stop") == "gave_back"


def test_a_loser_that_never_went_the_right_way() -> None:
    assert lesson_kind(-2.0, 2.0, path(0.3), "stop") == "never_worked"


def test_an_ordinary_loss() -> None:
    assert lesson_kind(-2.0, 2.0, path(1.0), "stop") == "plain_loss"


def bar(ts: int, h: float, lo: float, c: float) -> SimpleNamespace:
    return SimpleNamespace(ts=ts, high=h, low=lo, close=c)


def test_best_and_worst_of_a_long_and_of_a_short() -> None:
    bars = [bar(1, 105, 99, 104), bar(2, 110, 95, 100), bar(3, 120, 100, 120)]
    p = _path(bars, 1, 100.0, 2, 100.0, "1d")
    assert (round(p.best_pct), round(p.worst_pct), p.best_ts, p.worst_ts) == (10, -5, 2, 2)
    s = _path(bars, -1, 100.0, 2, 100.0, "1d")
    assert (round(s.best_pct), round(s.worst_pct)) == (5, -10)


def test_a_candle_after_the_exit_is_never_counted_as_part_of_the_trade() -> None:
    bars = [bar(1, 101, 99, 100), bar(2, 200, 99, 199)]
    assert round(_path(bars, 1, 100.0, 1, 100.0, "1d").best_pct) == 1
