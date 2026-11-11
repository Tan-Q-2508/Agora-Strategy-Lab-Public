"""Kairos, the agent: the conversation loop, its tools and the rule-based fallback."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.core.types import Market
from backend.fakes.ai_provider import FakeAIProvider
from backend.kairos import resolve, router
from backend.kairos.tools import ALL, select_tools
from backend.kairos.tools.base import ThreadState
from tests.data.helpers import wait_job


def chat(client: TestClient, message: str, **extra: Any) -> list[dict[str, Any]]:
    r = client.post("/api/kairos/chat", json={"message": message, **extra})
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: ")]


def steps(events: list[dict[str, Any]], status: str = "done") -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == "step" and e["status"] == status]


def load(client: TestClient, symbols: list[str], market: str = "IN") -> None:
    job = client.post("/api/data/refresh", json={"symbols": symbols, "market": market}).json()
    assert wait_job(client, job["job_id"])["status"] == "done"


# ---------------------------------------------------------------- practice mode (rules)


def test_practice_mode_reads_a_chart_and_saves_the_conversation(client: TestClient) -> None:
    load(client, ["RELIANCE", "TCS"])
    ev = chat(client, "analyse reliance please")
    assert ev[0]["type"] == "thread"
    [step] = steps(ev)
    assert step["tool"] == "analyze_chart" and step["card"]["type"] == "chart"
    assert step["card"]["symbol"] == "RELIANCE"
    assert step["ui"]["navigate"].startswith("/charts?symbol=RELIANCE")
    done = ev[-1]
    assert done["type"] == "done" and done["mode"] == "practice"
    assert "not financial advice" in done["footer"]
    tid = done["thread_id"]
    msgs = client.get(f"/api/kairos/threads/{tid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["payload"]["steps"][0]["tool"] == "analyze_chart"
    assert msgs[1]["payload"]["state"]["symbols"] == ["RELIANCE"]
    assert client.get("/api/kairos/threads").json()["threads"][0]["id"] == tid


def test_practice_mode_create_backtest_and_paper_trade(client: TestClient, ctx: AppContext) -> None:
    ev = chat(
        client, "Backtest RSI mean reversion on TCS and Infosys over 3 years, then paper trade it"
    )
    done = steps(ev)
    assert [s["tool"] for s in done] == [
        "create_strategy",
        "run_backtest",
        "start_paper_trading",
    ], [(s["tool"], s["status"], s.get("detail")) for s in ev if s["type"] == "step"]
    created, backtest, paper = done
    assert created["card"]["symbols"] == ["TCS", "INFY"]
    assert backtest["card"]["type"] == "backtest" and backtest["card"]["trades"] is not None
    assert backtest["ui"]["navigate"] == f"/backtests/{backtest['card']['id']}"
    assert paper["card"]["symbols"] == ["TCS", "INFY"]
    ctx.paper.stop(paper["card"]["id"])
    # "it" now means that strategy: a follow-up needs no names
    tid = ev[-1]["thread_id"]
    again = chat(client, "stop all paper trading", thread_id=tid)
    assert steps(again)[0]["tool"] == "stop_paper_trading"


def test_practice_mode_without_a_plan_offers_help(client: TestClient) -> None:
    ev = chat(client, "hello there")
    text = "".join(e["delta"] for e in ev if e["type"] == "text")
    assert "I can read any chart" in text and not steps(ev)


def test_basic_mode_without_the_ai_helper(client: TestClient, ctx: AppContext) -> None:
    ctx.ai = FakeAIProvider(state="not_installed")
    ev = chat(client, "what is a bear flag?")
    assert ev[-1]["mode"] == "basic"
    assert steps(ev)[0]["tool"] == "lookup_knowledge"
    text = "".join(e["delta"] for e in ev if e["type"] == "text")
    assert "Flags and pennants" in text or "flag" in text.lower()
    assert "Basic mode" in text


# ---------------------------------------------------------------- AI mode (scripted model)


def test_ai_mode_tool_call_then_answer(client: TestClient, ctx: AppContext) -> None:
    load(client, ["RELIANCE"])
    fake: FakeAIProvider = ctx.ai  # type: ignore[assignment]
    fake.queue_tools(
        {
            "thinking": "The user wants a chart reading.",
            "calls": [("analyze_chart", {"symbol": "reliance", "timeframe": "daily"})],
        },
        {"text": "RELIANCE is in a downtrend. Not financial advice."},
    )
    ev = chat(
        client, "What do you think of Reliance?", page={"screen": "/charts", "symbol": "RELIANCE"}
    )
    kinds = [e["type"] for e in ev]
    assert "thinking" in kinds
    [step] = steps(ev)
    assert step["tool"] == "analyze_chart" and step["args"]["timeframe"] == "daily"
    text = "".join(e["delta"] for e in ev if e["type"] == "text")
    assert text == "RELIANCE is in a downtrend. Not financial advice."
    assert ev[-1]["mode"] == "ai"
    # round 1 saw the persona, the page and only the selected tools; round 2 saw the result
    first, second = fake.tool_calls
    system = first["messages"][0].content
    assert system.startswith("You are Kairos") and "symbol=RELIANCE" in system
    assert "analyze_chart" in first["tools"] and "optimize_strategy" not in first["tools"]
    tool_turn = second["messages"][-1]
    assert tool_turn.role == "tool" and tool_turn.tool_name == "analyze_chart"
    assert "Verdict:" in tool_turn.content


def test_ai_mode_bad_arguments_are_sent_back(client: TestClient, ctx: AppContext) -> None:
    fake: FakeAIProvider = ctx.ai  # type: ignore[assignment]
    fake.queue_tools(
        {"calls": [("analyze_chart", {"symbol": "NOTASTOCKXYZ"})]},
        {"text": "I couldn't find that stock. Which one did you mean?"},
    )
    ev = chat(client, "analyse NOTASTOCKXYZ")
    [err] = steps(ev, "error")
    assert "couldn't find a stock" in err["detail"]
    second = fake.tool_calls[1]["messages"][-1]
    assert second.role == "tool" and second.content.startswith("Failed:")


def test_ai_mode_recovers_a_tool_call_written_as_text(client: TestClient, ctx: AppContext) -> None:
    fake: FakeAIProvider = ctx.ai  # type: ignore[assignment]
    fake.queue_tools(
        {"text": '{"name": "lookup_knowledge", "arguments": {"topic": "bear flag"}}'},
        {"text": "A bear flag is a pause after a sharp drop."},
    )
    ev = chat(client, "what is a bear flag")
    assert steps(ev)[0]["tool"] == "lookup_knowledge"
    assert any(e["type"] == "text_reset" for e in ev)


def test_ai_mode_stops_after_too_many_rounds(client: TestClient, ctx: AppContext) -> None:
    fake: FakeAIProvider = ctx.ai  # type: ignore[assignment]
    fake.queue_tools(*[{"calls": [("lookup_knowledge", {"topic": "rsi"})]} for _ in range(9)])
    ev = chat(client, "loop forever")
    assert len(steps(ev)) == 8
    text = "".join(e["delta"] for e in ev if e["type"] == "text")
    assert ev[-1]["type"] == "done" and text == ""


def test_status_endpoint(client: TestClient) -> None:
    s = client.get("/api/kairos/status").json()
    assert s["mode"] == "practice" and s["suggestions"]


def test_delete_thread(client: TestClient) -> None:
    tid = chat(client, "hello")[-1]["thread_id"]
    assert client.delete(f"/api/kairos/threads/{tid}").json() == {"deleted": tid}
    assert client.get(f"/api/kairos/threads/{tid}").status_code == 404


# ---------------------------------------------------------------- the router


@pytest.mark.parametrize(
    ("text", "tools"),
    [
        ("analyse RELIANCE and tcs", ["analyze_chart", "analyze_chart"]),
        ("which nifty stocks look oversold?", ["scan_market"]),
        ("forecast AAPL for next week", ["forecast"]),
        ("any news on Infosys?", ["get_news"]),
        ("is it safe to trade with this war going on?", ["news_risk"]),
        ("what's the world news today", ["get_news"]),
        ("how is the market today", ["market_overview"]),
        ("explain the Sharpe ratio", ["lookup_knowledge"]),
        ("what is the RSI strategy?", ["lookup_knowledge"]),
        ("create a supertrend strategy for TCS", ["create_strategy"]),
        ("backtest it over 5 years", ["run_backtest"]),
        ("optimise it with walk forward", ["optimize_strategy"]),
        ("stop all paper trading", ["stop_paper_trading"]),
        ("download prices for AAPL", ["refresh_data"]),
        ("hello", []),
    ],
)
def test_router_plans(ctx: AppContext, text: str, tools: list[str]) -> None:
    calls = router.plan(ctx, text, ThreadState(), {})
    assert [c.name for c in calls] == tools


def test_router_reads_years_and_market(ctx: AppContext) -> None:
    [create, bt] = router.plan(
        ctx, "backtest the MACD strategy on US stocks for 2.5 years", ThreadState(), {}
    )
    assert create.arguments == {"template": "macd_momentum", "market": "US"}
    assert bt.arguments == {"years": 2.5}


def test_router_uses_the_chart_on_screen(ctx: AppContext) -> None:
    [call] = router.plan(ctx, "what do you see on this chart?", ThreadState(), {"symbol": "TCS"})
    assert call.arguments["symbol"] == "TCS"


# ---------------------------------------------------------------- tools and resolvers


def test_news_risk_tool_reads_the_world_and_explains_the_guard(
    client: TestClient, ctx: AppContext
) -> None:
    ev = chat(client, "Is it safe to trade? Any geopolitical risk for Indian stocks?")
    [step] = steps(ev)  # finished, not failed
    assert step["tool"] == "news_risk"
    card = step["card"]
    assert card["market"] == "IN" and card["mode"] == "protective" and card["link"] == "/news"
    assert 0 <= card["level"] <= 100 and card["drivers"]
    world = router.plan(ctx, "any world news on oil and war?", ThreadState(), {})
    assert world[0].name == "news_risk"


def test_every_tool_schema_is_flat_and_described() -> None:
    for tool in ALL.values():
        s = tool.schema()
        text = json.dumps(s)
        assert "$defs" not in text and "$ref" not in text, tool.name
        assert s["function"]["description"]
        for name, prop in s["function"]["parameters"]["properties"].items():
            assert "type" in prop or "enum" in prop, (tool.name, name)


def test_tool_selection_keeps_the_prompt_small() -> None:
    core = {t.name for t in select_tools("analyse RELIANCE")}
    assert {"analyze_chart", "run_backtest", "lookup_knowledge"} <= core
    assert "optimize_strategy" not in core
    assert "optimize_strategy" in {t.name for t in select_tools("optimise my strategy")}


@pytest.mark.parametrize(
    ("text", "symbol"),
    [
        ("reliance", "RELIANCE"),
        ("Apple", "AAPL"),
        ("TCS.NS", "TCS"),
        ("relaince", "RELIANCE"),
        ("infy", "INFY"),
        ("nifty", "NIFTY50"),
    ],
)
def test_stock_resolution(ctx: AppContext, text: str, symbol: str) -> None:
    assert resolve.stock(ctx, text).symbol == symbol


def test_unknown_stock_is_plain_english(ctx: AppContext) -> None:
    with pytest.raises(resolve.NotFound, match="couldn't find a stock called “ZZZZZZ”"):
        resolve.stock(ctx, "ZZZZZZ", Market.IN)


def test_several_stocks_and_periods(ctx: AppContext) -> None:
    assert [i.symbol for i in resolve.stocks(ctx, "TCS, Infosys and reliance")] == [
        "TCS",
        "INFY",
        "RELIANCE",
    ]
    lo, hi = resolve.period(1_000 * 86_400_000, years=2)
    assert hi is None and lo == 1_000 * 86_400_000 - int(2 * 365.25 * 86_400_000)
    assert resolve.period(0, start="2021-01-01")[0] == 1_609_459_200_000
    assert resolve.template_key("the RSI one") == "rsi_mean_reversion"
    assert resolve.timeframe("hourly").value == "1h"


# ---------------------------------------------------------------- the desk and learning tools


def test_practice_mode_starts_the_desk_and_reports_on_it(
    client: TestClient, ctx: AppContext
) -> None:
    load(client, ["TCS", "INFY"])
    ctx.paper.threaded = False
    ev = chat(client, "Keep an eye on TCS and Infosys and trade them for me")
    [step] = steps(ev)
    assert step["tool"] == "start_desk", [
        (e.get("tool"), e.get("detail")) for e in ev if e["type"] == "step"
    ]
    assert step["card"]["type"] == "desk" and step["card"]["symbols"] == ["TCS", "INFY"]
    assert step["ui"]["navigate"] == f"/paper/desk/{step['card']['id']}"
    tid = ev[-1]["thread_id"]
    status = chat(client, "how is the desk doing?", thread_id=tid)
    assert steps(status)[0]["tool"] == "desk_status"
    learned = chat(client, "what have you learned so far?", thread_id=tid)
    assert steps(learned)[0]["tool"] == "get_lessons"
    text = "".join(e["delta"] for e in learned if e["type"] == "text")
    assert "studied" in text.lower()
    stop = chat(client, "stop the desk", thread_id=tid)
    assert steps(stop)[0]["tool"] == "stop_desk"


def test_practice_mode_backtests_kairos_itself(client: TestClient) -> None:
    load(client, ["RELIANCE", "TCS"])
    ev = chat(
        client, "How would Kairos have traded RELIANCE and TCS over the last 5 years? Backtest it"
    )
    done = steps(ev)
    assert [s["tool"] for s in done] == ["create_strategy", "run_backtest"], [
        (e.get("tool"), e.get("status"), e.get("detail")) for e in ev if e["type"] == "step"
    ]
    assert done[0]["card"]["name"].startswith("Kairos brain")
    assert done[1]["card"]["type"] == "backtest"


@pytest.mark.parametrize(
    ("text", "tools"),
    [
        ("watch RELIANCE and trade it on your own", ["start_desk"]),
        ("show me the desk", ["desk_status"]),
        ("retrain on the US market", ["train_kairos"]),
        ("backtest yourself on TCS", ["create_strategy", "run_backtest"]),
    ],
)
def test_router_plans_desk_and_learning(ctx: AppContext, text: str, tools: list[str]) -> None:
    calls = router.plan(ctx, text, ThreadState(), {})
    assert [c.name for c in calls] == tools


def test_listing_strategies_shows_their_latest_backtest(
    client: TestClient, ctx: AppContext
) -> None:
    """D-122: "which of my strategies is doing best?" needs no new backtests."""
    from backend.kairos.tools.lab import list_strategies
    from tests.data.helpers import wait_job
    from tests.strategy.test_backtest_api import make_strategy

    made = make_strategy(client, "ma_crossover", "IN")
    run = client.post(
        "/api/backtests",
        json={"strategy_version_id": made["version"]["id"], "symbols": ["TCS", "INFY"]},
    ).json()
    assert wait_job(client, run["job_id"])["status"] == "done"
    make_strategy(client, "rsi_mean_reversion", "IN")  # never backtested
    env = SimpleNamespace(ctx=ctx)
    out = list_strategies(env, None)  # type: ignore[arg-type]
    assert "latest backtest #" in out.summary and "not backtested yet" in out.summary
    assert out.summary.index("latest backtest #") < out.summary.index("not backtested yet")


def test_desk_status_tells_of_every_desk_and_finds_the_one_asked_about(
    client: TestClient, ctx: AppContext
) -> None:
    """Kairos described only its newest desk, so with ten running it told the user the India
    daily desk didn't exist (2026-11-04). It lists every running desk, with its judge's line,
    and narrows to the market and candle size the question names."""
    from backend.core.types import Timeframe
    from backend.kairos import resolve
    from backend.kairos.tools import desk as desk_tools
    from backend.kairos.tools.base import Env

    load(client, ["TCS", "INFY"])
    ctx.paper.threaded = False
    insts = [resolve.stock(ctx, s, Market.IN) for s in ("TCS", "INFY")]
    daily = ctx.desk.launch(insts, Timeframe.D1)
    hourly = ctx.desk.launch(insts, Timeframe.H1)
    env = Env(ctx=ctx, state=ThreadState())
    both = desk_tools.desk_status(env, desk_tools.DeskStatusArgs())
    assert both.ok and "2 Kairos desks running" in both.summary
    assert f"#{daily['id']} India daily desk" in both.summary
    assert f"#{hourly['id']} India 1-hour desk" in both.summary
    assert "trades closed since it started" in both.summary
    one = desk_tools.desk_status(env, desk_tools.DeskStatusArgs(market="IN", timeframe="daily"))
    assert one.card is not None and one.card["id"] == daily["id"]
    assert "1 Kairos desk running" in one.summary and "1-hour" not in one.summary
    none = desk_tools.desk_status(env, desk_tools.DeskStatusArgs(market="US"))
    assert "No such desk is running" in none.summary
    calls = router.plan(ctx, "How is the India daily desk doing?", ThreadState(), {})
    assert [(c.name, dict(c.arguments)) for c in calls] == [
        ("desk_status", {"market": "IN", "timeframe": "1d"})
    ]
