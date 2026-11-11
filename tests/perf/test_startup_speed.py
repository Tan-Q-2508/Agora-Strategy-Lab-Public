"""Startup: the app is answering well within SPEC §11's 10 seconds (the laptop adds the
launcher's own checks; this pins Agora's part)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.main import create_app


def test_app_answers_quickly_after_start(ctx: AppContext) -> None:
    t0 = time.perf_counter()
    with TestClient(create_app(ctx)) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/").status_code == 200
    assert time.perf_counter() - t0 < 3.0
