"""Metis's tries, checked for overfitting (D-89): the probability of backtest overfitting
(CSCV, ``backend/quant/overfit.py``) over every idea tested on a strategy and the versions they
were tested against, or over every new strategy tried in a market.

Each tested idea keeps its daily returns over the whole test period (``daily``, and the
baseline's as ``base_daily``), so the tries can be lined up day by day. Once there are at least
``MIN_TRIES`` of them, a change is kept only if picking the best of them on one half of the
history and checking it on the other works better than a coin toss (PBO below ½): otherwise
Metis is finding luck on those years, and the change waits for new candles (D-89, METIS §16).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from sqlalchemy import select

from backend.backtest.run import RunOutput
from backend.core.types import MARKET_TZ, Market
from backend.db.models import MetisIdea
from backend.metis.notebook import TESTED
from backend.quant import overfit, stats

MIN_TRIES = 8
MAX_PBO = 0.5
MIN_DAYS = 64


def daily_of(out: RunOutput, market: Market) -> dict[str, list[Any]]:
    """A run's daily returns, compact enough to keep with the idea."""
    pts = stats.daily_points(out.equity, MARKET_TZ[market])
    rets = stats.returns_of([v for _d, v in pts])
    return {"days": [d for d, _v in pts][1:], "r": [round(float(x), 7) for x in rets]}


def _pairs(d: dict[str, list[Any]] | None) -> list[tuple[str, float]]:
    if not d:
        return []
    return list(zip(d.get("days", []), (float(x) for x in d.get("r", [])), strict=False))


# The luck check's N for new strategies (D-162): how many independent patterns the tried
# strategies' exam-year returns hold, not how many were tried. Recomputed at most this often.
EFFECTIVE_TTL_MS = 3_600_000
EFFECTIVE_SHARE = 0.9  # patterns needed to explain this much of the tries' variation
_effective: dict[str, tuple[int, int, int]] = {}  # market → (at, counted, effective)


def effective_n(series: list[dict[str, float]]) -> int:
    """Independent patterns among return series: the principal components needed to explain
    ``EFFECTIVE_SHARE`` of their correlation (Bailey and López de Prado: deflate by the
    *effective* number of independent trials when tries are correlated)."""
    if len(series) < 3:
        return len(series)
    days = sorted(set().union(*(s.keys() for s in series)))
    cover = {d: sum(d in s for s in series) for d in days}
    keep = [d for d in days if cover[d] >= 0.8 * len(series)]
    if len(keep) < 30:
        return len(series)
    x = np.array([[s.get(d, 0.0) for d in keep] for s in series])
    x = x[x.std(axis=1) > 0]
    if len(x) < 3:
        return len(series)
    lam = np.sort(np.clip(np.linalg.eigvalsh(np.nan_to_num(np.corrcoef(x))), 0, None))[::-1]
    share = np.cumsum(lam) / lam.sum()
    return int(np.searchsorted(share, EFFECTIVE_SHARE) + 1)


def effective_tries(ctx: Any, market: str, counted: int) -> int:
    """The luck check's N for a new strategy in ``market``: the independent patterns among the
    new strategies already tried there (at most ``counted``; all of them when too few have
    saved returns to tell)."""
    now = ctx.clock.now_ms()
    hit = _effective.get(market)
    if hit is not None and now - hit[0] < EFFECTIVE_TTL_MS and hit[1] == counted:
        return hit[2]
    with ctx.db.session() as s:
        rows = s.scalars(
            select(MetisIdea.result).where(
                MetisIdea.status.in_(TESTED),
                MetisIdea.market_code == market,
                MetisIdea.kind == "new_strategy",
            )
        ).all()
    series = []
    for raw in rows:
        d = json.loads(raw or "{}").get("daily")
        if d and len(d.get("r", [])) > 100:
            series.append(dict(_pairs(d)))
    if len(series) < 0.5 * counted or len(series) < 30:
        n = counted  # too few saved returns to measure: count every try
    else:
        n = min(counted, effective_n(series))
    _effective[market] = (now, counted, n)
    return n


def collect(
    ctx: Any,
    *,
    strategy_id: int | None = None,
    market: str | None = None,
    kind: str | None = None,
    extra: list[dict[str, list[Any]]] | None = None,
    extra_base: tuple[int, dict[str, list[Any]]] | None = None,
) -> dict[str, Any]:
    """PBO over the saved tries (and ``extra``: the one being judged; ``extra_base``: its
    baseline's version id and returns, unless that version's returns are already saved)."""
    with ctx.db.session() as s:
        q = select(MetisIdea.strategy_version_id, MetisIdea.result).where(
            MetisIdea.status.in_(TESTED)
        )
        if strategy_id is not None:
            q = q.where(MetisIdea.strategy_id == strategy_id)
        if market is not None:
            q = q.where(MetisIdea.market_code == market)
        if kind is not None:
            q = q.where(MetisIdea.kind == kind)
        rows = s.execute(q.order_by(MetisIdea.id)).all()
    cols: list[list[tuple[str, float]]] = []
    bases: set[int] = set()
    for vid, raw in rows:
        res = json.loads(raw or "{}")
        if res.get("daily"):
            cols.append(_pairs(res["daily"]))
        if res.get("base_daily") and vid is not None and vid not in bases:
            bases.add(int(vid))
            cols.append(_pairs(res["base_daily"]))
    for d in extra or []:
        cols.append(_pairs(d))
    if extra_base is not None and extra_base[0] not in bases:
        cols.append(_pairs(extra_base[1]))
    cols = [c for c in cols if c]
    days, table = overfit.aligned(cols)
    if len(cols) < 2 or len(days) < MIN_DAYS:
        result: dict[str, Any] = {"pbo": None, "tries": len(cols), "days": len(days)}
    else:
        result = overfit.pbo(table)
    result["text"] = overfit.words(result, "tries")
    return result


def check(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The overfitting rule (D-89), once there are enough tries to measure it."""
    p = result.get("pbo")
    if p is None or result.get("tries", 0) < MIN_TRIES:
        return []
    return [
        {
            "ok": p < MAX_PBO,
            "text": f"Overfitting check: over the {result['tries']} tries so far, the best of "
            f"one half of the history was in the bottom half of the other {p * 100:.0f}% of "
            f"the time (probability of backtest overfitting; needs under {MAX_PBO * 100:.0f}%).",
        }
    ]
