"""FastAPI application: JSON API under ``/api`` plus the built frontend at ``/``.

One process serves everything on 127.0.0.1:8765 (D-17), so the user only ever starts
one thing. There is no module-level ``app``: importing this file must not open the real
database, so uvicorn uses ``--factory backend.main:create_app`` and tests pass their own
context.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend import actions
from backend.api import (
    ai,
    analysis,
    autopilot,
    backtests,
    checks,
    costs,
    data,
    indices,
    jobs,
    kairos,
    markets,
    metis,
    news,
    paper,
    portfolios,
    strategies,
    strategy_defs,
    system,
    watchlists,
    world,
    ws,
)
from backend.config import Paths, get_paths
from backend.context import AppContext
from backend.core.ai_provider import AIProvider
from backend.core.clock import Clock, SystemClock
from backend.core.data_source import DataSource
from backend.db.engine import Database
from backend.diagnostics import record_event
from backend.errors import AgoraError, install_error_handlers
from backend.logging_setup import get_logger, setup_logging
from backend.settings_store import read_setting
from backend.version import APP_VERSION

log = get_logger("main")

_NO_FRONTEND = """<!doctype html><html><head><meta charset="utf-8"><title>Agora</title></head>
<body style="font-family:system-ui;background:#FAF9F6;color:#1F1D1A;padding:48px">
<h1>Agora is running</h1><p>The screens haven't been built into this copy yet.
Pull the latest version in GitHub Desktop, then start Agora again.</p></body></html>"""


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | HTMLResponse:
        if path.startswith("api/") or path == "api":
            raise AgoraError(
                "NOT_FOUND",
                "That page or item doesn't exist.",
                "Go back and try again.",
                detail=f"No API route for /{path}",
                status=404,
            )
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        if index.is_file():
            # always ask again, so a window never keeps an old build's page list (D-137)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(_NO_FRONTEND)


def _ai_provider(db: Database) -> AIProvider:
    """Ollama on the laptop; ``AGORA_FAKE_AI=1`` uses canned replies (tests, demos)."""
    if os.environ.get("AGORA_FAKE_AI") == "1":
        from backend.fakes.ai_provider import FakeAIProvider

        return FakeAIProvider()
    from backend.ai.ollama import OllamaProvider

    return OllamaProvider(lambda: str(read_setting(db, "ai.base_url")))


def build_real_context(paths: Paths) -> AppContext:
    """The context the launcher uses. ``AGORA_FAKE_DATA=1`` swaps market data for the
    synthetic fixtures (cloud sessions and demos; never the user's default)."""
    clock: Clock = SystemClock()
    db = Database()
    ai_provider = _ai_provider(db)
    if os.environ.get("AGORA_FAKE_DATA") == "1":
        from backend.fakes.data_source import FakeSource
        from backend.markets.calendar import FixtureCalendar

        fake = FakeSource(clock)
        return AppContext(
            paths=paths,
            db=db,
            clock=clock,
            calendar=FixtureCalendar(fake.manifest),
            sources=[fake],
            data_mode="fake",
            ai=ai_provider,
        )
    from backend.data.accumulator import IntradayAccumulator
    from backend.data.nse import NseBhavcopySource
    from backend.data.stooq import StooqSource
    from backend.data.yahoo import YahooSource
    from backend.markets.calendar import ExchangeCalendar

    calendar = ExchangeCalendar()
    sources: list[DataSource] = [
        YahooSource(clock, calendar),
        NseBhavcopySource(clock, calendar),
        StooqSource(clock, calendar),
    ]
    ctx = AppContext(
        paths=paths, db=db, clock=clock, calendar=calendar, sources=sources, ai=ai_provider
    )
    from backend.ai.gpu import GpuGuard
    from backend.uptime import Uptime

    actions.open_log(paths.data_dir / "actions.db")
    ctx.services["uptime"] = Uptime(paths.data_dir)
    ctx.services["ai_gpu"] = GpuGuard(ctx)
    ctx.services["accumulator"] = IntradayAccumulator(
        db, ctx.cache, calendar, enabled=lambda: bool(read_setting(db, "intraday.accumulate"))
    )
    return ctx


def create_app(ctx: AppContext | None = None) -> FastAPI:
    if ctx is None:
        paths = get_paths()
        paths.ensure()
        setup_logging(paths.logs_dir)
        ctx = build_real_context(paths)
        # Hand Python's lock between threads every 1 ms (default 5): a screen's request then
        # isn't stuck behind a backtest's number crunching (D-113)
        sys.setswitchinterval(0.001)
        # each Kairos study in a process of its own, on a core of its own (D-148)
        ctx.learning.separate = True
    app_ctx = ctx

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for svc in list(app_ctx.services.values()):
            start = getattr(svc, "start", None)
            if callable(start):
                start()
        record_event(
            app_ctx.db, app_ctx.clock.now_ms(), "info", "app", f"Agora {APP_VERSION} started."
        )
        store = actions.current()
        if store is not None:
            store.close_unfinished()
        actions.note("app", "Agora started", APP_VERSION)
        yield
        app_ctx.shutdown()
        record_event(app_ctx.db, app_ctx.clock.now_ms(), "info", "app", "Agora stopped.")
        actions.note("app", "Agora stopped cleanly")
        actions.close_log()
        log.info("Agora stopped cleanly")

    app = FastAPI(
        title="Agora",
        version=APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    install_error_handlers(app)
    api = APIRouter(prefix="/api")
    api.include_router(system.router)
    api.include_router(markets.router)
    api.include_router(data.router)
    api.include_router(indices.router)
    api.include_router(jobs.router)
    api.include_router(strategy_defs.router)
    api.include_router(strategies.router)
    api.include_router(backtests.router)
    api.include_router(costs.router)
    api.include_router(paper.router)
    api.include_router(ai.router)
    api.include_router(analysis.router)
    api.include_router(news.router)
    api.include_router(kairos.router)
    api.include_router(metis.router)
    api.include_router(portfolios.router)
    api.include_router(checks.router)
    api.include_router(watchlists.router)
    api.include_router(world.router)
    api.include_router(autopilot.router)
    app.include_router(api)
    app.include_router(ws.router)
    _mount_frontend(app, ctx.paths.frontend_dist)
    log.info("Agora %s started; data folder %s", APP_VERSION, ctx.paths.data_dir)
    return app
