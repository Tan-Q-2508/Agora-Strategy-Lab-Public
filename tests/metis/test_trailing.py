"""Trailing stops in Metis's and Kairos's hands (D-119)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.context import AppContext
from backend.metis import diagnose, trial
from backend.strategy import templates


def test_metis_can_trail_by_atr() -> None:
    d = templates.template_definition("ma_crossover", "IN", ["TCS"])
    assert d.exit.trailing_stop is None
    out = trial.with_changes(d, {"trailing_stop_atr": 3})
    assert out.exit.trailing_stop is not None
    assert (out.exit.trailing_stop.kind, out.exit.trailing_stop.value) == ("atr", 3.0)
    with pytest.raises(trial.Untestable):
        trial.with_changes(d, {"trailing_stop_atr": 20})


@dataclass
class _Base:
    definition: Any
    strategy_id: int = 4
    study: dict[str, Any] = field(
        default_factory=lambda: {"trades": 40, "win_rate": 0.55, "avg_win": 100.0, "avg_loss": 80.0}
    )


def test_the_first_look_proposes_a_trailing_stop() -> None:
    d = templates.template_definition("ma_crossover", "IN", ["TCS"])
    gave = {"exits": {"gave_back": {"ahead": 9, "measured": 20}}}
    found = {f.key: f for f in diagnose.first_look(_Base(d), review=gave, characters={})}
    t = found["trailing"]
    assert "9 of 20 losing trades were ahead" in t.text
    assert [s["changes"] for s in t.seeds] == [
        {"trailing_stop_atr": 2.5},
        {"trailing_stop_atr": 3.5},
    ]
    plain = {f.key: f for f in diagnose.first_look(_Base(d), review=None, characters={})}
    assert "no trailing stop" in plain["trailing"].text
    trailed = trial.with_changes(d, {"trailing_stop_atr": 3})
    after = {f.key for f in diagnose.first_look(_Base(trailed), review=gave, characters={})}
    assert "trailing" not in after  # already has one


def test_kairos_desks_trail_their_trades(ctx: AppContext) -> None:
    from backend.kairos import brain
    from backend.settings_store import read_all

    with ctx.db.session() as s:
        assert read_all(s)["kairos.trail_atr"] == 3.0
    d = brain.definition("IN", ["TCS"], trail_atr=3.0)
    assert d.kairos.trail_atr == 3.0
    assert brain.definition("IN", ["TCS"]).kairos.trail_atr is None


def test_kairos_tries_a_trailing_stop_when_no_filter_helps(
    client: Any, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.kairos import improve
    from backend.kairos import review as rv
    from tests.metis.test_metis import FIVE
    from tests.strategy.test_backtest_api import make_strategy, start, wait_run

    made = make_strategy(client, "donchian_breakout", "IN")
    sid = made["strategy"]["id"]
    run = start(client, strategy_version_id=made["version"]["id"], symbols=FIVE)
    assert wait_run(client, run)["status"] == "done"
    real = rv.review

    def no_filters(*a: Any, **k: Any) -> dict[str, Any]:
        out = real(*a, **k)
        out["filters"] = {"rules": [], "note": "none held up"}
        return out

    monkeypatch.setattr(rv, "review", no_filters)
    out = improve.improve(ctx, sid)
    t = out["trailing"]  # tried: the width chosen on early trades, judged on later ones
    assert t["atr"] in improve.TRAIL_WIDTHS and t["kept"] is out["changed"]
    if out["changed"]:
        assert "trailing stop" in out["headline"] and t["after"]["net"] > t["before"]["net"]
