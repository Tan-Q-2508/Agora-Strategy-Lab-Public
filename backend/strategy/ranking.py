"""Ranking strategies (task 16.5, D-91; Portfolio123 and Quantpedia, LANDSCAPE §4): the
best-documented stock anomalies are cross-sectional, so these strategies compare stocks with
each other instead of reading one chart at a time.

Each month, on its first trading day, every stock of the universe is scored from closed candles
only, and the top ``hold`` are held in equal shares until the next month's ranking:

- **Momentum** (Jegadeesh and Titman, 1993): the rise over the last ``lookback_months`` months,
  leaving out the latest ``skip_months`` (the most recent month tends to reverse). With the
  trend filter, only stocks that rose qualify ("absolute momentum", Antonacci).
- **Low volatility** (Blitz and van Vliet, 2007; Baker, Bradley and Wurgler, 2011): the calmest
  stocks by the spread of their daily moves over ``lookback_months``. With the trend filter, only
  stocks above their 200-day average qualify.

It runs in the shared engine like every strategy (D-04): the engine hands the program all its
stocks (``bind``), each stock's ``on_bar`` buys when the stock is in this month's top and sells
when it drops out, and fills, costs and limits are the engine's own. Scores use split-adjusted
closes up to the current candle (no look-ahead), and a stock that wasn't in the index on the
day (when membership history is known) isn't ranked. In the builder's preview a stock is seen
alone, so there it is "held" whenever it passes the filter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.strategy.definition import RankingDefinition, RankingSettings, Universe
from backend.strategy.runtime import StrategyContext

DAYS_PER_MONTH = 21
TREND_DAYS = 200
STALE_MS = 10 * 86_400_000  # a stock with no candle for this long isn't ranked


@dataclass(frozen=True)
class RankingTemplate:
    key: str
    name: str
    summary: str
    description: str
    idea: str
    settings: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "summary": self.summary,
            "description": self.description,
            "idea": self.idea,
            "timeframe": "1d",
            "kind": "ranking",
        }


RANKING_TEMPLATES: dict[str, RankingTemplate] = {
    t.key: t
    for t in (
        RankingTemplate(
            "momentum_top",
            "Momentum: the 10 strongest risers",
            "Each month, hold the 10 stocks that rose most over the past year.",
            "Ranks every stock in the index by its rise over the last 12 months, leaving out "
            "the latest month, and holds the top 10 that actually rose, in equal shares, until "
            "next month. One of the best-documented effects in stock markets, worldwide. It can "
            "fall hard when markets turn sharply (momentum crashes, as in 2009).",
            "Stocks that have risen most tend to keep rising for a few more months.",
            {"rank_by": "momentum", "lookback_months": 12, "skip_months": 1, "hold": 10},
        ),
        RankingTemplate(
            "momentum_fast",
            "Momentum: six months, top 5",
            "Each month, hold the 5 stocks that rose most over the past six months.",
            "A quicker, more concentrated momentum: the 5 biggest risers of the last six months "
            "(leaving out the latest month). More turnover and bigger swings than the 12-month "
            "version.",
            "Recent winners keep winning for a while.",
            {"rank_by": "momentum", "lookback_months": 6, "skip_months": 1, "hold": 5},
        ),
        RankingTemplate(
            "low_volatility",
            "Low volatility: the 10 calmest stocks",
            "Each month, hold the 10 calmest stocks that are in an uptrend.",
            "Ranks every stock in the index by how much it moved day to day over the last six "
            "months and holds the 10 calmest that are above their 200-day average, in equal "
            "shares. Calm stocks have historically earned about as much as wild ones with "
            "smaller drops (the low-volatility anomaly). It usually lags in strong rallies.",
            "Calm, steady stocks are underpriced because investors chase exciting ones.",
            {"rank_by": "low_volatility", "lookback_months": 6, "skip_months": 0, "hold": 10},
        ),
    )
}


def ranking_definition(
    key: str, market: str, symbols: list[str] | None = None
) -> RankingDefinition:
    t = RANKING_TEMPLATES[key]
    return RankingDefinition(
        market=market,
        product="delivery" if market == "IN" else "cash",
        universe=Universe(kind="symbols", symbols=symbols) if symbols else Universe(kind="all"),
        ranking=RankingSettings(**t.settings),
    )


def describe(r: RankingSettings, hold_word: bool = True) -> str:
    """The rules in one plain sentence."""
    if r.rank_by == "momentum":
        how = f"{r.lookback_months}-month rise" + (
            f" (leaving out the latest {r.skip_months} month{'s' if r.skip_months != 1 else ''})"
            if r.skip_months
            else ""
        )
        flt = " that actually rose" if r.trend_filter else ""
    else:
        how = f"calmness over {r.lookback_months} months"
        flt = " above their 200-day average" if r.trend_filter else ""
    return f"Each month, rank the stocks by {how} and hold the top {r.hold}{flt}, in equal shares."


class Ranker:
    """The monthly ranking behind a ranking strategy's ``on_bar``."""

    def __init__(self, settings: RankingSettings) -> None:
        self.s = settings
        self.look = settings.lookback_months * DAYS_PER_MONTH
        self.skip = settings.skip_months * DAYS_PER_MONTH if settings.rank_by == "momentum" else 0
        self.symbols: list[Any] = []
        self._arrays: dict[int, tuple[int, np.ndarray, np.ndarray]] = {}
        self._month: str | None = None
        self._chosen: dict[str, tuple[int, float]] = {}
        self._ranked = 0
        self._solo: dict[str, tuple[str, tuple[int, float] | None]] = {}

    @property
    def warmup(self) -> int:
        trend = TREND_DAYS if self.s.trend_filter and self.s.rank_by == "low_volatility" else 0
        return max(self.look + 1, trend) + 10

    def bind(self, symbols: list[Any]) -> None:
        """The engine's stocks (``SymbolState``): what each month's ranking compares."""
        self.symbols = list(symbols)

    # -- scoring

    def score(self, close: np.ndarray) -> float | None:
        """The score of one stock from its split-adjusted closes up to now (newest last), or
        None when it has too little history or fails the trend filter. Higher is better."""
        n = len(close)
        if n <= self.look or not np.isfinite(close[-1]):
            return None
        if self.s.rank_by == "momentum":
            then, recent = close[n - 1 - self.look], close[n - 1 - self.skip]
            if not (then > 0 and np.isfinite(recent)):
                return None
            rise = float(recent / then - 1.0)
            if self.s.trend_filter and rise <= 0:
                return None
            return rise
        window = close[n - 1 - self.look :]
        if np.any(~np.isfinite(window)) or np.any(window <= 0):
            return None
        sd = float(np.std(np.diff(np.log(window)), ddof=1))
        if self.s.trend_filter:
            if n < TREND_DAYS:
                return None
            if close[-1] <= float(np.mean(close[n - TREND_DAYS :])):
                return None
        return -sd * math.sqrt(252)  # calmer ranks higher

    def _series(self, st: Any) -> tuple[np.ndarray, np.ndarray]:
        raw = st.raw
        hit = self._arrays.get(id(st))
        if hit is None or hit[0] != len(raw):
            ts = np.fromiter((b.ts for b in raw), dtype=np.int64, count=len(raw))
            close = np.fromiter(
                (b.close * b.split_factor for b in raw), dtype=np.float64, count=len(raw)
            )
            hit = self._arrays[id(st)] = (len(raw), ts, close)
        return hit[1], hit[2]

    def select(self, ts: int) -> dict[str, tuple[int, float]]:
        """This month's top stocks: symbol → (rank, score), from candles up to ``ts``."""
        scored: list[tuple[float, str]] = []
        for st in self.symbols:
            if st.member is not None and not st.member(ts):
                continue
            times, close = self._series(st)
            i = int(np.searchsorted(times, ts, side="right")) - 1
            if i < 0 or times[i] < ts - STALE_MS:
                continue
            sc = self.score(close[: i + 1])
            if sc is not None:
                scored.append((sc, st.inst.symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        self._ranked = len(scored)
        return {sym: (k, sc) for k, (sc, sym) in enumerate(scored[: self.s.hold], start=1)}

    # -- the strategy

    def _why(self, rank: int, sc: float) -> str:
        if self.s.rank_by == "momentum":
            return (
                f"Rank {rank} of {self._ranked} by {self.s.lookback_months}-month momentum "
                f"({sc * 100:+.0f}%)"
            )
        return f"Rank {rank} of {self._ranked} by calmness ({-sc * 100:.0f}% a year)"

    def on_bar(self, ctx: StrategyContext) -> None:
        month = ctx.date[:7]
        if self.symbols:
            if month != self._month:
                self._month = month
                self._chosen = self.select(ctx.time)
            pick = self._chosen.get(ctx.symbol)
        else:  # alone (the builder's preview): held whenever it passes, decided monthly
            last = self._solo.get(ctx.symbol)
            if last is None or last[0] != month:
                need = max(self.look + 1, TREND_DAYS) + 1
                sc = self.score(np.asarray(ctx.close.to_list(need), dtype=float))
                self._ranked = 1
                last = (month, (1, sc) if sc is not None else None)
                self._solo[ctx.symbol] = last
            pick = last[1]
        if pick is not None and ctx.position is None:
            ctx.buy(reason=self._why(*pick))
        elif pick is None and ctx.position is not None:
            what = "momentum" if self.s.rank_by == "momentum" else "calmness"
            ctx.sell_all(reason=f"Out of the top {self.s.hold} by {what} this month")
