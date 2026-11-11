"""Numbers for one test: study, exam and vault parts, by regime, after costs (D-143).

Every number comes from the shared engine's trades and equity (D-04, D-57). Trades are
assigned to a part by their entry time, like Metis's verdicts (METIS §4).
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

from backend.analysis import regime_map
from backend.core.types import MARKET_TZ, Market
from backend.engine.types import EquityPoint, Trade
from backend.indicators.series import BarSeries
from backend.quant import stats


def part(trades: Sequence[Trade], lo: int, hi: int) -> dict[str, Any]:
    """Closed trades that entered in [lo, hi)."""
    rows = [t for t in trades if t.closed and lo <= t.entry_ts < hi]
    wins = [t.net_pnl for t in rows if t.net_pnl > 0]
    losses = [-t.net_pnl for t in rows if t.net_pnl <= 0]
    net = sum(t.net_pnl for t in rows)
    rets = [t.return_pct for t in rows]
    return {
        "trades": len(rows),
        "net": round(net, 2),
        "win_rate": round(len(wins) / len(rows), 4) if rows else None,
        "profit_factor": round(sum(wins) / sum(losses), 3) if losses and sum(losses) > 0 else None,
        "avg_return_pct": round(float(np.mean(rets)), 4) if rets else None,
        "charges": round(sum(t.charges for t in rows), 2),
        "stocks": len({t.symbol for t in rows}),
        "stocks_up": len([s for s, v in _by_symbol(rows).items() if v > 0]),
        "avg_bars": round(float(np.mean([t.bars_held for t in rows])), 1) if rows else None,
    }


def _by_symbol(rows: Sequence[Trade]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for t in rows:
        out[t.symbol] += t.net_pnl
    return out


def curve(equity: Sequence[EquityPoint], market: Market, lo: int, hi: int) -> dict[str, Any]:
    """Sharpe, the worst fall and the money made over [lo, hi), from daily closes."""
    pts = [p for p in equity if lo <= p.ts < hi]
    if len(pts) < 3:
        return {"sharpe": None, "max_drawdown_pct": None, "days": 0}
    daily = stats.daily_points(pts, MARKET_TZ[market])
    vals = np.array([v for _d, v in daily], dtype=float)
    rets = stats.returns_of(vals)
    peak = np.maximum.accumulate(vals)
    dd = float(np.max((peak - vals) / peak)) if len(vals) else 0.0
    sr = stats.sharpe(rets) if len(rets) > 5 and float(np.std(rets)) > 0 else None
    return {
        "sharpe": None if sr is None or not math.isfinite(sr) else round(float(sr), 3),
        "max_drawdown_pct": round(100 * dd, 2),
        "days": len(vals),
        "returns": [round(float(x), 7) for x in rets],
    }


def index_sharpe(
    benchmark: Sequence[tuple[int, float]], market: Market, lo: int, hi: int
) -> float | None:
    """Buying and holding the market's index over [lo, hi): the bar a strategy must clear."""
    pts = [(ts, v) for ts, v in benchmark if lo <= ts < hi]
    if len(pts) < 10:
        return None
    daily = stats.daily_points(pts, MARKET_TZ[market])
    rets = stats.returns_of([v for _d, v in daily])
    if len(rets) < 5 or float(np.std(rets)) == 0:
        return None
    sr = stats.sharpe(rets)
    return round(float(sr), 3) if math.isfinite(sr) else None


def basket_sharpe(series: dict[str, BarSeries], market: Market, lo: int, hi: int) -> float | None:
    """Buying and holding the strategy's own stocks in equal shares over [lo, hi): the
    no-skill version of the strategy. Rules that can't beat it add nothing (D-143)."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for s in series.values():
        pts = [(int(ts), float(c)) for ts, c in zip(s.ts, s.close, strict=True) if lo <= ts < hi]
        daily = stats.daily_points(pts, MARKET_TZ[market])
        for (_d0, v0), (d1, v1) in itertools.pairwise(daily):
            if v0 > 0:
                by_day[d1].append(v1 / v0 - 1.0)
    rets = np.array([float(np.mean(v)) for _d, v in sorted(by_day.items())])
    if len(rets) < 10 or float(np.std(rets)) == 0:
        return None
    sr = stats.sharpe(rets)
    return round(float(sr), 3) if math.isfinite(sr) else None


def regime_of_entries(
    trades: Sequence[Trade], series: dict[str, BarSeries]
) -> dict[tuple[str, int], str | None]:
    """(symbol, entry time) → the stock's regime on the last candle that closed before the
    entry (the signal candle). Computed once per stock."""
    out: dict[tuple[str, int], str | None] = {}
    by_sym: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_sym[t.symbol].append(t)
    for sym, ts in by_sym.items():
        s = series.get(sym)
        if s is None or len(s) == 0:
            for t in ts:
                out[(sym, t.entry_ts)] = None
            continue
        labels = regime_map.regimes(s)
        for t in ts:
            i = int(np.searchsorted(s.ts, t.entry_ts, side="left")) - 1
            out[(sym, t.entry_ts)] = labels[i] if i >= 0 else None
    return out


def by_regime(
    trades: Sequence[Trade], tags: dict[tuple[str, int], str | None], lo: int, hi: int
) -> dict[str, dict[str, Any]]:
    """For each regime: trades, win rate and average return per trade after costs."""
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        if t.closed and lo <= t.entry_ts < hi:
            groups[tags.get((t.symbol, t.entry_ts)) or "unknown"].append(t)
    out = {}
    for reg, rows in sorted(groups.items()):
        wins = sum(1 for t in rows if t.net_pnl > 0)
        out[reg] = {
            "trades": len(rows),
            "win_rate": round(wins / len(rows), 4),
            "avg_return_pct": round(float(np.mean([t.return_pct for t in rows])), 4),
            "net": round(sum(t.net_pnl for t in rows), 2),
        }
    return out
