"""The objects every request handler shares, created once per app.

Keeping them in one place makes the real/fake swap explicit: tests build an
``AppContext`` with fakes (fixture data, fake clock, fake AI), the launcher builds one
with real implementations (Yahoo/NSE/Stooq, exchange calendars, wall clock, Ollama).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any

from fastapi import Request
from sqlalchemy import select

from backend.config import Paths
from backend.core.ai_provider import AIProvider
from backend.core.clock import Clock
from backend.core.data_source import DataSource
from backend.core.types import Market
from backend.data.cache import CacheManager
from backend.db.engine import Database
from backend.db.models import HolidayOverride
from backend.events import EventBus
from backend.jobs import JobManager
from backend.markets.calendar import Calendar, ExchangeCalendar, Override


@dataclass
class AppContext:
    paths: Paths
    db: Database
    clock: Clock
    ai: AIProvider | None = None
    calendar: Calendar = field(default_factory=ExchangeCalendar)
    sources: list[DataSource] = field(default_factory=list)
    data_mode: str = "real"  # "real" or "fake" (fixture data, for tests and cloud sessions)
    news_fetcher: Any = None  # RSS reader (real) or practice headlines (fake); see backend/news
    events: EventBus = field(default_factory=EventBus)
    jobs: JobManager = field(init=False)
    cache: CacheManager = field(init=False)
    services: dict[str, Any] = field(default_factory=dict)  # later phases register here
    _overrides_key: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.jobs = JobManager(self.events)
        self.cache = CacheManager(
            self.db,
            self.clock,
            self.calendar,
            self.sources,
            on_source_change=lambda name, state: self.events.publish(
                "source.status", {"source": name, "state": state}
            ),
        )
        self.refresh_overrides()
        from backend.backtest.manager import BacktestManager

        self.services["backtests"] = BacktestManager(self)
        from backend.paper.service import PaperService

        self.services["paper"] = PaperService(self)
        from backend.ai.service import AIService

        self.services["ai"] = AIService(self)
        from backend.analysis.service import AnalysisService

        self.services["analysis"] = AnalysisService(self)
        from backend.news.service import NewsService

        self.services["news"] = NewsService(self)
        from backend.kairos.learning import LearningService

        learning = LearningService(self)
        self.services["kairos_learning"] = learning
        self.services["kairos_stats"] = learning
        from backend.kairos.desk import DeskService

        self.services["kairos_desk"] = DeskService(self)
        from backend.kairos.coach import Coach

        self.services["kairos_coach"] = Coach(self)
        from backend.kairos.autolearn import AutoLearner

        self.services["kairos_learner"] = AutoLearner(self)
        from backend.metis.researcher import Metis

        self.services["metis"] = Metis(self)
        from backend.portfolio.live import Manager as PortfolioManager

        self.services["portfolio"] = PortfolioManager(self)
        from backend.watchlists.service import WatchlistService

        self.services["watchlists"] = WatchlistService(self)
        from backend.sectors.service import SectorService

        self.services["sectors"] = SectorService(self)
        from backend.world.service import WorldService

        self.services["world"] = WorldService(self)
        from backend.research.service import ResearchService

        self.services["research"] = ResearchService(self)
        from backend.autopilot import Autopilot

        self.services["autopilot"] = Autopilot(self)
        from backend.kairos.agent import KairosAgent

        self.services["kairos"] = KairosAgent(self)

    def refresh_overrides(self) -> None:
        """Load ``holiday_overrides`` into the real calendar (cheap when unchanged)."""
        if not isinstance(self.calendar, ExchangeCalendar):
            return
        with self.db.session() as s:
            rows = [
                (r.market_code, r.date, r.kind, r.close_time)
                for r in s.scalars(select(HolidayOverride).order_by(HolidayOverride.id))
            ]
        key = json.dumps(rows)
        if key == self._overrides_key:
            return
        by_market: dict[Market, dict[date, Override]] = {m: {} for m in Market}
        for market, day, kind, close in rows:
            by_market[Market(market)][date.fromisoformat(day)] = Override(
                kind, time.fromisoformat(close) if close else None
            )
        self.calendar.set_overrides(by_market)
        self._overrides_key = key

    @property
    def backtests(self) -> Any:
        return self.services["backtests"]

    @property
    def paper(self) -> Any:
        return self.services["paper"]

    @property
    def ai_service(self) -> Any:
        return self.services["ai"]

    @property
    def analysis(self) -> Any:
        return self.services["analysis"]

    @property
    def news(self) -> Any:
        return self.services["news"]

    @property
    def kairos(self) -> Any:
        return self.services["kairos"]

    @property
    def learning(self) -> Any:
        return self.services["kairos_learning"]

    @property
    def watchlists(self) -> Any:
        return self.services["watchlists"]

    @property
    def sectors(self) -> Any:
        return self.services["sectors"]

    @property
    def world(self) -> Any:
        return self.services["world"]

    @property
    def research(self) -> Any:
        return self.services["research"]

    @property
    def desk(self) -> Any:
        return self.services["kairos_desk"]

    def shutdown(self) -> None:
        for svc in self.services.values():
            stop = getattr(svc, "shutdown", None)
            if callable(stop):
                stop()
        self.jobs.shutdown()


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx
