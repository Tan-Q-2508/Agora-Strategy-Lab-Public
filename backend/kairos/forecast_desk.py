"""Kairos's candle forecasts, connected to its desks (D-175).

The user asked (2026-11-05) whether the forecasts were self-learning, trustable and used by the
desks. They learn from each forecast checked against what happened (KAIROS §17), but a forecast
was only made and checked when someone opened a chart (414 made, 2 checked), and no desk read
them. Now:

- **Every day** after a market closes, the autopilot forecasts every stock its daily desk trades
  (``AnalysisService.forecast`` records it and checks that stock's due forecasts) and checks every
  other stock's forecasts that have come due, so the record grows on schedule.
- **Skill** per market and timeframe: ``MIN_CHECKED``+ checked forecasts whose direction was right
  more often than a coin, by ``MIN_Z`` standard errors. Until then the desks ignore forecasts.
- **Use**: a live daily desk adds a nudge to a stock's score from today's forecast for it,
  ``WEIGHT`` × (2 × chance of rising − 1), only where skill is proven, like the judge (D-145):
  live only, so backtests stay reproducible (D-04).
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import func, select

from backend.core.types import Market, Timeframe
from backend.db.models import Instrument, KairosForecast
from backend.logging_setup import get_logger

log = get_logger("kairos.forecast_desk")

MIN_CHECKED = 60
MIN_Z = 2.0
WEIGHT = 10.0  # score points at full conviction (the brain's scores run −100 … 100)
DAY_MS = 86_400_000


def skill(ctx: Any, market: str, tf: Timeframe = Timeframe.D1) -> dict[str, Any]:
    """The checked record of ``market``'s forecasts on ``tf``, and whether it shows skill."""
    with ctx.db.session() as s:
        rows = s.execute(
            select(KairosForecast.hit, KairosForecast.inside80)
            .join(Instrument, Instrument.id == KairosForecast.instrument_id)
            .where(
                Instrument.market_code == market,
                KairosForecast.timeframe == tf.value,
                KairosForecast.resolved_at.is_not(None),
            )
        ).all()
    n = len(rows)
    hits = sum(int(h or 0) for h, _ in rows)
    inside = sum(int(x or 0) for _, x in rows)
    rate = hits / n if n else 0.0
    z = (rate - 0.5) / math.sqrt(0.25 / n) if n else 0.0
    proven = n >= MIN_CHECKED and z >= MIN_Z
    if n < MIN_CHECKED:
        text = (
            f"Not used yet: {n} of the {MIN_CHECKED} checked forecasts needed to judge its skill."
        )
    elif proven:
        text = (
            f"Used: direction right {rate:.0%} of {n} checked forecasts "
            f"({z:.1f} standard errors above a coin); inside its 80% range {inside / n:.0%}."
        )
    else:
        text = (
            f"Not used: direction right {rate:.0%} of {n} checked forecasts, no better than "
            "a coin by a clear margin."
        )
    return {
        "n": n,
        "hit_rate": round(rate, 3),
        "inside80": round(inside / n, 3) if n else None,
        "z": round(z, 2),
        "proven": proven,
        "text": text,
    }


def todays(ctx: Any, instrument_id: int, tf: Timeframe, last_bar_ts: int) -> float | None:
    """The chance of rising from the forecast made on the stock's latest candle, or None."""
    with ctx.db.session() as s:
        up = s.scalar(
            select(KairosForecast.up_prob).where(
                KairosForecast.instrument_id == instrument_id,
                KairosForecast.timeframe == tf.value,
                KairosForecast.made_at == last_bar_ts,
            )
        )
    return float(up) if up is not None else None


def nudge(up_prob: float | None) -> float:
    """Score points from a forecast's chance of rising (0 without one)."""
    if up_prob is None:
        return 0.0
    return round(WEIGHT * (2.0 * float(up_prob) - 1.0), 1)


def daily(ctx: Any, market: str, symbols: list[str]) -> dict[str, int]:
    """Forecast each of ``symbols`` (a daily desk's stocks), then check every due forecast."""
    from backend.data import store
    from backend.kairos import forecasts

    analysis = ctx.services.get("analysis")
    made = checked = 0
    if analysis is not None:
        for sym in symbols:
            with ctx.db.session() as s:
                inst = store.find_instrument(s, Market(market), sym)
            if inst is None:
                continue
            try:
                analysis.forecast(inst, Timeframe.D1)
                made += 1
            except Exception as exc:  # one stock without enough history doesn't stop the rest
                log.info("No forecast for %s: %r", sym, exc)
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        due = s.execute(
            select(KairosForecast.instrument_id, KairosForecast.timeframe)
            .join(Instrument, Instrument.id == KairosForecast.instrument_id)
            .where(Instrument.market_code == market, KairosForecast.resolved_at.is_(None))
            .group_by(KairosForecast.instrument_id, KairosForecast.timeframe)
            .having(func.min(KairosForecast.made_at) < now - 2 * DAY_MS)
        ).all()
    for iid, tfv in due:
        with ctx.db.session() as s:
            inst = store.get_instrument(s, iid)
        if inst is None:
            continue
        tf = Timeframe(tfv)
        try:
            # today's candle first (D-201): 15 minutes after the close only the desk's own stocks
            # had it, so 43 of the 51 forecasts due on 6 Nov waited for the next trading day
            ctx.cache.ensure(inst, tf, now - 30 * DAY_MS, now)
            bars = ctx.cache.bars(inst, tf, now - 400 * DAY_MS, now + 1)
            checked += forecasts.score(ctx, inst, tf, bars)
        except Exception as exc:
            log.info("Couldn't check forecasts for %s: %r", inst.symbol, exc)
    return {"made": made, "checked": checked}
