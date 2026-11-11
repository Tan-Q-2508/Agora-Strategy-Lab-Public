"""Kairos's review of a set of trades: why the money went where it went (KAIROS §16, D-72).

Backtests can look great until costs and the shape of the wins are read properly. This
module reads a backtest's (or a paper session's) closed trades and answers, by rules and
arithmetic only:

1. **Costs.** Profit before costs, the costs, profit after. The share of the gross profit
   that costs ate, the average trade before and after costs, trades per month. Lots of
   small trades that each earn about what they pay in charges is the classic way a good
   backtest turns into a loss.
2. **Wins and losses.** Win rate, average win and loss, the win rate needed just to break
   even with this win/loss size, expectancy per trade, and how much of the profit came from
   the best three trades (a strategy that lives on a few lucky trades is fragile).
3. **Exits.** Results by exit reason; losers that were ahead by at least one ATR before
   turning (a target or trailing stop would have kept something); stops hit within two
   candles (the stop sat inside normal noise).
4. **Why trades failed although the rules were met.** The market's condition on each
   signal candle (the trade check's readings, ``quality.py``), split into thirds. A third
   whose win rate is clearly below the rest is named with its numbers ("14 of 18 trades
   taken in choppy markets lost").
5. **Filters that would have helped.** Each "skip this third" rule is chosen on the first
   60% of the trades and then tested on the last 40% it never saw. Only rules that kept
   their promise there (higher win rate *and* more profit after costs, keeping at least a
   third of the trades) are offered, and each comes with the strategy condition that
   implements it.
6. **The worst losing trades, explained.** For each, the readings that were against it.

Everything returned is JSON-ready and every sentence carries its numbers.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.core.types import Market
from backend.indicators import catalog
from backend.indicators.series import BarSeries
from backend.kairos.casebook import CAUSES, casebook, causes_of
from backend.kairos.quality import (
    BY_KEY,
    PRIOR,
    THIRDS,
    FeatureBook,
    Reading,
    Sample,
    middle_words,
    past,
)
from backend.metrics.summary import money

MIN_FOR_CONDITIONS = 12
MIN_FOR_FILTERS = 20
TRAIN_SHARE = 0.6


@dataclass(frozen=True)
class TradeIn:
    """A closed trade, as the review needs it (prices may be raw; returns are used)."""

    symbol: str
    side: int
    entry_ts: int
    exit_ts: int
    gross: float
    charges: float
    net: float
    return_pct: float  # after costs
    bars_held: int
    exit_reason: str


@dataclass
class _Row:
    t: TradeIn
    features: dict[str, float]
    mfe_atr: float | None
    mae_atr: float | None
    signal_ts: int = 0


def trade_in(d: Mapping[str, Any]) -> TradeIn:
    """From a trade dict as the API and the database store them."""
    side = d.get("side")
    return TradeIn(
        symbol=str(d.get("symbol") or ""),
        side=-1 if side in ("short", -1) else 1,
        entry_ts=int(d.get("entry_ts") or 0),
        exit_ts=int(d.get("exit_ts") or 0),
        gross=float(d.get("gross_pnl") or 0.0),
        charges=float(d.get("charges") or 0.0),
        net=float(d.get("net_pnl") or 0.0),
        return_pct=float(d.get("return_pct") or 0.0),
        bars_held=int(d.get("bars_held") or 0),
        exit_reason=str(d.get("exit_reason") or "signal"),
    )


def _rows(
    trades: Sequence[TradeIn],
    series: Mapping[str, BarSeries],
    score_for: Callable[[BarSeries], Any] | None,
) -> list[_Row]:
    books: dict[str, FeatureBook] = {}
    atrs: dict[str, np.ndarray] = {}
    out: list[_Row] = []
    for t in trades:
        s = series.get(t.symbol)
        feats: dict[str, float] = {}
        mfe = mae = None
        signal_ts = 0
        if s is not None and len(s):
            if t.symbol not in books:
                books[t.symbol] = FeatureBook(s, score_for(s) if score_for else None)
                atrs[t.symbol] = catalog.compute("atr", s, {"period": 14})["value"]
            e = int(np.searchsorted(s.ts, t.entry_ts))
            x = int(np.searchsorted(s.ts, t.exit_ts))
            sig_i = e - 1
            if 0 <= sig_i < len(s):
                feats = books[t.symbol].at(sig_i, t.side)
                signal_ts = int(s.ts[sig_i])
            if 0 <= e < len(s) and e <= x < len(s):
                atr = float(atrs[t.symbol][max(sig_i, 0)])
                entry = float(s.open[e])
                if atr > 0 and math.isfinite(atr) and entry > 0:
                    hi = float(np.max(s.high[e : x + 1]))
                    lo = float(np.min(s.low[e : x + 1]))
                    if t.side > 0:
                        mfe, mae = (hi - entry) / atr, (entry - lo) / atr
                    else:
                        mfe, mae = (entry - lo) / atr, (hi - entry) / atr
        out.append(_Row(t, feats, mfe, mae, signal_ts))
    return out


def to_samples(trades: Sequence[TradeIn], features: Sequence[Mapping[str, float]]) -> list[Sample]:
    return [
        Sample(dict(f), t.net > 0, t.return_pct, 1.0, t.entry_ts, t.exit_ts, t.side, t.symbol)
        for t, f in zip(trades, features, strict=True)
    ]


# ---------------------------------------------------------------- parts of the review


def _money_part(rows: Sequence[_Row], market: Market, days: float) -> dict[str, Any]:
    gross = sum(r.t.gross for r in rows)
    charges = sum(r.t.charges for r in rows)
    net = sum(r.t.net for r in rows)
    n = len(rows)
    share = charges / gross if gross > 0 else None
    per_month = n / max(days / 30.44, 1e-9) if days > 0 else None
    if gross > 0 and net < 0:
        verdict = (
            f"Before costs the trades made {money(gross, market)}; costs of "
            f"{money(charges, market)} turned that into a loss of {money(net, market)}. "
            f"Each trade earned {money(gross / n, market)} on average but paid "
            f"{money(charges / n, market)} in charges."
        )
        level = "bad"
    elif share is not None and share >= 0.5:
        verdict = (
            f"Costs ate {share * 100:.0f}% of the profit before costs "
            f"({money(charges, market)} of {money(gross, market)}). Fewer trades that aim for "
            f"bigger moves would keep more of it."
        )
        level = "warn"
    elif share is not None:
        verdict = (
            f"Costs took {share * 100:.0f}% of the profit before costs: "
            f"{money(charges, market)} of {money(gross, market)}."
        )
        level = "ok"
    else:
        verdict = (
            f"The trades lost {money(-gross, market)} before costs, and costs added "
            f"{money(charges, market)}."
        )
        level = "bad"
    return {
        "gross": round(gross, 2),
        "charges": round(charges, 2),
        "net": round(net, 2),
        "cost_share": None if share is None else round(share, 3),
        "avg_gross": round(gross / n, 2) if n else 0.0,
        "avg_charges": round(charges / n, 2) if n else 0.0,
        "avg_net": round(net / n, 2) if n else 0.0,
        "trades_per_month": None if per_month is None else round(per_month, 1),
        "verdict": verdict,
        "level": level,
    }


def _wins_part(rows: Sequence[_Row], market: Market) -> dict[str, Any]:
    nets = [r.t.net for r in rows]
    wins = [x for x in nets if x > 0]
    losses = [-x for x in nets if x <= 0]
    n = len(nets)
    rate = len(wins) / n if n else 0.0
    avg_w = float(np.mean(wins)) if wins else 0.0
    avg_l = float(np.mean(losses)) if losses else 0.0
    payoff = avg_w / avg_l if avg_l > 0 else None
    breakeven = 1.0 / (1.0 + payoff) if payoff else None
    total = sum(nets)
    best = sorted(nets, reverse=True)[:3]
    without = total - sum(x for x in best if x > 0)
    streak = run = 0
    for x in sorted(rows, key=lambda r: r.t.exit_ts):
        run = run + 1 if x.t.net <= 0 else 0
        streak = max(streak, run)
    lines = []
    if payoff is not None and breakeven is not None:
        lines.append(
            f"It won {len(wins)} of {n} trades ({rate * 100:.0f}%). The average win "
            f"({money(avg_w, market)}) is {payoff:.1f}× the average loss "
            f"({money(avg_l, market)}), so it needs to win {breakeven * 100:.0f}% just to break "
            f"even after costs."
        )
    if total > 0 and without < 0 and n >= 10:
        lines.append(
            f"The profit depends on a few trades: without the best three it would have lost "
            f"{money(-without, market)}. Strategies like that are fragile."
        )
    elif total > 0 and best and sum(x for x in best if x > 0) > 0.6 * total and n >= 10:
        lines.append(
            f"The best three trades made {sum(best) / total * 100:.0f}% of the profit, so a few "
            f"missed trades would change the result a lot."
        )
    if rate < 0.4 and n >= 10:
        lines.append(
            f"Most trades lose ({100 - rate * 100:.0f}%). That can still pay when wins are big, "
            f"but long losing streaks (here up to {streak} in a row) are hard to sit through."
        )
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(rate, 3),
        "avg_win": round(avg_w, 2),
        "avg_loss": round(avg_l, 2),
        "payoff": None if payoff is None else round(payoff, 2),
        "breakeven_win_rate": None if breakeven is None else round(breakeven, 3),
        "expectancy": round(total / n, 2) if n else 0.0,
        "best3_share": round(sum(best) / total, 3) if total > 0 else None,
        "net_without_best3": round(without, 2),
        "longest_losing_streak": streak,
        "lines": lines,
    }


EXIT_WORDS = {
    "stop": "Stop-loss",
    "trailing": "Trailing stop",
    "target": "Take-profit",
    "signal": "Exit rule",
    "time": "Time limit",
    "square_off": "Intraday square-off",
}


def _exits_part(rows: Sequence[_Row]) -> dict[str, Any]:
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r.t.exit_reason, []).append(r.t.net)
    table = [
        {
            "reason": k,
            "label": EXIT_WORDS.get(k, k),
            "count": len(v),
            "win_rate": round(sum(1 for x in v if x > 0) / len(v), 3),
            "avg_net": round(float(np.mean(v)), 2),
        }
        for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))
    ]
    losers = [r for r in rows if r.t.net <= 0]
    winners = [r for r in rows if r.t.net > 0]
    lines = []
    ahead = [r for r in losers if r.mfe_atr is not None and r.mfe_atr >= 1.0]
    measured = [r for r in losers if r.mfe_atr is not None]
    if len(measured) >= 5 and len(ahead) / len(measured) >= 0.3:
        lines.append(
            f"{len(ahead)} of {len(measured)} losing trades were ahead by at least one ATR "
            f"before turning into losses. A take-profit or a trailing stop would have kept "
            f"some of that."
        )
    quick = [r for r in losers if r.t.exit_reason in ("stop", "trailing") and r.t.bars_held <= 2]
    if len(losers) >= 5 and len(quick) / len(losers) >= 0.3:
        lines.append(
            f"{len(quick)} of {len(losers)} losers were stopped out within two candles: the "
            f"stop probably sits inside the stock's normal wiggle. An ATR-based stop "
            f"(about 2× ATR) fits the stock's own noise."
        )
    if winners and losers:
        hw = float(np.mean([r.t.bars_held for r in winners]))
        hl = float(np.mean([r.t.bars_held for r in losers]))
        if hl > 1.5 * hw and len(losers) >= 5:
            lines.append(
                f"Losing trades were held {hl:.0f} candles on average, winners only {hw:.0f}: "
                f"the strategy cuts winners early and lets losers run."
            )
    return {
        "by_reason": table,
        "lines": lines,
        # for Metis's first look and Kairos's improvement (D-119): losers that were ahead first
        "gave_back": {"ahead": len(ahead), "measured": len(measured)},
    }


def _rate(wins: float, n: float, base: float) -> float:
    return (wins + PRIOR * base) / (n + PRIOR)


def _conditions_part(rows: Sequence[_Row], base: float) -> tuple[list[Any], list[Any]]:
    table: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    for key, r in BY_KEY.items():
        have = [(x.features[key], x.t.net > 0) for x in rows if key in x.features]
        if len(have) < MIN_FOR_CONDITIONS:
            continue
        vals = np.array([v for v, _ in have])
        e1, e2 = float(np.quantile(vals, 1 / 3)), float(np.quantile(vals, 2 / 3))
        thirds: list[dict[str, Any]] = []
        for b in range(3):
            pick = [
                w
                for v, w in have
                if (b == 0 and v < e1) or (b == 2 and v > e2) or (b == 1 and e1 <= v <= e2)
            ]
            n, wins = len(pick), sum(pick)
            thirds.append(
                {
                    "third": THIRDS[b],
                    "count": n,
                    "wins": wins,
                    "win_rate": round(wins / n, 3) if n else None,
                    "shrunk": round(_rate(wins, n, base), 3),
                }
            )
        spread = max(t["shrunk"] for t in thirds) - min(t["shrunk"] for t in thirds)
        table.append(
            {
                "key": key,
                "label": r.label,
                "unit": r.unit,
                "edges": [round(e1, 3), round(e2, 3)],
                "thirds": thirds,
                "spread": round(spread, 3),
            }
        )
        for b, t in enumerate(thirds):
            n = int(t["count"])
            if n < 8 or t["win_rate"] is None:
                continue
            losers = n - int(t["wins"])
            # Clearly worse: the shrunk rate is 8+ points under the usual and the raw count
            # is unlikely by chance (one-sided binomial z below −1.3).
            z = (t["win_rate"] - base) / math.sqrt(max(base * (1 - base), 1e-6) / n)
            if t["shrunk"] <= base - 0.08 and z <= -1.3:
                word = _third_words(r, b, e1, e2)
                reasons.append(
                    {
                        "key": key,
                        "third": THIRDS[b],
                        "count": n,
                        "losers": losers,
                        "win_rate": t["win_rate"],
                        "text": (
                            f"{losers} of {n} trades taken when {word} lost "
                            f"(won {t['win_rate'] * 100:.0f}%, against {base * 100:.0f}% overall)."
                        ),
                        "gap": round(base - t["shrunk"], 3),
                    }
                )
    table.sort(key=lambda x: -float(x["spread"]))
    reasons.sort(key=lambda x: -float(x["gap"]))
    return table, reasons[:6]


def _fmt(r: Reading, v: float) -> str:
    if r.unit == "%":
        return f"{v:+.1f}%" if r.directional else f"{v:.1f}%"
    if r.unit == "×":
        return f"{v:.2f}×"
    return f"{v:.1f}"


def _third_words(r: Reading, b: int, e1: float, e2: float) -> str:
    if b == 0:
        return f"{past(r.low_word)} ({r.label} below {_fmt(r, e1)})"
    if b == 2:
        return f"{past(r.high_word)} ({r.label} above {_fmt(r, e2)})"
    return f"{past(middle_words(r))} ({r.label} {_fmt(r, e1)} to {_fmt(r, e2)})"


def _stats(rows: Sequence[_Row]) -> dict[str, Any]:
    n = len(rows)
    nets = [r.t.net for r in rows]
    return {
        "trades": n,
        "win_rate": round(sum(1 for x in nets if x > 0) / n, 3) if n else None,
        "net": round(sum(nets), 2),
        "expectancy": round(sum(nets) / n, 2) if n else None,
    }


def condition_for(key: str, keep: str, value: float) -> dict[str, Any]:
    """The strategy condition that keeps trades on the ``keep`` side ("at_least" /
    "at_most") of ``value`` for a long trade; ``improve.py`` turns it round for shorts."""
    r = BY_KEY[key]
    return {
        "indicator": r.indicator,
        "params": dict(r.params),
        "output": r.output,
        "op": keep,
        "value": round(value, 4),
        "directional": r.directional,
        "flip": r.flip,
    }


def _filters_part(rows: Sequence[_Row], market: Market) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: r.t.exit_ts)
    n = len(ordered)
    if n < MIN_FOR_FILTERS:
        return {
            "note": f"Kairos needs at least {MIN_FOR_FILTERS} closed trades to test filters; "
            f"this has {n}.",
            "rules": [],
        }
    cut = int(n * TRAIN_SHARE)
    train, test = ordered[:cut], ordered[cut:]
    base_train = _stats(train)
    candidates = []
    for key in BY_KEY:
        if key == "score":
            continue  # Kairos's score isn't a strategy condition (the trade check uses it)
        vals = np.array([x.features[key] for x in train if key in x.features])
        if len(vals) < MIN_FOR_FILTERS * TRAIN_SHARE:
            continue
        e1, e2 = float(np.quantile(vals, 1 / 3)), float(np.quantile(vals, 2 / 3))
        for keep, edge, skip_word in (("at_least", e1, 0), ("at_most", e2, 2)):

            def ok(x: _Row, keep: str = keep, edge: float = edge, key: str = key) -> bool:
                v = x.features.get(key)
                if v is None:
                    return True
                return v >= edge if keep == "at_least" else v <= edge

            kept = [x for x in train if ok(x)]
            if len(kept) < max(8, 0.4 * len(train)):
                continue
            st = _stats(kept)
            gain = st["net"] - base_train["net"]
            if gain <= 0 or (st["win_rate"] or 0) <= (base_train["win_rate"] or 0):
                continue
            candidates.append((gain, key, keep, edge, skip_word, ok))
    candidates.sort(key=lambda c: -c[0])
    rules = []
    base_test = _stats(test)
    for _gain, key, keep, edge, b, ok in candidates[:5]:
        r = BY_KEY[key]
        kept_test = [x for x in test if ok(x)]
        st = _stats(kept_test)
        held = (
            len(kept_test) >= max(3, len(test) / 3)
            and st["net"] >= base_test["net"]
            and (st["win_rate"] or 0) >= (base_test["win_rate"] or 0)
        )
        skip = r.low_word if b == 0 else r.high_word
        sign = "below" if keep == "at_least" else "above"
        rules.append(
            {
                "key": key,
                "label": r.label,
                "keep": keep,
                "value": round(edge, 4),
                "text": f"Skip signals that come when {skip} ({r.label} {sign} {_fmt(r, edge)}).",
                "condition": condition_for(key, keep, edge),
                "train": {"before": base_train, "after": _stats([x for x in train if ok(x)])},
                "test": {"before": base_test, "after": st},
                "held_up": held,
            }
        )
    good = [x for x in rules if x["held_up"]]
    note = (
        f"Tested on the last {len(test)} trades, which the filters never saw while being chosen."
        if good
        else "No filter kept its promise on the trades it hadn't seen, so Kairos won't suggest "
        "one yet (that protects against rules that only fit the past)."
    )
    return {"note": note, "rules": rules, "train_trades": len(train), "test_trades": len(test)}


def _losers_part(rows: Sequence[_Row], market: Market, base: float) -> list[dict[str, Any]]:
    tables: dict[str, tuple[float, float]] = {}
    for key in BY_KEY:
        vals = [x.features[key] for x in rows if key in x.features]
        if len(vals) >= MIN_FOR_CONDITIONS:
            tables[key] = (float(np.quantile(vals, 1 / 3)), float(np.quantile(vals, 2 / 3)))
    rates: dict[tuple[str, int], tuple[float, int]] = {}
    for key, (e1, e2) in tables.items():
        for b in range(3):
            pick = [
                x.t.net > 0
                for x in rows
                if key in x.features
                and (
                    (b == 0 and x.features[key] < e1)
                    or (b == 2 and x.features[key] > e2)
                    or (b == 1 and e1 <= x.features[key] <= e2)
                )
            ]
            rates[(key, b)] = (_rate(sum(pick), len(pick), base), len(pick))
    worst = sorted((r for r in rows if r.t.net <= 0), key=lambda r: r.t.net)[:8]
    out = []
    for r in worst:
        why = []
        for key, (e1, e2) in tables.items():
            v = r.features.get(key)
            if v is None:
                continue
            b = 0 if v < e1 else 2 if v > e2 else 1
            rate, n = rates[(key, b)]
            if rate <= base - 0.06 and n >= 6:
                rd = BY_KEY[key]
                word = past(rd.low_word if b == 0 else rd.high_word if b == 2 else middle_words(rd))
                why.append(
                    (rate, f"{word} ({_fmt(rd, v)}): trades like that won {rate * 100:.0f}%")
                )
        why.sort()
        if not why:  # too few trades for statistics: the textbook causes (D-128)
            why = [(0.0, CAUSES[k].text) for k in causes_of(r)]
        out.append(
            {
                "symbol": r.t.symbol,
                "side": "long" if r.t.side > 0 else "short",
                "entry_ts": r.t.entry_ts,
                "exit_ts": r.t.exit_ts,
                "net": round(r.t.net, 2),
                "return_pct": round(r.t.return_pct, 2),
                "exit_reason": EXIT_WORDS.get(r.t.exit_reason, r.t.exit_reason),
                "why": [w for _, w in why[:3]]
                or ["Nothing unusual in the readings: the ordinary risk of the strategy."],
            }
        )
    return out


def _add_market(rows: Sequence[_Row], market: BarSeries) -> None:
    """The index against its 50-candle average at each signal, turned round for shorts:
    below zero means the whole market was moving against the trade."""
    if len(market) < 60:
        return
    above = catalog.compute("disparity", market, {"period": 50.0})["value"]
    for r in rows:
        i = int(np.searchsorted(market.ts, r.t.entry_ts)) - 1
        if 0 <= i < len(above) and math.isfinite(float(above[i])):
            r.features["market"] = float(above[i]) * r.t.side


def review(
    trades: Sequence[TradeIn],
    series: Mapping[str, BarSeries],
    market: Market,
    *,
    score_for: Callable[[BarSeries], Any] | None = None,
    market_series: BarSeries | None = None,
) -> dict[str, Any]:
    """The full review. ``series`` holds each symbol's split-adjusted candles covering the
    trades (plus warm-up so the readings exist); ``market_series`` the index's, for the
    market's trend at each entry (the casebook, D-128)."""
    closed = [t for t in trades if t.exit_reason != "end_of_test"]
    rows = _rows(closed, series, score_for)
    if market_series is not None:
        _add_market(rows, market_series)
    n = len(rows)
    if n == 0:
        return {
            "trades": 0,
            "headline": "No closed trades yet, so there's nothing to learn from.",
            "lines": [],
            "advice": [],
        }
    first = min(r.t.entry_ts for r in rows)
    last = max(r.t.exit_ts for r in rows)
    days = (last - first) / 86_400_000
    m = _money_part(rows, market, days)
    w = _wins_part(rows, market)
    ex = _exits_part(rows)
    base = (w["wins"] + 1) / (n + 2)
    table, reasons = _conditions_part(rows, base)
    filters = _filters_part(rows, market)
    losers = _losers_part(rows, market, base)
    book = casebook(rows)
    advice: list[str] = []
    if m["level"] in ("bad", "warn"):
        advice.append(
            "Cut the number of trades: add a trend or choppiness filter, use a higher "
            "timeframe, or hold for bigger moves, so each trade earns well above its costs."
        )
    good = [r for r in filters["rules"] if r["held_up"]]
    if good:
        advice.append(
            f"Kairos found {len(good)} filter{'s' if len(good) != 1 else ''} that held up on "
            f"unseen trades. Click Improve with Kairos to test it as a new version."
        )
    if reasons and not good:
        advice.append(
            "Turn on Kairos's trade check in the backtest settings: it learns to skip the "
            "conditions named above as more trades come in."
        )
    headline = m["verdict"].split(". ")[0] + "."
    lines = [m["verdict"], *w["lines"], *ex["lines"], *[r["text"] for r in reasons[:3]]]
    lines += [str(p["text"]) for p in book["patterns"][:2]]
    return {
        "trades": n,
        "period": [first, last],
        "money": m,
        "wins": w,
        "exits": ex,
        "conditions": table,
        "failure_reasons": reasons,
        "filters": filters,
        "losers": losers,
        "casebook": book,
        "headline": headline,
        "lines": lines,
        "advice": advice,
        "features": [r.features for r in rows],
        "closed": [
            {
                "symbol": r.t.symbol,
                "side": r.t.side,
                "entry_ts": r.t.entry_ts,
                "signal_ts": r.signal_ts,
            }
            for r in rows
        ],
    }
