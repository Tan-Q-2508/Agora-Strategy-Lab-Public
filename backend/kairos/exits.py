"""Kairos chooses its own exits from its record (D-140).

The user (2026-10-28): "I hope Kairos is learning from all the bad trades and good trades and
trying to improve or find ways to avoid losses or get more profit. Concepts like stop-loss,
trailing stop-loss, partial profits, everything must be known to it, but usage of these depends
on Kairos's brain."

Kairos knew every exit already (a stop at the signal's invalidation or a multiple of the ATR, a
target at the measured move or a multiple of the risk, a trailing stop, half sold at a multiple
of the risk with the stop then moved to the entry, a time limit), but the numbers were fixed
settings. Now it compares **exit plans** on its own trades and uses the one that has earned the
most per trade:

- **On history** (part of the signal study, ``learning.train``): every entry the brain would have
  made on the studied stocks (non-overlapping, ``SPACING`` candles apart) is played out under
  each plan with the same rules as the shared engine (filled at the next open; stop before target
  inside a candle; a gap through a level fills at the open; the trailing stop follows the best
  price of the candles before; after the partial sale the stop moves to the entry; out at the
  close after ``max_bars``). The result is in R (multiples of the risk), after an approximate
  round-trip cost. The first 70% of each stock's history is the **study**, the rest the **exam**.
- **On paper**: every closed desk trade is played out under every plan too (on the candles since
  its entry), counted 3× like the signals' paper record.
- **The choice** (``choose``): a plan may replace the settings' plan only when it did at least as
  well in the exam years (so it isn't just lucky in the study), and then the best average R wins,
  history weighted by up to ``PRIOR_N`` trades and paper trades 3× each. With too little history
  the settings' plan stays.

The brain's own exit (the score turning against the trade) applies to every plan alike, so the
plans are compared on stops, targets, trailing and partial exits.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.analysis import signals as sig
from backend.indicators import vector as vx
from backend.indicators.series import BarSeries

SPACING = 10  # candles between two sampled entries, so one move isn't counted many times
STUDY_SHARE = 0.7
MIN_HISTORY = 100  # sampled trades a plan needs before Kairos trusts the comparison
MIN_EXAM = 30
PRIOR_N = 200.0
PAPER_WEIGHT = 3.0
COST_PCT = {"IN": 0.15, "US": 0.03}  # an approximate round trip, % of the price
PARTIAL_PCT = 50.0


@dataclass(frozen=True)
class ExitPlan:
    stop_atr: float
    target_r: float
    trail_atr: float | None
    partial_r: float | None

    @property
    def key(self) -> str:
        tr = f"{self.trail_atr:g}" if self.trail_atr else "0"
        pr = f"{self.partial_r:g}" if self.partial_r else "0"
        return f"s{self.stop_atr:g}_t{self.target_r:g}_tr{tr}_p{pr}"

    def words(self) -> str:
        parts = [f"stop {self.stop_atr:g} ATR", f"target {self.target_r:g}× the risk"]
        parts.append(f"trailing stop {self.trail_atr:g} ATR" if self.trail_atr else "no trailing")
        parts.append(
            f"half sold at {self.partial_r:g}× the risk" if self.partial_r else "no partial sale"
        )
        return ", ".join(parts)


PLANS: list[ExitPlan] = [
    ExitPlan(s, t, tr, p)
    for s in (1.5, 2.0, 3.0)
    for t in (2.0, 2.5, 3.5)
    for tr in (None, 2.0, 3.0)
    for p in (None, 1.0)
]


def plan_from_key(key: str) -> ExitPlan:
    parts = {x.rstrip("0123456789."): float(x.lstrip("strp")) for x in key.split("_")}
    return ExitPlan(parts["s"], parts["t"], parts["tr"] or None, parts["p"] or None)


def plans_with(default: ExitPlan) -> list[ExitPlan]:
    return PLANS if default in PLANS else [*PLANS, default]


def play(
    o: np.ndarray,
    h: np.ndarray,
    lo: np.ndarray,
    c: np.ndarray,
    i: int,
    side: int,
    stop_pct: float,
    target_pct: float,
    atr: float,
    plan: ExitPlan,
    max_bars: int,
) -> float | None:
    """The trade signalled on candle ``i`` played out under ``plan``, in R before costs (None
    when there is no next candle to fill on). Shorts are played as longs on negated prices."""
    n = len(c)
    if i + 1 >= n or stop_pct <= 0:
        return None
    if side < 0:
        o, h, lo, c = -o, -lo, -h, -c
    entry = float(o[i + 1])
    risk = abs(entry) * stop_pct / 100.0
    if risk <= 0:
        return None
    stop = entry - risk
    target = entry + abs(entry) * target_pct / 100.0
    part = entry + plan.partial_r * risk if plan.partial_r else None
    left, booked = 1.0, 0.0
    peak = entry
    if plan.trail_atr:
        stop = max(stop, entry - plan.trail_atr * atr)
    last = min(n - 1, i + max_bars)
    for j in range(i + 1, last + 1):
        op = entry if j == i + 1 else float(o[j])
        if lo[j] <= stop:
            px = min(op, stop)
            return (booked + left * (px - entry)) / risk
        if part is not None and h[j] >= part:
            share = PARTIAL_PCT / 100.0
            booked += share * (max(op, part) - entry)
            left -= share
            part = None
            stop = max(stop, entry)  # the rest can't lose (D-125)
        if h[j] >= target:
            return (booked + left * (max(op, target) - entry)) / risk
        peak = max(peak, float(h[j]))
        if plan.trail_atr:
            stop = max(stop, peak - plan.trail_atr * atr)
    return (booked + left * (float(c[last]) - entry)) / risk


def entries(
    ss: sig.SignalSet, weights: dict[str, float], entry: float, shorts: bool
) -> Iterable[tuple[int, int, Any]]:
    """(candle, side, decision) for the brain's entries, at most one per ``SPACING`` candles."""
    from backend.kairos import brain

    nxt = brain.WARMUP
    prev = None
    for i in range(brain.WARMUP, ss.n - 1):
        d = brain.decide(ss, i, weights)
        if i >= nxt and prev is not None:
            trend = float(ss.trend[i])
            for side in (1, -1):
                if side < 0 and not shorts:
                    continue
                if d.score * side < entry or trend * side <= -brain.STRONG_TREND:
                    continue
                if d.fresh(side) or prev.score * side < entry:
                    yield i, side, d
                    nxt = i + SPACING
                    break
        prev = d


def tally(
    series: BarSeries,
    ss: sig.SignalSet,
    market: str,
    *,
    weights: dict[str, float],
    entry: float,
    shorts: bool,
    max_bars: int,
    default: ExitPlan,
    collect: list[tuple[int, int, Any, float]] | None = None,
) -> dict[str, tuple[float, float, float]]:
    """``exit:study:<plan>`` / ``exit:exam:<plan>`` → (trades, sum of R, sum of R²) after costs.
    With ``collect``, each entry's (candle, side, decision, R under the settings' plan) is
    appended too: the trade judge's lessons (D-145)."""
    from backend.kairos import brain

    o, h, lo, c = series.open, series.high, series.low, series.close
    atr = vx.atr(h, lo, c, 14)
    split = int(STUDY_SHARE * ss.n)
    out: dict[str, list[float]] = {}
    plans = plans_with(default)
    for i, side, d in entries(ss, weights, entry, shorts):
        a = float(atr[i])
        if not np.isfinite(a) or a <= 0:
            continue
        part = "study" if i < split else "exam"
        for p in plans:
            pl = brain.plan(ss, i, d, side, p.stop_atr, p.target_r)
            r = play(o, h, lo, c, i, side, pl.stop_pct, pl.target_pct, a, p, max_bars)
            if r is None:
                continue
            r -= COST_PCT[market] / pl.stop_pct
            if collect is not None and p == default:
                collect.append((i, side, d, r))
            acc = out.setdefault(f"exit:{part}:{p.key}", [0.0, 0.0, 0.0])
            acc[0] += 1
            acc[1] += r
            acc[2] += r * r
    return {k: (v[0], v[1], v[2]) for k, v in out.items()}


def replay_trade(
    series: BarSeries,
    ss: sig.SignalSet,
    i: int,
    side: int,
    d: Any,
    market: str,
    max_bars: int,
    default: ExitPlan,
) -> dict[str, float]:
    """A closed desk trade (signalled on candle ``i``) under every plan: plan key → R."""
    from backend.kairos import brain

    o, h, lo, c = series.open, series.high, series.low, series.close
    a = float(vx.atr(h, lo, c, 14)[i])
    if not np.isfinite(a) or a <= 0:
        return {}
    out: dict[str, float] = {}
    for p in plans_with(default):
        pl = brain.plan(ss, i, d, side, p.stop_atr, p.target_r)
        r = play(o, h, lo, c, i, side, pl.stop_pct, pl.target_pct, a, p, max_bars)
        if r is not None:
            out[p.key] = r - COST_PCT[market] / pl.stop_pct
    return out


def choose(
    rows: dict[str, tuple[float, float]], paper: dict[str, tuple[float, float]], default: ExitPlan
) -> dict[str, Any]:
    """The plan to use, from ``exit:study|exam:<key>`` history rows and paper rows (key →
    (trades, sum of R)); with the reason in plain words."""

    def mean(key: str) -> tuple[float, float]:
        n, total = rows.get(key, (0.0, 0.0))
        return n, (total / n if n else 0.0)

    base_n, _ = mean(f"exit:exam:{default.key}")
    study_n, _ = mean(f"exit:study:{default.key}")
    if base_n < MIN_EXAM or base_n + study_n < MIN_HISTORY:
        return {
            "plan": default,
            "chosen": False,
            "why": f"too few trades to compare exits yet ({int(base_n + study_n)}); "
            "using the settings",
        }
    _, base_exam = mean(f"exit:exam:{default.key}")

    def score(p: ExitPlan) -> float:
        sn, sm = mean(f"exit:study:{p.key}")
        en, em = mean(f"exit:exam:{p.key}")
        hn = sn + en
        hist = (sn * sm + en * em) / hn if hn else 0.0
        pn, ptotal = paper.get(p.key, (0.0, 0.0))
        prior = min(hn, PRIOR_N)
        denom = prior + PAPER_WEIGHT * pn
        return (prior * hist + PAPER_WEIGHT * ptotal) / denom if denom else 0.0

    eligible = [
        p
        for p in plans_with(default)
        if p == default or _beats(mean(f"exit:exam:{p.key}"), base_exam)
    ]
    best = max(eligible, key=lambda p: (score(p), p == default))
    n_paper = int(paper.get(best.key, (0.0, 0.0))[0])
    hn = int(mean(f"exit:study:{best.key}")[0] + mean(f"exit:exam:{best.key}")[0])
    record = f"{score(best):+.2f}R a trade over {hn} past trades" + (
        f" and {n_paper} paper trades" if n_paper else ""
    )
    if best == default:
        why = f"the settings' exits did best ({record})"
    else:
        why = f"chosen from its record: {record}, against {score(default):+.2f}R for the settings"
    return {"plan": best, "chosen": best != default, "why": why}


def _beats(exam: tuple[float, float], base: float) -> bool:
    """Enough exam trades, and at least as good there as the settings' plan."""
    n, avg = exam
    return n >= MIN_EXAM and avg >= base
