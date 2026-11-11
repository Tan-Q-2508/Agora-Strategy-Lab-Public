"""Forecasts connected to the desks (D-175): a skill test, then a nudge."""

from __future__ import annotations

from typing import Any

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.db.models import KairosForecast
from backend.kairos import forecast_desk, resolve
from tests.kairos.test_brain import load


def _checked(ctx: AppContext, iid: int, n: int, hits: int, start: int = 0) -> None:
    with ctx.db.session() as s:
        for k in range(n):
            s.add(
                KairosForecast(
                    instrument_id=iid,
                    timeframe="1d",
                    made_at=start + k,
                    horizon=10,
                    origin=100.0,
                    p10=90.0,
                    p50=101.0,
                    p90=110.0,
                    up_prob=0.6,
                    resolved_at=k + 10,
                    actual=105.0,
                    hit=int(k < hits),
                    inside80=1,
                )
            )


def test_forecasts_are_used_only_once_their_record_shows_skill(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["TCS"])
    iid = resolve.stock(ctx, "TCS", Market.IN).id
    assert forecast_desk.skill(ctx, "IN")["proven"] is False  # nothing checked yet
    _checked(ctx, iid, 40, 30)
    few = forecast_desk.skill(ctx, "IN")
    assert not few["proven"] and "40 of the 60" in few["text"]  # too few, however good
    _checked(ctx, iid, 20, 15, start=1000)  # 60 checked, 45 right: 75%, z ≈ 3.9
    sk = forecast_desk.skill(ctx, "IN")
    assert sk["n"] == 60 and sk["proven"] and sk["text"].startswith("Used:")


def test_a_coin_flip_record_is_not_used(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["TCS"])
    iid = resolve.stock(ctx, "TCS", Market.IN).id
    _checked(ctx, iid, 60, 31)
    assert not forecast_desk.skill(ctx, "IN")["proven"]


def test_the_nudge_follows_the_chance_of_rising() -> None:
    assert forecast_desk.nudge(None) == 0.0
    assert forecast_desk.nudge(0.5) == 0.0
    assert forecast_desk.nudge(0.75) == 5.0 and forecast_desk.nudge(0.25) == -5.0


def test_todays_forecast_is_read_from_the_latest_candle(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["TCS"])
    iid = resolve.stock(ctx, "TCS", Market.IN).id
    _checked(ctx, iid, 1, 1)
    assert forecast_desk.todays(ctx, iid, Timeframe.D1, 0) == 0.6
    assert forecast_desk.todays(ctx, iid, Timeframe.D1, 999) is None


def test_autopilot_forecast_round_once_per_closed_session(ctx: Any, monkeypatch: Any) -> None:
    """D-175: the round runs once for each closed session, even when Agora opens after midnight
    in the market's own time (India's close is 2 am on a laptop in California)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.kairos import forecast_desk

    calls: list[str] = []
    monkeypatch.setattr(
        forecast_desk, "daily", lambda _c, m, _s: calls.append(m) or {"made": 0, "checked": 0}
    )
    ap = ctx.services["autopilot"]
    ist = ZoneInfo("Asia/Kolkata")

    def at(y: int, mo: int, d: int, h: int) -> None:
        ctx.clock.set(int(datetime(y, mo, d, h, tzinfo=ist).timestamp() * 1000))

    state: dict[str, Any] = {}
    sessions = ctx.calendar.sessions(Market.IN, *_span(ctx))
    day = datetime.fromtimestamp(sessions[0].close_ms / 1000, ist)
    nxt = datetime.fromtimestamp(sessions[1].close_ms / 1000, ist)
    at(day.year, day.month, day.day, 23)  # evening after a session closed
    assert ap.forecasts("IN", state)["status"] == "done"
    assert ap.forecasts("IN", state)["status"] == "done today"
    at(nxt.year, nxt.month, nxt.day, 2)  # after midnight: still that same session, not again
    assert ap.forecasts("IN", state)["status"] == "done today"
    at(nxt.year, nxt.month, nxt.day, 17)  # the next session has closed: run again
    assert ap.forecasts("IN", state)["status"] == "done"
    assert calls == ["IN", "IN"]


def _span(ctx: Any) -> tuple[Any, Any]:
    from datetime import timedelta

    from backend.markets.calendar import local_date

    today = local_date(Market.IN, ctx.clock.now_ms())
    return today + timedelta(days=1), today + timedelta(days=20)


def test_the_round_fetches_todays_candle_before_checking(ctx: AppContext, monkeypatch: Any) -> None:
    """D-201: 15 minutes after the close only the desk's stocks had today's candle, so most due
    forecasts weren't checked until the next trading day."""
    from backend.kairos import forecasts

    load(ctx, Market.IN, ["RELIANCE"])
    iid = resolve.stock(ctx, "RELIANCE", Market.IN).id
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        s.add(
            KairosForecast(
                instrument_id=iid,
                timeframe="1d",
                made_at=now - 20 * 86_400_000,
                horizon=10,
                origin=100.0,
                p10=90.0,
                p50=101.0,
                p90=110.0,
                up_prob=0.6,
            )
        )
    order: list[str] = []
    real_ensure = ctx.cache.ensure
    monkeypatch.setattr(
        ctx.cache, "ensure", lambda *a, **k: order.append("ensure") or real_ensure(*a, **k)
    )
    monkeypatch.setattr(forecasts, "score", lambda *_a, **_k: order.append("score") or 1)
    out = forecast_desk.daily(ctx, "IN", [])
    assert order[:2] == ["ensure", "score"] and out["checked"] == 1
