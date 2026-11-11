"""Strategies on every timeframe (D-118): templates on other charts, discovery that goes to the
timeframes with the fewest strategies, minute strategies on stocks with minute history, and a
short-term Kairos desk."""

from __future__ import annotations

from typing import Any

import pytest

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import store
from backend.metis import agenda, timeframes
from backend.metis.think import _timeframe, clean_idea
from backend.strategy import templates

STOCKS = ("RELIANCE", "INFY")  # the practice stocks with minute candles (60 sessions)


@pytest.fixture(autouse=True)
def _small_practice_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Practice data has minute candles for two Indian stocks over 60 sessions."""
    monkeypatch.setattr(timeframes, "MIN_STOCKS", 2)
    monkeypatch.setattr(timeframes, "MIN_DAYS", {**timeframes.MIN_DAYS, "1d": 20, "1h": 20})
    timeframes._cache.clear()


def _download(ctx: AppContext, *tfs: Timeframe) -> None:
    with ctx.db.session() as s:
        refs = [store.find_instrument(s, Market.IN, x) for x in STOCKS]
    from backend.data.service import default_start_ms

    now = ctx.clock.now_ms()
    for ref in refs:
        assert ref is not None
        for tf in tfs:
            ctx.cache.ensure(ref, tf, default_start_ms(tf, now), now + 1)
    timeframes._cache.clear()


def test_templates_run_on_other_timeframes() -> None:
    assert templates.timeframes_for("rsi_mean_reversion") == ("1d", "1h", "15m", "5m", "1m")
    assert templates.timeframes_for("high_52w_momentum") == ("1d",)
    five = templates.template_definition("rsi_mean_reversion", "IN", ["TCS"], "5m")
    assert five.timeframe == "5m" and five.product == "intraday" and five.exit.exit_time
    hourly = templates.template_definition("rsi_mean_reversion", "IN", ["TCS"], "1h")
    assert hourly.timeframe == "1h" and hourly.product == "delivery"
    us = templates.template_definition("ma_crossover", "US", ["AAPL"], "15m")
    assert us.product == "cash" and us.exit.exit_time == "15:45"
    daily = templates.template_definition("ma_crossover", "IN", ["TCS"])
    assert daily.timeframe == "1d" and daily.product == "delivery"


def test_the_model_can_name_a_timeframe() -> None:
    assert [_timeframe(x) for x in ("hourly", "5 min", "15m", "daily", "1 minute", "2h")] == [
        "1h",
        "5m",
        "15m",
        "1d",
        "1m",
        None,
    ]
    got = clean_idea({"kind": "new_strategy", "idea": "Buy the VWAP reclaim", "timeframe": "5min"})
    assert got is not None and got["timeframe"] == "5m"


def test_discovery_goes_to_the_timeframes_with_fewest_strategies(
    client: Any, ctx: AppContext
) -> None:
    _download(ctx, Timeframe.D1, Timeframe.H1, Timeframe.M5)
    have = timeframes.stocks_by_timeframe(ctx, "IN")
    assert set(STOCKS) <= set(have["1d"]) and set(STOCKS) <= set(have["5m"])
    assert {"1d", "1h", "5m"} <= set(timeframes.usable(ctx, "IN"))
    # one daily strategy: discovery now starts with a timeframe that has none
    client.post("/api/strategies", json={"name": "Mine", "market": "IN", "template_key": "turtle"})
    # the desks' timeframes first (D-177): hourly (none yet), then daily, then 5-minute
    assert timeframes.order(ctx, "IN") == ["1h", "1d", "5m"]
    seeds = agenda.discover_seeds(ctx, ["IN"], limit=4)
    assert seeds and all(s["timeframe"] == "1h" for s in seeds)
    assert any("candles" in s["title"] for s in seeds)
    assert timeframes.summary(ctx, ["IN"])[0].startswith("India: daily: 1 strategies")


def test_a_minute_strategy_is_tested_on_stocks_with_minute_history(
    client: Any, ctx: AppContext
) -> None:
    from backend.metis import trial

    _download(ctx, Timeframe.D1, Timeframe.M5)
    idea = agenda._template_seed(
        "rsi_mean_reversion", templates.TEMPLATES["rsi_mean_reversion"], "IN", "5m"
    )
    assert trial.rules_of(idea)["timeframe"] == "5m"
    out = trial.try_new(ctx, idea, "fp-5m", provider=None, model="", num_ctx=0, markets=["IN"])
    assert out.status in ("held_up", "rejected"), out.verdict
    assert out.definition is not None and out.definition.timeframe == "5m"
    assert set(out.definition.universe.symbols) <= set(STOCKS)


def test_kairos_runs_a_short_term_desk_too(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    _download(ctx, Timeframe.D1, Timeframe.M5, Timeframe.M15)
    ap = ctx.services["autopilot"]
    ctx.paper.threaded = False
    state: dict[str, Any] = {}
    out = ap.desk("IN", state, Timeframe.M15)
    assert out["status"] == "started", out
    desk = next(d for d in ctx.desk.desks() if d["timeframe"] == "15m")
    assert desk["name"] == "Kairos desk · India · 15-minute"
    assert ap.desk("IN", state, Timeframe.M15)["status"] == "running"
    assert "IN:15m" in state["desks"]  # type: ignore[operator]
    # every desk takes the best of the whole market, as many as its candles allow (D-133)
    from backend.kairos import picks

    assert len(desk["symbols"]) <= picks.DESK_SIZE["15m"]
    assert desk["symbols"] == [p["symbol"] for p in ap.ranked("IN")][: len(desk["symbols"])]
    # the hourly and 15-minute desks run by default (D-132; 5m and 1m retired, D-177)
    from backend.autopilot import SHORT_DESKS
    from backend.settings_store import read_all

    with ctx.db.session() as s:
        assert read_all(s)["autopilot.intraday_desk"] == "all"
    assert SHORT_DESKS == ("1h", "15m")
    # D-177: a 5-minute desk left from before is retired once it has no open trades
    assert ap.desk("IN", state, Timeframe.M5)["status"] == "started"
    five = state["desks"]["IN:5m"]["session_id"]  # type: ignore[index]
    assert ap.retire("IN", state, SHORT_DESKS) == [five]
    assert "IN:5m" not in state["desks"]  # type: ignore[operator]
    assert "IN:15m" in state["desks"]  # type: ignore[operator]
    assert next(d for d in ctx.desk.desks() if d["id"] == five)["state"] == "stopped"


def test_kairos_ranks_every_liquid_stock_with_fresh_prices(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.kairos import picks
    from backend.watchlists import seed

    ctx.watchlists.ensure()
    _download(ctx, Timeframe.D1)
    with ctx.db.session() as s:
        everyone = seed.members(s, "IN", {})
    monkeypatch.setattr(picks, "MIN_TRADED", {"IN": 0.0, "US": 0.0})
    have = picks.pool(ctx, "IN", everyone)
    assert len(have) >= 2 and all(len(c) >= 130 for c in have.values())
    monkeypatch.setattr(picks, "MIN_TRADED", {"IN": 1e18, "US": 1e18})
    assert picks.pool(ctx, "IN", everyone) == {}  # too thinly traded: left out


def test_a_burst_of_trading_doesnt_lift_a_thin_stock_into_the_picks(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-155: the bar is the lower of the 20- and 120-day medians of value traded, so a stock
    that is thin all year but busy for a few weeks stays out."""
    from backend.core.types import Bar
    from backend.kairos import picks

    day = 86_400_000
    now = ctx.clock.now_ms()
    thin = [
        Bar(now - (200 - k) * day, 100, 101, 99, 100, 1_000 if k < 175 else 10_000_000, "test")
        for k in range(200)
    ]

    class Cache:
        def bars(self, *_a: object, **_k: object) -> list[Bar]:
            return thin

    from types import SimpleNamespace

    ref = SimpleNamespace(id=7)
    monkeypatch.setattr(ctx, "cache", Cache())
    monkeypatch.setattr("backend.data.store.get_instrument", lambda _s, _i: ref)
    monkeypatch.setattr(picks, "MIN_TRADED", {"IN": 1e8, "US": 1e8})
    assert picks.pool(ctx, "IN", [7]) == {}  # busy for 25 days, thin for 175
    monkeypatch.setattr(picks, "STEADY_DAYS", (20,))
    assert 7 in picks.pool(ctx, "IN", [7])  # the old 20-day bar let it in


def test_a_stock_whose_prices_stopped_isnt_ranked(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-182: thousands of stocks' daily prices stopped for up to ten days and were still
    ranked on them. A stock more than four days behind the market's newest is left out."""
    from types import SimpleNamespace

    from backend.core.types import Bar
    from backend.kairos import picks

    day = 86_400_000
    now = ctx.clock.now_ms()

    def series(end: int) -> list[Bar]:
        return [
            Bar(end - (200 - k) * day, 100, 101, 99, 100, 10_000_000, "test") for k in range(200)
        ]

    bars = {1: series(now), 2: series(now - 6 * day)}

    class Cache:
        def bars(self, ref: Any, *_a: object, **_k: object) -> list[Bar]:
            return bars[ref.id]

    monkeypatch.setattr(ctx, "cache", Cache())
    monkeypatch.setattr("backend.data.store.get_instrument", lambda _s, i: SimpleNamespace(id=i))
    monkeypatch.setattr(picks, "MIN_TRADED", {"IN": 0.0, "US": 0.0})
    assert set(picks.pool(ctx, "IN", [1, 2])) == {1}


def test_a_stock_skipped_while_its_source_is_paused_isnt_marked_done(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-182: the autopilot counted a download its paused source skipped as "topped up today"."""
    from types import SimpleNamespace

    ap = ctx.services["autopilot"]
    monkeypatch.setattr(ap, "wanted", lambda _m: ["RELIANCE", "TCS"])
    result = {"RELIANCE": True, "TCS": False}
    monkeypatch.setattr(
        ctx.cache, "ensure", lambda ref, *_a, **_k: SimpleNamespace(waited=result[ref.symbol])
    )
    state: dict[str, Any] = {}
    out = ap.prices("IN", state)
    assert "RELIANCE" not in state["prices"]["IN"] and "TCS" in state["prices"]["IN"]
    assert out["waiting"] == 1


def test_the_stalest_prices_are_topped_up_first(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-185: after prices stopped for days, a round spent its hour on current stocks."""
    from types import SimpleNamespace

    from backend import autopilot as apm

    ap = ctx.services["autopilot"]
    monkeypatch.setattr(ap, "wanted", lambda _m: ["RELIANCE", "TCS", "INFY"])
    now = ctx.clock.now_ms()
    day = 86_400_000
    last = {"RELIANCE": now - day, "TCS": now - 9 * day, "INFY": now - 5 * day, "OLD": 1}
    monkeypatch.setattr(ap, "_last_daily", lambda _m: last)
    monkeypatch.setattr(ap, "wanted", lambda _m: ["RELIANCE", "TCS", "INFY", "OLD"])
    monkeypatch.setattr(apm, "TOP_UP", 2)
    monkeypatch.setattr(apm, "WORKERS", 1)
    asked: list[str] = []
    monkeypatch.setattr(
        ctx.cache,
        "ensure",
        lambda ref, *_a, **_k: asked.append(ref.symbol) or SimpleNamespace(waited=False),
    )
    state: dict[str, Any] = {"prices": {"IN": {"RELIANCE": 1, "TCS": 1, "INFY": 1, "OLD": 1}}}
    ap.prices("IN", state)
    assert asked == ["TCS", "INFY"]


def test_the_price_top_up_stops_at_its_time_budget(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-186: a round of 1,000 downloads held the desks, trials and forecasts for 90 minutes."""
    from types import SimpleNamespace

    from backend import autopilot as apm

    ap = ctx.services["autopilot"]
    monkeypatch.setattr(ap, "wanted", lambda _m: ["RELIANCE", "TCS"])
    monkeypatch.setattr(apm, "PRICE_BUDGET_S", -1.0)
    asked: list[str] = []
    monkeypatch.setattr(
        ctx.cache,
        "ensure",
        lambda ref, *_a, **_k: asked.append(ref.symbol) or SimpleNamespace(waited=False),
    )
    state: dict[str, Any] = {"prices": {"IN": {"RELIANCE": 1, "TCS": 1}}}
    out = ap.prices("IN", state)
    assert asked == [] and out["waiting"] == 2


def test_the_top_up_steps_back_while_a_market_trades(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-192: during India's session four top-up threads crowded the desks' live polls."""
    from types import SimpleNamespace

    from backend import autopilot as apm

    ap = ctx.services["autopilot"]
    monkeypatch.setattr(ap, "wanted", lambda _m: ["RELIANCE", "TCS"])
    monkeypatch.setattr(ap, "_any_market_open", lambda: True)
    monkeypatch.setattr(apm, "OPEN_BUDGET_S", -1.0)
    asked: list[str] = []
    monkeypatch.setattr(
        ctx.cache,
        "ensure",
        lambda ref, *_a, **_k: asked.append(ref.symbol) or SimpleNamespace(waited=False),
    )
    out = ap.prices("IN", {"prices": {"IN": {"RELIANCE": 1, "TCS": 1}}})
    assert asked == [] and out["waiting"] == 2  # the open-market budget applies


def test_the_top_up_runs_again_after_each_close(ctx: AppContext) -> None:
    """D-203: keyed to the UTC day, India's top-up ran before its close every day, and most
    Indian stocks' daily prices lagged a day."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ap = ctx.services["autopilot"]
    ist = ZoneInfo("Asia/Kolkata")
    from datetime import timedelta

    from backend.markets.calendar import local_date

    today = local_date(Market.IN, ctx.clock.now_ms())
    sessions = ctx.calendar.sessions(
        Market.IN, today + timedelta(days=1), today + timedelta(days=20)
    )
    day = datetime.fromtimestamp(sessions[1].close_ms / 1000, ist)
    before = int(datetime(day.year, day.month, day.day, 12, tzinfo=ist).timestamp() * 1000)
    after = int(datetime(day.year, day.month, day.day, 16, tzinfo=ist).timestamp() * 1000)
    assert ap._session_key("IN", before) != ap._session_key("IN", after)
