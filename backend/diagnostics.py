"""Settings → Diagnostics (RUNBOOK §5–6): versions and paths, recent app events, live data
checks, the log folder, and a support bundle the user can hand to a Claude Code session.

There are no secrets anywhere in Agora (no accounts, no keys), so the bundle leaves nothing
out; it only skips market data and the database itself, which are large and not needed.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.config import REPO_ROOT, Paths
from backend.db.models import (
    AppEvent,
    BacktestRun,
    DataFetchLog,
    PaperSession,
    SettingRow,
    SourceStatus,
)
from backend.logging_setup import get_logger
from backend.version import APP_VERSION

log = get_logger("diagnostics")

LIVE_TESTS: dict[str, str] = {
    "test_yahoo_daily_india_and_us": "Yahoo Finance: daily prices (India and US)",
    "test_yahoo_intraday": "Yahoo Finance: intraday prices",
    "test_yahoo_latest_bars_for_paper_trading": "Yahoo Finance: live prices for paper trading",
    "test_nse_bhavcopy": "NSE end-of-day files (India backup)",
    "test_stooq_daily": "Stooq daily prices (US backup)",
    "test_ollama_answers_when_installed": "AI helper (Ollama on this laptop)",
    "test_world_news_feeds": "World news feeds (BBC, Al Jazeera, Guardian, NYT, RBI, Fed…)",
    "test_gdelt_news_api": "GDELT world news search",
}
LIVE_TIMEOUT_S = 300

TROUBLESHOOTING: list[dict[str, str]] = [
    {
        "symptom": "The browser says it can't connect",
        "fix": "Agora isn't running. Double-click Start Agora again.",
    },
    {
        "symptom": "“Yahoo is limiting requests”",
        "fix": "Agora uses saved prices meanwhile and retries by itself in about 15 minutes.",
    },
    {
        "symptom": "Paper trading stopped updating",
        "fix": "Usually a data outage or the laptop slept. The freshness badge turns red and "
        "the session picks up again by itself once prices arrive.",
    },
    {
        "symptom": "The AI helper isn't available",
        "fix": "Open Settings → AI helper; it shows the exact next step. Everything else "
        "works without it.",
    },
    {
        "symptom": "“Another program is using Agora's port”",
        "fix": "Close the other program or restart your computer, then start Agora again.",
    },
    {
        "symptom": "Prices stopped downloading for everything",
        "fix": "Run the live data checks below. If Yahoo fails, Yahoo may have changed; "
        "pull the latest Agora version in GitHub Desktop (fixes come with updates).",
    },
]


def record_event(db: Any, now_ms: int, level: str, area: str, message: str, **detail: Any) -> None:
    """Write a plain-English line to ``app_events`` (shown in Diagnostics and the bundle)."""
    try:
        with db.session() as s:
            s.add(
                AppEvent(
                    ts=now_ms,
                    level=level,
                    area=area,
                    message_plain=message,
                    detail=json.dumps(detail, default=str),
                )
            )
    except Exception:  # diagnostics must never cause a failure of their own
        log.exception("Couldn't record an app event")


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def info(ctx: Any) -> dict[str, Any]:
    paths = ctx.paths
    with ctx.db.session() as s:
        events = s.scalars(select(AppEvent).order_by(AppEvent.id.desc()).limit(50)).all()
        recent = [
            {"ts": e.ts, "level": e.level, "area": e.area, "message_plain": e.message_plain}
            for e in events
        ]
    ai = ctx.ai_service.status() if ctx.ai is not None else None
    return {
        "versions": {
            "agora": APP_VERSION,
            "python": platform.python_version(),
            "system": f"{platform.system()} {platform.release()}",
            "yfinance": _version("yfinance"),
            "fastapi": _version("fastapi"),
            "ollama": ai["version"] if ai else None,
        },
        "paths": {
            "data": str(paths.data_dir),
            "logs": str(paths.logs_dir),
            "database_mb": round(_size(paths.db_file) / 1e6, 1),
        },
        "data_mode": ctx.data_mode,
        "events": recent,
        "troubleshooting": TROUBLESHOOTING,
        "live_tests": [{"name": k, "label": v} for k, v in LIVE_TESTS.items()],
    }


# ---------------------------------------------------------------- support bundle


def support_bundle(ctx: Any) -> Path:
    paths: Paths = ctx.paths
    out_dir = paths.data_dir / "support"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"agora-support-{stamp}.zip"
    with ctx.db.session() as s:
        settings = {r.key: r.value for r in s.scalars(select(SettingRow))}
        events = [
            {
                "ts": e.ts,
                "level": e.level,
                "area": e.area,
                "message": e.message_plain,
                "detail": e.detail,
            }
            for e in s.scalars(select(AppEvent).order_by(AppEvent.id.desc()).limit(500))
        ]
        fetches = [
            {
                "source": f.source,
                "instrument_id": f.instrument_id,
                "timeframe": f.timeframe,
                "range": [f.range_start, f.range_end],
                "status": f.status,
                "rows": f.rows,
                "message": f.message,
                "started_at": f.started_at,
            }
            for f in s.scalars(select(DataFetchLog).order_by(DataFetchLog.id.desc()).limit(500))
        ]
        sources = [
            {"source": r.source, "state": r.state, "until": r.until, "last_error": r.last_error}
            for r in s.scalars(select(SourceStatus))
        ]
        failed_runs = [
            {"id": r.id, "error": r.error_plain, "detail": r.error_detail, "params": r.params}
            for r in s.scalars(
                select(BacktestRun)
                .where(BacktestRun.status == "failed")
                .order_by(BacktestRun.id.desc())
                .limit(20)
            )
        ]
        sessions = [
            {"id": p.id, "state": p.state, "started_at": p.started_at, "notes": p.notes[:4000]}
            for p in s.scalars(select(PaperSession).order_by(PaperSession.id.desc()).limit(20))
        ]
    about = {**info(ctx), "created_at": stamp}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.json", json.dumps(about, indent=2, default=str))
        z.writestr("settings.json", json.dumps(settings, indent=2))
        z.writestr("app_events.json", json.dumps(events, indent=2))
        z.writestr("data_fetch_log.json", json.dumps(fetches, indent=2))
        z.writestr("data_sources.json", json.dumps(sources, indent=2))
        z.writestr("failed_backtests.json", json.dumps(failed_runs, indent=2))
        z.writestr("paper_sessions.json", json.dumps(sessions, indent=2))
        if paths.logs_dir.is_dir():
            for f in sorted(paths.logs_dir.iterdir()):
                if f.is_file():
                    z.write(f, f"logs/{f.name}")
    log.info("Support bundle written to %s", target)
    return target


# ---------------------------------------------------------------- open a folder


def open_folder(path: Path, runner: Callable[[list[str]], Any] | None = None) -> None:
    """Show a folder in Explorer / Finder. Agora runs on the user's own laptop, so this
    opens a window there (never anywhere else)."""
    path.mkdir(parents=True, exist_ok=True)
    if runner is None and sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined,unused-ignore]
        return
    cmd = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    (runner or (lambda c: subprocess.Popen(c)))(cmd)


# ---------------------------------------------------------------- live checks

_LINE = re.compile(r"^(PASSED|FAILED|SKIPPED|ERROR)\s+(\S+?)(?:::(\w+))?(?:\s+-\s+(.*))?$")


def parse_pytest(output: str) -> list[dict[str, Any]]:
    """The ``-rA`` summary lines → one plain result per check."""
    results: dict[str, dict[str, Any]] = {}
    for raw in output.splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            continue
        outcome, _location, name, reason = m.groups()
        if name is None:  # "SKIPPED [1] file:line: reason" style
            continue
        results[name] = {
            "name": name,
            "label": LIVE_TESTS.get(name, name.replace("_", " ")),
            "outcome": {"PASSED": "passed", "FAILED": "failed", "SKIPPED": "skipped"}.get(
                outcome, "failed"
            ),
            "detail": (reason or "").strip()[:500],
        }
    for raw in output.splitlines():  # skip reasons: "SKIPPED [1] tests/live/x.py:13: why"
        m2 = re.match(r"^SKIPPED \[\d+\] (\S+?):\d+: (.*)$", raw.strip())
        if m2:
            for r in results.values():
                if r["outcome"] == "skipped" and not r["detail"]:
                    r["detail"] = m2.group(2)
    order = list(LIVE_TESTS)
    return sorted(
        results.values(), key=lambda r: order.index(r["name"]) if r["name"] in order else 99
    )


def run_live_tests(
    job: Any, runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
) -> dict[str, Any]:
    job.progress(5, "Checking Yahoo, NSE, Stooq and the AI helper… (about a minute)")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/live",
        "-m",
        "live",
        "-q",
        "-rA",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]

    def default(c: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            c, cwd=REPO_ROOT, capture_output=True, text=True, timeout=LIVE_TIMEOUT_S, check=False
        )

    try:
        proc = (runner or default)(cmd)
    except subprocess.TimeoutExpired:
        return {
            "results": [],
            "summary": "The checks took too long, which usually means the internet is very slow.",
        }
    results = parse_pytest(proc.stdout + "\n" + proc.stderr)
    failed = [r for r in results if r["outcome"] == "failed"]
    if not results:
        summary = "The checks couldn't run. Create a support bundle and share it in a session."
    elif failed:
        summary = f"{len(failed)} check(s) failed: " + ", ".join(r["label"] for r in failed) + "."
    else:
        summary = "Everything Agora connects to is answering."
    return {"results": results, "summary": summary, "output": proc.stdout[-4000:]}
