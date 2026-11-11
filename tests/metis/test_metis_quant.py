"""Metis the senior quant (METIS §11–14, D-79, D-81 to D-83): the expert's first look, the luck
check, simplify and universe ideas, price filters and the complexity limit, the sameness check,
the agenda, playbook rounds without the AI, and the daily limit on new strategies."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.core.types import Market
from backend.db.models import MetisIdea, Strategy
from backend.fakes.ai_provider import FakeAIProvider
from backend.metis import agenda, apply, brief, diagnose, library, notebook, think, trial
from backend.settings_store import update
from backend.strategy.definition import PriceOperand, VisualDefinition
from backend.strategy.templates import template_definition
from tests.strategy.test_backtest_api import Y2018, Y2026, make_strategy, start, wait_run

FIVE = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"]


def _set(ctx: AppContext, **changes: Any) -> None:
    with ctx.db.session() as s:
        update(s, {k.replace("__", "."): v for k, v in changes.items()}, ctx.clock)


def _strategy(client: TestClient, key: str = "bollinger_reversion") -> tuple[int, int]:
    created = make_strategy(client, key, "IN")
    sid, vid = created["strategy"]["id"], created["version"]["id"]
    run_id = start(client, strategy_version_id=vid, symbols=FIVE, start=Y2018, end=Y2026)
    assert wait_run(client, run_id)["status"] == "done"
    return sid, vid


# ---------------------------------------------------------------- the library


def test_the_library_holds_a_senior_quants_curriculum() -> None:
    secs = library.sections()
    assert len(secs) >= 100
    titles = [s.title for s in secs]
    assert len(titles) == len(set(titles))
    assert all(80 <= len(s.body) <= 2600 for s in secs)
    for question, expected in (
        ("deflated sharpe ratio multiple testing", "The deflated Sharpe ratio"),
        ("hierarchical risk parity", "Hierarchical risk parity"),
        ("time series momentum trend following", "Time-series momentum and trend following"),
        ("losers cluster in falling markets", "Losers cluster in falling markets"),
        ("kelly criterion fractional kelly", "Kelly and fractional Kelly"),
        ("post earnings announcement drift", "Post-earnings announcement drift"),
    ):
        assert expected in [s.title for s in library.search(question, k=3)], question


# ---------------------------------------------------------------- the expert's first look


def _baseline(d: Any, **study: Any) -> Any:
    base = {
        "trades": 60,
        "wins": 24,
        "win_rate": 0.4,
        "net": 1000.0,
        "gross": 5000.0,
        "charges": 2000.0,
        "avg_win": 300.0,
        "avg_loss": 250.0,
        "profit_factor": 1.1,
        "exits": {"stop": 40, "signal": 20},
    }
    base.update(study)
    return SimpleNamespace(definition=d, strategy_id=7, study=base)


def test_first_look_finds_what_an_expert_would() -> None:
    d = template_definition("bollinger_reversion", "IN")
    review = {
        "conditions": [{"key": "natr", "edges": [1.2, 2.8]}],
        "failure_reasons": [
            {"key": "natr", "third": "high", "text": "9 of 12 lost in wild markets."}
        ],
    }
    chars = {
        "RELIANCE": {"label": "trending"},
        "INFY": {"label": "mean-reverting"},
        "TCS": {"label": "close to random"},
        "HDFCBANK": {"label": "mean-reverting"},
    }
    daily = np.random.default_rng(1).normal(0.0005, 0.01, 400)
    found = diagnose.first_look(_baseline(d), review=review, characters=chars, daily=daily)
    keys = [f.key for f in found]
    # win rate 40% against a break-even of 250 / 550 = 45%: below break-even
    assert "below_break_even" in keys and "costs" in keys and "losers_cluster" in keys
    assert "tight_stops" in keys and "misfit" in keys and keys[0] == "confidence"
    seeds = {s["title"]: s for f in found for s in f.seeds}
    trend = seeds["Only buy above the 200-day average"]
    assert trend["conditions"] == [diagnose.TREND_FILTER] and trend["origin"] == "playbook"
    assert seeds["Trade only when the trend is strong"]["conditions"][0]["indicator"] == "adx"
    natr = next(
        s for s in seeds.values() if s["conditions"] and s["conditions"][0]["indicator"] == "natr"
    )
    assert natr["conditions"][0]["op"] == "at_most" and natr["conditions"][0]["value"] == 2.8
    assert seeds["Give trades more room"]["changes"] == {"stop_loss_pct": 9.0}  # 6% × 1.5
    assert seeds["Drop the trending stocks"]["drop"] == ["RELIANCE"]
    # every seed is a valid idea for Metis
    assert all(think.clean_idea(s) is not None for s in seeds.values())


def test_a_healthy_strategy_gets_few_findings() -> None:
    d = template_definition("ma_crossover", "IN")
    good = _baseline(d, win_rate=0.5, gross=8000.0, charges=500.0, exits={"signal": 60})
    found = diagnose.first_look(good, review=None, characters={})
    # only the standing advice to protect gains with a trailing stop (D-119)
    assert [f.key for f in found] == ["trailing"]


# ---------------------------------------------------------------- new idea shapes


def _bollinger() -> VisualDefinition:
    d = template_definition("bollinger_reversion", "IN")
    assert isinstance(d, VisualDefinition)
    return d


def test_price_filters_simplify_and_the_complexity_limit() -> None:
    d = _bollinger()
    idea = think.clean_idea(
        {"kind": "filter", "strategy_id": 1, "title": "t", "conditions": [diagnose.TREND_FILTER]}
    )
    assert idea is not None and idea["conditions"][0]["price"] == "close"
    out = trial.with_filter(d, idea)
    added = out.entry.long.conditions[-1]  # type: ignore[union-attr]
    assert isinstance(added.right, PriceOperand) and added.op == "below"
    many = d
    for k in range(5):
        cond = {"indicator": "rsi", "params": {"period": 14.0 + k}, "op": "below", "value": 50.0}
        many = trial.with_filter(many, {**idea, "conditions": [cond]})
    with pytest.raises(trial.Untestable, match="Too many rules"):
        trial.with_filter(many, idea)
    simpler = trial.with_simplify(many, {"remove": 2, "side": "long"})
    assert len(diagnose.entry_parts(simpler, "long")) == len(diagnose.entry_parts(many, "long")) - 1
    with pytest.raises(trial.Untestable, match="only one"):
        trial.with_simplify(d, {"remove": 1, "side": "long"})
    with pytest.raises(trial.Untestable, match="no rule number 9"):
        trial.with_simplify(many, {"remove": 9, "side": "long"})


def test_the_luck_check_and_simplify_verdicts_by_hand() -> None:
    def p(trades: int, net: float) -> dict[str, Any]:
        return {"trades": trades, "net": net, "win_rate": 0.5, "profit_factor": 1.5}

    base = {"study": p(40, 1000.0), "exam": p(20, 500.0)}
    better = {"study": p(40, 1100.0), "exam": p(20, 900.0)}
    lucky = {"dsr": 0.31, "tries": 25, "days": 600}
    held, _v, checks = trial.judge_change(base, better, 100_000, Market.IN)
    assert held and len(checks) == 3
    held, verdict, checks = trial.judge_change(base, better, 100_000, Market.IN, lucky)
    assert not held and len(checks) == 4 and "Luck check: 31% chance" in verdict
    real = {"dsr": 0.77, "tries": 25, "days": 600}
    assert trial.judge_change(base, better, 100_000, Market.IN, real)[0]
    # simplify: exam at least as good, study at least 95% (1000 − 50 = 950)
    assert trial.judge_simplify(base, {"study": p(40, 950.0), "exam": p(20, 500.0)}, Market.IN)[0]
    assert not trial.judge_simplify(base, {"study": p(40, 949.0), "exam": p(20, 500.0)}, Market.IN)[
        0
    ]
    assert not trial.judge_simplify(base, {"study": p(40, 990.0), "exam": p(20, 499.0)}, Market.IN)[
        0
    ]
    # the luck of a series of daily differences, counted over the tries
    rng = np.random.default_rng(5)
    edge = rng.normal(0.0008, 0.004, 600)
    assert trial.luck(edge, 1)["dsr"] > trial.luck(edge, 200)["dsr"]
    assert trial.luck(edge[:10], 1) is None


# ---------------------------------------------------------------- rounds


def _change_ideas(sid: int) -> str:
    return json.dumps(
        {
            "noticed": "Too many rules for a dip-buyer.",
            "ideas": [
                {
                    "kind": "filter",
                    "strategy_id": sid,
                    "title": "Trend filter",
                    "why": "Dip-buying works best in up-trends.",
                    "conditions": [diagnose.TREND_FILTER],
                    "side": "long",
                },
                {
                    "kind": "universe",
                    "strategy_id": sid,
                    "title": "Fewer stocks",
                    "why": "RELIANCE trends.",
                    "drop": ["RELIANCE"],
                },
            ],
        }
    )


def test_an_improve_round_with_the_new_ideas(client: TestClient, ctx: AppContext) -> None:
    sid, _vid = _strategy(client)
    _set(ctx, metis__apply=False)
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    ai.queue_tools({"text": _change_ideas(sid)})
    out = ctx.services["metis"].round("user")
    assert out["status"] == "done" and out["direction"] == "improve", out
    r = notebook.get_round(ctx, out["round_id"])
    assert r is not None and r["direction"] == "improve"
    assert "A senior quant's first look" in r["brief"] and "From your library" in r["brief"]
    assert "Buy when: (1)" in r["brief"] or "Buy when:" in r["brief"]
    ideas = {i["title"]: i for i in notebook.ideas(ctx)}
    assert (
        ideas["Trend filter"]["status"] in ("held_up", "rejected")
        and ideas["Trend filter"]["origin"] == "ai"
    )
    uni = ideas["Fewer stocks"]
    assert uni["status"] in ("held_up", "rejected")
    assert "RELIANCE" not in uni["result"]["symbols"] and len(uni["result"]["symbols"]) == 4
    luck = ideas["Trend filter"]["result"]["luck"]
    assert luck is None or (0 <= luck["dsr"] <= 1 and luck["tries"] >= 1)
    assert notebook.tries(ctx, strategy_id=sid) == sum(
        1 for i in ideas.values() if i["status"] in notebook.TESTED
    )


def test_without_the_ai_metis_works_from_its_playbook(client: TestClient, ctx: AppContext) -> None:
    _strategy(client)
    _set(ctx, ai__enabled=False, metis__apply=False)
    m = ctx.services["metis"]
    assert m.ai_ready()[0] is False
    out = m.round("user")
    assert out["status"] == "done", out
    r = notebook.get_round(ctx, out["round_id"])
    assert (
        r is not None and r["model"] == "playbook" and "Working from the playbook" in r["noticed"]
    )
    assert "Playbook round" in r["note"]
    ideas = notebook.ideas(ctx, round_id=out["round_id"])
    assert ideas and all(i["origin"] == "playbook" for i in ideas)
    status = m.status()
    assert status["ai_ready"] is False and status["ai_note"]


def test_discovering_starts_from_the_textbook(client: TestClient, ctx: AppContext) -> None:
    _set(ctx, ai__enabled=False, metis__apply=True, markets=["IN"])
    assert agenda.choose(ctx).direction == "discover"  # no strategies yet
    seeds = agenda.discover_seeds(ctx, ["IN"])
    assert [s["template"] for s in seeds] == ["ma_crossover", "rsi_mean_reversion"]
    out = ctx.services["metis"].round("user")
    assert out["direction"] == "discover"
    ideas = notebook.ideas(ctx, round_id=out["round_id"])
    assert {i["rules"]["template"] for i in ideas} == {"ma_crossover", "rsi_mean_reversion"}
    # a template the user already has is never proposed again as "new"
    make_strategy(client, "bollinger_reversion", "IN")
    keys = [s["template"] for s in agenda.discover_seeds(ctx, ["IN"], limit=30)]
    assert "bollinger_reversion" not in keys and "ma_crossover" not in keys


def test_a_new_strategy_that_already_exists_is_judged_as_a_revision(
    client: TestClient, ctx: AppContext
) -> None:
    sid, vid = _strategy(client, "bollinger_reversion")
    idea = think.clean_idea(
        {
            "kind": "new_strategy",
            "title": "Bands",
            "why": "x",
            "market": "IN",
            "template": "bollinger_reversion",
        }
    )
    assert idea is not None
    fp = trial.fingerprint_of(idea, {})
    out = trial.try_new(ctx, idea, fp, provider=None, model="", num_ctx=4096, markets=["IN"])
    assert out.verdict.startswith("Not a new strategy: it is a version of")
    assert out.strategy_id == sid and out.version_id == vid
    assert out.status == "rejected" and "nothing new to keep" in out.verdict


def test_the_agenda_rules(client: TestClient, ctx: AppContext) -> None:
    sid, vid = _strategy(client)
    assert agenda.choose(ctx, f"look into #{sid}").direction == "improve"
    # a running paper session makes it "in use" and earns it a round
    session = client.post(
        "/api/paper/sessions", json={"strategy_version_id": vid, "account": {"market": "IN"}}
    ).json()
    assert agenda.in_use(ctx) == [sid]
    assert agenda.choose(ctx).direction == "improve_live"
    client.post(f"/api/paper/sessions/{session['session_id']}/stop")
    # the Thompson draw is repeatable for a round number
    first = agenda.choose(ctx, round_no=11).direction
    assert all(agenda.choose(ctx, round_no=11).direction == first for _ in range(3))


def test_metis_adds_few_new_strategies_on_its_own(client: TestClient, ctx: AppContext) -> None:
    sid, _vid = _strategy(client)  # downloads practice prices for five stocks …
    client.delete(f"/api/strategies/{sid}")  # … and leaves no strategy to improve
    _set(ctx, ai__enabled=False, metis__apply=False, metis__new_per_day=0, markets=["IN"])
    out = ctx.services["metis"].round("user")
    ideas = [
        i for i in notebook.ideas(ctx, round_id=out["round_id"]) if i["status"] != "untestable"
    ]
    assert ideas, notebook.ideas(ctx, round_id=out["round_id"])
    for i in ideas:  # pretend they held up
        with ctx.db.session() as s:
            row = s.get(MetisIdea, i["id"])
            assert row is not None
            row.status = "held_up"
    first = ideas[0]
    with pytest.raises(Exception, match="already added 0 new"):
        apply.save(ctx, first["id"], auto=True)
    saved = apply.save(ctx, first["id"])  # by hand, the daily limit doesn't apply
    assert saved["status"] == "saved" and saved["saved_as"] == "new_strategy"
    with ctx.db.session() as s:
        row = s.get(Strategy, saved["saved_strategy_id"])
        assert row is not None and row.name.startswith("Metis · ")


def test_the_brief_for_discovery_lists_what_the_user_has(
    client: TestClient, ctx: AppContext
) -> None:
    sid, _vid = _strategy(client, "ma_crossover")
    b = brief.build(ctx, "", ["IN"], direction="discover")
    assert "don't propose these again" in b.text and f"#{sid}" in b.text
    assert "discover NEW strategies" in b.text


def test_the_library_endpoint(client: TestClient) -> None:
    body = client.get("/api/metis/library").json()
    assert body["total"] >= 100 and body["areas"][0]["title"] == "The research method"
    assert sum(len(a["sections"]) for a in body["areas"]) == body["total"]
