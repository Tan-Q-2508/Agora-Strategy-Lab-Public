"""The Indices page's data (D-174)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.watchlists import catalog


def test_every_index_is_listed_by_group(client: TestClient, ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    for market in ("IN", "US"):
        body = client.get(f"/api/indices?market={market}").json()
        assert [g["key"] for g in body["groups"]] == ["broad", "sector", "gauge"]
        listed = {r["symbol"] for g in body["groups"] for r in g["indices"]}
        assert listed == {x[1] for x in catalog.INDICES if x[0] == market}
        sectors = next(g for g in body["groups"] if g["key"] == "sector")["indices"]
        assert len(sectors) >= 10  # sector indices, as the user asked


def test_an_index_with_prices_has_its_changes(client: TestClient, ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    body = client.get("/api/indices?market=IN").json()
    rows = [r for g in body["groups"] for r in g["indices"] if r.get("value") is not None]
    for r in rows:
        assert r["spark"] and r["spark"][-1] == r["value"]
        assert "change_pct" in r and "ytd_pct" in r
