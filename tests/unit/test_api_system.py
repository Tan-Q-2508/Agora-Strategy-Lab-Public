from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.main import create_app
from tests.conftest import T0


def test_health_reports_ok(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["app"] == "agora"
    assert body["status"] == "ok"
    assert body["db_ok"] is True
    assert body["ai"] == {"state": "ready", "models": ["qwen3.5:4b"]}
    assert body["server_time"] == T0


def test_health_survives_ai_errors(client: TestClient, ctx: AppContext) -> None:
    class Broken:
        def status(self) -> None:
            raise RuntimeError("ollama exploded")

    ctx.ai = Broken()  # type: ignore[assignment]
    assert client.get("/api/health").json()["ai"] == {"state": "error"}


def test_settings_defaults_have_explanations(client: TestClient) -> None:
    body = client.get("/api/settings").json()
    assert body["values"]["theme"] == "light"
    assert body["values"]["intraday_square_off_time"] == "15:20"
    for key, meta in body["meta"].items():
        assert meta["description"], f"{key} needs a one-line explanation"


def test_settings_update_round_trip(client: TestClient) -> None:
    r = client.put("/api/settings", json={"theme": "dark", "volume_cap_pct": 2.5})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["values"]["theme"] == "dark"
    assert client.get("/api/settings").json()["values"]["volume_cap_pct"] == 2.5


def test_invalid_settings_are_rejected_all_or_nothing(client: TestClient) -> None:
    r = client.put(
        "/api/settings",
        json={"theme": "dark", "intraday_square_off_time": "15:45", "nonsense": 1},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "INVALID_SETTING"
    assert "before 15:30" in err["detail"]
    assert "nonsense" in err["detail"]
    assert client.get("/api/settings").json()["values"]["theme"] == "light"


def test_unknown_api_route_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert set(r.json()["error"]) == {"code", "message", "action", "detail"}


def test_bad_body_uses_error_envelope(client: TestClient) -> None:
    r = client.put(
        "/api/settings", content=b"not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_unexpected_errors_are_plain_english(ctx: AppContext) -> None:
    app = create_app(ctx)

    @app.get("/api/boom")
    def boom() -> None:
        raise ValueError("kaboom")

    # Route order: the SPA catch-all is registered first, so move /api/boom ahead of it.
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/boom")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["message"] == "Something went wrong inside Agora."
    assert "kaboom" in err["detail"]


def test_serves_placeholder_without_built_frontend(ctx: AppContext, tmp_path: Path) -> None:
    from dataclasses import replace

    class NoDist(type(ctx.paths)):  # type: ignore[misc]
        @property
        def frontend_dist(self) -> Path:
            return tmp_path / "missing"

    app = create_app(replace(ctx, paths=NoDist(ctx.paths.data_dir)))
    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "Agora is running" in r.text


def test_serves_built_frontend_with_spa_fallback(ctx: AppContext, tmp_path: Path) -> None:
    from dataclasses import replace

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>INDEX</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")

    class WithDist(type(ctx.paths)):  # type: ignore[misc]
        @property
        def frontend_dist(self) -> Path:
            return dist

    app = create_app(replace(ctx, paths=WithDist(ctx.paths.data_dir)))
    with TestClient(app) as c:
        assert "INDEX" in c.get("/").text
        assert c.get("/").headers["cache-control"] == "no-cache"  # D-137
        assert "INDEX" in c.get("/strategies/12").text  # client-side route
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/favicon.svg").text == "<svg/>"
        assert c.get("/../../etc/passwd").status_code in (200, 404)
        assert "root:" not in c.get("/..%2F..%2Fetc%2Fpasswd").text


def test_health_shows_a_cool_down_that_ran_out_as_ok(client: TestClient, ctx: AppContext) -> None:
    from backend.db.models import SourceStatus

    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        s.add(SourceStatus(source="yahoo", state="cooling_down", until=now - 1, updated_at=now))
        s.add(SourceStatus(source="nse", state="cooling_down", until=now + 60_000, updated_at=now))
    got = {x["source"]: x["state"] for x in client.get("/api/health").json()["data_sources"]}
    assert got == {"yahoo": "ok", "nse": "cooling_down"}


def test_threads_diagnostics_lists_running_threads(client: TestClient) -> None:
    """D-196: a view of where each thread waits, for a desk whose poll is stuck."""
    r = client.get("/api/diagnostics/threads")
    assert r.status_code == 200
    assert any(t["stack"] for t in r.json()["threads"])
