"""A tear sheet for any backtest (task 16.2, D-89; pyfolio and QuantStats, LANDSCAPE §4): how
much of a result could be luck, and what the bad times looked like.

- **Sharpe band**: the Sharpe ratio with a 90% range from a stationary block bootstrap of the
  daily returns, the probability that the true Sharpe is above zero (PSR), the luck check over
  the settings tried when it came from a sweep (DSR, D-82), and the track record needed for 95%
  confidence (``backend/quant/stats.py``).
- **Range of outcomes**: the same bootstrap's yearly return and worst drop (5th, 50th and 95th
  percentiles): other histories the strategy could just as well have had.
- **Trade order**: the same trades in random orders (``resample.trade_order``): a fairer "worst
  drop to expect" than the one order history took, and the losing streak to be ready for.
- **Rolling Sharpe**: the Sharpe ratio of each 6-month window, to see whether the edge is steady
  or came from one lucky stretch.
- **Underwater periods**: the five deepest falls from a high, with how long each took to fall and
  to recover.
- **Risk numbers**: value at risk and expected shortfall (historical: the k-th worst day, k =
  ⌈n × 5%⌉, and the average of the k worst), best and worst days and months, the share of
  winning months, the tail ratio (k-th best day ÷ k-th worst), skew and kurtosis.

Everything is worked out from the run's daily equity (the last value of each local day), so it is
the same for every kind of strategy. Seeded, so a run's tear sheet always repeats.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.core.clock import ms_to_dt
from backend.quant import resample, stats

WINDOW = 126  # about six months of trading days
MAX_POINTS = 300
N_BOOT = 400
MEAN_BLOCK = 10.0


def daily(points: Sequence[tuple[int, float]], tz: ZoneInfo) -> list[tuple[str, float]]:
    """(local day, the day's last equity), oldest first."""
    by_day: dict[str, float] = {}
    for ts, v in points:
        by_day[ms_to_dt(ts, tz).strftime("%Y-%m-%d")] = float(v)
    return list(by_day.items())


def drawdown_periods(
    days: Sequence[str], values: Sequence[float], start_value: float, top: int = 5
) -> list[dict[str, Any]]:
    """The deepest falls from a high: peak, trough and recovery days (None if not recovered),
    depth as a fraction, and their lengths in calendar days. Deepest first."""
    periods: list[dict[str, Any]] = []
    peak, peak_day = start_value, days[0] if days else ""
    cur: dict[str, Any] | None = None
    for day, v in zip(days, values, strict=True):
        if v >= peak:
            if cur is not None:
                cur["recovered"] = day
                periods.append(cur)
                cur = None
            peak, peak_day = v, day
            continue
        depth = 1.0 - v / peak if peak > 0 else 0.0
        if cur is None:
            cur = {"peak": peak_day, "trough": day, "recovered": None, "depth": depth}
        elif depth > cur["depth"]:
            cur["trough"], cur["depth"] = day, depth
    if cur is not None:
        periods.append(cur)
    out = sorted(periods, key=lambda p: -p["depth"])[:top]
    for p in out:
        p["depth"] = round(p["depth"], 6)
        p["days_falling"] = _days(p["peak"], p["trough"])
        p["days_recovering"] = _days(p["trough"], p["recovered"]) if p["recovered"] else None
    return out


def _days(a: str, b: str) -> int:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days


def rolling_sharpe(
    returns: Sequence[float] | np.ndarray, window: int = WINDOW, periods: int = stats.DAYS
) -> np.ndarray:
    """Annualised Sharpe ratio of each window of ``window`` returns ending at each day (NaN
    before the first full window, and where the window didn't move)."""
    r = np.asarray(returns, dtype=float)
    out = np.full(len(r), np.nan)
    for i in range(window - 1, len(r)):
        w = r[i - window + 1 : i + 1]
        sd = float(w.std(ddof=1))
        if sd > 0:
            out[i] = float(w.mean()) / sd * math.sqrt(periods)
    return out


def tail(returns: Sequence[float] | np.ndarray, level: float = 0.95) -> dict[str, float]:
    """Historical value at risk and expected shortfall at ``level`` (as positive losses), and the
    tail ratio: with k = ⌈n × (1 − level)⌉, the k-th worst day, the average of the k worst, and
    the k-th best ÷ the k-th worst."""
    r = np.sort(np.asarray(returns, dtype=float))
    if len(r) == 0:
        return {"var": 0.0, "cvar": 0.0, "tail_ratio": 0.0}
    k = max(1, math.ceil(len(r) * (1.0 - level) - 1e-9))
    worst, best = float(r[k - 1]), float(r[-k])
    return {
        "var": max(0.0, -worst),
        "cvar": max(0.0, -float(r[:k].mean())),
        "tail_ratio": abs(best) / abs(worst) if worst != 0 else 0.0,
    }


def resamples(
    returns: Sequence[float] | np.ndarray,
    n_boot: int = N_BOOT,
    *,
    mean_block: float = MEAN_BLOCK,
    seed: int = 11,
) -> np.ndarray:
    """``n_boot`` stationary-bootstrap resamples of the returns (Politis and Romano, 1994), one
    per row: blocks of consecutive days with random starts and lengths averaging
    ``mean_block``, wrapping round at the end. Vectorised, so it costs little on every run."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    rng = np.random.default_rng(seed)
    starts = rng.integers(n, size=(n_boot, n))
    new_block = rng.random((n_boot, n)) < 1.0 / max(mean_block, 1.0)
    new_block[:, 0] = True
    pos = np.arange(n)
    # where the current block began, and the random day it starts from
    began = np.maximum.accumulate(np.where(new_block, pos, 0), axis=1)
    first = np.take_along_axis(starts, began, axis=1)
    return np.asarray(r[(first + (pos - began)) % n])


def sharpe_band(
    returns: Sequence[float] | np.ndarray, periods: int = stats.DAYS, *, seed: int = 7
) -> dict[str, float]:
    """5th, 50th and 95th percentiles of the annualised Sharpe ratio over resamples."""
    r = np.asarray(returns, dtype=float)
    if len(r) < 10:
        v = stats.sharpe(r, periods) if len(r) > 1 else 0.0
        return {"p5": v, "p50": v, "p95": v}
    m = resamples(r, seed=seed)
    sd = m.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        vals = np.where(sd > 0, m.mean(axis=1) / sd, 0.0) * math.sqrt(periods)
    p5, p50, p95 = np.percentile(vals, [5, 50, 95])
    return {"p5": float(p5), "p50": float(p50), "p95": float(p95)}


def outcomes(
    returns: Sequence[float] | np.ndarray, periods: int = stats.DAYS, *, seed: int = 11
) -> dict[str, float]:
    """Other histories from the bootstrap: yearly return and worst drop (as fractions), 5th,
    50th and 95th percentiles."""
    r = np.asarray(returns, dtype=float)
    if len(r) < 20:
        return {}
    paths = np.cumprod(1.0 + resamples(r, seed=seed), axis=1)
    last = paths[:, -1]
    with np.errstate(invalid="ignore"):
        yearly = np.where(last > 0, np.abs(last) ** (periods / len(r)) - 1.0, -1.0)
    full = np.concatenate([np.ones((len(paths), 1)), paths], axis=1)
    peaks = np.maximum.accumulate(full, axis=1)
    drops = ((peaks - full) / np.where(peaks > 0, peaks, 1.0)).max(axis=1)
    y5, y50, y95 = np.percentile(yearly, [5, 50, 95])
    d50, d95 = np.percentile(drops, [50, 95])
    return {
        "return_p5": float(y5),
        "return_p50": float(y50),
        "return_p95": float(y95),
        "drop_p50": float(d50),
        "drop_p95": float(d95),
    }


def _years(day_values: Sequence[tuple[str, float]], start_value: float) -> list[dict[str, Any]]:
    year_end: dict[str, float] = {}
    for day, v in day_values:
        year_end[day[:4]] = v
    out, prev = [], start_value
    for y, v in year_end.items():
        out.append({"year": y, "return": round(v / prev - 1.0, 6) if prev > 0 else 0.0})
        prev = v
    return out


def _months(day_values: Sequence[tuple[str, float]], start_value: float) -> list[float]:
    month_end: dict[str, float] = {}
    for day, v in day_values:
        month_end[day[:7]] = v
    out, prev = [], start_value
    for v in month_end.values():
        out.append(v / prev - 1.0 if prev > 0 else 0.0)
        prev = v
    return out


def _thin(days: Sequence[str], values: np.ndarray) -> list[list[Any]]:
    pts = [[d, round(float(v), 3)] for d, v in zip(days, values, strict=True) if math.isfinite(v)]
    step = max(1, math.ceil(len(pts) / MAX_POINTS))
    out = pts[::step]
    if pts and out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def compute(
    points: Sequence[tuple[int, float]],
    pnls: Sequence[float],
    capital: float,
    tz: ZoneInfo,
    *,
    n_trials: int = 1,
) -> dict[str, Any]:
    """The whole tear sheet for one run: equity points (ts, equity), each closed trade's money
    after costs, the starting money, the market's time zone, and how many settings were tried
    (a sweep's cells) for the luck check."""
    day_values = daily(points, tz)
    days = [d for d, _v in day_values]
    values = [v for _d, v in day_values]
    rets = stats.returns_of([capital, *values]) if values else np.array([], dtype=float)
    n = len(rets)
    if n < 20:
        return {"days": n, "empty": True, "text": "Too short a backtest for a tear sheet."}
    sharpe = stats.sharpe(rets)
    band = sharpe_band(rets)
    psr = stats.psr(rets)
    mtr = stats.min_track_record(rets)
    sharpe_part: dict[str, Any] = {
        "value": round(sharpe, 3),
        "band": {k: round(v, 3) for k, v in band.items()},
        "psr": round(psr, 4),
        "trials": n_trials,
        "dsr": round(stats.dsr(rets, n_trials), 4) if n_trials > 1 else None,
        "min_track_record_days": None if math.isinf(mtr) else round(mtr),
        "have_days": n,
    }
    out_part = outcomes(rets)
    order = resample.trade_order(list(pnls), capital, n=1000, seed=7)
    roll = rolling_sharpe(rets)
    finite = roll[np.isfinite(roll)]
    rolling_part = {
        "window": WINDOW,
        "points": _thin(days, roll),
        "share_positive": round(float((finite > 0).mean()), 4) if len(finite) else None,
    }
    periods = drawdown_periods(days, values, capital)
    peak = np.maximum.accumulate(np.concatenate([[capital], np.asarray(values)]))[1:]
    under = float((np.asarray(values) < peak).mean())
    months = _months(day_values, capital)
    _m, _sd, skew, kurt = stats.moments(rets)
    t = tail(rets)
    risk = {
        "var_95": round(t["var"], 6),
        "cvar_95": round(t["cvar"], 6),
        "tail_ratio": round(t["tail_ratio"], 3),
        "best_day": round(float(rets.max()), 6),
        "worst_day": round(float(rets.min()), 6),
        "best_month": round(max(months), 6) if months else None,
        "worst_month": round(min(months), 6) if months else None,
        "positive_months": round(sum(1 for m in months if m > 0) / len(months), 4)
        if months
        else None,
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
    }
    sheet = {
        "days": n,
        "sharpe": sharpe_part,
        "outcomes": {k: round(v, 6) for k, v in out_part.items()},
        "trade_order": order,
        "rolling": rolling_part,
        "underwater": {"periods": periods, "time_underwater": round(under, 4)},
        "risk": risk,
        "years": _years(day_values, capital),
    }
    sheet["summary"] = summary(sheet)
    return sheet


def summary(sheet: dict[str, Any]) -> list[str]:
    """The tear sheet in a few plain sentences, written by rules (no AI)."""
    lines: list[str] = []
    sh = sheet["sharpe"]
    b = sh["band"]
    lines.append(
        f"Sharpe ratio {sh['value']:.2f}; anywhere from {b['p5']:.2f} to {b['p95']:.2f} is "
        f"plausible (90% range), and there is a {sh['psr'] * 100:.0f}% chance the true Sharpe "
        "is above zero."
    )
    if sh["dsr"] is not None:
        lines.append(
            f"It was the best of {sh['trials']} settings tried; allowing for that, the luck "
            f"check gives {sh['dsr'] * 100:.0f}% (at least 50% is wanted)."
        )
    mtr = sh["min_track_record_days"]
    if mtr is None:
        lines.append("With no edge above zero, no length of track record would make it trusted.")
    elif mtr > sh["have_days"]:
        lines.append(
            f"To be 95% sure the edge is real it would need about {mtr:,} days of results; it "
            f"has {sh['have_days']:,}."
        )
    o = sheet["outcomes"]
    if o:
        lines.append(
            f"Other histories it could just as well have had: a yearly return between "
            f"{_pct(o['return_p5'])} and {_pct(o['return_p95'])}, and a worst drop of "
            f"{_pct(o['drop_p50'])} half the time, {_pct(o['drop_p95'])} in a bad case."
        )
    tr = sheet["trade_order"]
    if tr.get("trades", 0) >= 5:
        lines.append(
            f"The same {tr['trades']} trades in other orders: the worst drop was {tr['p50']:.1f}% "
            f"half the time and up to {tr['p95']:.1f}% in 1 in 20 orders (history: "
            f"{tr['history']:.1f}%); be ready for {tr['losing_streak_p95']} losing trades in a row."
        )
    roll = sheet["rolling"]
    if roll["share_positive"] is not None:
        lines.append(
            f"Its six-month Sharpe ratio was above zero {roll['share_positive'] * 100:.0f}% of "
            "the time."
        )
    deep = sheet["underwater"]["periods"]
    if deep:
        d = deep[0]
        rec = (
            f"took {d['days_recovering']} days to recover"
            if d["days_recovering"] is not None
            else "hasn't recovered yet"
        )
        lines.append(
            f"The deepest fall was {_pct(d['depth'])} over {d['days_falling']} days and {rec}; "
            f"it spent {sheet['underwater']['time_underwater'] * 100:.0f}% of days below an "
            "earlier high."
        )
    return lines
