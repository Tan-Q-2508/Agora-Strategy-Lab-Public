from __future__ import annotations

from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import service, store
from tests.data.helpers import wait_job


def test_instrument_search(client: TestClient) -> None:
    body = client.get("/api/instruments", params={"market": "IN", "q": "relia"}).json()
    assert [i["symbol"] for i in body["instruments"]] == ["RELIANCE"]


def test_refresh_job_then_coverage(client: TestClient) -> None:
    before = client.get("/api/data/coverage", params={"market": "US"}).json()
    assert before["totals"]["empty"] == before["totals"]["symbols"] >= 10
    job = client.post(
        "/api/data/refresh", json={"symbols": ["SPY", "AAPL"], "market": "US"}
    ).json()
    done = wait_job(client, job["job_id"])
    assert done["status"] == "done", done
    assert done["result"]["symbols"] == 2 and done["result"]["failed"] == []
    cov = client.get("/api/data/coverage", params={"market": "US"}).json()
    rows = {r["symbol"]: r for r in cov["rows"]}
    # stock by stock, only the ones with something wrong; the totals cover the whole set
    assert "SPY" not in rows and cov["totals"]["ok"] == 2
    assert rows["MSFT"]["status"] == "empty"
    assert cov["data_mode"] == "fake" and cov["last_update"] is not None


def test_coverage_reports_gaps(client: TestClient) -> None:
    wait_job(client, client.post("/api/data/refresh", json={"symbols": ["TCS"]}).json()["job_id"])
    rows = client.get("/api/data/coverage", params={"market": "IN"}).json()["rows"]
    tcs = next(r for r in rows if r["symbol"] == "TCS")
    assert tcs["status"] == "gaps" and tcs["gaps"] == 3


def test_candles_adjusted_and_raw(client: TestClient, ctx: AppContext) -> None:
    rel = client.get("/api/instruments", params={"q": "RELIANCE"}).json()["instruments"][0]
    params = {"instrument_id": rel["id"], "timeframe": "1d", "fetch": True}
    adj = client.get("/api/candles", params=params).json()
    raw = client.get("/api/candles", params={**params, "adjusted": False}).json()
    assert adj["bars"][0]["close"] * 2 == raw["bars"][0]["close"]  # 2:1 split in 2020
    assert adj["bars"][-1]["close"] == raw["bars"][-1]["close"]


def test_intraday_coverage_counts_days(client: TestClient, ctx: AppContext) -> None:
    wait_job(
        client,
        client.post("/api/data/refresh", json={"symbols": ["AAPL"], "timeframes": ["5m"]}).json()["job_id"],
    )
    cov = client.get("/api/data/coverage", params={"market": "US", "timeframe": "5m"}).json()
    assert cov["totals"]["ok"] == 1
    # The default window is Yahoo's: 59 calendar days back (≈41 sessions of the 60 in the fixture).
    with ctx.db.session() as s:
        inst = store.find_instrument(s, Market.US, "AAPL")
        assert inst is not None and service.intraday_days(s, inst, Timeframe.M5) == 41


def test_add_and_remove_us_ticker(client: TestClient, ctx: AppContext) -> None:
    bad = client.post("/api/instruments", json={"symbol": "NOPE"})
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "TICKER_NOT_FOUND"
    assert client.post("/api/instruments", json={"symbol": "$$"}).status_code == 422
    # The fake source knows MSFT; pretend the user removed it, then adds it back.
    msft = client.get("/api/instruments", params={"q": "MSFT"}).json()["instruments"][0]
    assert client.delete(f"/api/instruments/{msft['id']}").status_code == 200
    assert client.get("/api/instruments", params={"q": "MSFT"}).json()["instruments"] == []
    added = client.post("/api/instruments", json={"symbol": "msft"})
    assert added.status_code == 201
    assert wait_job(client, added.json()["job_id"])["status"] == "done"
    spy = client.get("/api/instruments", params={"q": "SPY"}).json()["instruments"][0]
    assert client.delete(f"/api/instruments/{spy['id']}").status_code == 409


def test_universes_and_history_import(client: TestClient) -> None:
    unis = {u["name"]: u for u in client.get("/api/universes").json()["universes"]}
    nifty = unis["NIFTY50"]
    assert nifty["members"] == 50 and nifty["has_history"] is False
    csv = "symbol,start_date,end_date\nRELIANCE,2010-01-01,\nOLDCO,2010-01-01,2018-03-29\n"
    rep = client.post(f"/api/universes/{nifty['id']}/import-history", json={"csv": csv}).json()
    assert rep == {"rows": 2, "instruments_added": 1, "problems": []}
    in_2017 = client.get(
        f"/api/universes/{nifty['id']}/members", params={"as_of": 1_483_228_800_000}
    ).json()["members"]
    assert {m["symbol"] for m in in_2017} == {"RELIANCE", "OLDCO"}
    now = client.get(f"/api/universes/{nifty['id']}/members").json()["members"]
    assert {m["symbol"] for m in now} == {"RELIANCE"}
    bad = client.post(f"/api/universes/{nifty['id']}/import-history", json={"csv": "a,b\n1,2"})
    assert bad.status_code == 422


def test_sources_and_jobs_endpoints(client: TestClient) -> None:
    wait_job(client, client.post("/api/data/refresh", json={"symbols": ["ITC"]}).json()["job_id"])
    body = client.get("/api/data/sources").json()
    assert body["sources"][0]["source"] == "fake" and body["sources"][0]["state"] == "ok"
    assert body["recent"][0]["symbol"] == "ITC"
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs", params={"kind": "data_refresh"}).json()["jobs"]


def test_bad_timeframe_is_plain_english(client: TestClient) -> None:
    r = client.get("/api/data/coverage", params={"timeframe": "3m"})
    assert r.status_code == 422 and "timeframe" in r.json()["error"]["message"]


def test_full_history_keeps_saved_intraday_beyond_the_window(
    client: TestClient, ctx: AppContext
) -> None:
    """Charts ask for ``full``: every candle there is, including intraday candles Agora
    saved before Yahoo's window moved past them."""
    aapl = client.get("/api/instruments", params={"q": "AAPL"}).json()["instruments"][0]
    p = {"instrument_id": aapl["id"], "timeframe": "5m"}
    saved = client.get("/api/candles", params={**p, "fetch": True, "full": True}).json()["bars"]
    assert saved
    ctx.clock.advance(30 * 86_400_000)  # type: ignore[attr-defined]
    recent = client.get("/api/candles", params=p).json()["bars"]
    full = client.get("/api/candles", params={**p, "full": True}).json()["bars"]
    assert len(recent) < len(saved)
    assert full[0]["ts"] == saved[0]["ts"] and len(full) == len(saved)


def test_full_daily_history_reaches_the_oldest_candle(client: TestClient) -> None:
    spy = client.get("/api/instruments", params={"q": "SPY"}).json()["instruments"][0]
    p = {"instrument_id": spy["id"], "timeframe": "1d", "fetch": True}
    full = client.get("/api/candles", params={**p, "full": True, "limit": 50_000}).json()
    usual = client.get("/api/candles", params=p).json()
    assert full["note"] is None
    assert full["bars"][0]["ts"] <= usual["bars"][0]["ts"]
    assert full["bars"][-1]["ts"] == usual["bars"][-1]["ts"]


def test_refresh_saved_scope_covers_every_saved_stock(client: TestClient, ctx: AppContext) -> None:
    """"Refresh now" on the Data screen updates every stock with saved prices, not only the
    starter list (the user's request 2026-10-24, D-107)."""
    from backend.core.types import Market, Timeframe
    from backend.data import service

    from sqlalchemy import delete

    from backend.db.models import UniverseMember

    msft = client.get("/api/instruments", params={"q": "MSFT"}).json()["instruments"][0]
    wait_job(client, client.post("/api/data/refresh", json={"instrument_ids": [msft["id"]]}).json()["job_id"])
    with ctx.db.session() as s:  # MSFT leaves the starter list but keeps its saved prices
        s.execute(delete(UniverseMember).where(UniverseMember.instrument_id == msft["id"]))
    with ctx.db.session() as s:
        listed = {i.id for i in service.default_symbols(s, Market.US)}
    extra = msft
    with ctx.db.session() as s:
        saved = {i.id for i in service.saved_symbols(s, Market.US, Timeframe.D1)}
    assert listed < saved and extra["id"] in saved
    job = client.post("/api/data/refresh", json={"market": "US", "scope": "saved"}).json()
    done = wait_job(client, job["job_id"])
    assert done["status"] == "done" and done["result"]["symbols"] == len(saved)


def test_running_jobs_can_be_found_again(client: TestClient) -> None:
    job = client.post("/api/data/refresh", json={"symbols": ["MSFT"], "market": "US"}).json()
    listed = client.get("/api/jobs", params={"kind": "data_refresh,metis_round"}).json()["jobs"]
    assert listed[0]["job_id"] == job["job_id"] and listed[0]["created_at"] > 0
    wait_job(client, job["job_id"])
    active = client.get("/api/jobs", params={"kind": "data_refresh", "active": True}).json()
    assert all(j["job_id"] != job["job_id"] for j in active["jobs"])
