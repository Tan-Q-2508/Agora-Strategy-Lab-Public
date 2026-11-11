"""The paper-trading API and the WebSocket push channel."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from backend.context import AppContext


def make_strategy(client: TestClient, key: str = "bollinger_reversion") -> dict[str, Any]:
    r = client.post("/api/strategies", json={"name": "Bands", "market": "IN", "template_key": key})
    assert r.status_code == 201, r.json()
    body: dict[str, Any] = r.json()
    return body


def test_accounts(client: TestClient) -> None:
    r = client.post("/api/paper/accounts", json={"market": "US", "starting_capital": 25000})
    assert r.status_code == 201
    acct = r.json()["account"]
    assert acct["name"] == "Paper account 1" and acct["starting_capital"] == 25000
    assert acct["brokerage_profile_id"] and acct["slippage_bps"] >= 0
    listed = client.get("/api/paper/accounts").json()["accounts"]
    assert [a["id"] for a in listed] == [acct["id"]]
    # Kairos's own accounts (one per desk run) stay out of the user's picker (D-208)
    desk = client.post("/api/paper/accounts", json={"market": "US", "name": "Kairos desk (US)"})
    client.post("/api/paper/accounts", json={"market": "US", "name": "Metis"})
    listed = client.get("/api/paper/accounts").json()["accounts"]
    assert [a["id"] for a in listed] == [acct["id"]]
    every = client.get("/api/paper/accounts", params={"include_kairos": True}).json()["accounts"]
    assert desk.json()["account"]["id"] in [a["id"] for a in every]


def test_threaded_practice_replay_end_to_end(client: TestClient, ctx: AppContext) -> None:
    ctx.paper.pace_scale = 0.0
    created = make_strategy(client)
    # A narrower list keeps the replay quick.
    d = created["version"]["definition"]
    d["universe"] = {"kind": "symbols", "symbols": ["RELIANCE", "TCS"]}
    r = client.post(f"/api/strategies/{created['strategy']['id']}/versions", json={"definition": d})
    vid = r.json()["version"]["id"]
    r = client.post("/api/paper/sessions", json={"strategy_version_id": vid})
    assert r.status_code == 201, r.json()
    sid = r.json()["session_id"]
    deadline = time.monotonic() + 60
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/paper/sessions/{sid}").json()["session"]
        if body["state"] == "stopped":
            break
        time.sleep(0.1)
    assert body["state"] == "stopped", body
    assert body["mode"] == "replay"
    assert body["equity_curve"] and body["fills"] and body["closed_trades"]
    kinds = [e["kind"] for e in body["events"]]
    assert "started" in kinds and "stopped" in kinds
    listed = client.get("/api/paper/sessions").json()
    assert listed["mode"] == "replay" and listed["sessions"][0]["id"] == sid

    cmp = client.get(f"/api/paper/sessions/{sid}/vs-backtest").json()
    assert cmp["ready"] is True
    assert cmp["live"]["trades"] == cmp["backtest"]["trades"] == cmp["matched_trades"]
    assert cmp["reasons"] == ["Paper trading and the backtest made exactly the same trades."]
    assert [s["label"] for s in cmp["series"]] == ["Paper trading", "Backtest"]

    inst = body["instruments"][0]
    candles = client.get(
        f"/api/paper/sessions/{sid}/candles", params={"instrument_id": inst["id"]}
    ).json()
    assert candles["bars"] and candles["bars"][-1]["ts"] <= body["now"]
    # stopped sessions can't be controlled
    r = client.post(f"/api/paper/sessions/{sid}/pause")
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "This paper session has already stopped."


def test_controls_on_a_manual_session(client: TestClient, ctx: AppContext) -> None:
    ctx.paper.threaded = False
    vid = make_strategy(client)["version"]["id"]
    sid = client.post("/api/paper/sessions", json={"strategy_version_id": vid}).json()["session_id"]
    runner = ctx.paper.runner(sid)
    assert runner is not None and runner._boot()
    for _ in range(5):
        runner.replay_step()
    s = client.post(f"/api/paper/sessions/{sid}/pause").json()["session"]
    assert s["state"] == "paused_user"
    s = client.post(f"/api/paper/sessions/{sid}/resume").json()["session"]
    assert s["state"] == "running"
    assert s["freshness"]["level"] in ("green", "amber", "closed")
    early = client.get(f"/api/paper/sessions/{sid}/vs-backtest").json()
    assert early["ready"] is False and "trading days" in early["message"]
    s = client.post(f"/api/paper/sessions/{sid}/stop").json()["session"]
    assert s["state"] == "stopped" and s["stopped_at"]


def test_bad_requests(client: TestClient) -> None:
    r = client.post("/api/paper/sessions", json={"strategy_version_id": 999})
    assert r.status_code == 404
    vid = make_strategy(client)["version"]["id"]
    acct = client.post("/api/paper/accounts", json={"market": "US"}).json()["account"]
    r = client.post(
        "/api/paper/sessions", json={"strategy_version_id": vid, "account_id": acct["id"]}
    )
    assert r.status_code == 422
    assert "different market" in r.json()["error"]["message"]
    assert client.get("/api/paper/sessions/999").status_code == 404


def test_websocket_pushes_events(client: TestClient, ctx: AppContext) -> None:
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        deadline = time.monotonic() + 5
        while ctx.events.subscriber_count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        ctx.events.publish("paper.tick", {"session_id": 1, "equity": 100.0})
        msg = ws.receive_json()
        assert msg == {"type": "paper.tick", "data": {"session_id": 1, "equity": 100.0}}
    deadline = time.monotonic() + 5
    while ctx.events.subscriber_count and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ctx.events.subscriber_count == 0


def test_the_tab_count_and_boot_id(client: TestClient) -> None:
    """The launcher asks how many tabs are connected; the hello carries the start (D-111)."""
    assert client.get("/api/tabs").json()["tabs"] == 0
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["data"]["boot_id"] > 0
        assert client.get("/api/tabs").json() == {"tabs": 1, "boot_id": hello["data"]["boot_id"]}
    assert client.get("/api/tabs").json()["tabs"] == 0
