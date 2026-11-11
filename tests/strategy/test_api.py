from __future__ import annotations

from fastapi.testclient import TestClient


def test_indicator_catalog(client: TestClient) -> None:
    body = client.get("/api/indicators").json()
    keys = {i["key"] for i in body["indicators"]}
    assert {"sma", "rsi", "vwap", "opening_range", "high_52w", "prev_day"} <= keys
    rsi = next(i for i in body["indicators"] if i["key"] == "rsi")
    assert rsi["params"][0] == {
        "name": "period",
        "label": "Length (candles)",
        "default": 14,
        "min": 1,
        "max": 500,
        "type": "int",
    }


def test_templates(client: TestClient) -> None:
    items = client.get("/api/templates").json()["templates"]
    # the eight starters + 20 world classics (D-67), then the three rankings (D-91)
    assert len(items) == 31
    assert [t["kind"] for t in items].count("ranking") == 3
    for key in ("opening_range_breakout", "vwap_pullback"):  # intraday ones move to NY hours
        us = client.get(f"/api/templates/{key}", params={"market": "US"}).json()
        assert us["definition"]["product"] == "cash"
        assert us["definition"]["exit"]["exit_time"] == "15:45"
        assert us["definition"]["entry"]["long"]["conditions"][0]["after"] == "09:45"
    assert client.get("/api/templates/nope").status_code == 404


def test_validate_endpoint(client: TestClient) -> None:
    good = client.get("/api/templates/ma_crossover").json()["definition"]
    assert client.post("/api/strategies/validate", json={"definition": good}).json()["ok"] is True
    bad = {**good, "universe": {"kind": "symbols", "symbols": ["NOTREAL"]}}
    body = client.post("/api/strategies/validate", json={"definition": bad}).json()
    assert body["ok"] is False
    assert body["issues"][0]["message"] == "Agora doesn't know the stock NOTREAL."
    assert body["issues"][0]["hint"] == "Pick it from the list."


def test_indicator_values_for_the_charts_screen(client: TestClient) -> None:
    inst = next(
        i
        for i in client.get("/api/instruments?market=IN").json()["instruments"]
        if i["symbol"] == "RELIANCE"
    )
    start = 1_735_689_600_000  # 2025-01-01
    client.get(
        "/api/candles",
        params={"instrument_id": inst["id"], "start": start - 400 * 86_400_000, "fetch": True},
    )
    r = client.get(
        "/api/indicators/bollinger/values",
        params={"instrument_id": inst["id"], "start": start, "params": '{"period": 20}'},
    ).json()
    assert r["label"] and r["params"]["period"] == 20
    assert set(r["outputs"]) >= {"upper", "lower"}
    upper = r["outputs"]["upper"]
    assert upper and upper[0]["ts"] >= start, "warmed up before the first value shown"
    assert (
        client.get("/api/indicators/nope/values", params={"instrument_id": inst["id"]}).status_code
        == 404
    )
    bad = client.get(
        "/api/indicators/sma/values", params={"instrument_id": inst["id"], "params": '{"zz": 1}'}
    )
    assert bad.status_code == 422
