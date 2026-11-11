"""Metis's tries checked for overfitting (D-89): every tested idea keeps its daily returns,
and after enough tries a change is kept only if picking the best of them isn't a coin toss."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.core.types import Market
from backend.db.models import MetisIdea
from backend.fakes.ai_provider import FakeAIProvider
from backend.metis import notebook, trial
from backend.metis import overfit as mo
from tests.metis.test_metis import _ideas, _p, _strategy

DAYS = [(date(2022, 1, 3) + timedelta(days=k)).isoformat() for k in range(400)]


def _daily(r: np.ndarray) -> dict[str, list[Any]]:
    return {"days": DAYS[: len(r)], "r": [float(x) for x in r]}


def _add_tries(ctx: AppContext, sid: int, vid: int, table: np.ndarray) -> None:
    """Tested ideas on one strategy: column 0 is the version they were tested against."""
    rnd = notebook.start_round(ctx, "user", "", "fake")
    for k in range(1, table.shape[1]):
        notebook.add_idea(
            ctx,
            rnd,
            kind="tweak",
            title=f"try {k}",
            market_code="IN",
            strategy_id=sid,
            strategy_version_id=vid,
            spec="{}",
            fingerprint=f"fp-{sid}-{k}",
            status="rejected",
            result=json.dumps({"daily": _daily(table[:, k]), "base_daily": _daily(table[:, 0])}),
        )


def test_the_rule_waits_for_enough_tries() -> None:
    assert mo.check({"pbo": 0.9, "tries": 7}) == []
    assert mo.check({"pbo": None, "tries": 30}) == []
    bad = mo.check({"pbo": 0.62, "tries": 10})
    assert len(bad) == 1 and bad[0]["ok"] is False and "62%" in bad[0]["text"]
    assert mo.check({"pbo": 0.3, "tries": 10})[0]["ok"] is True


def test_a_failed_overfitting_check_rejects_a_good_change() -> None:
    base = {"study": _p(40, 1000.0), "exam": _p(20, 500.0)}
    better = {"study": _p(40, 2000.0), "exam": _p(20, 5000.0)}
    held, verdict, checks = trial.judge_change(
        base, better, 100_000, Market.IN, None, mo.check({"pbo": 0.7, "tries": 12})
    )
    assert not held and verdict.startswith("Didn't hold up. Overfitting check")
    assert len(checks) == 4
    assert trial.judge_change(
        base, better, 100_000, Market.IN, None, mo.check({"pbo": 0.2, "tries": 12})
    )[0]


def test_tries_are_lined_up_by_day(client: TestClient, ctx: AppContext) -> None:
    sid, vid = _strategy(client)
    rng = np.random.default_rng(9)
    table = rng.normal(0, 0.01, (400, 10))
    _add_tries(ctx, sid, vid, table)
    got = mo.collect(ctx, strategy_id=sid)
    assert got["tries"] == 10 and got["days"] == 400 and got["pbo"] is not None
    assert got["text"].startswith("Probability of backtest overfitting: ")
    # the one being judged joins them; its baseline isn't counted twice
    more = mo.collect(
        ctx,
        strategy_id=sid,
        extra=[_daily(rng.normal(0, 0.01, 400))],
        extra_base=(vid, _daily(table[:, 0])),
    )
    assert more["tries"] == 11
    # a strategy with no tries has nothing to check
    assert mo.collect(ctx, strategy_id=sid + 999)["pbo"] is None
    # the daily returns stay out of what screens get
    with ctx.db.session() as s:
        row = s.query(MetisIdea).first()
        assert row is not None
        public = notebook.idea_public(row)
    assert "daily" not in public["result"] and "base_daily" not in public["result"]


def test_a_round_keeps_each_ideas_daily_returns(client: TestClient, ctx: AppContext) -> None:
    sid, _vid = _strategy(client)
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    ai.queue_tools({"text": _ideas(sid)})
    out = ctx.services["metis"].round("user")
    assert out["status"] == "done", out
    with ctx.db.session() as s:
        rows = [r for r in s.query(MetisIdea).all() if r.status != "untestable"]
    assert rows
    for r in rows:
        res = json.loads(r.result)
        assert len(res["daily"]["days"]) == len(res["daily"]["r"]) > 200
        assert "overfit" in res and res["overfit"]["text"]
        if r.kind != "new_strategy":
            assert len(res["base_daily"]["r"]) > 200


def test_correlated_tries_count_as_few_and_independent_ones_as_many() -> None:
    """D-162: the luck check deflates by the effective number of independent tries."""
    import numpy as np

    from backend.metis import overfit as mo

    rng = np.random.default_rng(5)
    days = [f"d{k:04d}" for k in range(400)]
    base = [rng.normal(0, 0.01, 400) for _ in range(3)]
    clones = [
        dict(zip(days, base[k % 3] + rng.normal(0, 0.0005, 400), strict=True)) for k in range(60)
    ]
    assert mo.effective_n(clones) <= 5  # 60 near-copies of 3 strategies
    apart = [dict(zip(days, rng.normal(0, 0.01, 400), strict=True)) for _ in range(60)]
    assert mo.effective_n(apart) >= 40  # 60 unrelated ones
