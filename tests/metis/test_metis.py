"""Metis, Kairos's AI researcher (docs/METIS.md, D-76, D-77), tested offline with the fake AI."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.backtest.run import RunOutput
from backend.context import AppContext
from backend.core.types import Market
from backend.db.models import KairosMemory, MetisIdea
from backend.fakes.ai_provider import FakeAIProvider
from backend.kairos import router
from backend.kairos.tools.base import ThreadState
from backend.metis import apply, brief, notebook, think, trial
from backend.metis.brief import part
from backend.settings_store import read_all, update
from backend.strategy.templates import template_definition
from tests.data.helpers import wait_job
from tests.strategy.test_backtest_api import Y2018, Y2026, make_strategy, start, wait_run

FIVE = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"]


def _strategy(client: TestClient) -> tuple[int, int]:
    created = make_strategy(client, "bollinger_reversion", "IN")
    sid, vid = created["strategy"]["id"], created["version"]["id"]
    run_id = start(client, strategy_version_id=vid, symbols=FIVE, start=Y2018, end=Y2026)
    assert wait_run(client, run_id)["status"] == "done"
    return sid, vid


def _ideas(sid: int) -> str:
    return json.dumps(
        {
            "noticed": "Losing trades clustered when the market was trending.",
            "ideas": [
                {
                    "kind": "filter",
                    "strategy_id": sid,
                    "title": "Only buy dips in choppy markets",
                    "why": "Losers clustered when choppiness was low.",
                    "conditions": [
                        {
                            "indicator": "chop",
                            "params": {"period": 14},
                            "op": "at_least",
                            "value": 44.2,
                        }
                    ],
                    "side": "long",
                },
                {
                    "kind": "tweak",
                    "strategy_id": sid,
                    "title": "Wider bands",
                    "why": "Fewer, deeper dips.",
                    "changes": {"width": 2.5},
                },
                {
                    "kind": "new_strategy",
                    "title": "Trend follower",
                    "why": "Two stocks trend.",
                    "idea": "Buy when the 20-day average crosses above the 50-day average; sell "
                    "on the cross back.",
                    "market": "IN",
                    "symbols": ["INFY", "HDFCBANK", "NOPE"],
                },
            ],
        }
    )


# ---------------------------------------------------------------- the brief


def test_the_brief_never_reads_the_exam_years(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid, _vid = _strategy(client)
    first = brief.build(ctx, "", ["IN"])
    b = first.baselines[sid]
    assert b.study["trades"] > 0 and b.exam["trades"] > 0
    assert f"STRATEGY #{sid}" in first.text and "Study years" in first.text
    assert "exam" not in first.text.lower()
    # make the exam years wildly different: the brief must not change at all
    real_run = brief.run

    def doctored(cache: Any, spec: Any) -> RunOutput:
        out = real_run(cache, spec)
        split = spec.start_ms + int((spec.end_ms - spec.start_ms) * brief.STUDY_SHARE)
        out.trades = [
            replace(t, net_pnl=t.net_pnl * 50 + 12_345.0, gross_pnl=t.gross_pnl * 50)
            if t.entry_ts >= split
            else t
            for t in out.trades
        ]
        return out

    monkeypatch.setattr(brief, "run", doctored)
    second = brief.build(ctx, "", ["IN"])
    assert second.text == first.text
    assert second.baselines[sid].exam != b.exam  # the test itself does see the exam years


def test_parts_split_by_entry_time() -> None:
    from backend.engine.types import Trade

    def t(entry: int, net: float, reason: str = "signal") -> Trade:
        return Trade("X", 1, "long", 1, entry, 1, entry + 5, 1, net, 1.0, net - 1, 0, 1, "", reason)  # type: ignore[arg-type]

    trades = [t(0, 11), t(10, -4), t(20, 6), t(30, 3, "end_of_test")]
    study, exam = part(trades, 0, 20), part(trades, 20, 100)
    assert study["trades"] == 2 and study["wins"] == 1 and study["net"] == pytest.approx(5.0)
    assert study["charges"] == pytest.approx(2.0)
    assert study["profit_factor"] == pytest.approx(10 / 5)
    assert exam["trades"] == 1 and exam["net"] == pytest.approx(5.0)  # end-of-test isn't closed


# ---------------------------------------------------------------- thinking


def test_reading_the_models_answer() -> None:
    reply = "Sure!\n```json\n" + _ideas(7) + "\n```\nHope that helps."
    obj = think.extract_json(reply)
    assert obj is not None and len(obj["ideas"]) == 3
    idea = think.clean_idea(
        {
            "kind": "Filter",
            "strategy_id": "#7",
            "title": "x",
            "conditions": [
                {"indicator": "ADX", "params": {"period": "14"}, "op": ">=", "value": "20%"}
            ],
            "side": "sideways",
        }
    )
    assert idea is not None
    assert idea["strategy_id"] == 7 and idea["side"] == "long"
    assert idea["conditions"] == [
        {
            "indicator": "adx",
            "params": {"period": 14.0},
            "output": None,
            "op": "at_least",
            "value": 20.0,
        }
    ]
    assert think.clean_idea({"kind": "buy everything"}) is None
    assert think.extract_json("no json here") is None


def test_unreadable_answers_get_one_structured_retry() -> None:
    ai = FakeAIProvider()
    ai.queue_tools({"thinking": "Hmm, choppy markets…", "text": "I think you should add a filter."})
    ai.queue(_ideas(3))
    t = think.think(ai, "evidence", model="qwen3.5:4b", num_ctx=8192)
    assert t.structured_retry and len(t.ideas) == 3
    assert t.thinking == "Hmm, choppy markets…"
    assert ai.tool_calls[0]["think"] is True and ai.tool_calls[0]["tools"] == []
    assert ai.calls[-1]["format"] == think.schema()
    # nonsense twice: no ideas, no crash
    ai.queue_tools({"text": "?"})
    ai.queue("still not json")
    assert think.think(ai, "evidence", model="m", num_ctx=8192).ideas == []


# ---------------------------------------------------------------- ideas → rules, verdicts


def test_ideas_become_rules_or_say_why_not() -> None:
    d = template_definition("bollinger_reversion", "IN")
    idea = think.clean_idea(json.loads(_ideas(1))["ideas"][0])
    assert idea is not None
    out = trial.with_filter(d, idea)
    assert out.entry.long is not None and "chop" in out.entry.long.model_dump_json()
    assert out.entry.short == d.entry.short
    with pytest.raises(trial.Untestable, match="doesn't open short"):
        trial.with_filter(d, {**idea, "side": "short"})
    tweaked = trial.with_changes(d, {"width": 2.5, "stop_loss_pct": 4})
    assert next(p.default for p in tweaked.parameters if p.name == "width") == 2.5
    assert tweaked.exit.stop_loss is not None and tweaked.exit.stop_loss.value == 4
    with pytest.raises(trial.Untestable, match="between 1 and 4"):
        trial.with_changes(d, {"width": 9})
    with pytest.raises(trial.Untestable, match="no setting called"):
        trial.with_changes(d, {"speed": 3})
    with pytest.raises(trial.Untestable, match="current settings"):
        trial.with_changes(d, {"width": 2})


def _p(trades: int, net: float, wr: float = 0.5, pf: float | None = 1.2) -> dict[str, Any]:
    return {"trades": trades, "net": net, "win_rate": wr, "profit_factor": pf}


def test_the_verdict_rules_by_hand() -> None:
    base = {"study": _p(100, 5_000), "exam": _p(40, 1_000)}
    capital = 1_000_000  # the gain must be ≥ ₹1,000
    good = {"study": _p(70, 5_000), "exam": _p(30, 2_000, 0.6)}
    held, verdict, checks = trial.judge_change(base, good, capital, Market.IN)
    assert held and verdict.startswith("Held up") and all(c["ok"] for c in checks)
    small = {"study": _p(70, 5_000), "exam": _p(30, 1_999)}  # ₹999 more: not enough
    assert not trial.judge_change(base, small, capital, Market.IN)[0]
    lucky = {"study": _p(70, 4_999), "exam": _p(30, 9_000)}  # worse where it was thought up
    held, verdict, _ = trial.judge_change(base, lucky, capital, Market.IN)
    assert not held and "Study years" in verdict
    starved = {"study": _p(70, 6_000), "exam": _p(11, 9_000)}  # needs 12 of 40 trades
    assert not trial.judge_change(base, starved, capital, Market.IN)[0]
    # new strategies: profit in both parts, 5+ trades each, exam profit factor ≥ 1.1
    assert trial.judge_new({"study": _p(9, 10), "exam": _p(5, 10, pf=1.1)}, Market.US)[0]
    assert not trial.judge_new({"study": _p(9, 10), "exam": _p(5, 10, pf=1.09)}, Market.US)[0]
    assert not trial.judge_new({"study": _p(4, 10), "exam": _p(9, 10)}, Market.US)[0]
    assert not trial.judge_new({"study": _p(9, -1), "exam": _p(9, 10)}, Market.US)[0]


# ---------------------------------------------------------------- a whole round


def _set(ctx: AppContext, **changes: Any) -> None:
    with ctx.db.session() as s:
        update(s, {k.replace("__", "."): v for k, v in changes.items()}, ctx.clock)


def test_a_round_thinks_tests_keeps_and_remembers(client: TestClient, ctx: AppContext) -> None:
    sid, vid = _strategy(client)
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    ai.queue_tools({"thinking": "Choppy markets suit dip buying.", "text": _ideas(sid)})
    metis = ctx.services["metis"]
    out = metis.round("user")
    assert out["status"] == "done", out
    assert out["ideas"] == 3
    rnd = notebook.get_round(ctx, out["round_id"])
    assert rnd is not None and rnd["status"] == "done" and rnd["trigger"] == "user"
    assert rnd["thinking"] == "Choppy markets suit dip buying."
    assert rnd["noticed"].startswith("Losing trades") and "STRATEGY #" in rnd["brief"]
    ideas = {i["kind"]: i for i in notebook.ideas(ctx)}
    assert set(ideas) == {"filter", "tweak", "new_strategy"}
    for i in ideas.values():
        assert i["status"] in ("held_up", "saved", "rejected"), i
        checks = i["result"]["checks"]
        assert (i["status"] != "rejected") == all(c["ok"] for c in checks)
        assert i["result"]["study_line"].startswith("Study years")
        assert i["verdict"].startswith(("Held up", "Didn't hold up"))
    assert ideas["filter"]["strategy_version_id"] == vid
    assert ideas["new_strategy"]["result"]["symbols"] == ["INFY", "HDFCBANK"]  # NOPE dropped
    # what held up was saved (metis.apply is on by default) and became a Kairos lesson
    saved = [i for i in ideas.values() if i["status"] == "saved"]
    with ctx.db.session() as s:
        lessons = [m.text for m in s.query(KairosMemory).all() if m.text.startswith("Metis found")]
    assert len(lessons) == len(saved)
    for i in saved:
        assert i["saved_version_id"] is not None and i["run_id"] is not None
    # the notebook feeds the next round, and repeats aren't tested again
    nxt = brief.build(ctx, "", ["IN"])
    assert "Only buy dips in choppy markets" in nxt.text
    for i in ideas.values():
        exam_net = i["result"]["candidate"]["exam"]["net"]
        assert f"{exam_net:,.0f}" not in nxt.text.split("Your notebook")[1].split("Indicators")[0]
    ai.queue_tools({"text": _ideas(sid)})
    again = metis.round("user")
    assert again["status"] == "done", again
    # repeats are never tested twice (when the AI only repeats itself, the playbook's first
    # experiments are tested instead, METIS §14)
    with ctx.db.session() as s:
        fps = [r.fingerprint for r in s.query(MetisIdea).all()]
    assert len(fps) == len(set(fps))
    st = client.get("/api/metis").json()
    assert st["totals"]["ideas"] >= 3 and st["rounds"] and st["ideas"]
    assert client.get(f"/api/metis/rounds/{out['round_id']}").json()["round"]["brief"]


def test_saving_an_idea_by_hand(client: TestClient, ctx: AppContext) -> None:
    sid, _vid = _strategy(client)
    _set(ctx, metis__apply=False)
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    ai.queue_tools({"text": _ideas(sid)})
    ctx.services["metis"].round("user")
    rejected = next(i for i in notebook.ideas(ctx) if i["kind"] == "filter")
    # pretend the filter held up, then save it with the button
    with ctx.db.session() as s:
        row = s.get(MetisIdea, rejected["id"])
        assert row is not None
        row.status = "held_up"
    r = client.post(f"/api/metis/ideas/{rejected['id']}/save")
    assert r.status_code == 200, r.json()
    idea = r.json()["idea"]
    assert idea["status"] == "saved" and idea["saved_strategy_id"] == sid
    versions = client.get(f"/api/strategies/{sid}/versions").json()["versions"]
    assert versions[0]["note"].startswith("Metis:") and versions[0]["created_by"] == "metis"
    assert "chop" in json.dumps(versions[0]["definition"]["entry"])
    assert client.post(f"/api/metis/ideas/{rejected['id']}/save").status_code == 200  # no-op
    other = next(i for i in notebook.ideas(ctx) if i["status"] == "rejected")
    assert client.post(f"/api/metis/ideas/{other['id']}/save").status_code == 409
    # a strategy that changed since the test isn't overwritten
    tweak = next(i for i in notebook.ideas(ctx) if i["kind"] == "tweak")
    with ctx.db.session() as s:
        row = s.get(MetisIdea, tweak["id"])
        assert row is not None
        row.status = "held_up"
    with pytest.raises(Exception, match="changed since Metis tested"):
        apply.save(ctx, tweak["id"])


# ---------------------------------------------------------------- on its own, giving way


def test_metis_waits_for_the_switch_the_ai_and_the_user(ctx: AppContext) -> None:
    metis = ctx.services["metis"]
    _set(ctx, metis__enabled=False)  # on by default since Phase 18 (D-99); switched off here
    assert not metis.due() and metis.status()["state"] == "off"
    _set(ctx, metis__enabled=True)
    assert not metis.due()  # two minutes after Agora opens
    assert metis.status()["state"] == "scheduled" and metis.status()["next_round_at"]
    ctx.clock.advance(121_000)
    assert metis.due()
    # the user is talking to Kairos
    ctx.services["kairos"].last_active_ms = ctx.clock.now_ms()
    assert not metis.due() and "Kairos" in metis.status()["waiting"]
    ctx.clock.advance(61_000)
    assert metis.due()
    # no AI helper: it keeps working from its playbook (D-81) and says how to get its own ideas
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    ai.state = "not_running"
    ctx.ai_service._cache = None
    assert metis.due()
    st = metis.status()
    assert st["state"] == "playbook" and "Settings → AI helper" in st["ai_note"]
    assert metis.round("auto")["status"] == "done"
    _set(ctx, metis__enabled=False)
    assert not metis.due() and metis.status()["next_round_at"] is None
    with ctx.db.session() as s:
        assert read_all(s)["metis.every_minutes"] == 1


def test_research_now_with_and_without_the_ai(client: TestClient, ctx: AppContext) -> None:
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    ai.queue_tools({"text": json.dumps({"noticed": "Nothing yet.", "ideas": []})})
    job = client.post("/api/metis/round").json()["job_id"]
    done = wait_job(client, job, timeout=120)
    assert done["status"] == "done", done
    # no strategies yet: a discovery round; the AI had no idea, so the playbook's were tested
    assert done["result"]["direction"] == "discover"
    first = notebook.get_round(ctx, done["result"]["round_id"])
    assert first is not None and "playbook" in first["noticed"]
    ai.state = "not_running"
    ctx.ai_service._cache = None
    r = client.post("/api/metis/round")
    assert r.status_code == 200
    again = wait_job(client, r.json()["job_id"], timeout=120)
    assert again["status"] == "done" and "Playbook round" in again["result"]["note"]
    st = client.get("/api/metis").json()
    assert st["ai_ready"] is False and st["thread"] is False  # practice data: no thread


def test_kairos_talks_to_metis(ctx: AppContext) -> None:
    from backend.kairos.tools import ALL, Env

    calls = router.plan(ctx, "Turn on Metis", ThreadState(), {})
    assert [(c.name, dict(c.arguments)) for c in calls] == [("metis", {"action": "on"})]
    calls = router.plan(ctx, "Metis, look into my RSI strategy", ThreadState(), {})
    assert dict(calls[0].arguments) == {"action": "now", "focus": "my RSI strategy"}
    assert dict(router.plan(ctx, "what has metis found?", ThreadState(), {})[0].arguments) == {
        "action": "status"
    }
    tool = ALL["metis"]
    res = tool.run(Env(ctx, ThreadState()), tool.args(action="on", focus="breakouts"))
    assert res.ok and "Metis is on" in res.summary and res.ui == {"navigate": "/metis"}
    with ctx.db.session() as s:
        st = read_all(s)
    assert st["metis.enabled"] is True and st["metis.focus"] == "breakouts"


def test_rounds_cut_off_by_a_closed_agora_are_closed_on_start(ctx: AppContext) -> None:
    """A round left "running" when Agora closed is marked failed when Metis starts, so it
    doesn't show as running for ever or count as done in the choice of direction."""
    from backend.db.models import MetisRound
    from backend.metis import notebook

    rid = notebook.start_round(ctx, "auto", "", "qwen3.5:4b", "discover")
    assert notebook.recent_directions(ctx) == ["discover"]
    assert notebook.close_unfinished(ctx) == 1
    with ctx.db.session() as s:
        row = s.get(MetisRound, rid)
        assert row is not None and row.status == "failed" and row.finished_at is not None
        assert row.note == "Agora closed during this round."
    assert notebook.recent_directions(ctx) == []
    assert notebook.close_unfinished(ctx) == 0


def test_thinking_that_runs_out_of_room_is_kept_for_the_second_ask() -> None:
    """D-153: Qwen 3.5 thinks past the reading size and stops with no answer. Its thinking is
    capped, and the second ask carries the end of it instead of starting from nothing."""
    from backend.ai import reading

    ai = FakeAIProvider()
    ai.queue_tools({"thinking": "early musing " * 600 + "Idea taking shape: dips in uptrends."})
    ai.queue(_ideas(1))
    t = think.think(ai, "a brief", model="qwen3.5:4b", num_ctx=16384)
    opts = ai.tool_calls[-1]["options"]
    assert opts.extra["num_predict"] == reading.THINK_RESERVE + reading.ANSWER_RESERVE
    assert t.structured_retry and t.ideas
    said = ai.calls[-1]["messages"][2].content
    assert said.startswith("(My thinking so far, cut short:)")
    assert said.endswith("Idea taking shape: dips in uptrends.")
    assert len(said) <= think.NOTES_CHARS + 40
    assert "ran out of room" in ai.calls[-1]["messages"][3].content


def test_the_instructions_name_every_bigger_chart_agora_allows() -> None:
    """Metis kept asking 5-minute strategies to read the weekly chart: its instructions only
    listed the bigger charts of daily and hourly strategies. Keep them in step with Agora's."""
    from backend.analysis import mtf

    words = {"1d": "daily", "1h": "hourly", "15m": "15-minute", "5m": "5-minute", "1m": "1-minute"}
    for base, bigger in mtf.BIGGER.items():
        part = think.PERSONA.split(f"for {words[base]} ")[0].rsplit(" for ", 1)[-1]
        part = part.split(", ", 1)[-1] if base != "1d" else part
        for b in bigger:
            assert f'"{b}"' in part, (base, b, part)


def test_a_finding_whose_ideas_were_all_tested_is_only_mentioned(
    client: TestClient, ctx: AppContext
) -> None:
    """D-156: the brief kept telling the model the same fix (partial exits) after it had been
    tested, so it proposed only repeats and rounds ended empty. Such a finding gets one line."""
    _strategy(client)
    first = brief.build(ctx, "", ["IN"])
    sid, found = next((k, v) for k, v in first.findings.items() if any(f.seeds for f in v))
    f = next(x for x in found if x.seeds)
    rid = notebook.start_round(ctx, "auto", "", "m", "improve")
    for s in f.seeds:
        notebook.add_idea(
            ctx,
            rid,
            kind=s["kind"],
            title=s["title"],
            strategy_id=sid,
            fingerprint=trial.fingerprint_of(s, first.baselines),
            status="rejected",
        )
    nxt = brief.build(ctx, "", ["IN"])
    assert "Already tested on this strategy" in nxt.text
    assert f.key not in [x.key for x in nxt.findings.get(sid, [])]
    assert not any(s in nxt.seeds for s in f.seeds)


def test_the_brief_tells_metis_about_todays_market(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-159: Metis researched without news, world events, sectors or the market's regime."""
    from backend.metis import agenda

    _strategy(client)
    monkeypatch.setattr(agenda, "market_regime", lambda _c, _m: "down-volatile")
    monkeypatch.setattr(
        ctx.services["news"], "risk", lambda _m: {"level": 40.0, "text": "Watchful."}
    )
    monkeypatch.setattr(
        ctx.services["world"],
        "view",
        lambda _m: {
            "drivers": [{"title": "War in the Middle East"}],
            "tags": {"airline": -2.0, "oil_producer": 0.8, "it_services": -1.0},
        },
    )
    text = brief.build(ctx, "", ["IN"]).text
    assert "Today's market" in text and "a jumpy downtrend" in text
    assert "news risk 40/100" in text and "War in the Middle East" in text
    assert "help oil producer" in text and "hurt airline, it services" in text


def test_metis_runs_without_its_own_ideas_when_switched_off(
    client: TestClient, ctx: AppContext
) -> None:
    """D-166: the user had Claude write Metis's ideas; Metis then never asks the model."""
    _strategy(client)
    _set(ctx, metis__own_ideas=False)
    metis = ctx.services["metis"]
    ready, why = metis.ai_ready()
    assert not ready and "own ideas are switched off" in why
    ai = ctx.ai
    assert isinstance(ai, FakeAIProvider)
    before = len(ai.tool_calls)
    out = metis.round("user")
    assert out["status"] == "done" and len(ai.tool_calls) == before  # the model wasn't asked
    assert metis.status()["state"] == "playbook"
