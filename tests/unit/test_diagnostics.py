"""Settings → Diagnostics: info, live checks (with a fake pytest run), support bundle."""

from __future__ import annotations

import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.diagnostics import parse_pytest

PYTEST_OUTPUT = """
..sF.s
=========================== short test summary info ============================
PASSED tests/live/test_live_sources.py::test_yahoo_daily_india_and_us
PASSED tests/live/test_live_sources.py::test_yahoo_intraday
FAILED tests/live/test_live_sources.py::test_nse_bhavcopy - EmptyResponse: NSE sent no file
SKIPPED [1] tests/live/test_live_ollama.py:17: Ollama is not installed; the AI helper is optional
PASSED tests/live/test_live_sources.py::test_stooq_daily
"""


def test_parse_pytest_summary_lines() -> None:
    rows = {r["name"]: r for r in parse_pytest(PYTEST_OUTPUT)}
    assert rows["test_yahoo_daily_india_and_us"]["outcome"] == "passed"
    assert rows["test_nse_bhavcopy"]["outcome"] == "failed"
    assert rows["test_nse_bhavcopy"]["label"] == "NSE end-of-day files (India backup)"
    assert "NSE sent no file" in rows["test_nse_bhavcopy"]["detail"]


def test_info_and_startup_event(client: TestClient) -> None:
    body = client.get("/api/diagnostics").json()
    assert body["versions"]["agora"] and body["versions"]["python"]
    assert body["paths"]["logs"].endswith("logs")
    assert any(e["message_plain"].startswith("Agora ") for e in body["events"])
    assert body["troubleshooting"][0]["symptom"] == "The browser says it can't connect"


def test_live_checks_run_as_a_job(client: TestClient, ctx: AppContext) -> None:
    calls: list[list[str]] = []

    def fake(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, PYTEST_OUTPUT, "")

    ctx.services["pytest_runner"] = fake
    job_id = client.post("/api/diagnostics/live-test").json()["job_id"]
    job: dict[str, Any] = {}
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert "-m" in calls[0] and "live" in calls[0]
    result = job["result"]
    assert result["summary"] == "1 check(s) failed: NSE end-of-day files (India backup)."
    assert len(result["results"]) == 4


def test_support_bundle_and_open_folder(client: TestClient, ctx: AppContext) -> None:
    opened: list[list[str]] = []
    ctx.services["folder_opener"] = opened.append
    (ctx.paths.logs_dir / "agora.log").write_text("hello log\n")
    r = client.post("/api/diagnostics/support-bundle").json()
    path = Path(r["path"])
    assert path.is_file() and path.name.startswith("agora-support-")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    assert {"about.json", "settings.json", "app_events.json", "data_fetch_log.json"} <= names
    assert "logs/agora.log" in names
    assert not any(n.endswith(".db") for n in names)
    assert opened and opened[-1][-1] == r["folder"]
    client.post("/api/diagnostics/open-folder", json={"which": "logs"})
    assert opened[-1][-1] == str(ctx.paths.logs_dir)
