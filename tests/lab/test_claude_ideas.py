"""Claude's ideas through Metis's tests (D-160)."""

from __future__ import annotations

from typing import Any

from backend.context import AppContext
from backend.lab import families
from backend.metis import claude, notebook


def test_claudes_new_strategy_goes_through_metis_verdict_once(stocked: AppContext) -> None:
    d = families.BY_KEY["sma_cross"].definition("IN", "1d")
    idea = claude.normal(
        {
            "kind": "new_strategy",
            "title": "20/100 crossover",
            "why": "Time-series momentum.",
            "market": "IN",
            "timeframe": "1d",
            "definition": d,
        }
    )
    out = claude.run(stocked, [idea], "test")
    assert out["tried"] == 1, out["lines"]
    rnd = notebook.get_round(stocked, out["round_id"])
    assert rnd is not None and rnd["model"] == "claude" and rnd["status"] == "done"
    [i] = notebook.ideas(stocked, round_id=out["round_id"])
    assert i["status"] in ("held_up", "saved", "rejected") and i["verdict"]
    assert i["result"]["study_line"].startswith("Study years")
    again = claude.run(stocked, [idea], "test")
    assert again["tried"] == 0 and again["skipped"] == 1  # never counted twice


def test_an_unknown_kind_is_refused() -> None:
    import pytest

    with pytest.raises(ValueError):
        claude.normal({"kind": "guess"})


def test_ideas_rejected_on_luck_alone_are_judged_again_once_per_return_series(
    stocked: AppContext, monkeypatch: object
) -> None:
    """D-163: past new strategies that failed only the luck check are judged again on their
    saved exam returns; copies with the same returns count once; names get their real chart."""
    import json

    import numpy as np

    from backend.metis import overfit
    from backend.settings_store import update

    with stocked.db.session() as s:
        update(s, {"metis.apply": False}, stocked.clock)
    monkeypatch.setattr(overfit, "effective_tries", lambda _c, _m, n: 1)  # type: ignore[attr-defined]
    rng = np.random.default_rng(1)
    days = [f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}" for k in range(300)]
    daily = {"days": days, "r": [float(x) for x in rng.normal(0.002, 0.01, 300)]}
    res = {
        "split": 1704067200000,  # 2024-01-01
        "daily": daily,
        "checks": [
            {"ok": True, "text": "Exam years: made money"},
            {"ok": False, "text": "Luck check: 1% chance it beats the best of 1400 lucky tries"},
        ],
    }
    rid = notebook.start_round(stocked, "auto", "", "m", "discover")
    spec = json.dumps({"definition": {"timeframe": "1d"}})
    ids = [
        notebook.add_idea(
            stocked,
            rid,
            kind="new_strategy",
            title=t,
            market_code="IN",
            fingerprint=t,
            status="rejected",
            spec=spec,
            result=json.dumps(res),
        )
        for t in ("India Hourly ADX Trend", "India 1h ADX Trend copy")
    ]
    lines = claude.rejudge(stocked)
    assert len([x for x in lines if x.startswith("held_up")]) == 1
    [first] = notebook.ideas(stocked, round_id=rid, limit=10)[-1:]
    got = {i["id"]: i for i in notebook.ideas(stocked, round_id=rid, limit=10)}
    assert got[ids[0]]["status"] == "held_up" and got[ids[0]]["title"] == "India ADX Trend (daily)"
    assert got[ids[1]]["status"] == "rejected"  # the same returns: judged once
    assert first is not None


def test_a_ranking_idea_gets_the_markets_most_traded_stocks(stocked: AppContext) -> None:
    """Every ranking idea came back "no stocks are chosen" until it was given stocks to rank."""
    d = families.BY_KEY["ranking_momentum_6m"].definition("IN", "1d")
    idea = claude.normal(
        {
            "kind": "new_strategy",
            "title": "Momentum",
            "market": "IN",
            "timeframe": "1d",
            "definition": d,
        }
    )
    out = claude.run(stocked, [idea], "test")
    [i] = notebook.ideas(stocked, round_id=out["round_id"])
    assert i["status"] != "untestable", i["verdict"]
    assert len(i["result"]["symbols"]) > 8  # all of the market's most traded, not eight


def test_results_print_rupees_to_a_windows_file(monkeypatch: Any) -> None:
    """A batch's results went to a log file in cp1252 and the ₹ in a verdict crashed the print
    after every idea was tested (2026-11-05)."""
    import io
    import sys

    from backend.metis import claude

    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    claude.utf8_output()
    print("made −₹70,767 after costs")
    sys.stdout.flush()
    assert "₹70,767" in raw.getvalue().decode("utf-8")
