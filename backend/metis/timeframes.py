"""Strategies on every timeframe (D-118).

The user (2026-10-24): "Are all the backtests and strategies happening only on Day level? I want
strategies for day, 1 hour, 15 min, and 5 min and 1 min ones too." Until then Metis discovered and
tested daily strategies only. This module tells Metis which timeframes it can research (enough
saved history), which stocks to use for each (the ones with that history), and how many strategies
the user already has on each, so discovery goes to the timeframes with the fewest first.

How much history there is depends on Yahoo's window (about 2 years of hourly candles, 60 days of
15- and 5-minute, 30 days of 1-minute) plus what Agora has saved every day since (D-92).
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from sqlalchemy import func, select

from backend.db.models import Candle, Instrument, Strategy
from backend.strategy import service as strategies

ALL = ("1d", "1h", "15m", "5m", "1m")
# The timeframes Kairos's desks trade (D-177: daily long term, hourly and 15-minute short term).
# Discovery researches these first; 5- and 1-minute strategies come only after them, since every
# 5- and 1-minute family lost to costs on the user's data and no desk trades them any more.
DESK = ("1d", "1h", "15m")
LABEL = {"1d": "daily", "1h": "hourly", "15m": "15-minute", "5m": "5-minute", "1m": "1-minute"}
# Trading days of saved candles a stock needs before a strategy is tested on that timeframe:
# enough trades for the study/exam split (METIS §4) without waiting months.
MIN_DAYS = {"1d": 250, "1h": 120, "15m": 20, "5m": 20, "1m": 10}
MIN_STOCKS = 4
CACHE_S = 600.0

_cache: dict[str, tuple[float, dict[str, list[str]]]] = {}


def stocks_by_timeframe(ctx: Any, market: str) -> dict[str, list[str]]:
    """For each timeframe, the market's stocks with enough saved history, most history first
    (cached 10 minutes: counting days reads the candle index)."""
    hit = _cache.get(market)
    if hit is not None and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    c = Candle.__table__.c
    out: dict[str, list[str]] = {}
    with ctx.db.session() as s:
        for tf in ALL:
            days = func.count(func.distinct(c.ts.op("/")(86_400_000)))
            rows = s.execute(
                select(Instrument.symbol, days)
                .join(Instrument, Instrument.id == c.instrument_id)
                .where(
                    c.timeframe == tf,
                    Instrument.market_code == market,
                    Instrument.instrument_type == "equity",
                )
                .group_by(Instrument.symbol)
                .having(days >= MIN_DAYS[tf])
                .order_by(days.desc(), Instrument.symbol)
            ).all()
            out[tf] = [sym for sym, _n in rows]
    _cache[market] = (time.monotonic(), out)
    return out


def usable(ctx: Any, market: str) -> list[str]:
    """Timeframes with enough stocks to test a strategy on. Daily always: a daily test
    downloads the years it needs; shorter timeframes need history Agora has saved."""
    have = stocks_by_timeframe(ctx, market)
    return ["1d", *(tf for tf in ALL[1:] if len(have.get(tf, [])) >= MIN_STOCKS)]


def stocks_for(ctx: Any, market: str, timeframe: str, n: int = 6) -> list[str]:
    return stocks_by_timeframe(ctx, market).get(timeframe, [])[:n]


def strategy_counts(ctx: Any, market: str) -> Counter[str]:
    """The user's strategies (not archived) per timeframe in this market."""
    out: Counter[str] = Counter()
    with ctx.db.session() as s:
        ids = s.scalars(select(Strategy.id).where(Strategy.archived_at.is_(None))).all()
        for sid in ids:
            v = strategies.latest_version(s, sid)
            if v is not None and v.definition.market == market:
                out[v.definition.timeframe] += 1
    return out


def order(ctx: Any, market: str) -> list[str]:
    """Usable timeframes: the desks' timeframes first (D-177), within them the ones with the
    fewest strategies first (daily wins ties)."""
    counts = strategy_counts(ctx, market)
    return sorted(usable(ctx, market), key=lambda tf: (tf not in DESK, counts[tf], ALL.index(tf)))


def summary(ctx: Any, markets: list[str]) -> list[str]:
    """For the brief: what Metis can research on each timeframe."""
    lines = []
    for m in markets:
        have = stocks_by_timeframe(ctx, m)
        counts = strategy_counts(ctx, m)
        parts = [
            f"{LABEL[tf]}: {counts[tf]} strategies, {len(have.get(tf, []))} stocks with history"
            for tf in ALL
            if len(have.get(tf, [])) >= MIN_STOCKS
        ]
        if parts:
            lines.append(f"{'India' if m == 'IN' else 'US'}: " + "; ".join(parts) + ".")
    return lines
