"""Backtest metrics (SPEC §6.3), defined precisely so golden tests can pin them.

Definitions (also shown as tooltips in the UI, GLOSSARY.md words):
- Returns are measured on the equity curve resampled to one point per trading day (the last
  equity of each local date), so daily and intraday strategies are comparable.
- Volatility, Sharpe and Sortino are annualised with √252 and a 0% risk-free rate.
  Sharpe = mean / sample standard deviation of daily returns × √252.
  Sortino = mean / downside deviation (root-mean-square of negative daily returns) × √252.
- CAGR uses calendar time: (final ÷ start)^(365.25 days ÷ length) − 1.
- Max drawdown is the deepest fall from a running peak, over every equity point; its
  duration is the longest stretch (in days) spent below a previous peak.
- Trade statistics use closed trades only; trades still open at the end are excluded.
- Profit factor = total won ÷ total lost (None when nothing was lost).
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from backend.core.clock import ms_to_dt
from backend.engine.types import EquityPoint, Trade

DAY_MS = 86_400_000
YEAR_DAYS = 365.25


@dataclass(frozen=True)
class Drawdown:
    max_dd: float  # e.g. 0.18 for an 18% fall (positive number)
    peak_ts: int | None
    trough_ts: int | None
    recovered_ts: int | None
    longest_days: float


def daily_closes(points: Sequence[EquityPoint], tz: ZoneInfo) -> list[tuple[str, float]]:
    """(local date, last equity of that date), in order."""
    out: OrderedDict[str, float] = OrderedDict()
    for p in points:
        out[ms_to_dt(p.ts, tz).strftime("%Y-%m-%d")] = p.equity
    return list(out.items())


def returns(values: Sequence[float], start: float | None = None) -> list[float]:
    """Simple period returns; ``start`` (the capital) makes the first period count too."""
    seq = ([start] if start is not None else []) + list(values)
    return [seq[i] / seq[i - 1] - 1.0 for i in range(1, len(seq)) if seq[i - 1] > 0]


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sharpe(rets: Sequence[float]) -> float | None:
    sd = stdev(rets)
    return mean(rets) / sd * math.sqrt(252) if sd > 0 else None


def sortino(rets: Sequence[float]) -> float | None:
    if not rets:
        return None
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets))
    return mean(rets) / downside * math.sqrt(252) if downside > 0 else None


def cagr(start: float, end: float, days: float) -> float | None:
    if start <= 0 or end <= 0 or days <= 0:
        return None
    return float((end / start) ** (YEAR_DAYS / days)) - 1.0


def drawdown(points: Sequence[tuple[int, float]], start_value: float | None = None) -> Drawdown:
    if not points:
        return Drawdown(0.0, None, None, None, 0.0)
    peak = start_value if start_value is not None else points[0][1]
    peak_ts = points[0][0]
    worst, w_peak, w_trough, w_peak_value = 0.0, None, None, 0.0
    under_since: int | None = None
    longest = 0.0
    for ts, v in points:
        if v >= peak:
            if under_since is not None:
                longest = max(longest, (ts - under_since) / DAY_MS)
                under_since = None
            peak, peak_ts = v, ts
            continue
        if under_since is None:
            under_since = peak_ts
        dd = 1.0 - v / peak if peak > 0 else 0.0
        if dd > worst:
            worst, w_peak, w_trough, w_peak_value = dd, peak_ts, ts, peak
    if under_since is not None:
        longest = max(longest, (points[-1][0] - under_since) / DAY_MS)
    recovered = None
    if w_trough is not None:
        recovered = next((ts for ts, v in points if ts > w_trough and v >= w_peak_value), None)
    return Drawdown(worst, w_peak, w_trough, recovered, longest)


def underwater(points: Sequence[tuple[int, float]], start_value: float) -> list[tuple[int, float]]:
    """(ts, drawdown as a negative fraction) for the underwater chart."""
    peak = start_value
    out = []
    for ts, v in points:
        peak = max(peak, v)
        out.append((ts, v / peak - 1.0 if peak > 0 else 0.0))
    return out


def monthly_returns(daily: Sequence[tuple[str, float]], start_value: float) -> dict[str, float]:
    """{"YYYY-MM": return} from month-end equity (the first month starts at the capital)."""
    month_end: OrderedDict[str, float] = OrderedDict()
    for day, v in daily:
        month_end[day[:7]] = v
    out: dict[str, float] = {}
    prev = start_value
    for m, v in month_end.items():
        out[m] = v / prev - 1.0 if prev > 0 else 0.0
        prev = v
    return out


def trade_stats(trades: Sequence[Trade]) -> dict[str, Any]:
    closed = [t for t in trades if t.closed]
    wins = [t for t in closed if t.net_pnl > 0]
    losses = [t for t in closed if t.net_pnl <= 0]
    won = sum(t.net_pnl for t in wins)
    lost = -sum(t.net_pnl for t in losses)
    hold_days = [(t.exit_ts - t.entry_ts) / DAY_MS for t in closed]
    return {
        "trades": len(closed),
        "open_at_end": len(trades) - len(closed),
        "win_rate": len(wins) / len(closed) if closed else None,
        "profit_factor": won / lost if lost > 0 else None,
        "expectancy": mean([t.net_pnl for t in closed]) if closed else None,
        "avg_win": mean([t.net_pnl for t in wins]) if wins else None,
        "avg_loss": mean([t.net_pnl for t in losses]) if losses else None,
        "largest_win": max((t.net_pnl for t in closed), default=None),
        "largest_loss": min((t.net_pnl for t in closed), default=None),
        "avg_bars_held": mean([t.bars_held for t in closed]) if closed else None,
        "avg_hold_days": mean(hold_days) if hold_days else None,
        "gross_pnl": sum(t.gross_pnl for t in closed),
        "net_pnl": sum(t.net_pnl for t in closed),
    }


def compute(
    points: Sequence[EquityPoint],
    trades: Sequence[Trade],
    capital: float,
    tz: ZoneInfo,
    *,
    charges_total: float,
    traded_notional: float,
    benchmark: Sequence[tuple[int, float]] | None = None,
) -> dict[str, Any]:
    """Every headline and full metric for one run (JSON-ready)."""
    if not points:
        return {"empty": True}
    final = points[-1].equity
    days = max((points[-1].ts - points[0].ts) / DAY_MS, 1.0)
    daily = daily_closes(points, tz)
    rets = returns([v for _, v in daily], capital)
    dd = drawdown([(p.ts, p.equity) for p in points], capital)
    growth = cagr(capital, final, days)
    vol = stdev(rets) * math.sqrt(252) if len(rets) > 1 else None
    ts_ = trade_stats(trades)
    avg_equity = mean([p.equity for p in points])
    gross_profit = ts_["gross_pnl"]
    out: dict[str, Any] = {
        "start_equity": capital,
        "final_equity": final,
        "total_return": final / capital - 1.0,
        "cagr": growth,
        "volatility": vol,
        "sharpe": sharpe(rets),
        "sortino": sortino(rets),
        "max_drawdown": dd.max_dd,
        "max_drawdown_peak": dd.peak_ts,
        "max_drawdown_trough": dd.trough_ts,
        "max_drawdown_recovered": dd.recovered_ts,
        "max_drawdown_days": dd.longest_days,
        "calmar": (growth / dd.max_dd) if growth is not None and dd.max_dd > 0 else None,
        "time_in_market": mean([1.0 if p.exposure > 0 else 0.0 for p in points]),
        "avg_exposure": mean([p.exposure for p in points]),
        "turnover": traded_notional / avg_equity / (days / YEAR_DAYS) if avg_equity > 0 else None,
        "charges_total": charges_total,
        "charges_pct_of_gross_profit": charges_total / gross_profit if gross_profit > 0 else None,
        "days": days,
        "monthly_returns": monthly_returns(daily, capital),
        **ts_,
    }
    if benchmark:
        b0, b1 = benchmark[0][1], benchmark[-1][1]
        bdays = max((benchmark[-1][0] - benchmark[0][0]) / DAY_MS, 1.0)
        bdd = drawdown(benchmark)
        out["benchmark"] = {
            "total_return": b1 / b0 - 1.0 if b0 > 0 else None,
            "cagr": cagr(b0, b1, bdays),
            "max_drawdown": bdd.max_dd,
        }
        if out["benchmark"]["total_return"] is not None:
            out["vs_benchmark"] = out["total_return"] - out["benchmark"]["total_return"]
    return out


def per_symbol(trades: Sequence[Trade]) -> list[dict[str, Any]]:
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(t.symbol, []).append(t)
    rows = []
    for sym, ts in sorted(groups.items()):
        closed = [t for t in ts if t.closed]
        wins = [t for t in closed if t.net_pnl > 0]
        rows.append(
            {
                "symbol": sym,
                "trades": len(closed),
                "win_rate": len(wins) / len(closed) if closed else None,
                "net_pnl": sum(t.net_pnl for t in ts),
                "charges": sum(t.charges for t in ts),
                "open_at_end": len(ts) - len(closed),
            }
        )
    return rows
