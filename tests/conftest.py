"""Shared test setup: every test gets its own throwaway data folder and database, and an
app context wired to fakes (fixture market data, fixture calendar, fake clock, fake AI)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Paths
from backend.context import AppContext
from backend.db.engine import Database
from backend.db.migrate import upgrade_and_seed
from backend.fakes.ai_provider import FakeAIProvider
from backend.fakes.clock import FakeClock
from backend.fakes.data_source import FakeSource
from backend.main import create_app
from backend.markets.calendar import FixtureCalendar

T0 = 1_767_225_600_000  # 2026-01-01 00:00 UTC


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGORA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AGORA_DATABASE_URL", raising=False)
    monkeypatch.delenv("AGORA_FAKE_DATA", raising=False)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(tmp_path / "data")
    p.ensure()
    return p


@pytest.fixture
def db(paths: Paths, clock: FakeClock) -> Iterator[Database]:
    database = upgrade_and_seed(clock=clock, paths=paths)
    yield database
    database.engine.dispose()


@pytest.fixture
def fake_source(clock: FakeClock) -> FakeSource:
    return FakeSource(clock)


@pytest.fixture
def fixture_calendar(fake_source: FakeSource) -> FixtureCalendar:
    return FixtureCalendar(fake_source.manifest)


@pytest.fixture
def ctx(
    paths: Paths,
    db: Database,
    clock: FakeClock,
    fake_source: FakeSource,
    fixture_calendar: FixtureCalendar,
) -> Iterator[AppContext]:
    from backend.news.fetch import FakeFetcher

    c = AppContext(
        paths=paths,
        db=db,
        clock=clock,
        ai=FakeAIProvider(),
        calendar=fixture_calendar,
        sources=[fake_source],
        data_mode="fake",
        news_fetcher=FakeFetcher(clock, {"RELIANCE": "Reliance Industries", "AAPL": "Apple"}),
    )
    c.cache._sleep = lambda _s: None  # no real back-off waits in tests
    c.learning.auto = False  # tests start Kairos's training explicitly
    yield c
    c.shutdown()


@pytest.fixture
def client(ctx: AppContext) -> Iterator[TestClient]:
    with TestClient(create_app(ctx), raise_server_exceptions=False) as c:
        yield c
