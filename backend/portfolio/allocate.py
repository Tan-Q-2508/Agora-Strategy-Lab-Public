"""The allocator: one budget, split across sleeves by tested code (PORTFOLIO §4, D-84).

The AI never sets a weight. Every choice below is a fixed rule with a plain-English reason:

1. **Screen** on the exam years (unseen when the strategy or opportunity was chosen): made money
   after costs with at least 8 trades, won at least 1.1× what it lost, and passed the luck check
   (deflated Sharpe ratio ≥ 0.5 over the number of candidates).
2. **Score** = exam-year Sharpe ratio × luck-check probability.
3. **Pick** best score first, skipping a candidate whose study-year daily returns move with one
   already picked (correlation ≥ 0.7), up to the risk level's most sleeves.
4. **Weigh** by risk: hierarchical risk parity (3+ sleeves) or inverse volatility (1–2) on a
   Ledoit–Wolf covariance of study-year returns; tilt towards stronger evidence
   (× (0.5 + 0.5 × score ÷ best score)); cap each sleeve; scale down to the risk level's
   volatility aim (the rest stays in cash).
5. **Fit to the budget**: a sleeve whose money can't buy one share of its dearest stock per trade
   is dropped (the weakest such first) and the weights are worked out again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.core.types import Market
from backend.metrics.summary import money
from backend.quant import portfolio as pf

MIN_EXAM_TRADES = 8
MIN_PROFIT_FACTOR = 1.1
MIN_LUCK = 0.5
MAX_CORRELATION = 0.7
MIN_OVERLAP_DAYS = 60
DAYS = 252


@dataclass(frozen=True)
class Risk:
    label: str
    reserve: float  # share of the budget kept in cash
    cap: float  # most in one sleeve, as a share of the invested money
    most: int  # most sleeves
    target_vol: float  # volatility aimed for, a year


RISK = {
    "careful": Risk("Careful", 0.20, 0.30, 6, 0.10),
    "balanced": Risk("Balanced", 0.10, 0.40, 6, 0.15),
    "bold": Risk("Bold", 0.05, 0.50, 6, 0.22),
}


@dataclass
class Candidate:
    key: str
    name: str
    strategy_id: int
    version_id: int
    symbols: list[str]
    size_pct: float
    max_open: int
    dearest: float
    days: list[str]  # local days; returns[i] is the move into days[i + 1]
    returns: np.ndarray
    split_index: int  # returns[:split_index] are study-year days
    exam: dict[str, Any]
    sharpe: float  # exam years, a year
    dsr: float  # luck check
    worst_drop_pct: float = 0.0
    overrides: dict[str, float] = field(default_factory=dict)
    opportunity_id: int | None = None
    sleeve_id: int | None = None

    @property
    def score(self) -> float:
        return max(self.sharpe, 0.0) * self.dsr

    def study(self) -> dict[str, float]:
        """Study-year daily returns by day."""
        days = self.days[1 : self.split_index + 1]
        return dict(zip(days, self.returns[: self.split_index].tolist(), strict=False))

    def volatility(self) -> float:
        r = self.returns[: self.split_index]
        return float(np.std(r, ddof=1)) * math.sqrt(DAYS) if len(r) > 2 else 0.0

    def min_capital(self) -> float:
        return self.dearest * 100.0 / self.size_pct * 1.05 if self.size_pct > 0 else math.inf


@dataclass
class Plan:
    market: str
    budget: float
    risk: str
    sleeves: list[dict[str, Any]] = field(default_factory=list)
    left_out: list[dict[str, Any]] = field(default_factory=list)
    cash: float = 0.0
    method: str = ""
    estimate: dict[str, Any] = field(default_factory=dict)
    overlaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "budget": self.budget,
            "risk": self.risk,
            "sleeves": self.sleeves,
            "left_out": self.left_out,
            "cash": round(self.cash, 2),
            "invested": round(self.budget - self.cash, 2),
            "method": self.method,
            "estimate": self.estimate,
            "overlaps": self.overlaps,
            "notes": self.notes,
        }


def screen(c: Candidate) -> str | None:
    """Why a candidate fails the screen, or None when it passes."""
    ex = c.exam
    if (ex.get("trades") or 0) < MIN_EXAM_TRADES:
        return f"too few trades on unseen years ({ex.get('trades') or 0}; needs {MIN_EXAM_TRADES})"
    if (ex.get("net") or 0) <= 0:
        return "it didn't make money on unseen years after costs"
    if (ex.get("profit_factor") or 0) < MIN_PROFIT_FACTOR:
        return f"it won less than {MIN_PROFIT_FACTOR}× what it lost on unseen years"
    if c.dsr < MIN_LUCK:
        return f"it could be luck ({c.dsr * 100:.0f}% chance it isn't; needs {MIN_LUCK * 100:.0f}%)"
    return None


def correlation(a: Candidate, b: Candidate) -> float | None:
    ra, rb = a.study(), b.study()
    days = sorted(set(ra) & set(rb))
    if len(days) < MIN_OVERLAP_DAYS:
        return None
    x, y = np.array([ra[d] for d in days]), np.array([rb[d] for d in days])
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def covariance(cands: list[Candidate]) -> np.ndarray:
    """Ledoit–Wolf shrunk covariance of study-year returns on common days (or a diagonal one
    from each sleeve's own volatility when they share too few days)."""
    maps = [c.study() for c in cands]
    days = sorted(set.intersection(*(set(m) for m in maps))) if maps else []
    if len(days) >= max(MIN_OVERLAP_DAYS, 2 * len(cands)):
        x = np.array([[m[d] for m in maps] for d in days])
        cov, _delta = pf.ledoit_wolf(x)
        return cov
    var = [max(c.volatility() ** 2 / DAYS, 1e-10) for c in cands]
    return np.diag(var)


def weigh(cands: list[Candidate], risk: Risk) -> tuple[np.ndarray, np.ndarray, str]:
    """(weights of the invested money, the covariance, the method in words)."""
    cov = covariance(cands)
    if len(cands) >= 3:
        base, method = pf.hrp(cov), "hierarchical risk parity"
    else:
        base, method = pf.inverse_vol(cov), "inverse volatility"
    best = max(c.score for c in cands) or 1.0
    tilt = np.array([0.5 + 0.5 * c.score / best for c in cands])
    w = base * tilt
    w = w / w.sum()
    w = pf.cap(w, risk.cap)
    vol = pf.volatility(w, cov)
    if vol > risk.target_vol > 0:
        w = w * (risk.target_vol / vol)
    return w, cov, method


def _reasons(
    c: Candidate, weight: float, capital: float, rc: float, market: Market, capped: bool
) -> list[str]:
    ex = c.exam
    wr = (ex["wins"] / ex["trades"] * 100) if ex.get("trades") and "wins" in ex else None
    held = (
        f"Held up on unseen years: Sharpe {c.sharpe:.2f}, {ex.get('trades')} trades"
        + (f", won {wr:.0f}%" if wr is not None else "")
        + f", made {money(ex.get('net') or 0, market)} after costs."
    )
    return [
        held,
        f"Luck check: {c.dsr * 100:.0f}% chance it isn't luck.",
        f"Volatility {c.volatility() * 100:.0f}% a year; carries {rc * 100:.0f}% of the "
        "portfolio's risk.",
        f"Gets {money(capital, market)}, {weight * 100:.0f}% of the budget"
        + (" (capped)." if capped else "."),
    ]


def plan(cands: list[Candidate], budget: float, risk_name: str, market: str) -> Plan:
    risk = RISK[risk_name]
    m = Market(market)
    out = Plan(market=market, budget=budget, risk=risk_name)
    passed: list[Candidate] = []
    for c in cands:
        why = screen(c)
        if why:
            out.left_out.append({"name": c.name, "key": c.key, "reason": f"Left out: {why}."})
        else:
            passed.append(c)
    passed.sort(key=lambda c: -c.score)
    picked: list[Candidate] = []
    for c in passed:
        if len(picked) >= risk.most:
            out.left_out.append(
                {"name": c.name, "key": c.key, "reason": f"Left out: already {risk.most} sleeves."}
            )
            continue
        clash = None
        for p in picked:
            rho = correlation(c, p)
            if rho is not None and rho >= MAX_CORRELATION:
                clash = (p, rho)
                break
        if clash:
            out.left_out.append(
                {
                    "name": c.name,
                    "key": c.key,
                    "reason": f"Left out: it moves with “{clash[0].name}” (correlation "
                    f"{clash[1]:.2f}), which is already in and scored higher.",
                }
            )
            continue
        picked.append(c)
    investable = budget * (1 - risk.reserve)
    while picked:
        w, cov, method = weigh(picked, risk)
        capitals = w * investable
        short = [(c.score, k) for k, c in enumerate(picked) if capitals[k] < c.min_capital()]
        if not short:
            break
        _s, k = min(short)
        c = picked.pop(k)
        out.left_out.append(
            {
                "name": c.name,
                "key": c.key,
                "reason": f"Left out: its share ({money(float(capitals[k]), m)}) can't buy one "
                f"share of its dearest stock per trade (needs {money(c.min_capital(), m)}).",
            }
        )
    if not picked:
        out.cash = budget
        out.notes.append(
            "Nothing passed all the tests, so the money stays in cash. Find new opportunities "
            "or add strategies, then plan again."
        )
        return out
    rcs = pf.risk_contributions(w, cov)
    for k, c in enumerate(picked):
        capital = float(capitals[k])
        weight = capital / budget
        capped = abs(w[k] - risk.cap) < 1e-9
        out.sleeves.append(
            {
                "key": c.key,
                "name": c.name,
                "strategy_id": c.strategy_id,
                "version_id": c.version_id,
                "symbols": c.symbols,
                "overrides": c.overrides,
                "size_pct": c.size_pct,
                "opportunity_id": c.opportunity_id,
                "sleeve_id": c.sleeve_id,
                "weight": round(weight, 4),
                "capital": round(capital, 2),
                "score": round(c.score, 4),
                "sharpe": round(c.sharpe, 3),
                "luck": round(c.dsr, 4),
                "volatility": round(c.volatility(), 4),
                "worst_drop_pct": round(c.worst_drop_pct, 2),
                "reasons": _reasons(c, weight, capital, float(rcs[k]), m, capped),
            }
        )
    out.cash = budget - sum(s["capital"] for s in out.sleeves)
    out.method = method
    vol = pf.volatility(w, cov)
    mean = np.array(
        [float(np.mean(c.returns[: c.split_index])) if c.split_index else 0.0 for c in picked]
    )
    yearly = float(w @ mean) * DAYS
    out.estimate = {
        "volatility": round(vol * (1 - risk.reserve), 4),
        "return": round(yearly * (1 - risk.reserve), 4),
        "sharpe": round(yearly / vol, 3) if vol > 0 else 0.0,
        "diversification": round(pf.diversification_ratio(w, cov), 3),
    }
    seen: dict[str, list[str]] = {}
    for c in picked:
        for sym in c.symbols:
            seen.setdefault(sym, []).append(c.name)
    out.overlaps = [
        f"{sym} is traded by {len(names)} sleeves ({', '.join(names)})."
        for sym, names in sorted(seen.items())
        if len(names) > 1
    ]
    out.notes.append(
        f"Weighted by {method} on study-year returns (shrunk covariance), tilted towards "
        f"stronger evidence, at most {risk.cap * 100:.0f}% in one sleeve, "
        f"{risk.reserve * 100:.0f}% kept in cash, aiming at {risk.target_vol * 100:.0f}% "
        "volatility a year."
    )
    return out


def ranking_plan(
    c: Candidate, budget: float, risk_name: str, market: str, method_word: str
) -> Plan:
    """A ranking portfolio (D-91): the whole budget, less the risk level's cash, runs one
    ranking strategy over the index; scaled down when its study-year volatility is above the
    risk level's aim. The exam-year screen is reported, not enforced: the user chose the
    method, so a failed screen is a warning, not a veto."""
    risk = RISK[risk_name]
    m = Market(market)
    out = Plan(market=market, budget=budget, risk=risk_name, method=method_word)
    vol = c.volatility()
    scale = min(1.0, risk.target_vol / vol) if vol > 0 else 1.0
    capital = budget * (1 - risk.reserve) * scale
    why = screen(c)
    reasons = [
        f"{method_word.capitalize()}: the stocks change every month by rank, so this one sleeve "
        f"spreads {money(capital, m)} over {c.max_open} stocks "
        f"({money(capital * c.size_pct / 100, m)} each).",
        f"Held up on unseen years: Sharpe {c.sharpe:.2f}; {c.dsr * 100:.0f}% chance it isn't luck."
        if why is None
        else f"Careful: {why} (kept because you chose this method).",
    ]
    if scale < 1.0:
        reasons.append(
            f"Its volatility ({vol * 100:.0f}% a year) is above the {risk_name} aim "
            f"({risk.target_vol * 100:.0f}%), so {money(budget * (1 - risk.reserve) - capital, m)}"
            " more stays in cash."
        )
    out.sleeves.append(
        {
            "key": c.key,
            "name": c.name,
            "strategy_id": c.strategy_id,
            "version_id": c.version_id,
            "symbols": c.symbols,
            "overrides": c.overrides,
            "size_pct": c.size_pct,
            "opportunity_id": c.opportunity_id,
            "sleeve_id": c.sleeve_id,
            "weight": round(capital / budget, 4),
            "capital": round(capital, 2),
            "score": round(c.score, 4),
            "sharpe": round(c.sharpe, 3),
            "luck": round(c.dsr, 4),
            "volatility": round(vol, 4),
            "worst_drop_pct": round(c.worst_drop_pct, 2),
            "reasons": reasons,
        }
    )
    out.cash = budget - capital
    mean = float(np.mean(c.returns[: c.split_index])) if c.split_index else 0.0
    w = capital / budget
    out.estimate = {
        "volatility": round(vol * w, 4),
        "return": round(mean * DAYS * w, 4),
        "sharpe": round(mean * DAYS / vol, 3) if vol > 0 else 0.0,
        "diversification": 1.0,
    }
    if why is not None:
        out.notes.append(
            f"This ranking didn't pass the usual screen on unseen years ({why}). The plan "
            "follows your choice of method anyway; a mix of strategies is the safer default."
        )
    out.notes.append(
        f"{risk.reserve * 100:.0f}% kept in cash; the ranking re-picks its stocks on the first "
        "trading day of each month, inside the shared engine."
    )
    return out
