"""Metis and Kairos with partial exits (D-125) and the beat-the-index bar (D-126)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.types import Market
from backend.engine.types import EquityPoint
from backend.metis import diagnose, trial
from backend.strategy import templates


def test_metis_can_scale_out() -> None:
    d = templates.template_definition("ma_crossover", "IN", ["TCS"])
    with pytest.raises(trial.Untestable, match="stop-loss"):
        trial.with_changes(d, {"partial_half_r": 1})
    out = trial.with_changes(d, {"stop_loss_pct": 5, "partial_thirds_r": 1})
    assert out.exit.scale_out is not None
    assert [(s.value, s.sell_pct) for s in out.exit.scale_out.steps] == [(1.0, 33.0), (2.0, 33.0)]


@dataclass
class _Base:
    definition: Any
    strategy_id: int = 4
    study: dict[str, Any] = field(default_factory=dict)


def test_the_first_look_proposes_partials_only_with_a_symptom() -> None:
    d = templates.template_definition("ma_crossover", "IN", ["TCS"])
    weak = {"trades": 40, "win_rate": 0.4, "avg_win": 150.0, "avg_loss": 80.0}
    found = {
        f.key: f for f in diagnose.first_look(_Base(d, study=weak), review=None, characters={})
    }
    seeds = [s["changes"] for s in found["partials"].seeds]
    assert seeds[0] == {"stop_loss_pct": 6.0, "partial_half_r": 1.0}  # adds the stop it needs
    healthy = {"trades": 40, "win_rate": 0.6, "avg_win": 100.0, "avg_loss": 80.0}
    keys = {f.key for f in diagnose.first_look(_Base(d, study=healthy), review=None, characters={})}
    assert "partials" not in keys


def _out(equity: list[float], bench: list[float]) -> Any:
    ts = list(range(len(equity)))
    return SimpleNamespace(
        equity=[EquityPoint(t, e, e, 0.0) for t, e in zip(ts, equity, strict=True)],
        benchmark=list(zip(ts, bench, strict=False)),
    )


def test_a_new_strategy_must_beat_the_index() -> None:
    # split at 1: the exam years are points 1 onward
    lost = trial.against_index(_out([100, 100, 104], [100, 100, 110]), 1, Market.IN)
    assert not lost["ok"] and "Nifty 50" in lost["text"] and "+4.0%" in lost["text"]
    won = trial.against_index(_out([100, 100, 115], [100, 100, 110]), 1, Market.IN)
    assert won["ok"]
    none = trial.against_index(_out([100, 100, 115], []), 1, Market.US)
    assert none["ok"]  # no index prices: never rejects on its own


def test_kairos_desks_book_half_at_1r() -> None:
    from backend.kairos import brain
    from backend.settings_store import SETTINGS

    assert SETTINGS["kairos.partial_r"].default == 1.0
    d = brain.definition("IN", ["TCS"], partial_r=1.0)
    assert d.kairos.partial_r == 1.0
    assert brain.definition("IN", ["TCS"]).kairos.partial_r is None
