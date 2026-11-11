"""End to end: create a strategy from a template, backtest it in every mode, read results."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.db.models import BacktestRun

Y2018 = 1_514_764_800_000
Y2022 = 1_640_995_200_000
Y2026 = 1_767_225_600_000


def wait_run(client: TestClient, run_id: int, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, Any] = client.get(f"/api/backtests/{run_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("backtest did not finish")


def make_strategy(
    client: TestClient, key: str = "ma_crossover", market: str = "IN"
) -> dict[str, Any]:
    r = client.post(
        "/api/strategies", json={"name": "My MA", "market": market, "template_key": key}
    )
    assert r.status_code == 201, r.json()
    body: dict[str, Any] = r.json()
    return body


def start(client: TestClient, **body: Any) -> int:
    r = client.post("/api/backtests", json=body)
    assert r.status_code == 202, r.json()
    run_id: int = r.json()["run_id"]
    return run_id


def test_strategy_library_and_versions(client: TestClient) -> None:
    created = make_strategy(client)
    sid = created["strategy"]["id"]
    assert created["version"]["version"] == 1
    d = created["version"]["definition"]
    # Saving the same rules doesn't make a new version; a change does.
    same = client.post(f"/api/strategies/{sid}/versions", json={"definition": d}).json()
    assert same["version"]["version"] == 1
    d2 = {**d, "sizing": {"kind": "percent_equity", "value": 20}}
    v2 = client.post(
        f"/api/strategies/{sid}/versions", json={"definition": d2, "note": "bigger"}
    ).json()
    assert v2["version"]["version"] == 2
    bad = {**d, "entry": {}}
    r = client.post(f"/api/strategies/{sid}/versions", json={"definition": bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_STRATEGY"
    assert len(client.get(f"/api/strategies/{sid}/versions").json()["versions"]) == 2
    dup = client.post(f"/api/strategies/{sid}/duplicate").json()
    assert dup["strategy"]["name"] == "My MA (copy)"
    code = client.post(f"/api/strategies/{sid}/to-code").json()
    assert (
        code["strategy"]["kind"] == "code"
        and "def on_bar(ctx):" in code["version"]["definition"]["code"]
    )
    client.patch(f"/api/strategies/{sid}", json={"name": "Renamed"})
    client.delete(f"/api/strategies/{dup['strategy']['id']}")
    names = [s["name"] for s in client.get("/api/strategies").json()["strategies"]]
    assert "Renamed" in names and "My MA (copy)" not in names


def test_preview_shows_signals(client: TestClient) -> None:
    created = make_strategy(client, "ma_crossover", "US")
    d = created["version"]["definition"]
    spy = client.get("/api/instruments", params={"q": "SPY"}).json()["instruments"][0]
    body = client.post(
        "/api/strategies/preview", json={"definition": d, "instrument_id": spy["id"], "days": 400}
    ).json()
    assert body["ok"] and body["bars"] and body["signals"]
    assert {s["action"] for s in body["signals"]} <= {"buy", "sell"}


def test_single_backtest_end_to_end(client: TestClient) -> None:
    created = make_strategy(client, "rsi_mean_reversion", "IN")
    vid = created["version"]["id"]
    run_id = start(
        client, strategy_version_id=vid, symbols=["RELIANCE", "INFY", "TCS"], start=Y2018, end=Y2026
    )
    body = wait_run(client, run_id)
    assert body["status"] == "done", body
    m = body["metrics"]
    assert m["trades"] > 0 and m["benchmark"]["total_return"] is not None
    assert body["summary"].startswith("This strategy ")
    codes = {w["code"] for w in body["warnings"]}
    assert "practice_data" in codes
    assert body["repro"]["content_hash"] == created["version"]["content_hash"]
    assert body["repro"]["charge_schedule_ids"]
    eq = client.get(f"/api/backtests/{run_id}/equity").json()
    assert eq["points"] and eq["benchmark"]
    tr = client.get(
        f"/api/backtests/{run_id}/trades", params={"sort": "net_pnl", "order": "desc", "limit": 5}
    ).json()
    assert tr["total"] >= len(tr["trades"]) > 0
    assert tr["trades"][0]["net_pnl"] >= tr["trades"][-1]["net_pnl"]
    csv = client.get(f"/api/backtests/{run_id}/trades.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("Symbol,Side,Quantity")
    assert (
        client.patch(f"/api/backtests/{run_id}", json={"starred": True}).json()["starred"] is True
    )
    listed = client.get("/api/backtests").json()["backtests"]
    assert listed[0]["id"] == run_id and listed[0]["headline"]["trades"] == m["trades"]
    lib = client.get("/api/strategies").json()["strategies"]
    assert lib[0]["last_backtest"]["run_id"] == run_id and lib[0]["last_backtest"]["points"]


def test_universe_all_shows_survivorship_badge(client: TestClient) -> None:
    created = make_strategy(client, "ma_crossover", "IN")
    run_id = start(client, strategy_version_id=created["version"]["id"], start=Y2022, end=Y2026)
    body = wait_run(client, run_id)
    assert body["status"] == "done", body
    codes = {w["code"] for w in body["warnings"]}
    assert "survivorship" in codes and "no_data" in codes  # 40 of the 50 have no fixture data


def test_oos_sweep_and_walk_forward(client: TestClient) -> None:
    created = make_strategy(client, "ma_crossover", "US")
    vid = created["version"]["id"]
    common = {"strategy_version_id": vid, "symbols": ["AAPL", "SPY"], "start": Y2018, "end": Y2026}
    oos = wait_run(client, start(client, **common, mode="oos", oos_fraction=0.6))
    periods = oos["metrics"]["periods"]
    assert (
        periods["in_sample"]["total_return"] is not None
        and periods["out_of_sample"]["total_return"] is not None
    )
    sweep = wait_run(
        client,
        start(
            client,
            **common,
            mode="sweep",
            sweep={
                "params": [
                    {"name": "fast", "values": [10, 20]},
                    {"name": "slow", "values": [50, 100]},
                ]
            },
        ),
    )
    assert sweep["status"] == "done", sweep
    cells = sweep["metrics"]["sweep"]["cells"]
    assert len(cells) == 4 and sweep["metrics"]["sweep"]["best"] in [c["overrides"] for c in cells]
    # D-89: the chance the best cell is just the luckiest, and the luck check over 4 settings
    pbo = sweep["metrics"]["sweep"]["pbo"]
    assert pbo["tries"] == 4 and 0.0 <= pbo["pbo"] <= 1.0 and pbo["combinations"] == 12_870
    assert pbo["text"].startswith("Probability of backtest overfitting: ")
    assert sweep["metrics"]["tear_sheet"]["sharpe"]["trials"] == 4
    assert ("overfit" in {w["code"] for w in sweep["warnings"]}) == (pbo["pbo"] >= 0.5)
    kids = client.get(f"/api/backtests/{sweep['id']}/children").json()["children"]
    assert len(kids) == 4 and all(k["parent_run_id"] == sweep["id"] for k in kids)
    wf = wait_run(
        client,
        start(
            client,
            **common,
            mode="walk_forward",
            walk_forward={
                "train_days": 730,
                "test_days": 365,
                "params": [{"name": "fast", "values": [10, 20]}],
            },
        ),
    )
    assert wf["status"] == "done", wf
    windows = wf["metrics"]["walk_forward"]["windows"]
    assert len(windows) >= 4 and all(w["best"]["fast"] in (10, 20) for w in windows)
    cmp = client.post(
        "/api/backtests/compare", json={"run_ids": [oos["id"], sweep["id"], wf["id"]]}
    ).json()
    assert len(cmp["series"]) == 3 and cmp["series"][0]["points"][0]["value"] > 0


def test_code_strategy_errors_fail_plainly(client: TestClient) -> None:
    created = make_strategy(client, "ma_crossover", "US")
    d = {
        **created["version"]["definition"],
        "kind": "code",
        "code": "def on_bar(ctx):\n    x = 1 / 0\n",
    }
    for k in ("entry", "exit"):
        d.pop(k)
    sid = created["strategy"]["id"]
    v = client.post(f"/api/strategies/{sid}/versions", json={"definition": d}).json()["version"]
    body = wait_run(
        client, start(client, strategy_version_id=v["id"], symbols=["SPY"], start=Y2022, end=Y2026)
    )
    assert body["status"] == "failed"
    assert body["error"].startswith("Your strategy code stopped: Line 2: ZeroDivisionError")


def test_bad_requests(client: TestClient) -> None:
    created = make_strategy(client)
    vid = created["version"]["id"]
    r = client.post("/api/backtests", json={"strategy_version_id": vid, "symbols": ["NOPE"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_SYMBOLS"
    r = client.post(
        "/api/backtests", json={"strategy_version_id": vid, "start": Y2026, "end": Y2022}
    )
    assert r.json()["error"]["code"] == "BAD_DATES"
    r = client.post(
        "/api/backtests",
        json={
            "strategy_version_id": vid,
            "mode": "sweep",
            "sweep": {"params": [{"name": "zzz", "values": [1]}]},
        },
    )
    assert r.json()["error"]["code"] == "BAD_PARAM"
    assert client.get("/api/backtests/99999").status_code == 404


def test_interrupted_runs_are_marked_failed_on_start(ctx: AppContext) -> None:
    from backend.strategy import service
    from backend.strategy.templates import template_definition

    with ctx.db.session() as s:
        _, v = service.create(
            s, name="X", description="", definition=template_definition("ma_crossover", "IN"), now=0
        )
        s.add(BacktestRun(strategy_version_id=v.id, status="running", params="{}", created_at=0))
    ctx.backtests.recover()
    with ctx.db.session() as s:
        row = s.query(BacktestRun).one()
        assert row.status == "failed" and "closed while" in (row.error_plain or "")


def test_cost_profiles_by_market(client: TestClient) -> None:
    r = client.get("/api/costs/profiles", params={"market": "IN"})
    assert r.status_code == 200
    body = r.json()
    assert body["brokerage"] and all(p["market"] == "IN" for p in body["brokerage"])
    assert sum(p["is_default"] for p in body["brokerage"]) == 1
    assert body["slippage"] and all(p["market"] == "IN" for p in body["slippage"])
    every = client.get("/api/costs/profiles").json()
    assert {p["market"] for p in every["brokerage"]} == {"IN", "US"}


def test_tear_sheet_is_saved_and_served(client: TestClient, ctx: AppContext) -> None:
    """Every run saves its tear sheet (D-89); older runs get one worked out from their rows."""
    created = make_strategy(client, "rsi_mean_reversion", "IN")
    run_id = start(
        client,
        strategy_version_id=created["version"]["id"],
        symbols=["RELIANCE", "INFY"],
        start=Y2018,
        end=Y2026,
    )
    body = wait_run(client, run_id)
    sheet = body["metrics"]["tear_sheet"]
    assert sheet["days"] > 1000 and sheet["sharpe"]["dsr"] is None
    assert sheet["trade_order"]["trades"] == body["metrics"]["trades"]
    assert client.get(f"/api/backtests/{run_id}/tearsheet").json() == sheet
    # An older run (saved before Phase 16) has no tear sheet in its metrics.
    import json

    with ctx.db.session() as s:
        row = s.get(BacktestRun, run_id)
        assert row is not None and row.metrics is not None
        m = json.loads(row.metrics)
        del m["tear_sheet"]
        row.metrics = json.dumps(m)
    worked = client.get(f"/api/backtests/{run_id}/tearsheet").json()
    assert worked["sharpe"]["value"] == pytest.approx(sheet["sharpe"]["value"], abs=0.05)
    assert worked["trade_order"]["trades"] == sheet["trade_order"]["trades"]
