"""``/api/analysis``: the Charts screen's Kairos switch, on practice data."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.data.helpers import wait_job


def _load(client: TestClient, symbols: list[str], market: str = "IN") -> dict[str, int]:
    job = client.post("/api/data/refresh", json={"symbols": symbols, "market": market}).json()
    assert wait_job(client, job["job_id"])["status"] == "done"
    found = client.get("/api/instruments", params={"market": market}).json()["instruments"]
    return {i["symbol"]: i["id"] for i in found}


def test_chart_reading_with_forecast_and_peers(client: TestClient) -> None:
    ids = _load(client, ["RELIANCE", "TCS", "INFY", "HDFCBANK"])
    r = client.get("/api/analysis/chart", params={"instrument_id": ids["RELIANCE"]})
    assert r.status_code == 200, r.text
    body = r.json()
    json.dumps(body, allow_nan=False)
    rep = body["report"]
    assert rep["symbol"] == "RELIANCE" and rep["summary"]
    fc = body["forecast"]
    assert fc is not None and fc["peers"] >= 1 and fc["horizon"] == 10
    assert len(fc["path"]) == 11 and fc["path"][1]["ts"] == rep["future"][0]
    assert fc["text"].startswith("Over the next 10 trading days")
    assert "not financial advice" in body["disclaimer"]
    # the second call is served from the cache
    again = client.get("/api/analysis/chart", params={"instrument_id": ids["RELIANCE"]}).json()
    assert again["computed_ms"] == body["computed_ms"]


def test_intraday_chart_reading(client: TestClient) -> None:
    ids = _load(client, ["INFY"])
    job = client.post("/api/data/refresh", json={"symbols": ["INFY"], "timeframes": ["5m"]}).json()
    wait_job(client, job["job_id"])
    r = client.get("/api/analysis/chart", params={"instrument_id": ids["INFY"], "timeframe": "5m"})
    assert r.status_code == 200, r.text
    assert r.json()["forecast"]["horizon"] == 12


def test_not_enough_prices_is_plain_english(client: TestClient) -> None:
    ids = {
        i["symbol"]: i["id"]
        for i in client.get("/api/instruments", params={"market": "US"}).json()["instruments"]
    }
    r = client.get("/api/analysis/chart", params={"instrument_id": ids["MSFT"]})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["message"] == "Kairos needs more prices to read this chart."
    assert "Data screen" in err["action"]


def test_forecast_endpoint(client: TestClient) -> None:
    ids = _load(client, ["AAPL"], "US")
    r = client.get("/api/analysis/forecast", params={"instrument_id": ids["AAPL"], "horizon": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["horizon"] == 5 and body["track"]["tests"] > 10
