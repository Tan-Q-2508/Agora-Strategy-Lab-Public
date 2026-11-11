"""Kairos tries Metis's strategies on paper, by its own judgement (D-139)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.context import AppContext
from backend.db.models import MetisIdea, MetisRound, Strategy
from backend.kairos import trials
from backend.strategy import service as strategies
from backend.strategy.templates import template_definition

DAY = trials.DAY_MS


def rec(**kw: Any) -> dict[str, Any]:
    base = {"state": "running", "trades": 0, "net": 0.0, "pf": 0.0, "open": 0}
    return base | {"equity": 20_000.0, "capital": 20_000.0} | kw


def test_verdicts_by_hand() -> None:
    assert trials.verdict(rec(equity=17_900.0), DAY) == "stop"  # down 10.5%: stop at once
    assert trials.verdict(rec(trades=8, net=50.0, pf=1.5), 5 * DAY) is None  # too early
    assert trials.verdict(rec(trades=20, net=300.0, pf=1.3), 5 * DAY) == "works"
    assert trials.verdict(rec(trades=20, net=40.0, pf=1.05), 5 * DAY) == "retire"  # thin edge
    assert trials.verdict(rec(trades=3, net=90.0, pf=3.0), 31 * DAY) == "retire"  # too few
    assert trials.verdict(rec(trades=12, net=-10.0, pf=0.9), 31 * DAY) == "retire"


def _metis_strategy(ctx: AppContext, name: str, pf: float, trades: int) -> int:
    d = template_definition("rsi_mean_reversion", "US", ["AAPL", "MSFT"])
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row, version = strategies.create(
            s, name=name, description="", definition=d, now=now, created_by="metis", note=""
        )
        rnd = MetisRound(started_at=now, status="done")
        s.add(rnd)
        s.flush()
        result = {"candidate": {"exam": {"profit_factor": pf, "trades": trades}}}
        s.add(
            MetisIdea(
                round_id=rnd.id,
                created_at=now,
                kind="new_strategy",
                title=name,
                market_code="US",
                fingerprint=f"fp-{name}",
                status="saved",
                result=json.dumps(result),
                saved_strategy_id=row.id,
                saved_version_id=version.id,
            )
        )
        s.commit()
        return int(row.id)


def test_candidates_are_metis_strategies_best_exam_first(ctx: AppContext) -> None:
    weak = _metis_strategy(ctx, "Weak", 1.15, 40)
    strong = _metis_strategy(ctx, "Strong", 1.6, 30)
    gone = _metis_strategy(ctx, "Archived", 2.0, 50)
    with ctx.db.session() as s:
        row = s.get(Strategy, gone)
        assert row is not None
        row.archived_at = ctx.clock.now_ms()
        s.commit()
    got = [c["strategy_id"] for c in trials.candidates(ctx, "US")]
    assert got == [strong, weak] and trials.candidates(ctx, "IN") == []


def test_kairos_passes_on_a_thin_exam_without_testing_it(ctx: AppContext) -> None:
    c = {"strategy_id": 1, "version_id": 1, "name": "x", "exam_pf": 1.15, "exam_trades": 75}
    ok, why = trials.kairos_view(ctx, c)
    assert not ok and "below Kairos's bar" in why


def test_a_monthly_ranking_is_judged_on_its_own_trade_count(ctx: AppContext) -> None:
    """D-171: a monthly ranking makes few trades by design; 15 strong ones aren't thin."""
    c = {"strategy_id": 1, "version_id": 999, "name": "x", "exam_pf": 12.0, "exam_trades": 15}
    ok, why = trials.kairos_view(ctx, c)
    assert not ok and "20+ trades" in why  # an ordinary strategy: too few
    ok, why = trials.kairos_view(ctx, {**c, "kind": "ranking"})
    assert "below Kairos's bar" not in why  # a ranking: past the bar, on to the re-test
    ok, why = trials.kairos_view(ctx, {**c, "kind": "ranking", "exam_trades": 8})
    assert not ok and "12+ trades" in why


def _patched(ctx: AppContext, monkeypatch: pytest.MonkeyPatch, views: dict[int, bool]) -> list[int]:
    cands = [
        {
            "strategy_id": i,
            "version_id": 100 + i,
            "name": f"S{i}",
            "exam_pf": 2.0,
            "exam_trades": 50,
        }
        for i in (1, 2, 3, 4, 5)
    ]
    started: list[int] = []
    monkeypatch.setattr(trials, "candidates", lambda ctx, m: cands)
    monkeypatch.setattr(trials, "kairos_view", lambda ctx, c: (views[c["strategy_id"]], "test"))

    def start(req: Any) -> int:
        started.append(req.strategy_version_id)
        return 1000 + len(started)

    monkeypatch.setattr(ctx.paper, "start_session", start)
    return started


def test_no_compulsion_and_a_ceiling_not_a_quota(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _patched(ctx, monkeypatch, {1: False, 2: True, 3: False, 4: True, 5: True})
    monkeypatch.setattr(trials, "record", lambda ctx, sid: rec())
    state: dict[str, Any] = {}
    out = trials.run(ctx, "US", state)
    # it passed on 1 and 3, and stopped at the ceiling of 3 (the default setting)
    assert started == [102, 104, 105] and out["trials"] == 3
    assert state["trial_views"]["1"]["ok"] is False
    trials.run(ctx, "US", state)  # the next round: nothing new while the three are on trial
    assert len(started) == 3


def test_none_believed_none_tried(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    started = _patched(ctx, monkeypatch, dict.fromkeys(range(1, 6), False))
    assert trials.run(ctx, "US", {})["trials"] == 0 and started == []


def test_trials_are_judged_kept_or_retired(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _patched(ctx, monkeypatch, dict.fromkeys(range(1, 6), True))
    records = {1001: rec(trades=20, net=500.0, pf=1.4), 1002: rec(trades=20, net=-50.0, pf=0.9)}
    records[1003] = rec(equity=17_000.0, open=2)
    monkeypatch.setattr(trials, "record", lambda ctx, sid: records.get(sid, rec()))
    stopped: list[int] = []
    monkeypatch.setattr(trials, "_stop", lambda ctx, t, msg: stopped.append(t["session_id"]))
    state: dict[str, Any] = {}
    trials.run(ctx, "US", state)
    assert started == [101, 102, 103]
    out = trials.run(ctx, "US", state)
    book = state["trials"]
    assert book["1"]["status"] == "proven"  # works live: keeps running
    assert book["2"]["status"] == "retired" and book["3"]["status"] == "retired"
    assert sorted(stopped) == [1002, 1003]  # 3 stopped at once on its 10% loss
    # their places go to the next ones Kairos believes in
    assert started[3:] == [104, 105] and out["trials"] == 2


def test_too_new_to_re_test_is_not_held_against_it(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.checks.forward as forward

    sid = _metis_strategy(ctx, "Fresh", 1.6, 40)
    c = next(x for x in trials.candidates(ctx, "US") if x["strategy_id"] == sid)

    def short(*a: Any, **k: Any) -> Any:
        raise ValueError("That period is too short for daily candles.")

    monkeypatch.setattr(forward, "_forward_run", short)
    ok, why = trials.kairos_view(ctx, c)
    assert ok and "too recently" in why
    ctx.clock.advance(40 * DAY)  # type: ignore[attr-defined]
    ok, why = trials.kairos_view(ctx, c)
    assert not ok and "couldn't re-test" in why
