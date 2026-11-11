"""The AI helper API with the fake provider: status states, streamed explanations with the
number check, strategy drafts, model download, and conversation history."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.fakes.ai_provider import FakeAIProvider
from tests.strategy.test_backtest_api import Y2018, Y2022, make_strategy, start, wait_run


def ai(ctx: AppContext) -> FakeAIProvider:
    assert isinstance(ctx.ai, FakeAIProvider)
    return ctx.ai


def events(client: TestClient, body: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    with client.stream("POST", "/api/ai/explain", json=body) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


@pytest.fixture
def run_id(client: TestClient) -> int:
    vid = make_strategy(client, "bollinger_reversion", "IN")["version"]["id"]
    rid = start(
        client, strategy_version_id=vid, symbols=["RELIANCE", "TCS"], start=Y2018, end=Y2022
    )
    assert wait_run(client, rid)["status"] == "done"
    return rid


def test_status_states(client: TestClient, ctx: AppContext) -> None:
    s = client.get("/api/ai/status").json()
    assert s["state"] == "ready" and s["model"] == "qwen3.5:4b"
    assert [r["name"] for r in s["recommended"]] == ["qwen3.5:4b", "gemma4:e4b"]
    ai(ctx).models = ["llama3:8b"]
    assert client.get("/api/ai/status?fresh=true").json()["state"] == "model_missing"
    client.put("/api/settings", json={"ai.enabled": False})
    assert client.get("/api/ai/status?fresh=true").json()["state"] == "disabled"
    assert client.get("/api/health").json()["ai"]["state"] == "disabled"
    client.put("/api/settings", json={"ai.enabled": True})
    ai(ctx).state = "not_installed"
    assert client.get("/api/ai/status?fresh=true").json()["state"] == "not_installed"
    r = client.post("/api/ai/explain", json={"kind": "metric", "question": "What is Sharpe?"})
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "The free AI helper isn't installed."


def test_status_says_where_the_model_runs(client: TestClient, ctx: AppContext) -> None:
    """The user's laptop answered from ordinary memory with an idle graphics card: Settings
    must say so and how to fix it, instead of leaving him to read Task Manager."""
    assert client.get("/api/ai/status?fresh=true").json()["runs_on"] is None  # not loaded yet
    ai(ctx).loaded = {"qwen3.5:4b": (4_000_000_000, 4_000_000_000)}
    on = client.get("/api/ai/status?fresh=true").json()["runs_on"]
    assert on["where"] == "gpu" and on["gpu_percent"] == 100 and "fix" not in on
    ai(ctx).loaded = {"qwen3.5:4b": (4_000_000_000, 2_000_000_000)}
    on = client.get("/api/ai/status?fresh=true").json()["runs_on"]
    assert on["where"] == "partly" and on["gpu_percent"] == 50
    ai(ctx).loaded = {"qwen3.5:4b": (4_000_000_000, 0)}
    on = client.get("/api/ai/status?fresh=true").json()["runs_on"]
    assert on["where"] == "cpu" and "Quit Ollama" in on["fix"]
    ai(ctx).loaded = {"gemma4:e4b": (7_000_000_000, 0)}  # another model loaded: not ours
    assert client.get("/api/ai/status?fresh=true").json()["runs_on"] is None


def test_explain_backtest_streams_and_checks_numbers(
    client: TestClient, ctx: AppContext, run_id: int
) -> None:
    detail = client.get(f"/api/backtests/{run_id}").json()
    trades = detail["metrics"]["trades"]
    ai(ctx).queue(f"**What worked** It made {trades} trades. **Biggest risk** A 87.3% drop.")
    evs = events(client, {"kind": "backtest", "id": run_id})
    assert evs[0]["type"] == "start"
    text = "".join(e["text"] for e in evs if e["type"] == "text")
    assert text.startswith("**What worked**")
    done = evs[-1]
    assert done["type"] == "done" and done["unverified"] == ["87.3"]
    assert done["note"] == "AI-generated. Check important numbers."
    prompt = ai(ctx).calls[-1]["messages"][1].content
    assert '"total_return"' in prompt and "best_and_worst_trades" in prompt
    conv = client.get(f"/api/ai/conversations/{evs[0]['conversation_id']}").json()
    assert conv["kind"] == "backtest" and conv["messages"][-1]["content"] == text


def test_explain_trade_includes_candles_and_indicators(
    client: TestClient, ctx: AppContext, run_id: int
) -> None:
    trade = client.get(f"/api/backtests/{run_id}/trades?limit=1").json()["trades"][0]
    evs = events(client, {"kind": "trade", "id": trade["id"]})
    assert evs[-1]["type"] == "done"
    data = ai(ctx).calls[-1]["messages"][1].content
    assert "candles_split_adjusted" in data and "bollinger" in data and "before_entry" in data


def test_metric_question_uses_the_users_value(
    client: TestClient, ctx: AppContext, run_id: int
) -> None:
    evs = events(
        client, {"kind": "metric", "id": run_id, "question": "What does Sharpe ratio mean?"}
    )
    assert evs[-1]["type"] == "done"
    prompt = ai(ctx).calls[-1]["messages"][1].content
    assert "What does Sharpe ratio mean?" in prompt and '"sharpe"' in prompt
    r = client.post("/api/ai/explain", json={"kind": "metric", "question": "  "})
    assert r.status_code == 422


def test_draft_strategy_returns_a_valid_unsaved_draft(client: TestClient) -> None:
    r = client.post(
        "/api/ai/draft-strategy",
        json={"idea": "Buy when the fast average crosses up", "market": "US"},
    )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True and body["attempts"] == 1
    assert body["definition"]["market"] == "US" and body["definition"]["product"] == "cash"
    assert "20-day average" in body["explanation"]
    assert client.get("/api/strategies").json()["strategies"] == [], "nothing is saved"
    v = client.post("/api/strategies/validate", json={"definition": body["definition"]}).json()
    assert v["ok"] is True


def test_model_download_runs_as_a_job(client: TestClient, ctx: AppContext) -> None:
    ai(ctx).state = "model_missing"
    job_id = client.post("/api/ai/pull", json={"model": "gemma4:e4b"}).json()["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert "gemma4:e4b" in ai(ctx).models


def test_paper_day_summary(client: TestClient, ctx: AppContext) -> None:
    from backend.paper.service import SessionIn

    vid = make_strategy(client, "bollinger_reversion", "IN")["version"]["id"]
    ctx.paper.threaded = False
    sid = ctx.paper.start_session(SessionIn(strategy_version_id=vid))
    runner = ctx.paper.runner(sid)
    assert runner is not None and runner._boot()
    for _ in range(30):
        runner.replay_step()
    evs = events(client, {"kind": "paper_day", "id": sid})
    assert evs[-1]["type"] == "done"
    prompt = ai(ctx).calls[-1]["messages"][1].content
    assert "money_at_end_of_day" in prompt
