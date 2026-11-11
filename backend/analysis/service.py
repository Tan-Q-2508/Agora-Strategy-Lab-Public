"""Kairos's chart reading for the API and the agent: load candles, analyse, forecast, cache.

Uses saved prices only (the Charts screen downloads missing candles first), so reading a
chart never waits on Yahoo. Results are cached per stock, timeframe and latest candle: the
Kairos switch can be flipped back and forth instantly, and a new candle refreshes it.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.analysis import forecast as fc
from backend.analysis import mtf
from backend.analysis.report import Analysis, price
from backend.backtest.run import warmup_ms
from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import service as data_service
from backend.data.store import InstrumentRef
from backend.errors import AgoraError
from backend.indicators.series import BarSeries, from_bars
from backend.logging_setup import get_logger

log = get_logger("analysis")

DAY_MS = 86_400_000
VISIBLE_DAYS = {"1d": 730, "1h": 120, "15m": 30, "5m": 10, "1m": 3}  # matches the Charts screen
HORIZON = {"1d": 10, "1h": 7, "15m": 12, "5m": 12, "1m": 15}
FORECAST_DAYS = {"1d": 6 * 365, "1h": 729, "15m": 59, "5m": 59, "1m": 29}
MAX_PEERS = 8
# The timeframes read together with each chart (biggest first, D-97).
MTF_SET = {
    "1d": ("1mo", "1w", "1d"),
    "1h": ("1w", "1d", "1h"),
    "15m": ("1d", "1h", "15m"),
    "5m": ("1d", "1h", "15m", "5m"),
    "1m": ("1h", "15m", "5m", "1m"),
}
DISCLAIMER = "Kairos is a research tool, not financial advice. Paper money only."
StatsFor = Callable[[Market, Timeframe], Callable[[str], Mapping[str, Any] | None]]


class AnalysisService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ loading

    def series(
        self, inst: InstrumentRef, tf: Timeframe, start_ms: int, warm_bars: int = 260
    ) -> BarSeries:
        now = self.ctx.clock.now_ms()
        lo = start_ms - warmup_ms(tf, warm_bars)
        bars = self.ctx.cache.bars(inst, tf, lo, now + 1, adjusted_prices=True)
        return from_bars(bars, tf, inst.market)

    def _peers(self, inst: InstrumentRef, tf: Timeframe, lo: int, last_ts: int) -> list[np.ndarray]:
        """Closes of up to 8 other stocks in the same market that end on the same candle."""
        if tf is not Timeframe.D1:
            return []
        with self.ctx.db.session() as s:
            others = [
                i
                for i in data_service.default_symbols(s, inst.market)
                if i.id != inst.id and not i.is_index
            ]
        out: list[np.ndarray] = []
        now = self.ctx.clock.now_ms()
        for other in sorted(others, key=lambda i: i.symbol):
            bars = self.ctx.cache.bars(other, tf, lo, now + 1, adjusted_prices=True)
            if len(bars) >= 120 and bars[-1].ts == last_ts:
                out.append(np.array([b.close for b in bars], dtype=np.float64))
            if len(out) >= MAX_PEERS:
                break
        return out

    def clear_cache(self) -> None:
        """Forget cached readings (after Kairos learns, their statistics change)."""
        with self._lock:
            self._cache.clear()

    def _stats(self, market: Market, tf: Timeframe) -> Callable[[str], Mapping[str, Any] | None]:
        learner = self.ctx.services.get("kairos_stats")
        if learner is None:
            return lambda _key: None
        fn: Callable[[str], Mapping[str, Any] | None] = learner.lookup(market, tf)
        return fn

    # ------------------------------------------------------------ the chart reading

    def chart(
        self,
        inst: InstrumentRef,
        tf: Timeframe,
        start_ms: int | None = None,
        *,
        with_forecast: bool = True,
    ) -> dict[str, Any]:
        now = self.ctx.clock.now_ms()
        start = start_ms if start_ms is not None else now - VISIBLE_DAYS[tf.value] * DAY_MS
        s = self.series(inst, tf, start)
        if len(s) < 30:
            raise AgoraError(
                "NOT_ENOUGH_PRICES",
                "Kairos needs more prices to read this chart.",
                "Open the Data screen and download this stock's history, then try again.",
                detail=f"{len(s)} candles saved for {inst.symbol} {tf.value}",
                status=409,
            )
        key = (inst.id, tf.value, start // DAY_MS, int(s.ts[-1]), len(s), with_forecast)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        t0 = time.perf_counter()
        visible = int((s.ts >= start).sum())
        an = Analysis(s, inst.market, inst.symbol, inst.name)
        report = an.report(self._stats(inst.market, tf), window=max(60, visible))
        out: dict[str, Any] = {
            "instrument": {
                "id": inst.id,
                "symbol": inst.symbol,
                "name": inst.name,
                "market": inst.market.value,
            },
            "timeframe": tf.value,
            "report": report,
            "forecast": None,
            "disclaimer": DISCLAIMER,
        }
        try:
            out["timeframes"] = self.timeframes(inst, tf, chart=s)
        except Exception:  # a bonus reading: never cost the user their chart
            log.exception("Multi-timeframe reading failed for %s", inst.symbol)
            out["timeframes"] = None
        if with_forecast:
            try:
                out["forecast"] = self.forecast(inst, tf, future=report["future"])
            except (ValueError, AgoraError) as exc:
                log.info("No forecast for %s %s: %s", inst.symbol, tf.value, exc)
        out["computed_ms"] = round((time.perf_counter() - t0) * 1000)
        with self._lock:
            self._cache[key] = out
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
        return out

    def timeframes(
        self, inst: InstrumentRef, tf: Timeframe, chart: BarSeries | None = None
    ) -> dict[str, Any] | None:
        """The same stock on bigger (and, for the daily chart, smaller) timeframes, each from
        its own saved candles, and one verdict over them (D-97). Weeks and months are built
        from daily candles; an unfinished week or month is left out."""
        now = self.ctx.clock.now_ms()
        zone = ZoneInfo(MARKET_TZ[inst.market])
        wanted = MTF_SET[tf.value]
        readings: list[mtf.Reading] = []
        daily: BarSeries | None = None
        for t in wanted:
            if t in ("1w", "1mo"):
                if daily is None:
                    daily = self.series(inst, Timeframe.D1, now - 12 * 365 * DAY_MS, warm_bars=0)
                big, _ = mtf.resample(daily, t, zone)
                if len(big) and _period_open(int(big.ts[-1]), t, now, zone):
                    big = big.upto(len(big) - 1)
                r = mtf.reading(big, t)
            elif t == tf.value and chart is not None:
                r = mtf.reading(chart, t)
            else:
                days = {"1d": 3 * 365, "1h": 200, "15m": 50, "5m": 20, "1m": 5}[t]
                r = mtf.reading(self.series(inst, Timeframe(t), now - days * DAY_MS, 0), t)
            if r is not None:
                readings.append(r)
        if len(readings) < 2:
            return None
        return mtf.confluence(readings, tf.value)

    def forecast(
        self,
        inst: InstrumentRef,
        tf: Timeframe,
        horizon: int | None = None,
        future: list[int] | None = None,
    ) -> dict[str, Any]:
        now = self.ctx.clock.now_ms()
        lo = now - FORECAST_DAYS[tf.value] * DAY_MS
        bars = self.ctx.cache.bars(inst, tf, lo, now + 1, adjusted_prices=True)
        if len(bars) < 60:
            raise AgoraError(
                "NOT_ENOUGH_PRICES",
                "Kairos needs at least 60 candles to forecast.",
                "Download more history on the Data screen.",
                status=409,
            )
        closes = np.array([b.close for b in bars], dtype=np.float64)
        peers = self._peers(inst, tf, lo, bars[-1].ts)
        n = min([len(closes), *(len(p) for p in peers)]) if peers else len(closes)
        h = horizon or HORIZON[tf.value]
        series = from_bars(bars, tf, inst.market)
        from backend.kairos import forecasts

        scores = self._scores(series)
        tilt, vol_scale, news_note = self._news(inst)
        try:
            mem = forecasts.memory(self.ctx, inst, tf)
        except Exception:  # memory is a bonus; never cost the user their forecast
            log.exception("Forecast memory failed for %s", inst.symbol)
            mem = None
        f = fc.forecast(
            closes,
            h,
            peers=[p[-n:] for p in peers],
            scores=scores,
            news_tilt=tilt,
            vol_scale=vol_scale,
            memory=mem,
        )
        if future is None:
            from backend.analysis.report import future_times

            future = future_times(from_bars(bars[-400:], tf, inst.market), max(h, 15))
        out = fc.to_json(f, future, bars[-1].ts)
        words = fc.describe(
            f,
            symbol=inst.symbol,
            money=lambda v: price(v, inst.market),
            minutes=tf.minutes,
        )
        out.update(words)
        out["peers"] = len(peers)
        out["candles"] = fc.expected_candles(
            f, series.open, series.high, series.low, series.close, future
        )
        out["raw"] = {"median": f.raw_median, "half": f.raw_half}
        out["models_q"] = f.model_q
        out["news"] = news_note
        # Keep score of the forecasts Kairos shows (KAIROS §5, §17): settle old ones, keep
        # this one, and show the latest one whose candles have formed next to reality.
        try:
            checked = forecasts.score(self.ctx, inst, tf, bars)
            forecasts.record(self.ctx, inst, tf, bars[-1].ts, out)
            out["live"] = forecasts.live_record(self.ctx, tf, inst=inst)
            out["calibration"]["checked"] = checked
            prev = forecasts.previous(self.ctx, inst, tf, bars)
            out["previous"] = prev or self._hindcast(closes, bars, h, scores, series)
        except Exception:  # bookkeeping must never cost the user their forecast
            log.exception("Forecast bookkeeping failed for %s", inst.symbol)
            out["live"] = None
            out.setdefault("previous", None)
        out.pop("raw", None)
        out.pop("models_q", None)
        return out

    # ------------------------------------------------------------ forecast helpers

    def _scores(self, series: BarSeries) -> np.ndarray | None:
        """Kairos's score on every candle (neutral weights: the same for every user), for
        the analyst model. Too short a history: none."""
        if len(series) < 120:
            return None
        from backend.kairos import brain

        ss = brain.shared_signals(series)
        return np.array([brain.decide(ss, i, {}).score for i in range(len(series))])

    def _news(self, inst: InstrumentRef) -> tuple[float, float, dict[str, Any] | None]:
        """Live only: the stock's own news leans the analyst model; high market news risk
        widens every model's range."""
        news = self.ctx.services.get("news")
        if news is None or not news.enabled():
            return 0.0, 1.0, None
        tilt, scale = 0.0, 1.0
        note: dict[str, Any] = {}
        try:
            alert = news.alert(inst.id)
            state = alert.get("state")
            if state == "critical":
                tilt = -1.0
            elif state in ("positive", "negative"):
                tilt = float(alert.get("score") or 0.0)
            note["stock"] = state
            gauge = news.risk(inst.market)
            level = float(gauge.get("level") or 0.0)  # 0–100
            scale = 1.0 + max(0.0, level - 25.0) / 150.0
            note["risk"] = round(level)
        except Exception:
            log.info("No news for the forecast of %s", inst.symbol)
            return 0.0, 1.0, None
        note["tilt"] = round(tilt, 2)
        note["widen_pct"] = round((scale - 1.0) * 100)
        return tilt, scale, note

    def _hindcast(
        self,
        closes: np.ndarray,
        bars: list[Any],
        h: int,
        scores: np.ndarray | None,
        series: BarSeries,
    ) -> dict[str, Any] | None:
        """No saved prediction has formed yet: re-create the one Kairos would have made
        ``h`` candles ago, using only what was known then, and compare it with reality."""
        from backend.kairos import forecasts

        cut = len(closes) - h
        if cut < 120:
            return None
        f = fc.forecast(
            closes[:cut],
            h,
            scores=None if scores is None else scores[:cut],
            tests=20,
        )
        future = [b.ts for b in bars[cut : cut + h]]
        past = series.upto(cut)
        candles = fc.expected_candles(f, past.open, past.high, past.low, past.close, future)
        path = fc.to_json(f, future, bars[cut - 1].ts)["path"][1:]
        detail = {"candles": candles, "path": path}
        out = forecasts.compare(detail, f.origin, bars[cut : cut + h])
        out.update(
            {
                "made_at": bars[cut - 1].ts,
                "origin": f.origin,
                "kind": "re-created",
                "predicted": candles,
                "path": path,
                "complete": True,
            }
        )
        return out


def _period_open(start_ts: int, bigger: str, now_ms: int, zone: ZoneInfo) -> bool:
    """Is the week or month that started at ``start_ts`` still going on at ``now_ms``?"""
    a = ms_to_dt(start_ts, zone).date()
    b = ms_to_dt(now_ms, zone).date()
    if bigger == "1w":
        return a.isocalendar()[:2] == b.isocalendar()[:2]
    return (a.year, a.month) == (b.year, b.month)
