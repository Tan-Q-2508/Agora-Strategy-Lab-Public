"""System endpoints: health and settings (docs/API_CONTRACT.md → System)."""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, text

from backend import actions, settings_store
from backend import diagnostics as diag
from backend.context import AppContext, get_ctx
from backend.db.models import SourceStatus
from backend.errors import AgoraError
from backend.logging_setup import get_logger
from backend.version import APP_VERSION

router = APIRouter()
log = get_logger("api.system")
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _ai_state(ctx: AppContext) -> dict[str, Any]:
    if ctx.ai is None:
        return {"state": "not_checked"}
    try:
        info = ctx.ai_service.status()
    except Exception as exc:  # health must never fail because of the optional AI helper
        log.warning("AI status check failed: %s", exc)
        return {"state": "error"}
    if info["state"] == "error":
        return {"state": "error"}
    return {"state": info["state"], "models": [m["name"] for m in info["models"]]}


@router.get("/health")
def health(ctx: Ctx) -> dict[str, Any]:
    db_ok = True
    sources: list[dict[str, Any]] = []
    try:
        with ctx.db.session() as s:
            s.execute(text("SELECT 1"))
            now = ctx.clock.now_ms()
            for row in s.scalars(select(SourceStatus)):
                # a cool-down that has run out is over, as on the data page
                state = row.state
                if state == "cooling_down" and row.until and row.until <= now:
                    state = "ok"
                sources.append({"source": row.source, "state": state, "until": row.until})
    except Exception as exc:
        log.error("Database health check failed: %s", exc)
        db_ok = False
    return {
        "app": "agora",
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "db_ok": db_ok,
        "data_sources": sources,
        "ai": _ai_state(ctx),
        "server_time": ctx.clock.now_ms(),
    }


def _stopper(agent: str) -> str:
    """Who asked for a stop: a tool's PowerShell also calls itself Mozilla."""
    if "PowerShell" in agent:
        return "tool"
    return "user" if "Mozilla" in agent else "tray"


@router.post("/system/quit")
def system_quit(request: Request) -> dict[str, Any]:
    """Shut Agora down cleanly (the tray's Stop and Restart, D-124). Only from this computer."""
    from backend import launch

    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise AgoraError("FORBIDDEN", "Only this computer can stop Agora.", "", status=403)
    agent = request.headers.get("user-agent", "")[:80]
    log.info("Asked to stop Agora (from %s, %s)", host, agent)
    actions.note("app", "Asked to stop", agent, who=_stopper(agent))
    return {"stopping": launch.request_stop()}


@router.get("/settings")
def get_settings(ctx: Ctx) -> dict[str, Any]:
    with ctx.db.session() as s:
        return {"values": settings_store.read_all(s), "meta": settings_store.describe()}


@router.put("/settings")
def put_settings(ctx: Ctx, changes: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    with ctx.db.session() as s:
        values = settings_store.update(s, changes, ctx.clock)
    log.info("Settings changed: %s", sorted(changes))
    actions.note("settings", "Settings changed", str(changes)[:500], who="user")
    return {"values": values, "meta": settings_store.describe()}


# ---------------------------------------------------------------- the action log (D-220)


@router.get("/alarms")
def alarms(ctx: Ctx) -> dict[str, Any]:
    """What should have happened and didn't (D-222)."""
    from backend.diagnosis import alarms as checks

    return {"alarms": checks.current(ctx)}


@router.get("/actions")
def list_actions(
    q: str = "",
    kind: str = "",
    status: str = "",
    who: str = "",
    hours: float = 24.0,
    limit: int = 200,
) -> dict[str, Any]:
    """Everything Agora did, newest first, searchable."""
    from backend import actions as a

    store = a.current()
    if store is None:
        return {"actions": [], "summary": []}
    since = int(time.time() * 1000 - hours * 3_600_000)
    return {
        "actions": store.search(q, kind, status, who, since, limit),
        "summary": store.summary(since),
    }


# ---------------------------------------------------------------- diagnostics


class OpenFolderIn(BaseModel):
    which: Literal["logs", "support", "data"] = "logs"


@router.get("/diagnostics")
def diagnostics(ctx: Ctx) -> dict[str, Any]:
    return diag.info(ctx)


@router.post("/diagnostics/live-test", status_code=202)
def live_test(ctx: Ctx) -> dict[str, Any]:
    runner = ctx.services.get("pytest_runner")
    job = ctx.jobs.submit(
        "live_test",
        "Live data checks",
        lambda j: diag.run_live_tests(j, runner),
        job_id="live-test",
    )
    return {"job_id": job.id}


@router.post("/diagnostics/support-bundle")
def support_bundle(ctx: Ctx, open_folder: bool = True) -> dict[str, Any]:
    path = diag.support_bundle(ctx)
    if open_folder:
        _open(ctx, path.parent)
    return {"path": str(path), "folder": str(path.parent), "name": path.name}


@router.post("/diagnostics/open-folder")
def open_folder(ctx: Ctx, body: OpenFolderIn) -> dict[str, Any]:
    folder = {
        "logs": ctx.paths.logs_dir,
        "support": ctx.paths.data_dir / "support",
        "data": ctx.paths.data_dir,
    }[body.which]
    _open(ctx, folder)
    return {"folder": str(folder)}


def _open(ctx: AppContext, folder: Any) -> None:
    try:
        diag.open_folder(folder, ctx.services.get("folder_opener"))
    except Exception as exc:
        raise AgoraError(
            "OPEN_FAILED",
            "Agora couldn't open the folder.",
            f"Open it yourself: {folder}",
            detail=repr(exc),
            status=500,
        ) from exc


@router.get("/diagnostics/threads")
def threads() -> dict[str, Any]:
    """Where each of Agora's threads is right now (D-196): the watch found a desk's poll stuck
    with nothing in the log, and only a view of the running threads can say where."""
    import sys
    import threading
    import traceback

    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        stack = traceback.extract_stack(frame)[-8:]
        out.append(
            {
                "name": names.get(ident, str(ident)),
                "stack": [f"{f.filename.split('backend')[-1]}:{f.lineno} {f.name}" for f in stack],
            }
        )
    return {"threads": sorted(out, key=lambda t: str(t["name"]))}
