"""The expert's first look (METIS §11, D-81).

The checklist a senior quant runs on any strategy before changing it, written as code. It reads
the **study years only** (the same evidence Metis is shown) and returns findings in plain words,
each with the library topics to read and the **first experiments** an expert would run, as
ready-to-test ideas in Metis's own shape. Those experiments go into the brief as hints, and are
what Metis tests when the AI helper isn't available (playbook rounds, METIS §14).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.analysis import mtf
from backend.engine.types import Trade
from backend.kairos import review as rv
from backend.kairos.quality import BY_KEY
from backend.quant import stats
from backend.strategy import lineage
from backend.strategy.definition import VisualDefinition

PARTIAL_BELOW_WIN_RATE = 0.5  # propose partial exits under this win rate (D-125)
MAX_RULES = 6  # entry conditions per side (METIS §2, AlphaAgent's complexity limit)
TREND_FILTER = {"indicator": "sma", "params": {"period": 200.0}, "op": "below", "price": "close"}
TREND_FILTER_SHORT = {
    "indicator": "sma",
    "params": {"period": 200.0},
    "op": "above",
    "price": "close",
}
STRENGTH = {
    "indicator": "adx",
    "params": {"period": 14.0},
    "output": None,
    "op": "at_least",
    "value": 20.0,
}
# Indicators that, used to buy on the way down, mark a dip-buying (mean-reversion) strategy
REVERSION = {
    "rsi",
    "stochastic",
    "stoch_rsi",
    "williams_r",
    "cci",
    "mfi",
    "bollinger",
    "bollinger_pct",
    "zscore",
    "connors_rsi",
    "cmo",
    "ultimate",
    "smi",
    "fisher",
    "disparity",
    "lowest",
}
# Indicators that, used to buy on the way up, mark a trend-following strategy
TREND = {
    "sma",
    "ema",
    "wma",
    "hma",
    "dema",
    "tema",
    "kama",
    "donchian",
    "supertrend",
    "macd",
    "adx",
    "aroon",
    "psar",
    "keltner",
    "ichimoku",
    "highest",
    "high_52w",
    "roc",
    "momentum",
    "vortex",
    "trix",
    "kst",
    "ppo",
    "squeeze",
    "alligator",
    "linreg",
    "mcginley",
    "zlema",
    "t3",
    "vidya",
}


@dataclass
class Finding:
    key: str
    text: str
    topics: str
    seeds: list[dict[str, Any]] = field(default_factory=list)


def _seed(kind: str, sid: int, title: str, why: str, **extra: Any) -> dict[str, Any]:
    idea: dict[str, Any] = {
        "kind": kind,
        "strategy_id": sid,
        "title": title,
        "why": why,
        "conditions": [],
        "side": "long",
        "changes": {},
        "remove": None,
        "add": [],
        "drop": [],
        "idea": "",
        "market": None,
        "symbols": [],
        "template": None,
        "origin": "playbook",
    }
    idea.update(extra)
    return idea


def entry_parts(d: Any, side: str) -> list[dict[str, Any]]:
    """The entry conditions of one side as a list (the parts of a top-level AND)."""
    if not isinstance(d, VisualDefinition):
        return []
    rule = d.entry.long if side == "long" else d.entry.short
    if rule is None:
        return []
    data = json.loads(rule.model_dump_json())
    return list(data["conditions"]) if data.get("type") == "all" else [data]


BANDS = {"bollinger", "keltner", "donchian", "envelope", "highest", "lowest", "high_52w", "low_52w"}
AVERAGES = {"sma", "ema", "wma", "hma", "dema", "tema", "kama", "vwma", "alma", "t3", "zlema"}


def style(d: Any) -> str:
    """ "reversion", "trend" or "" from the buy rules' indicators and directions. The price
    against a band votes by direction (a dip below the lower band is a reversion, a break above
    the upper band a trend); the price against a moving average is a filter and doesn't vote."""
    sig = lineage.signature(d)
    votes = {"reversion": 0, "trend": 0}
    for token in sig.entry.elements():
        bits = token.split("|")
        if len(bits) < 4:
            continue
        side, left, direction, right = bits[0], bits[1], bits[2], bits[3]
        buying, down = side == "buy", direction == "down"
        if left.startswith("ind:"):
            name = left[4:].split(".")[0]
        elif left.startswith("price:") and right.startswith("ind:"):
            name = right[4:].split(".")[0]
            if name in AVERAGES:
                continue  # "close above the 200-day average" is a filter, not the trigger
            if name in BANDS:
                votes["reversion" if buying == down else "trend"] += 1
                continue
        else:
            continue
        if name in REVERSION and buying == down:
            votes["reversion"] += 1
        elif name in TREND and buying != down:
            votes["trend"] += 1
    if votes["reversion"] > votes["trend"]:
        return "reversion"
    if votes["trend"] > votes["reversion"]:
        return "trend"
    return ""


# "The bigger chart's close is above its average": 40 weeks ≈ 200 days, 20 days ≈ a month.
BIGGER_FILTER: dict[str, dict[str, Any]] = {
    "1w": {
        "indicator": "sma",
        "params": {"period": 40.0},
        "output": None,
        "op": "below",
        "value": None,
        "price": "close",
        "chart": "1w",
    },
    "1d": {
        "indicator": "sma",
        "params": {"period": 50.0},
        "output": None,
        "op": "below",
        "value": None,
        "price": "close",
        "chart": "1d",
    },
    "1h": {
        "indicator": "sma",
        "params": {"period": 50.0},
        "output": None,
        "op": "below",
        "value": None,
        "price": "close",
        "chart": "1h",
    },
    "15m": {
        "indicator": "sma",
        "params": {"period": 50.0},
        "output": None,
        "op": "below",
        "value": None,
        "price": "close",
        "chart": "15m",
    },
}


def _has_bigger_chart(d: Any, side: str) -> bool:
    return any(
        (c.get("left") or {}).get("chart") or (c.get("right") or {}).get("chart")
        for c in entry_parts(d, side)
    )


def _has_trend_filter(d: Any, side: str) -> bool:
    for c in entry_parts(d, side):
        left, right = c.get("left", {}), c.get("right", {})
        names = {o.get("name") for o in (left, right) if o.get("kind") == "indicator"}
        kinds = {left.get("kind"), right.get("kind")}
        if "price" in kinds and names & {"sma", "ema", "wma", "hma"}:
            return True
    return False


def _review_seeds(
    sid: int, review: dict[str, Any] | None, sides: list[str]
) -> list[tuple[str, dict[str, Any]]]:
    """A filter for each condition where the study years' losers clustered (Kairos's review)."""
    if not review or "long" not in sides:
        return []
    edges = {row["key"]: row["edges"] for row in review.get("conditions", [])}
    out = []
    for reason in review.get("failure_reasons", [])[:2]:
        key, third = reason.get("key"), reason.get("third")
        if key not in edges or key == "score" or third not in ("low", "high"):
            continue
        keep, edge = ("at_least", edges[key][0]) if third == "low" else ("at_most", edges[key][1])
        cond = rv.condition_for(key, keep, edge)
        if cond.get("directional"):
            continue  # direction-aware readings need the side flipped; leave them to the AI
        title = f"Skip the {BY_KEY[key].label.lower()} that lost"
        out.append(
            (
                str(reason.get("text", "")),
                _seed(
                    "filter",
                    sid,
                    title[:120],
                    f"In the study years: {reason.get('text', '')} A filter on that condition "
                    "tests whether those trades were the problem.",
                    conditions=[
                        {
                            "indicator": cond["indicator"],
                            "params": {k: float(v) for k, v in cond["params"].items()},
                            "output": cond["output"],
                            "op": keep,
                            "value": float(cond["value"]),
                        }
                    ],
                ),
            )
        )
    return out


def first_look(
    b: Any,
    *,
    review: dict[str, Any] | None,
    characters: dict[str, dict[str, Any]],
    daily: np.ndarray | None = None,
) -> list[Finding]:
    """Findings and first experiments for one strategy's baseline (study years only)."""
    d, sid, st = b.definition, b.strategy_id, b.study
    visual = isinstance(d, VisualDefinition)
    sides = [s for s in ("long", "short") if entry_parts(d, s)] if visual else []
    out: list[Finding] = []
    n = int(st["trades"] or 0)

    if daily is not None and len(daily) > 20:
        p = stats.psr(daily)
        out.append(
            Finding(
                "confidence",
                f"Statistical confidence: {p * 100:.0f}% chance its study-year edge is real "
                f"(probabilistic Sharpe ratio over {len(daily)} days, annual Sharpe "
                f"{stats.sharpe(daily):.2f}).",
                "probabilistic sharpe ratio confidence track record",
            )
        )
    if n < 30:
        out.append(
            Finding(
                "too_few",
                f"Only {n} study-year trades: too few to tell skill from luck, and filters would "
                "remove more. Better to test it on more stocks of the right character.",
                "too few trades statistical power sample size",
            )
        )

    aw, al, wr = st.get("avg_win"), st.get("avg_loss"), st.get("win_rate")
    if aw and al and wr is not None and n >= 10:
        be = al / (aw + al)
        if wr <= be + 0.02:
            f = Finding(
                "below_break_even",
                f"It wins {wr * 100:.0f}% of trades but needs {be * 100:.0f}% to break even "
                "after costs (average win against average loss): the entries need a better "
                "market condition, or the exits a better payoff.",
                "win rate below break even trend filter payoff",
            )
            if visual and "long" in sides and not _has_trend_filter(d, "long"):
                f.seeds.append(
                    _seed(
                        "filter",
                        sid,
                        "Only buy above the 200-day average",
                        "The win rate is under break-even; the classic trend filter keeps buys "
                        "on the side of the main trend (Faber 2007; Connors' dip-buying rules).",
                        conditions=[dict(TREND_FILTER)],
                    )
                )
            if visual and "short" in sides and not _has_trend_filter(d, "short"):
                f.seeds.append(
                    _seed(
                        "filter",
                        sid,
                        "Only short below the 200-day average",
                        "Shorts against the main trend lose more often.",
                        conditions=[dict(TREND_FILTER_SHORT)],
                        side="short",
                    )
                )
            out.append(f)

    big = mtf.DESK_BIGGER.get(d.timeframe)
    if (
        visual
        and big
        and "long" in sides
        and n >= 10
        and (wr or 0) < 0.5
        and not _has_bigger_chart(d, "long")
    ):
        out.append(
            Finding(
                "bigger_chart",
                f"It wins {(wr or 0) * 100:.0f}% of {n} trades and never looks at the bigger "
                "chart: buy signals against the bigger trend are the classic false alarm.",
                "multiple timeframe trend filter bigger chart weekly false signals faber",
                [
                    _seed(
                        "filter",
                        sid,
                        f"Only buy while the {mtf.LABEL[big]} trend is up",
                        f"Top-down traders only buy when the {mtf.LABEL[big]} chart agrees; it "
                        "removes signals against the bigger trend (Elder's triple screen; "
                        "Faber 2007).",
                        conditions=[dict(BIGGER_FILTER[big])],
                    )
                ],
            )
        )

    gross, charges = float(st.get("gross") or 0.0), float(st.get("charges") or 0.0)
    if n >= 10 and gross > 0 and charges / gross > 0.3:
        f = Finding(
            "costs",
            f"Costs took {charges / gross * 100:.0f}% of the gross profit: fewer, stronger "
            "trades should keep more of it.",
            "costs eat edge turnover holding period",
        )
        if visual and sides:
            f.seeds.append(
                _seed(
                    "filter",
                    sid,
                    "Trade only when the trend is strong",
                    "Costs eat a large share of the profit; requiring ADX(14) of at least 20 "
                    "drops weak, choppy signals and the costs that come with them.",
                    conditions=[dict(STRENGTH)],
                    side="both" if len(sides) == 2 else sides[0],
                )
            )
        if visual and d.exit.max_bars:
            longer = float(min(round(float(d.exit.max_bars) * 1.5), 1000))
            f.seeds.append(
                _seed(
                    "tweak",
                    sid,
                    "Hold trades longer",
                    "Longer holding means fewer round trips paying costs.",
                    changes={"max_bars": longer},
                )
            )
        out.append(f)

    if visual and sides and n >= 10 and d.exit.trailing_stop is None:
        out.append(_trailing_finding(sid, review, d))
    if visual and sides and n >= 10 and d.exit.scale_out is None:
        partial = _partial_finding(sid, review, d, wr)
        if partial is not None:
            out.append(partial)

    if visual and sides:
        book = _casebook_finding(sid, review, d, sides)
        if book is not None:
            out.append(book)

    for text, seed in _review_seeds(sid, review, sides):
        out.append(
            Finding(
                "losers_cluster",
                f"Where losers clustered: {text}",
                "losers cluster filter regime",
                [seed],
            )
        )

    exits = st.get("exits") or {}
    stops = int(exits.get("stop", 0) or 0)
    if visual and n >= 10 and stops / n > 0.5 and (wr or 0) < 0.45 and d.exit.stop_loss:
        sl = d.exit.stop_loss
        if sl.kind == "percent" and isinstance(sl.value, int | float):
            wider = float(min(round(float(sl.value) * 1.5, 2), 50.0))
            out.append(
                Finding(
                    "tight_stops",
                    f"{stops} of {n} trades ended at the stop-loss and it wins only "
                    f"{(wr or 0) * 100:.0f}%: the stop may sit inside the stocks' normal noise.",
                    "stops cut too many trades stop loss research kaminski lo",
                    [
                        _seed(
                            "tweak",
                            sid,
                            "Give trades more room",
                            "Most trades end at the stop; a wider stop tests whether normal noise "
                            "was stopping good trades (Kaminski and Lo, 2014).",
                            changes={"stop_loss_pct": wider},
                        )
                    ],
                )
            )
    if visual and aw and al and al > 2 * aw and not d.exit.stop_loss and not d.exit.max_bars:
        out.append(
            Finding(
                "losses_run",
                "The average loss is more than twice the average win and nothing limits a losing "
                "trade: no stop-loss and no time limit.",
                "losses run time exit stop loss",
                [
                    _seed(
                        "tweak",
                        sid,
                        "Add a time limit",
                        "Losers run much longer than winners; a time limit frees money from "
                        "stale trades.",
                        changes={"max_bars": 20.0},
                    ),
                    _seed(
                        "tweak",
                        sid,
                        "Add a stop-loss",
                        "Nothing cuts a losing trade; a stop-loss caps each loss so one bad "
                        "trade can't undo many good ones.",
                        changes={"stop_loss_pct": _stop_guess(d)},
                    ),
                ],
            )
        )

    kind = style(d)
    if kind and characters:
        wrong = "trending" if kind == "reversion" else "mean-reverting"
        misfits = [s for s, c in characters.items() if c.get("label") == wrong]
        if misfits:
            what = "dip-buying (mean-reversion)" if kind == "reversion" else "trend-following"
            f = Finding(
                "misfit",
                f"It is a {what} strategy, but {', '.join(misfits)} "
                f"{'were' if len(misfits) > 1 else 'was'} "
                f"{wrong} in the study years (variance ratio and Hurst exponent).",
                "strategy doesn't fit stocks character trending mean reverting",
            )
            keep = len(characters) - len(misfits)
            if keep >= 3:
                f.seeds.append(
                    _seed(
                        "universe",
                        sid,
                        f"Drop the {wrong} stocks",
                        "Stocks whose character fights the strategy's logic add losing trades.",
                        drop=misfits[:3],
                    )
                )
            out.append(f)

    if visual:
        for side in sides:
            parts = entry_parts(d, side)
            if len(parts) >= 5:
                out.append(
                    Finding(
                        "too_many_rules",
                        f"{len(parts)} entry conditions on {side} trades: every extra rule is "
                        "another chance to fit noise.",
                        "too many rules simplify complexity",
                        [
                            _seed(
                                "simplify",
                                sid,
                                f"Drop rule {k}",
                                "A simpler strategy that does as well is more likely to last.",
                                remove=k,
                                side=side,
                            )
                            for k in (len(parts), len(parts) - 1)
                        ],
                    )
                )
    return out


def _trailing_finding(sid: int, review: dict[str, Any] | None, d: Any) -> Finding:
    """No trailing stop: propose one, sized to the stock's own wiggle (D-119). Winners that
    turned into losers are the clearest case; a trend strategy without one is the next."""
    gave = ((review or {}).get("exits") or {}).get("gave_back") or {}
    ahead, measured = int(gave.get("ahead") or 0), int(gave.get("measured") or 0)
    if measured >= 5 and ahead / measured >= 0.3:
        text = (
            f"{ahead} of {measured} losing trades were ahead by at least one ATR before turning "
            "into losses, and nothing locks gains in: a trailing stop would have kept some."
        )
        widths: tuple[float, ...] = (2.5, 3.5)
    else:
        text = (
            "It has no trailing stop: a winning trade can give back its whole gain before the "
            "exit rule fires."
        )
        widths = (3.0,) if style(d) != "trend" else (3.0, 4.0)
    return Finding(
        "trailing",
        text,
        "trailing stop chandelier exit atr protect gains let winners run",
        [
            _seed(
                "tweak",
                sid,
                f"Trail the stop {w:g} ATRs behind the best price",
                "A trailing stop follows the price and never moves back: winners keep most of "
                f"their gain, losers are still cut. {w:g} × ATR(14) fits the stock's own wiggle "
                "(LeBeau's chandelier exit; Kaminski and Lo, 2014).",
                changes={"trailing_stop_atr": w},
            )
            for w in widths
        ],
    )


# The casebook's shared causes (D-128) and the entry filter that tests each one. "market" and
# "gave_back" are left out: rules read one stock (the weekly-trend filter stands in for the
# market), and giving gains back is the partial-exit finding's job.
CASE_FILTERS: dict[str, dict[str, Any]] = {
    "long_trend": dict(TREND_FILTER),
    "mid_trend": {"indicator": "sma", "params": {"period": 50.0}, "op": "below", "price": "close"},
    "market": {
        "indicator": "sma",
        "params": {"period": 40.0},
        "op": "below",
        "price": "close",
        "chart": "1w",
    },
    "chop": dict(STRENGTH),
    "rvol": {"indicator": "rvol", "params": {"period": 20.0}, "op": "at_least", "value": 1.0},
    "stretch": {"indicator": "zscore", "params": {"period": 20.0}, "op": "at_most", "value": 2.0},
}


def _casebook_finding(
    sid: int, review: dict[str, Any] | None, d: Any, sides: list[str]
) -> Finding | None:
    """What the losing trades had in common, trade by trade (D-128), with the matching fix.
    Works from three trades, where the statistical review is still quiet."""
    patterns = ((review or {}).get("casebook") or {}).get("patterns") or []
    if not patterns:
        return None
    side = sides[0] if len(sides) == 1 else "long"
    seeds = []
    for p in patterns[:3]:
        key = str(p["key"])
        cond = CASE_FILTERS.get(key)
        if key == "market" and d.timeframe != "1d":
            cond = None  # the weekly chart is only a bigger chart for daily strategies
        if cond is not None and side == "long":
            seeds.append(
                _seed(
                    "filter",
                    sid,
                    f"Fix the losers' shared cause: {p['fix']}",
                    str(p["text"]),
                    conditions=[dict(cond)],
                    side=side,
                )
            )
        elif key == "noise_stop" and d.exit.stop_loss is not None:
            sl = d.exit.stop_loss
            if sl.kind == "percent" and isinstance(sl.value, int | float):
                wider = float(min(round(float(sl.value) * 1.5, 2), 50.0))
                seeds.append(
                    _seed(
                        "tweak",
                        sid,
                        "Give trades room beyond the noise",
                        str(p["text"]),
                        changes={"stop_loss_pct": wider},
                    )
                )
    text = "Why the losing trades lost, one by one: " + " ".join(
        str(p["text"]) for p in patterns[:3]
    )
    return Finding("casebook", text, "losing trades causes against trend market volume", seeds)


def _stop_guess(d: Any) -> float:
    """A first stop-loss in percent for a strategy without one: tighter on short charts."""
    return {"1d": 6.0, "1h": 3.0, "15m": 1.5, "5m": 1.0, "1m": 0.6}.get(d.timeframe, 5.0)


def _partial_finding(
    sid: int, review: dict[str, Any] | None, d: Any, wr: float | None
) -> Finding | None:
    """No partial exits (D-125): book part of the profit at 1R and move the stop to the entry,
    so trades that were ahead can no longer turn into full losses. Raises the win rate; caps
    the very best trades a little, so the exam years decide whether it pays."""
    gave = ((review or {}).get("exits") or {}).get("gave_back") or {}
    ahead, measured = int(gave.get("ahead") or 0), int(gave.get("measured") or 0)
    if measured >= 5 and ahead / measured >= 0.3:
        text = (
            f"{ahead} of {measured} losing trades were ahead first and gave it all back: "
            "selling part at the first target and moving the stop to the entry would have "
            "banked some of it."
        )
    elif wr is not None and wr < PARTIAL_BELOW_WIN_RATE:
        text = (
            f"It wins {(wr or 0) * 100:.0f}% of trades and takes no profit on the way: partial "
            "exits (half at 1R, or thirds) bank gains early and let the rest run for free."
        )
    else:
        return None  # no symptom: winners aren't given back and most trades already win
    stop = {} if d.exit.stop_loss is not None else {"stop_loss_pct": _stop_guess(d)}
    return Finding(
        "partials",
        text,
        "partial exits scale out profit booking breakeven stop R multiple win rate",
        [
            _seed(
                "tweak",
                sid,
                "Sell half at 1R, stop to the entry",
                "Half the trade is sold once it has made as much as it risked; the stop then "
                "moves to the entry price, so the rest rides the trend without risk.",
                changes={**stop, "partial_half_r": 1.0},
            ),
            _seed(
                "tweak",
                sid,
                "Sell a third at 1R and a third at 2R",
                "Two profit targets, the last third rides the exit rule or the trailing stop.",
                changes={**stop, "partial_thirds_r": 1.0},
            ),
        ],
    )


def best_three_share(trades: list[Trade], lo: int, hi: int) -> float | None:
    """Share of the net profit from the three best trades (None when it lost money)."""
    rows = [t.net_pnl for t in trades if t.closed and lo <= t.entry_ts < hi]
    total = sum(rows)
    if total <= 0 or len(rows) < 6:
        return None
    return sum(sorted(rows, reverse=True)[:3]) / total


def lines(findings: list[Finding]) -> list[str]:
    """The findings and their first experiments, as the brief shows them."""
    out = [f"- {f.text}" for f in findings]
    seeds = [s for f in findings for s in f.seeds]
    if seeds:
        out.append("First experiments a senior quant would run:")
        out += [f"  · {s['kind']}: {s['title']}" for s in seeds[:4]]
    return out
