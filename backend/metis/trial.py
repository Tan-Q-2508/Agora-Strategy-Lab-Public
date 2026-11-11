"""Metis's ideas, tested (METIS §2, §4, D-76).

Each idea becomes valid Agora rules and is backtested in the shared engine (D-04) over the same
stocks, period, money and costs as its baseline. Trades are split by entry time at the 70%
point: the **study years**, which Metis was shown, and the **exam years**, which it wasn't. The
verdict is fixed here, in code; nothing the model says can change it.

A change to a strategy (``filter``, ``tweak``) holds up only if, after costs:
1. in the exam years it made more than the current version, by ≥ 0.1% of the starting money;
2. in the study years it made at least as much (an idea that doesn't help where it was
   thought up is luck);
3. in the exam years it kept ≥ 5 trades and ≥ 30% of the current version's trades.

A new strategy holds up only if it made money in both parts with ≥ 5 trades each and won at
least 1.1× what it lost in the exam years.

Since Phase 14 (D-82, D-83): every change and new strategy must also pass the **luck check**
(deflated Sharpe ratio ≥ 0.5 over the ideas already tried); a **simplify** idea holds up when
the exam years made at least as much as the current version and the study years at least 95%
as much; a **universe** idea is judged like any change, on the new stock list; and a "new"
strategy that is really one the user has (D-79) is judged against that strategy's current
version on its own stocks instead.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import select

from backend.ai.draft import draft
from backend.analysis import mtf
from backend.backtest.manager import BacktestRequest
from backend.backtest.run import NoData, RunOutput, RunSpec, run
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import service as data_service
from backend.data import store
from backend.db.models import Candle, Instrument
from backend.metis import brief as brief_mod
from backend.metis import notebook, overfit, precheck
from backend.metis.brief import STUDY_SHARE, Baseline, part
from backend.metis.diagnose import MAX_RULES, entry_parts
from backend.metrics.summary import money
from backend.quant import stats
from backend.strategy import revisions, templates
from backend.strategy import service as strategies
from backend.strategy.definition import (
    AllOf,
    AnyDefinition,
    Compare,
    Condition,
    IndicatorOperand,
    NumberOperand,
    PriceOperand,
    ScaleOutSpec,
    ScaleStepSpec,
    StopSpec,
    Universe,
    VisualDefinition,
    content_hash,
)
from backend.strategy.validator import validate

MIN_GAIN_OF_CAPITAL = 0.001
MIN_EXAM_TRADES = 5
MIN_KEEP = 0.3
MIN_PROFIT_FACTOR = 1.1
MIN_LUCK = 0.5  # deflated Sharpe ratio (D-82)
SIMPLE_STUDY_SHARE = 0.95
NEW_SYMBOLS = 6
WIDE_LIST = 30  # more stocks than this and the list itself carries hindsight (D-231)
TRADED_WINDOW_MS = 30 * 86_400_000
MIN_TRADED_DAYS = 10
MIN_UNIVERSE = 4  # a universe idea tests on at least this many stocks (D-128)
EXIT_LIMITS = {
    "stop_loss_pct": (0.2, 50.0),
    "take_profit_pct": (0.2, 500.0),
    "trailing_stop_pct": (0.2, 50.0),
    "trailing_stop_atr": (0.5, 8.0),  # × ATR(14) from the best price since entry (D-119)
    "max_bars": (1.0, 1000.0),
    # partial exits (D-125), in R (the stop distance); the stop moves to the entry after
    # the first: half at R, or a third at R and a third at 2R
    "partial_half_r": (0.3, 5.0),
    "partial_thirds_r": (0.3, 3.0),
}


def partial_spec(name: str, r: float) -> ScaleOutSpec:
    r = round(r, 2)
    if name == "partial_half_r":
        steps = [ScaleStepSpec(kind="r", value=r, sell_pct=50.0)]
    else:
        steps = [
            ScaleStepSpec(kind="r", value=r, sell_pct=33.0),
            ScaleStepSpec(kind="r", value=round(2 * r, 2), sell_pct=33.0),
        ]
    return ScaleOutSpec(steps=steps, breakeven=True)


class Untestable(Exception):
    """The idea can't be turned into valid rules (the message says why, in plain words)."""


@dataclass
class Outcome:
    status: str  # held_up | rejected | untestable
    verdict: str
    rules: dict[str, Any]
    fingerprint: str
    market: str | None = None
    strategy_id: int | None = None
    version_id: int | None = None
    result: dict[str, Any] = field(default_factory=dict)
    spec: RunSpec | None = None
    definition: AnyDefinition | None = None


# ---------------------------------------------------------------- ideas → rules


def _compare(c: dict[str, Any]) -> Compare:
    if c["op"] not in ("above", "below", "at_least", "at_most"):
        raise Untestable(f"“{c['op']}” isn't a comparison Agora knows.")
    chart = c.get("chart")  # a bigger chart of the same stock (D-97)
    left = IndicatorOperand(
        name=c["indicator"], params=c["params"], output=c.get("output"), chart=chart
    )
    if c.get("price"):  # "SMA(200) below the close": the indicator against the price
        return Compare(left=left, op=c["op"], right=PriceOperand(field=c["price"], chart=chart))
    if c.get("value") is None:
        raise Untestable("A filter condition needs a number or a price to compare with.")
    return Compare(left=left, op=c["op"], right=NumberOperand(value=round(float(c["value"]), 4)))


def _add(rule: Condition | None, extra: list[Compare]) -> Condition | None:
    if rule is None:
        return None
    if isinstance(rule, AllOf) and len(rule.conditions) + len(extra) <= 20:
        return AllOf(conditions=[*rule.conditions, *extra])
    return AllOf(conditions=[rule, *extra])


def with_filter(d: AnyDefinition, idea: dict[str, Any]) -> VisualDefinition:
    if not isinstance(d, VisualDefinition):
        raise Untestable(
            "Filters can only be added to visual strategies; a settings change can be tried "
            "on this one instead."
        )
    if not idea["conditions"]:
        raise Untestable("The idea didn't say which condition to add.")
    for c in idea["conditions"]:
        if c.get("chart") and not mtf.allowed(d.timeframe, c["chart"]):
            have, want = mtf.LABEL[d.timeframe], mtf.LABEL.get(c["chart"], c["chart"])
            raise Untestable(f"A {have} strategy can't read the {want} chart; pick a bigger one.")
    extra = [_compare(c) for c in idea["conditions"]]
    side = idea["side"]
    for s in ("long", "short"):
        if side in (s, "both") and len(entry_parts(d, s)) + len(extra) > MAX_RULES:
            raise Untestable(
                f"Too many rules already: {s} entries would have more than {MAX_RULES} "
                "conditions. Simpler strategies hold up better; try simplifying instead."
            )
    entry = d.entry
    long = _add(entry.long, extra) if side in ("long", "both") else entry.long
    short = _add(entry.short, extra) if side in ("short", "both") else entry.short
    if (long, short) == (entry.long, entry.short):
        raise Untestable(
            f"This strategy doesn't open {side} trades, so the filter changes nothing."
        )
    return d.model_copy(update={"entry": entry.model_copy(update={"long": long, "short": short})})


def with_changes(d: AnyDefinition, changes: dict[str, float]) -> AnyDefinition:
    if not changes:
        raise Untestable("The idea didn't say which setting to change.")
    params = {p.name: p for p in d.parameters}
    new_params = list(d.parameters)
    exit_update: dict[str, Any] = {}
    changed = False
    for name, value in changes.items():
        if name in params:
            p = params[name]
            if not p.min <= value <= p.max:
                raise Untestable(
                    f"{p.label} ({name}) must stay between {p.min:g} and {p.max:g}; "
                    f"the idea asked for {value:g}."
                )
            v = float(round(value)) if p.type == "int" else value
            changed = changed or v != p.default
            new_params = [
                x.model_copy(update={"default": v}) if x.name == name else x for x in new_params
            ]
        elif name in EXIT_LIMITS:
            if not isinstance(d, VisualDefinition):
                raise Untestable("Exits can only be changed on visual strategies.")
            lo, hi = EXIT_LIMITS[name]
            if not lo <= value <= hi:
                raise Untestable(f"{name.replace('_', ' ')} must be between {lo:g} and {hi:g}.")
            if name == "max_bars":
                exit_update["max_bars"] = float(round(value))
                changed = changed or d.exit.max_bars != exit_update["max_bars"]
            elif name == "trailing_stop_atr":
                spec = StopSpec(kind="atr", value=round(value, 2))
                exit_update["trailing_stop"] = spec
                changed = changed or d.exit.trailing_stop != spec
            elif name in ("partial_half_r", "partial_thirds_r"):
                if d.exit.stop_loss is None and "stop_loss_pct" not in changes:
                    raise Untestable(
                        "Partial exits in R need a stop-loss to measure R; add stop_loss_pct."
                    )
                scale = partial_spec(name, value)
                exit_update["scale_out"] = scale
                changed = changed or d.exit.scale_out != scale
            else:
                key = name.removesuffix("_pct")
                spec = StopSpec(kind="percent", value=round(value, 3))
                exit_update[key] = spec
                changed = changed or getattr(d.exit, key) != spec
        else:
            raise Untestable(f"This strategy has no setting called “{name}”.")
    if not changed:
        raise Untestable("Those are the strategy's current settings already.")
    out = d.model_copy(update={"parameters": new_params})
    if exit_update and isinstance(out, VisualDefinition):
        out = out.model_copy(update={"exit": out.exit.model_copy(update=exit_update)})
    return out


def with_simplify(d: AnyDefinition, idea: dict[str, Any]) -> VisualDefinition:
    """The strategy with one entry condition removed (by its number in the brief)."""
    if not isinstance(d, VisualDefinition):
        raise Untestable("Only visual strategies have separate rules to remove.")
    side = "short" if idea.get("side") == "short" else "long"
    conds = entry_parts(d, side)
    k = idea.get("remove")
    if not conds:
        raise Untestable(f"This strategy doesn't open {side} trades.")
    if len(conds) < 2:
        raise Untestable("A strategy needs at least one entry rule; this one has only one.")
    if not isinstance(k, int) or not 1 <= k <= len(conds):
        raise Untestable(f"There is no rule number {k} on {side} entries (1 to {len(conds)}).")
    kept = [c for n, c in enumerate(conds, start=1) if n != k]
    rule: dict[str, Any] = kept[0] if len(kept) == 1 else {"type": "all", "conditions": kept}
    data = json.loads(d.model_dump_json())
    data["entry"][side] = rule
    res = validate(data)
    if not res.ok or not isinstance(res.definition, VisualDefinition):
        raise Untestable("Without that rule the strategy isn't valid any more.")
    return res.definition


def new_symbols(ctx: Any, b: Baseline, idea: dict[str, Any]) -> list[str]:
    """The baseline's stocks with the idea's stocks added and dropped (known stocks only)."""
    have = [i.symbol for i in b.spec.instruments]
    with ctx.db.session() as s:
        add = [
            i.symbol
            for x in idea.get("add") or []
            if (i := store.find_instrument(s, b.market, x)) is not None and not i.is_index
        ]
    drop = {str(x).upper() for x in idea.get("drop") or []}
    out = [x for x in have if x.upper() not in drop] + [x for x in add if x not in have]
    if idea.get("add") and len(out) < MIN_UNIVERSE:
        # the model named stocks Agora doesn't know (D-128): top up with the market's main
        # stocks, which is what "test it on more stocks" needs anyway
        with ctx.db.session() as s:
            peers = [i.symbol for i in data_service.default_symbols(s, b.market) if not i.is_index]
        for sym in peers:
            if len(out) >= MIN_UNIVERSE:
                break
            if sym not in out and sym.upper() not in drop:
                out.append(sym)
    if out == have:
        raise Untestable("The idea doesn't change the strategy's stocks (unknown or same stocks).")
    if len(out) < 2:
        raise Untestable("A strategy needs at least two stocks to judge it fairly.")
    return out[:30]


def _warm_ms(spec: RunSpec, compares: list[Compare]) -> int:
    from backend.backtest.run import warmup_ms
    from backend.indicators import catalog

    bars = 5
    for c in compares:
        for o in (c.left, c.right):
            if isinstance(o, IndicatorOperand):
                try:
                    ind = catalog.get(o.name)
                except KeyError:
                    continue
                p = {k: float(v) for k, v in o.params.items() if not isinstance(v, str)}
                bars = max(bars, ind.warmup(p) + o.offset)
    return warmup_ms(spec.timeframe, bars)


def reach_problems(
    ctx: Any, spec: RunSpec, d: AnyDefinition, compares: list[Compare], split_ms: int
) -> list[str]:
    """Conditions that can't work on the study years (D-142); [] when all can, or when there
    is nothing to check. A failing check never blocks a test: it only explains earlier."""
    if not compares:
        return []
    from backend.strategy.compiler import parameter_values

    try:
        series = precheck.load(
            ctx.cache,
            spec.instruments,
            spec.timeframe,
            Market(d.market),
            spec.start_ms,
            split_ms,
            _warm_ms(spec, compares),
        )
        return precheck.problems(compares, series, parameter_values(d))
    except Exception:  # the check is a shortcut, never a gate of its own
        return []


def _checked(d: AnyDefinition) -> AnyDefinition:
    res = validate(json.loads(d.model_dump_json()))
    if not res.ok or res.definition is None:
        first = res.errors[0].sentence() if res.errors else "The rules aren't valid."
        raise Untestable(f"Agora couldn't use the rules: {first}")
    return res.definition


# ---------------------------------------------------------------- verdicts


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def luck_check(luck: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The fourth rule (D-82), when the luck check could be measured."""
    if not luck:
        return []
    return [
        {
            "ok": luck["dsr"] >= MIN_LUCK,
            "text": f"Luck check: {luck['dsr'] * 100:.0f}% chance it beats the best of "
            f"{luck['tries']} lucky {'try' if luck['tries'] == 1 else 'tries'} (deflated Sharpe "
            f"ratio over {luck['days']} exam days; "
            f"needs {MIN_LUCK * 100:.0f}%).",
        }
    ]


def judge_change(
    base: dict[str, dict[str, Any]],
    cand: dict[str, dict[str, Any]],
    capital: float,
    market: Market,
    luck: dict[str, Any] | None = None,
    more: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """Fixed rules for a change to a strategy; returns (held up, verdict, the checks).
    ``more``: further checks every change must pass (the overfitting check, D-89)."""
    gain = cand["exam"]["net"] - base["exam"]["net"]
    need = MIN_GAIN_OF_CAPITAL * capital
    keep = max(MIN_EXAM_TRADES, MIN_KEEP * base["exam"]["trades"])
    checks = [
        {
            "ok": gain >= need,
            "text": f"Exam years: made {money(cand['exam']['net'], market)} after costs against "
            f"{money(base['exam']['net'], market)} for the current version "
            f"(needs at least {money(need, market)} more than that).",
        },
        {
            "ok": cand["study"]["net"] >= base["study"]["net"],
            "text": f"Study years: made {money(cand['study']['net'], market)} against "
            f"{money(base['study']['net'], market)} (needs at least as much).",
        },
        {
            "ok": cand["exam"]["trades"] >= keep,
            "text": f"Exam years: kept {cand['exam']['trades']} of "
            f"{base['exam']['trades']} trades (needs {keep:.0f}).",
        },
        *luck_check(luck),
        *(more or []),
    ]
    held = all(c["ok"] for c in checks)
    if held:
        verdict = (
            f"Held up. In the exam years it made {money(gain, market)} more after costs than the "
            f"current version ({money(cand['exam']['net'], market)} against "
            f"{money(base['exam']['net'], market)}), winning {_pct(cand['exam']['win_rate'])} of "
            f"{cand['exam']['trades']} trades against {_pct(base['exam']['win_rate'])} of "
            f"{base['exam']['trades']}, and it did at least as well in the study years."
        )
    else:
        failed = next(c for c in checks if not c["ok"])
        verdict = "Didn't hold up. " + failed["text"]
    return held, verdict, checks


def judge_simplify(
    base: dict[str, dict[str, Any]],
    cand: dict[str, dict[str, Any]],
    market: Market,
    more: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """Fewer rules at equal results win: exam ≥ current, study ≥ 95% of current."""
    st_need = base["study"]["net"] - (1 - SIMPLE_STUDY_SHARE) * abs(base["study"]["net"])
    checks = [
        {
            "ok": cand["exam"]["net"] >= base["exam"]["net"],
            "text": f"Exam years: made {money(cand['exam']['net'], market)} after costs against "
            f"{money(base['exam']['net'], market)} (needs at least as much).",
        },
        {
            "ok": cand["study"]["net"] >= st_need,
            "text": f"Study years: made {money(cand['study']['net'], market)} against "
            f"{money(base['study']['net'], market)} (needs at least {money(st_need, market)}).",
        },
        {
            "ok": cand["exam"]["trades"] >= MIN_EXAM_TRADES,
            "text": f"Exam years: {cand['exam']['trades']} trades (needs {MIN_EXAM_TRADES}).",
        },
        *(more or []),
    ]
    held = all(c["ok"] for c in checks)
    if held:
        verdict = (
            "Held up. With one rule fewer it did at least as well in the exam years "
            f"({money(cand['exam']['net'], market)} against "
            f"{money(base['exam']['net'], market)}): simpler is more likely to last."
        )
    else:
        verdict = "Didn't hold up. " + next(c for c in checks if not c["ok"])["text"]
    return held, verdict, checks


INDEX_NAME = {"IN": "Nifty 50", "US": "S&P 500 (SPY)"}


def against_index(out: RunOutput, split: int, market: Market) -> dict[str, Any]:
    """The user's bar (D-126): a strategy that makes less than simply holding the index over
    the exam years isn't worth running. Both are measured on the whole starting money, after
    costs for the strategy, price only for the index. Passes when the index can't be measured
    (no saved index prices), so missing data never rejects a strategy on its own."""
    name = INDEX_NAME.get(market.value, "the index")
    bench = [(t, v) for t, v in out.benchmark if t >= split]
    eq = [p for p in out.equity if p.ts >= split]
    if len(bench) < 2 or len(eq) < 2 or not bench[0][1] or not eq[0].equity:
        return {"ok": True, "text": f"Against the {name}: no index prices saved to compare."}
    idx = bench[-1][1] / bench[0][1] - 1
    mine = eq[-1].equity / eq[0].equity - 1
    return {
        "ok": mine > idx,
        "text": f"Exam years: made {mine * 100:+.1f}% against {idx * 100:+.1f}% for simply "
        f"holding the {name} (needs more than the index).",
        "strategy_pct": mine,
        "index_pct": idx,
    }


def list_then(ctx: Any, market: Market, at_ms: int, n: int) -> list[str]:
    """The ``n`` most traded stocks as they stood at ``at_ms``, from what was known then."""
    c = Candle.__table__.c
    i = Instrument.__table__.c
    with ctx.db.session() as s:
        rows = s.execute(
            select(i.symbol, c.close * c.volume)
            .select_from(Candle.__table__.join(Instrument.__table__, c.instrument_id == i.id))
            .where(
                i.market_code == market.value,
                i.instrument_type == "equity",
                c.timeframe == "1d",
                c.ts >= at_ms - TRADED_WINDOW_MS,
                c.ts < at_ms,
            )
        ).all()
    days: dict[str, list[float]] = {}
    for sym, money_traded in rows:
        days.setdefault(sym, []).append(float(money_traded))
    medians = {k: statistics.median(v) for k, v in days.items() if len(v) >= MIN_TRADED_DAYS}
    return sorted(medians, key=lambda k: -medians[k])[:n]


def survivorship_check(ctx: Any, spec: RunSpec, d: AnyDefinition, split: int) -> dict[str, Any]:
    """A long list of today's most traded stocks has hindsight in it: they are the ones that did
    well. It flattered India's momentum rule from a loss to +155% (D-231), which no other check
    could see. So a wide idea must also earn on the list as it stood when the exam began, chosen
    from prices before it. Stocks since delisted aren't saved, so some hindsight remains."""
    market = spec.market
    then = list_then(ctx, market, split, len(spec.instruments))
    if len(then) < WIDE_LIST:
        return {"ok": True, "text": "List as it stood: too few saved prices to compare."}
    fair = d.model_copy(update={"universe": d.universe.model_copy(update={"symbols": then})})
    spec2, _x = ctx.backtests.spec_for(fair, BacktestRequest(strategy_version_id=0, symbols=then))
    spec2 = replace(spec2, start_ms=spec.start_ms, end_ms=spec.end_ms)
    _s, parts, _sp, out = _parts(spec2, fair, ctx)
    ex = parts["exam"]
    pf = ex["profit_factor"]
    index = against_index(out, split, market)
    ok = ex["net"] > 0 and pf is not None and pf >= MIN_PROFIT_FACTOR and index["ok"]
    return {
        "ok": ok,
        "text": f"Exam years on the stocks most traded before they began: "
        f"{money(ex['net'], market)} after costs, won {'–' if pf is None else f'{pf:.2f}'}× what "
        f"it lost. {index['text']}",
    }


def judge_new(
    cand: dict[str, dict[str, Any]],
    market: Market,
    luck: dict[str, Any] | None = None,
    more: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, list[dict[str, Any]]]:
    st, ex = cand["study"], cand["exam"]
    pf = ex["profit_factor"]
    checks = [
        {
            "ok": st["trades"] >= MIN_EXAM_TRADES and st["net"] > 0,
            "text": f"Study years: {st['trades']} trades, made {money(st['net'], market)} after "
            f"costs (needs 5+ trades and a profit).",
        },
        {
            "ok": ex["trades"] >= MIN_EXAM_TRADES and ex["net"] > 0,
            "text": f"Exam years: {ex['trades']} trades, made {money(ex['net'], market)} after "
            f"costs (needs 5+ trades and a profit).",
        },
        {
            "ok": pf is not None and pf >= MIN_PROFIT_FACTOR,
            "text": f"Exam years: won {'–' if pf is None else f'{pf:.2f}'}× what it lost "
            f"(needs {MIN_PROFIT_FACTOR}×).",
        },
        *luck_check(luck),
        *(more or []),
    ]
    held = all(c["ok"] for c in checks)
    if held:
        verdict = (
            f"Held up. It made {money(st['net'], market)} in the study years and "
            f"{money(ex['net'], market)} in the exam years after costs, winning "
            f"{_pct(ex['win_rate'])} of {ex['trades']} exam trades."
        )
    else:
        verdict = "Didn't hold up. " + next(c for c in checks if not c["ok"])["text"]
    return held, verdict, checks


# ---------------------------------------------------------------- running


def _parts(
    spec: RunSpec, definition: AnyDefinition, ctx: Any
) -> tuple[RunSpec, dict[str, Any], int, RunOutput]:
    s = replace(spec, definition=definition)
    ctx.backtests.ensure_data_for(s)
    out = run(ctx.cache, s)
    split = s.start_ms + int((s.end_ms - s.start_ms) * STUDY_SHARE)
    return (
        s,
        {
            "study": part(out.trades, s.start_ms, split),
            "exam": part(out.trades, split, s.end_ms + 1),
        },
        split,
        out,
    )


def luck(returns: Any, tries: int) -> dict[str, Any] | None:
    """The deflated Sharpe ratio of exam-year daily returns over ``tries`` tries (D-82)."""
    import numpy as np

    r = np.asarray(returns, dtype=float)
    if len(r) < 20:
        return None
    return {
        "dsr": round(stats.dsr(r, tries), 4),
        "psr": round(stats.psr(r), 4),
        "tries": tries,
        "days": len(r),
        "sharpe": round(stats.sharpe(r), 3),
    }


def change_luck(base: RunOutput, cand: RunOutput, market: Market, split: int, tries: int) -> Any:
    """Luck check of a change: the daily difference between the two versions' returns."""
    tz = MARKET_TZ[market]
    a = dict(stats.daily_points(base.equity, tz, lo=split))
    b = dict(stats.daily_points(cand.equity, tz, lo=split))
    days = sorted(set(a) & set(b))
    ra = stats.returns_of([a[d] for d in days])
    rb = stats.returns_of([b[d] for d in days])
    return luck(rb - ra, tries)


def rules_of(idea: dict[str, Any]) -> dict[str, Any]:
    if idea["kind"] == "filter":
        return {"conditions": idea["conditions"], "side": idea["side"]}
    if idea["kind"] == "tweak":
        return {"changes": idea["changes"]}
    if idea["kind"] == "simplify":
        return {"remove": idea.get("remove"), "side": idea.get("side")}
    if idea["kind"] == "universe":
        return {"add": sorted(idea.get("add") or []), "drop": sorted(idea.get("drop") or [])}
    tf = idea.get("timeframe")
    if idea.get("playbook"):
        return {"playbook": idea["playbook"], "market": idea["market"]}
    if idea.get("definition"):
        # finished rules written by Claude in a laptop session (D-160): the rules are the idea
        raw = json.dumps(idea["definition"], sort_keys=True, separators=(",", ":"))
        return {
            "rules": hashlib.sha256(raw.encode()).hexdigest()[:16],
            "market": idea["market"],
            "timeframe": tf or "1d",
            "symbols": sorted(idea.get("symbols") or []),
        }
    if idea.get("template"):
        out = {"template": idea["template"], "market": idea["market"]}
        own = templates.TEMPLATES.get(str(idea["template"]))
        if tf and (own is None or tf != own.timeframe):
            out["timeframe"] = tf  # a template on another chart is a different idea (D-118)
        return out
    rules = {
        "idea": " ".join(idea["idea"].lower().split()),
        "market": idea["market"],
        "symbols": sorted(idea["symbols"]),
    }
    if tf and tf != "1d":
        rules["timeframe"] = tf
    return rules


def fingerprint_of(idea: dict[str, Any], baselines: dict[int, Baseline]) -> str:
    b = baselines.get(idea["strategy_id"] or -1)
    version = b.version_id if b is not None and idea["kind"] != "new_strategy" else None
    return notebook.fingerprint(idea["kind"], version, rules_of(idea))


def _result(
    spec: RunSpec,
    split: int,
    baseline: dict[str, Any] | None,
    cand: dict[str, Any],
    checks: list[dict[str, Any]],
    luck_result: dict[str, Any] | None,
    study_line: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "start": spec.start_ms,
        "end": spec.end_ms,
        "split": split,
        "symbols": [i.symbol for i in spec.instruments],
        "capital": spec.capital,
        "baseline": baseline,
        "candidate": cand,
        "checks": checks,
        "luck": luck_result,
        "study_line": study_line,
        **extra,
    }


def judge_against(
    ctx: Any,
    b: Baseline,
    cand: AnyDefinition,
    kind: str,
    *,
    symbols: list[str] | None = None,
) -> tuple[bool, str, dict[str, Any], RunSpec]:
    """Run ``cand`` like the baseline ``b`` (same period, money and costs; ``symbols`` when the
    idea changes the stocks) and judge it against the baseline by the fixed rules."""
    tf = b.spec.definition.timeframe
    run_def = cand.model_copy(update={"timeframe": tf}) if cand.timeframe != tf else cand
    base_spec, base_out = b.spec, b.out
    baseline = {"study": b.study, "exam": b.exam}
    if symbols is not None:
        new_spec, _x = ctx.backtests.spec_for(
            run_def,
            BacktestRequest(
                strategy_version_id=0,
                symbols=symbols,
                start=b.spec.start_ms,
                end=b.spec.end_ms,
                capital=b.spec.capital,
            ),
        )
        base_spec = replace(new_spec, definition=b.definition)
    spec, cparts, split, out = _parts(base_spec, run_def, ctx)
    m = b.market
    tries = notebook.tries(ctx, strategy_id=b.strategy_id) + 1
    lk = change_luck(base_out, out, m, split, tries)
    cand_daily, base_daily = overfit.daily_of(out, m), overfit.daily_of(base_out, m)
    ov = overfit.collect(
        ctx,
        strategy_id=b.strategy_id,
        extra=[cand_daily],
        extra_base=(b.version_id, base_daily),
    )
    more = overfit.check(ov)
    if len(spec.instruments) > WIDE_LIST:  # a change can widen the list too (D-231)
        more.append(survivorship_check(ctx, spec, run_def, split))
    if kind == "simplify":
        held, verdict, checks = judge_simplify(baseline, cparts, m, more)
    else:
        held, verdict, checks = judge_change(baseline, cparts, b.spec.capital, m, lk, more)
    study_line = (
        f"Study years: {money(cparts['study']['net'], m)} against "
        f"{money(b.study['net'], m)} for the current version, won "
        f"{_pct(cparts['study']['win_rate'])} against {_pct(b.study['win_rate'])}."
    )
    result = _result(
        spec,
        split,
        baseline,
        cparts,
        checks,
        lk,
        study_line,
        overfit=ov,
        daily=cand_daily,
        base_daily=base_daily,
    )
    return held, verdict, result, spec


def try_change(ctx: Any, idea: dict[str, Any], b: Baseline, fp: str) -> Outcome:
    rules = rules_of(idea)
    base_out = Outcome("untestable", "", rules, fp, b.market.value, b.strategy_id, b.version_id)
    cand: AnyDefinition
    symbols: list[str] | None = None
    try:
        if idea["kind"] == "filter":
            cand = with_filter(b.definition, idea)
        elif idea["kind"] == "simplify":
            cand = with_simplify(b.definition, idea)
        elif idea["kind"] == "universe":
            symbols = new_symbols(ctx, b, idea)
            cand = b.definition.model_copy(
                update={"universe": Universe(kind="symbols", symbols=symbols)}
            )
        else:
            cand = with_changes(b.definition, idea["changes"])
        cand = _checked(cand)
        if idea["kind"] == "filter":
            extra = [_compare(c) for c in idea["conditions"]]
            found = reach_problems(ctx, b.spec, cand, extra, b.split_ms)
            if found:
                raise Untestable(" ".join(found) + " Pick a threshold inside that range.")
    except Untestable as exc:
        base_out.verdict = str(exc)
        return base_out
    except ValueError as exc:  # pydantic: a value the schema can't hold
        base_out.verdict = f"Agora couldn't use the rules: {str(exc).splitlines()[0]}"
        return base_out
    held, verdict, result, spec = judge_against(ctx, b, cand, idea["kind"], symbols=symbols)
    rules = {**rules, "definition": json.loads(cand.model_dump_json())}
    return Outcome(
        "held_up" if held else "rejected",
        verdict,
        rules,
        fp,
        b.market.value,
        b.strategy_id,
        b.version_id,
        result,
        spec,
        cand,
    )


def _symbols(ctx: Any, market: Market, wanted: list[str], timeframe: str = "1d") -> list[str]:
    """The idea's stocks, or the market's stocks that already have prices saved (on the idea's
    timeframe: minute strategies need stocks with minute history, D-118)."""
    from backend.metis import timeframes

    with ctx.db.session() as s:
        found = [i.symbol for sym in wanted if (i := store.find_instrument(s, market, sym))]
    if timeframe != "1d":
        have = set(timeframes.stocks_by_timeframe(ctx, market.value).get(timeframe, []))
        found = [x for x in found if x in have] or timeframes.stocks_for(
            ctx, market.value, timeframe, NEW_SYMBOLS
        )
        if found:
            return list(dict.fromkeys(found))[:8]
    with ctx.db.session() as s:
        if found:
            return list(dict.fromkeys(found))[:8]
        insts = [i for i in data_service.default_symbols(s, market) if not i.is_index]
        cov = store.coverage_stats(s, Timeframe.D1, [i.id for i in insts])
    with_prices = [i for i in insts if cov.get(i.id, (0, 0, 0, ""))[2] >= 250]
    return [i.symbol for i in (with_prices or insts)[:NEW_SYMBOLS]]


def _definition_for(
    ctx: Any,
    idea: dict[str, Any],
    market: Market,
    symbols: list[str],
    *,
    provider: Any,
    model: str,
    num_ctx: int,
) -> tuple[AnyDefinition, str]:
    """The new strategy's rules: a research-sprint playbook entry (D-144), finished rules
    written by Claude (D-160), a textbook template, or the AI-draft loop (D-52)."""
    if idea.get("definition"):
        raw = json.loads(json.dumps(idea["definition"]))
        raw["market"] = market.value
        if raw.get("kind") in ("visual", "kairos"):
            raw["universe"] = {"kind": "symbols", "symbols": symbols}
        res = validate(raw)
        if not res.ok or res.definition is None:
            raise Untestable(f"Agora couldn't use these rules: {res.errors[0].sentence()}")
        return res.definition, str(idea.get("why") or idea.get("title") or "")[:600]
    if idea.get("playbook"):
        from backend.lab import playbook

        entry = next((e for e in playbook.load() if e["key"] == idea["playbook"]), None)
        if entry is None:
            raise Untestable(f"The playbook has no entry “{idea['playbook']}” any more.")
        raw = json.loads(json.dumps(entry["definition"]))
        if raw.get("kind") == "visual":
            raw["universe"] = {"kind": "symbols", "symbols": symbols}
        res = validate(raw)
        if not res.ok or res.definition is None:
            raise Untestable(f"Agora couldn't use the playbook's rules: {res.errors[0].sentence()}")
        return res.definition, f"{entry['name']}: {entry['why']}"[:600]
    if idea.get("template"):
        key = str(idea["template"])
        if key not in templates.TEMPLATES:
            raise Untestable(f"Agora has no starter strategy called “{key}”.")
        tf = idea.get("timeframe") or templates.TEMPLATES[key].timeframe
        d: AnyDefinition = templates.template_definition(key, market.value, symbols, tf)
        return d, templates.TEMPLATES[key].description
    if len(idea["idea"]) < 10:
        raise Untestable("The idea didn't describe the strategy's rules.")
    if provider is None:
        raise Untestable("Turning an idea into rules needs the AI helper.")
    drafted = draft(provider, model=model, idea=idea["idea"], market=market.value, num_ctx=num_ctx)
    if not drafted.ok or drafted.definition is None:
        first = drafted.issues[0].sentence() if drafted.issues else "no rules came back"
        raise Untestable(f"Agora couldn't turn the idea into rules: {first}")
    raw = dict(drafted.definition)
    raw["universe"] = {"kind": "symbols", "symbols": symbols}
    tf = idea.get("timeframe")
    drafted_tf = raw.get("timeframe", "1d")
    if tf == "1d" and drafted_tf != "1d":
        tf = drafted_tf  # the draft moved a VWAP idea to intraday candles (D-123)
    if tf in ("1d", "1h", "15m", "5m", "1m"):  # the timeframe Metis chose (D-118)
        raw["timeframe"] = tf
        if market.value == "IN":
            raw["product"] = "intraday" if tf in templates.SHORT_TERM else "delivery"
    res = validate(raw)
    if not res.ok or res.definition is None:
        raise Untestable(f"Agora couldn't use the rules: {res.errors[0].sentence()}")
    d = res.definition
    if isinstance(d, VisualDefinition):
        d = d.model_copy(update={"universe": Universe(kind="symbols", symbols=symbols)})
    return d, drafted.explanation[:600]


def _wider_than(ctx: Any, symbols: list[str], strategy_id: int) -> bool:
    """A wide idea isn't a revision of the same rules on a few stocks (D-232): judged as one it ran
    on that strategy's stocks, so India's RSI(2) "on 250" really ran on two."""
    if len(symbols) <= WIDE_LIST:
        return False
    with ctx.db.session() as s:
        version = strategies.latest_version(s, strategy_id)
    if version is None or version.definition.universe.kind != "symbols":
        return False
    return len(version.definition.universe.symbols) <= WIDE_LIST


def _as_revision(ctx: Any, idea: dict[str, Any], d: AnyDefinition, found: Any, fp: str) -> Outcome:
    """A "new" strategy that is really one the user has (D-79): judged against that
    strategy's current version, on its own stocks and period."""
    market = Market(d.market)
    head = (
        f"Not a new strategy: it is a version of “{found.name}” (#{found.strategy_id}), "
        f"{found.why}. "
    )
    out = Outcome(
        "untestable", "", rules_of(idea), fp, market.value, found.strategy_id, found.version_id
    )
    fb = brief_mod.baseline(ctx, found.strategy_id)
    if fb is None:
        out.verdict = head + "That strategy couldn't be run, so nothing was tested."
        return out
    cand = d.model_copy(
        update={"universe": fb.definition.universe, "timeframe": fb.definition.timeframe}
    )
    if content_hash(cand) == content_hash(fb.definition):
        out.status = "rejected"
        out.verdict = (
            head + "With its stocks it is exactly that strategy, so there's nothing new to keep."
        )
        return out
    held, verdict, result, spec = judge_against(ctx, fb, cand, "tweak")
    result["family"] = {
        "strategy_id": found.strategy_id,
        "name": found.name,
        "version_id": fb.version_id,
        "why": found.why,
    }
    out.status = "held_up" if held else "rejected"
    out.verdict = head + "Judged against its current version: " + verdict
    out.version_id = fb.version_id
    out.result = result
    out.rules = {**out.rules, "definition": json.loads(cand.model_dump_json())}
    out.spec, out.definition = spec, cand
    return out


def _dead_entries(ctx: Any, spec: RunSpec, d: AnyDefinition) -> list[str]:
    """For a visual strategy: the reasons when *every* side it trades has a must-hold
    condition that was never true in the study years (D-142)."""
    if not isinstance(d, VisualDefinition):
        return []
    split = spec.start_ms + int((spec.end_ms - spec.start_ms) * STUDY_SHARE)
    reasons: list[str] = []
    sides = [r for r in (d.entry.long, d.entry.short) if r is not None]
    if not sides:
        return []
    for rule in sides:
        compares = list(precheck.leaves(rule))
        found = [p for p in reach_problems(ctx, spec, d, compares, split) if "never true" in p]
        if not found:
            return []  # this side can trade
        reasons += found
    return reasons


def playbook_tries(ctx: Any, market: str) -> int:
    """The luck check's N for a research sprint's playbook entry (D-151): it was chosen from
    the market's playbook (and the sprint's own luck check already covered its family's
    grid), not from every idea the model ever wrote, so it is one of the market's entries,
    or of the entries Metis has re-tested so far if that is more."""
    from backend.lab import playbook

    entries = sum(1 for e in playbook.load() if e.get("market") == market)
    return max(entries, notebook.playbook_tries(ctx, market) + 1, 1)


def try_new(
    ctx: Any,
    idea: dict[str, Any],
    fp: str,
    *,
    provider: Any,
    model: str,
    num_ctx: int,
    markets: list[str],
) -> Outcome:
    market = Market(idea["market"] or (markets[0] if markets else "IN"))
    rules = rules_of(idea)
    out = Outcome("untestable", "", rules, fp, market.value)
    symbols = _symbols(ctx, market, idea["symbols"], idea.get("timeframe") or "1d")
    given = idea.get("definition") or {}
    if given.get("kind") in ("ranking", "visual") and (given.get("universe") or {}).get("symbols"):
        # finished rules keep the stocks they name, not the first eight (D-160): a wide idea cut
        # to eight stocks was titled "250" and tested on 8, too few trades to judge (D-230)
        symbols = list(given["universe"]["symbols"])
    try:
        d, explanation = _definition_for(
            ctx, idea, market, symbols, provider=provider, model=model, num_ctx=num_ctx
        )
    except Untestable as exc:
        out.verdict = str(exc)
        return out
    with ctx.db.session() as s:
        found = revisions.match(s, d, template_key=idea.get("template"))
    if found is not None and not _wider_than(ctx, symbols, found.strategy_id):
        return _as_revision(ctx, idea, d, found, fp)
    spec, _extra = ctx.backtests.spec_for(
        d, BacktestRequest(strategy_version_id=0, symbols=symbols)
    )
    dead = _dead_entries(ctx, spec, d)
    if dead:
        out.verdict = (
            "Its entry rule could never be met, so it would never trade: "
            + " ".join(dead)
            + " Pick a threshold inside that range."
        )
        out.rules = {**rules, "definition": json.loads(d.model_dump_json())}
        return out
    try:
        spec, cparts, split, run_out = _parts(spec, d, ctx)
    except NoData as exc:
        out.verdict = f"Couldn't test it: {exc} Agora downloads prices as you use the stocks."
        return out
    tries = (
        playbook_tries(ctx, market.value)
        if rules.get("playbook")
        else overfit.effective_tries(
            ctx, market.value, notebook.tries(ctx, market=market.value, kind="new_strategy")
        )
        + 1
    )
    lk = luck(stats.daily_returns(run_out.equity, MARKET_TZ[market], lo=split), tries)
    new_daily = overfit.daily_of(run_out, market)
    ov = overfit.collect(ctx, market=market.value, kind="new_strategy", extra=[new_daily])
    index = against_index(run_out, split, market)
    more = [*overfit.check(ov), index]
    if len(spec.instruments) > WIDE_LIST:
        more.append(survivorship_check(ctx, spec, d, split))
    held, verdict, checks = judge_new(cparts, market, lk, more)
    if held and len(spec.instruments) > WIDE_LIST:  # the honest figure, not today's list's
        verdict = f"{verdict} {more[-1]['text']}"
    out.status = "held_up" if held else "rejected"
    out.verdict = verdict
    out.result = _result(
        spec,
        split,
        None,
        cparts,
        checks,
        lk,
        f"Study years: {cparts['study']['trades']} trades, won "
        f"{_pct(cparts['study']['win_rate'])}, made {money(cparts['study']['net'], market)}.",
        drafted=explanation,
        overfit=ov,
        daily=new_daily,
    )
    out.rules = {**rules, "definition": json.loads(d.model_dump_json())}
    out.spec, out.definition = spec, d
    return out
