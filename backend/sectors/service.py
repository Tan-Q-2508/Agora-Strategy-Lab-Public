"""Where money is moving: every sector and industry of a market, from saved daily prices (D-98).

Reads the stocks that have saved daily prices (the index stocks Agora downloads, plus any other
stock the user, a watchlist or a desk brought in), groups them by sector (and by industry), and
reads each group with ``rotation.py``. Results are cached per market until a new daily candle
arrives. Kairos's ``sectors`` tool, Metis's brief, the autopilot's stock picks and the move
investigator all use it.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy import func, select

from backend.core.types import Market, Timeframe
from backend.data import store
from backend.db.models import Candle, Instrument, InstrumentProfile
from backend.logging_setup import get_logger
from backend.sectors import rotation as rot
from backend.watchlists import seed

log = get_logger("sectors")
DAY_MS = 86_400_000
LOOK_DAYS = 3 * 365 + 60
BENCH = {"IN": "NIFTY50", "US": "SPY"}
MIN_INDUSTRY = 3


class SectorService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, int], dict[str, Any]] = {}

    def _with_prices(self, market: str) -> list[tuple[int, str, str, str]]:
        """(id, symbol, sector, industry) of stocks with recent saved daily candles."""
        since = self.ctx.clock.now_ms() - 30 * DAY_MS
        with self.ctx.db.session() as s:
            # One primary-key lookup per stock: a scan of every candle gets slow once the
            # whole market is saved (D-102).
            recent = (
                select(Candle.instrument_id)
                .where(
                    Candle.instrument_id == Instrument.id,
                    Candle.timeframe == "1d",
                    Candle.ts >= since,
                )
                .exists()
            )
            rows = s.execute(
                select(
                    Instrument.id,
                    Instrument.symbol,
                    InstrumentProfile.sector,
                    InstrumentProfile.industry,
                )
                .join(InstrumentProfile, InstrumentProfile.instrument_id == Instrument.id)
                .where(
                    Instrument.market_code == market,
                    Instrument.instrument_type == "equity",
                    InstrumentProfile.sector != "",
                    InstrumentProfile.lists != seed.LISTED_ONLY,  # index stocks (D-102)
                    recent,
                )
            ).all()
        return [(int(a), str(b), str(c), str(d)) for a, b, c, d in rows]

    def _latest(self, market: str) -> int:
        with self.ctx.db.session() as s:
            bench = store.find_instrument(s, Market(market), BENCH[market])
            if bench is None:
                return 0
            return int(
                s.scalar(
                    select(func.max(Candle.ts)).where(
                        Candle.instrument_id == bench.id, Candle.timeframe == "1d"
                    )
                )
                or 0
            )

    def overview(self, market: str) -> dict[str, Any]:
        """Every sector (and the industries with 3+ priced stocks), strongest first."""
        self.ctx.watchlists.ensure()
        key = (market, self._latest(market))
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        out = self._compute(market)
        with self._lock:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != market}
            self._cache[key] = out
        return out

    def _compute(self, market: str) -> dict[str, Any]:
        now = self.ctx.clock.now_ms()
        lo = now - LOOK_DAYS * DAY_MS
        with self.ctx.db.session() as s:
            bench_ref = store.find_instrument(s, Market(market), BENCH[market])
        empty: dict[str, Any] = {
            "market": market,
            "as_of": None,
            "sectors": [],
            "industries": [],
            "booms": [],
            "slumps": [],
            "stocks": 0,
            "sentence": "Sector readings need saved daily prices: open the Data screen and "
            "download the index's history.",
        }
        if bench_ref is None:
            return empty
        bench_bars = self.ctx.cache.bars(bench_ref, Timeframe.D1, lo, now + 1, adjusted_prices=True)
        if len(bench_bars) < 80:
            return empty
        dates = np.array([b.ts for b in bench_bars], dtype=np.int64)
        bench = np.array([b.close for b in bench_bars], dtype=np.float64)
        pos = {int(t): i for i, t in enumerate(dates)}
        by_sector: dict[str, list[rot.Member]] = defaultdict(list)
        by_industry: dict[str, list[rot.Member]] = defaultdict(list)
        stocks = self._with_prices(market)
        for iid, sym, sector, industry in stocks:
            ref = store.InstrumentRef(iid, Market(market), sym, sym, sym, "equity")
            bars = self.ctx.cache.bars(ref, Timeframe.D1, lo, now + 1, adjusted_prices=True)
            close = np.full(len(dates), np.nan)
            vol = np.full(len(dates), np.nan)
            for b in bars:
                i = pos.get(b.ts)
                if i is not None:
                    close[i], vol[i] = b.close, b.volume
            m = rot.Member(iid, sym, close, vol)
            by_sector[sector].append(m)
            if industry:
                by_industry[industry].append(m)
        sectors = {
            name: r
            for name, ms in by_sector.items()
            if (r := rot.read(name, ms, bench)) is not None
        }
        industries = {
            name: r
            for name, ms in by_industry.items()
            if len(ms) >= MIN_INDUSTRY and (r := rot.read(name, ms, bench)) is not None
        }
        ranked = rot.rank(sectors)
        ind_ranked = rot.rank(industries)
        booms = [r.name for r in [*ranked, *ind_ranked] if r.state == "boom"]
        slumps = [r.name for r in [*ranked, *ind_ranked] if r.state == "slump"]
        if booms:
            sentence = "Booming now: " + ", ".join(booms[:4]) + "."
        elif ranked:
            top, low = ranked[0], ranked[-1]
            sentence = (
                f"Strongest: {top.name} ({top.returns.get('1m') or 0:+.1f}% this month); "
                f"weakest: {low.name} ({low.returns.get('1m') or 0:+.1f}%)."
            )
        else:
            sentence = empty["sentence"]
        return {
            "market": market,
            "as_of": int(dates[-1]),
            "sectors": [r.to_json() for r in ranked],
            "industries": [r.to_json() for r in ind_ranked],
            "booms": booms,
            "slumps": slumps,
            "stocks": len(stocks),
            "sentence": sentence,
            "lines": {r.name: r.line for r in ranked},
        }

    def sector_of(self, iid: int) -> str:
        with self.ctx.db.session() as s:
            p = s.get(InstrumentProfile, iid)
            return p.sector if p else ""

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
