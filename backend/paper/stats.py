"""A paper strategy's whole record in numbers (D-209).

The user, 2026-11-06: "whenever I open completed trades it is zero… I want the whole history of
strategy performance: win rate, highest loss, highest wins, top percentile wins… all the
statistics". Computed over every closed trade of the session and, for a Kairos desk, the earlier
runs it carried its money on from (D-207).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol


class TradeLike(Protocol):
    net_pnl: float
    return_pct: float
    charges: float
    bars_held: int
    exit_reason: str
    exit_ts: int
    side: str


def _pct(values: Sequence[float], q: float) -> float | None:
    """The q-th percentile (0–100) by linear interpolation, like numpy's default."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _streaks(results: Sequence[bool]) -> tuple[int, int]:
    best = worst = run_w = run_l = 0
    for won in results:
        run_w, run_l = (run_w + 1, 0) if won else (0, run_l + 1)
        best, worst = max(best, run_w), max(worst, run_l)
    return best, worst


def summarize(trades: Sequence[TradeLike]) -> dict[str, Any]:
    """Win rate, sizes of wins and losses, percentiles, streaks and how trades ended."""
    ts = sorted(trades, key=lambda t: t.exit_ts)
    n = len(ts)
    if n == 0:
        return {"trades": 0}
    pnl = [float(t.net_pnl) for t in ts]
    ret = [float(t.return_pct) for t in ts]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    best, worst = _streaks([p > 0 for p in pnl])
    i_best = max(range(n), key=lambda i: pnl[i])
    i_worst = min(range(n), key=lambda i: pnl[i])
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": 100.0 * len(wins) / n,
        "net_pnl": sum(pnl),
        "charges": sum(float(t.charges) for t in ts),
        "avg_pnl": sum(pnl) / n,
        "avg_win": gross_win / len(wins) if wins else None,
        "avg_loss": -gross_loss / len(losses) if losses else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "biggest_win": pnl[i_best] if pnl[i_best] > 0 else None,
        "biggest_win_pct": ret[i_best] if pnl[i_best] > 0 else None,
        "biggest_loss": pnl[i_worst] if pnl[i_worst] <= 0 else None,
        "biggest_loss_pct": ret[i_worst] if pnl[i_worst] <= 0 else None,
        "avg_return_pct": sum(ret) / n,
        "median_return_pct": _pct(ret, 50),
        "top10_return_pct": _pct(ret, 90),  # the best 10% of trades made at least this
        "bottom10_return_pct": _pct(ret, 10),  # the worst 10% lost at least this
        "avg_bars_held": sum(int(t.bars_held) for t in ts) / n,
        "best_streak": best,
        "worst_streak": worst,
        "longs": sum(1 for t in ts if t.side == "long"),
        "shorts": sum(1 for t in ts if t.side != "long"),
        "exits": dict(Counter(t.exit_reason or "other" for t in ts).most_common()),
        "first_ts": ts[0].exit_ts,
        "last_ts": ts[-1].exit_ts,
    }
