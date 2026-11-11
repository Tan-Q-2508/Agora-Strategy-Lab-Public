"""Kairos chooses its own exits from its record (D-140)."""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import select

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.db.models import KairosSignalStat
from backend.kairos import brain, exits
from backend.kairos.exits import ExitPlan
from backend.strategy.compiler import compile_definition
from tests.kairos.test_brain import load

PLAIN = ExitPlan(2.0, 2.0, None, None)


def bars(rows: list[tuple[float, float, float, float]]) -> tuple[np.ndarray, ...]:
    o, h, lo, c = (np.array(col, dtype=np.float64) for col in zip(*rows, strict=True))
    return o, h, lo, c


def play(rows: list[tuple[float, float, float, float]], plan: ExitPlan, side: int = 1) -> float:
    o, h, lo, c = bars(rows)
    # signal on candle 0; stop 2%, target 4% of the 100 entry (risk 2), ATR 1
    r = exits.play(o, h, lo, c, 0, side, 2.0, 4.0, 1.0, plan, max_bars=5)
    assert r is not None
    return r


SIGNAL = (100.0, 100.0, 100.0, 100.0)


def test_stop_target_and_time_by_hand() -> None:
    assert play([SIGNAL, (100, 101, 97, 98)], PLAIN) == pytest.approx(-1.0)  # stop at 98
    assert play([SIGNAL, (100, 105, 99, 104)], PLAIN) == pytest.approx(2.0)  # target at 104
    # stop and target in one candle: the stop first (as the engine does)
    assert play([SIGNAL, (100, 105, 97, 104)], PLAIN) == pytest.approx(-1.0)
    # a gap through the stop fills at the open
    assert play([SIGNAL, (100, 101, 99.5, 100), (96, 97, 95, 96)], PLAIN) == pytest.approx(-2.0)
    # out at the close after max_bars (5 candles): +1 → +0.5R
    flat = [SIGNAL] + [(100, 101.5, 99, 101)] * 5
    assert play(flat, PLAIN) == pytest.approx(0.5)


def test_partial_sale_moves_the_stop_to_the_entry() -> None:
    plan = ExitPlan(2.0, 2.0, None, 1.0)
    # half sold at 102 (1R), then the rest stopped at the entry: +0.5R
    rows = [SIGNAL, (100, 102.5, 99, 102), (102, 102, 99.5, 100)]
    assert play(rows, plan) == pytest.approx(0.5)


def test_trailing_stop_follows_the_best_price() -> None:
    plan = ExitPlan(2.0, 4.0, 1.5, None)  # target 8 away (not reached); trail 1.5 ATR
    rows = [SIGNAL, (100, 103, 99, 103), (103, 103.2, 101, 101)]
    # after candle 1 the peak is 103, the trail 101.5: candle 2 trades down to 101 → out at 101.5
    o, h, lo, c = bars(rows)
    r = exits.play(o, h, lo, c, 0, 1, 2.0, 8.0, 1.0, plan, max_bars=5)
    assert r == pytest.approx(0.75)


def test_shorts_are_mirrored() -> None:
    assert play([SIGNAL, (100, 103, 99, 102)], PLAIN, side=-1) == pytest.approx(-1.0)
    assert play([SIGNAL, (100, 101, 95, 96)], PLAIN, side=-1) == pytest.approx(2.0)


def test_plan_keys_round_trip() -> None:
    for p in [*exits.PLANS, ExitPlan(2.0, 2.5, 3.0, 1.0), PLAIN]:
        assert exits.plan_from_key(p.key) == p
    assert "trailing stop 3 ATR" in ExitPlan(2.0, 2.5, 3.0, 1.0).words()


def _rows(
    plan: ExitPlan, study: tuple[int, float], exam: tuple[int, float]
) -> dict[str, tuple[float, float]]:
    return {
        f"exit:study:{plan.key}": (float(study[0]), study[0] * study[1]),
        f"exit:exam:{plan.key}": (float(exam[0]), exam[0] * exam[1]),
    }


def test_the_choice_needs_the_exam_years_too() -> None:
    default = ExitPlan(2.0, 2.5, 3.0, 1.0)
    better = ExitPlan(1.5, 3.5, 2.0, None)
    lucky = ExitPlan(3.0, 2.0, None, None)
    rows = _rows(default, (200, 0.10), (80, 0.05))
    rows |= _rows(better, (200, 0.20), (80, 0.12))
    rows |= _rows(lucky, (200, 0.50), (80, 0.01))  # great in the study, worse in the exam
    ch = exits.choose(rows, {}, default)
    assert ch["plan"] == better and ch["chosen"] and "chosen from its record" in ch["why"]
    # too little history: the settings stay
    few = exits.choose(_rows(better, (20, 0.5), (10, 0.5)), {}, default)
    assert few["plan"] == default and not few["chosen"]
    # paper trades count: 60 losing paper trades for the better plan tip it back
    paper = {better.key: (60.0, -60.0)}
    assert exits.choose(rows, paper, default)["plan"] != better


def test_the_brain_trades_with_the_chosen_exits() -> None:
    b = compile_definition(brain.definition("US", ["AAPL"], trail_atr=3.0, partial_r=1.0)).brain
    assert b is not None and b.trail_atr == 3.0 and b.scale is not None
    b.use_exits({"plan": ExitPlan(1.5, 3.5, None, None), "why": "test"})
    assert (b.stop_atr, b.target_r, b.trail_atr, b.scale) == (1.5, 3.5, None, None)
    assert "no trailing" in b.exit_words


def test_the_study_measures_every_plan_and_the_desk_card_shows_the_choice(
    ctx: AppContext,
) -> None:
    load(ctx, Market.IN, ["RELIANCE", "TCS"])
    ctx.learning.train(Market.IN, Timeframe.D1)
    with ctx.db.session() as s:
        keys = set(
            s.scalars(select(KairosSignalStat.signal).where(KairosSignalStat.signal.like("exit:%")))
        )
    default = ctx.learning.default_exits()
    assert f"exit:study:{default.key}" in keys and f"exit:exam:{default.key}" in keys
    assert len(keys) >= len(exits.PLANS)  # every plan was played out
    assert not any(k.startswith("exit:") for k in ctx.learning.weights(Market.IN, Timeframe.D1))
    card = ctx.learning.learned(Market.IN, Timeframe.D1)["exits"]
    assert card is not None and card["plan"] and card["why"]
    # a closed paper trade under every plan
    before = ctx.learning.version
    ctx.learning.record_exits(Market.IN, Timeframe.D1, {default.key: 1.5, PLAIN.key: -1.0})
    assert ctx.learning.version > before
    ch = ctx.learning.exit_plan(Market.IN, Timeframe.D1)
    assert isinstance(ch["plan"], ExitPlan)
