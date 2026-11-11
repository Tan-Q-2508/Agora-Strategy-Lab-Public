"""The trade autopsy: why did good rules make bad trades? (METIS §18, D-109)

The user's request (2026-10-24): Metis and Kairos must keep improving the strategies, first by
analysing what went wrong. A moving-average cross, for example, fires false alarms that a
volume reading, a bigger chart or the market's mood would have warned about. Try different
strategies on the same stock and see which trades were good in all of them, which were mixed
and which none of them took. Read several timeframes to find the bad trades. Make it broad and
self-learning, not a fixed list of examples.

So, for every strategy Metis studies, code opens up each closed trade of the **study years**
(the exam years stay unseen, METIS §3) and records, on the candle the signal came from:

1. **Its own chart**: about twenty readings from the indicator catalog covering trend
   strength, momentum, volume and money flow, volatility, stretch, the candle's shape and where
   price sits in its range. Not only the ten of the trade check: anything that can become an
   ordinary strategy rule.
2. **The bigger charts** (weekly and monthly for a daily strategy, daily for an hourly one…):
   trend, momentum and stretch on the last *finished* bigger candle, read exactly as a rule
   with ``chart`` reads it (D-97).
3. **The market**: the benchmark's trend and its last few candles. Rules can't read another
   stock, so this is evidence for the AI and for the user, not a filter.
4. **Second opinions**: up to three of the user's other strategies on the same stocks and
   timeframe, run over the study years. Each trade is labelled: another strategy agreed (was
   in the same trade) and both won, everyone lost (the market turned against everybody: news
   or the market's mood, not the rules), only this strategy took it, and so on.

Then it searches for the condition that separates the losers from the winners. Each candidate
("skip trades when relative volume is under 0.9×") is chosen on the first 60% of the study
trades and must keep its promise on the last 40% it never saw (more money after costs, a
higher win rate, at least a third of the trades kept), the way Kairos's review does (D-72).
The best ones become ready-to-test filter ideas; the strongest two together become a
combined idea, so a strategy can keep adding what it learns. Every idea then goes through
Metis's normal test on the exam years, with the luck and overfitting checks (METIS §4, §12,
§16): the autopsy proposes, it never decides.

**Self-learning.** Every autopsy idea carries the name of its reading (``probe``). Metis
counts, over its whole notebook, how often ideas from each kind of reading held up, and ranks
the next autopsy's candidates by that record (a Beta average, like the research agenda), so
the readings that keep working on this user's strategies are tried first and the ones that
never hold up fade. A reading already tried on a strategy version isn't tried again on it.
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select

from backend.analysis import mtf
from backend.backtest.manager import BacktestRequest
from backend.backtest.run import run
from backend.core.types import MARKET_TZ, Market
from backend.data import service as data_service
from backend.data import store
from backend.db.models import MetisIdea, Strategy
from backend.engine.types import Trade
from backend.indicators import catalog
from backend.indicators.series import BarSeries
from backend.kairos.coach import Coach
from backend.logging_setup import get_logger
from backend.metrics.summary import money
from backend.strategy import service as strategies
from backend.strategy.definition import VisualDefinition

log = get_logger("metis.autopsy")

MIN_TRADES = 20  # study trades of one side needed before searching
TRAIN_SHARE = 0.6
QUANTILES = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
MAX_SEEDS = 3
MAX_OTHERS = 3
CACHE_SIZE = 24


@dataclass(frozen=True)
class Probe:
    """One reading at the signal candle. ``chart`` reads a bigger chart of the same stock."""

    indicator: str
    output: str | None
    label: str
    family: str  # trend | momentum | volume | volatility | stretch | candle | range
    chart: str | None = None
    params: tuple[tuple[str, float], ...] = ()

    @property
    def key(self) -> str:
        p = ",".join(f"{v:g}" for _, v in self.params)
        head = f"{self.indicator}{f'({p})' if p else ''}{'.' + self.output if self.output else ''}"
        return f"{self.chart}:{head}" if self.chart else head

    def words(self) -> str:
        return f"{self.label} on the {mtf.LABEL[self.chart]} chart" if self.chart else self.label

    def param_dict(self) -> dict[str, float]:
        if self.params:
            return {k: float(v) for k, v in self.params}
        ind = catalog.INDICATORS[self.indicator]
        return {p.name: float(p.default) for p in ind.params}


# The chart the strategy trades on: broad on purpose (the user: "any other indicator").
OWN: tuple[Probe, ...] = (
    Probe("adx", "adx", "trend strength (ADX)", "trend"),
    Probe("chop", None, "choppiness", "trend"),
    Probe("aroon", "oscillator", "Aroon oscillator", "trend"),
    Probe(
        "disparity",
        None,
        "distance from the 50-candle average %",
        "trend",
        params=(("period", 50),),
    ),
    Probe(
        "disparity",
        None,
        "distance from the 200-candle average %",
        "trend",
        params=(("period", 200),),
    ),
    Probe("rsi", None, "RSI", "momentum"),
    Probe("macd", "histogram", "MACD histogram", "momentum"),
    Probe("roc", None, "rate of change %", "momentum"),
    Probe("mfi", None, "money flow index", "volume"),
    Probe("cmf", None, "Chaikin money flow", "volume"),
    Probe("rvol", None, "relative volume", "volume"),
    Probe("pvo", "histogram", "volume oscillator", "volume"),
    Probe("natr", None, "volatility (ATR %)", "volatility"),
    Probe("bollinger_pct", "bandwidth", "Bollinger bandwidth (squeeze)", "volatility"),
    Probe("zscore", None, "stretch from the 20-candle average (z-score)", "stretch"),
    Probe("bollinger_pct", "pct_b", "place in the Bollinger bands (%B)", "stretch"),
    Probe("stochastic", "k", "place in the recent range (stochastic %K)", "range"),
    Probe("williams_r", None, "Williams %R", "range"),
    Probe("bop", None, "candle strength (balance of power)", "candle"),
)
# The bigger charts: direction and stretch, the classic false-alarm filters (Elder, Murphy).
BIG: tuple[tuple[str, str | None, str, str, tuple[tuple[str, float], ...]], ...] = (
    ("rsi", None, "RSI", "momentum", ()),
    ("adx", "adx", "trend strength (ADX)", "trend", ()),
    ("disparity", None, "distance from the 20-candle average %", "trend", (("period", 20),)),
    ("macd", "histogram", "MACD histogram", "momentum", ()),
    ("roc", None, "rate of change %", "momentum", ()),
    ("rvol", None, "relative volume", "volume", ()),
)


def probes_for(timeframe: str) -> list[Probe]:
    out = list(OWN)
    for chart in mtf.BIGGER.get(timeframe, ()):  # every bigger chart (D-132)
        out += [Probe(i, o, label, fam, chart, p) for i, o, label, fam, p in BIG]
    return out


# ---------------------------------------------------------------- the readings


def _line(series: BarSeries, p: Probe, frames: dict[str, mtf.Frame], zone: ZoneInfo) -> np.ndarray:
    params = p.param_dict()
    if p.chart:
        frame = frames.get(p.chart)
        if frame is None:
            frame = frames[p.chart] = mtf.Frame.build(series, p.chart, zone)
        out = catalog.compute(p.indicator, frame.series, params)
        arr = out[p.output] if p.output else next(iter(out.values()))
        return frame.line(p.key, np.asarray(arr, dtype=np.float64))
    out = catalog.compute(p.indicator, series, params)
    arr = out[p.output] if p.output else next(iter(out.values()))
    return np.asarray(arr, dtype=np.float64)


@dataclass
class Row:
    trade: Trade
    values: dict[str, float] = field(default_factory=dict)
    agree: dict[int, bool] = field(default_factory=dict)  # other strategy id → was in it too
    agree_won: dict[int, bool] = field(default_factory=dict)
    market: dict[str, float] = field(default_factory=dict)

    @property
    def won(self) -> bool:
        return self.trade.net_pnl > 0


def readings(
    trades: Sequence[Trade],
    series: dict[str, BarSeries],
    probes: Sequence[Probe],
    zone: ZoneInfo,
) -> list[Row]:
    """Each trade's readings on its signal candle (the candle before the entry)."""
    lines: dict[str, dict[str, np.ndarray]] = {}
    rows = []
    for t in trades:
        row = Row(t)
        s = series.get(t.symbol)
        if s is not None and len(s):
            if t.symbol not in lines:
                frames: dict[str, mtf.Frame] = {}
                got: dict[str, np.ndarray] = {}
                for p in probes:
                    try:
                        got[p.key] = _line(s, p, frames, zone)
                    except Exception:  # a reading that can't run on this stock isn't used
                        continue
                lines[t.symbol] = got
            i = int(np.searchsorted(s.ts, t.entry_ts)) - 1
            for k, arr in lines[t.symbol].items():
                if 0 <= i < len(arr) and math.isfinite(float(arr[i])):
                    row.values[k] = float(arr[i])
        rows.append(row)
    return rows


# ---------------------------------------------------------------- the search


@dataclass
class Rule:
    probe: Probe
    side: str
    keep: str  # at_least | at_most
    value: float
    train_gain: float
    val_gain: float
    kept_rate: float
    all_rate: float
    kept: int
    total: int
    bad_rate: float  # win rate of the trades it skips
    bad: int
    score: float = 0.0

    def condition(self) -> dict[str, Any]:
        c: dict[str, Any] = {
            "indicator": self.probe.indicator,
            "params": self.probe.param_dict(),
            "output": self.probe.output,
            "op": self.keep,
            "value": self.value,
            "probe": self.probe.key,
        }
        if self.probe.chart:
            c["chart"] = self.probe.chart
        return c

    def text(self) -> str:
        word = "under" if self.keep == "at_least" else "over"
        return (
            f"{self.side.capitalize()} trades taken when the {self.probe.words()} was {word} "
            f"{_num(self.value)} won {self.bad_rate * 100:.0f}% of {self.bad}; the rest won "
            f"{self.kept_rate * 100:.0f}%."
        )


def _num(v: float) -> str:
    return f"{v:.3g}" if abs(v) < 1000 else f"{v:,.0f}"


def _nice(v: float) -> float:
    """Round a threshold to 2–3 significant figures: tiny shifts as new candles arrive must not
    turn an idea already tested into a "new" one."""
    if v == 0 or not math.isfinite(v):
        return 0.0
    digits = 2 - math.floor(math.log10(abs(v)))
    return round(v, max(digits, -3))


def _gain(rows: Sequence[Row], keep: np.ndarray) -> float:
    return -sum(r.trade.net_pnl for r, k in zip(rows, keep, strict=True) if not k)


def _rate(rows: Sequence[Row]) -> float:
    return sum(1 for r in rows if r.won) / len(rows) if rows else 0.0


def search(rows: Sequence[Row], probe: Probe, side: str) -> Rule | None:
    """The best "skip these trades" threshold on the first 60%, kept only if it holds on the
    last 40%."""
    have = [r for r in rows if probe.key in r.values]
    if len(have) < MIN_TRADES:
        return None
    have.sort(key=lambda r: r.trade.entry_ts)
    cut = int(len(have) * TRAIN_SHARE)
    train, val = have[:cut], have[cut:]
    tv = np.array([r.values[probe.key] for r in train])
    vv = np.array([r.values[probe.key] for r in val])
    best: tuple[float, str, float] | None = None
    for q in QUANTILES:
        t = _nice(float(np.quantile(tv, q)))
        for keep in ("at_least", "at_most"):
            k = tv >= t if keep == "at_least" else tv <= t
            if k.sum() < max(5, 0.4 * len(train)) or k.all():
                continue
            g = _gain(train, k)
            if g > 0 and (best is None or g > best[0]):
                best = (g, keep, t)
    if best is None:
        return None
    g, keep, t = best
    kv = vv >= t if keep == "at_least" else vv <= t
    kept = [r for r, k in zip(val, kv, strict=True) if k]
    skipped = [r for r, k in zip(val, kv, strict=True) if not k]
    vg = _gain(val, kv)
    if len(kept) < max(3, len(val) / 3) or not skipped or vg <= 0:
        return None
    if _rate(kept) < _rate(val) + 0.02:
        return None
    ka = np.array([r.values[probe.key] for r in have])
    k_all = ka >= t if keep == "at_least" else ka <= t
    bad = [r for r, k in zip(have, k_all, strict=True) if not k]
    good = [r for r, k in zip(have, k_all, strict=True) if k]
    return Rule(
        probe,
        side,
        keep,
        t,
        g,
        vg,
        _rate(good),
        _rate(have),
        len(good),
        len(have),
        _rate(bad),
        len(bad),
    )


# ---------------------------------------------------------------- second opinions


def _others(ctx: Any, b: Any) -> list[tuple[int, str, int, Any]]:
    """(strategy id, name, version id, definition) of up to three other strategies on the same
    market and timeframe: the most recently changed first, of a different style first."""
    from backend.metis.diagnose import style

    mine = style(b.definition)
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Strategy)
            .where(
                Strategy.archived_at.is_(None),
                Strategy.kind.in_(("visual", "code")),
                Strategy.id != b.strategy_id,
            )
            .order_by(Strategy.updated_at.desc())
            .limit(60)
        ).all()
        found = []
        for r in rows:
            v = strategies.latest_version(s, r.id)
            if v is None:
                continue
            d = v.definition
            if d.market != b.definition.market or d.timeframe != b.definition.timeframe:
                continue
            found.append((style(d) == mine, r.id, r.name, v.id, d))
    found.sort(key=lambda x: x[0])  # a different style first: a real second opinion
    return [(sid, name, vid, d) for _same, sid, name, vid, d in found[:MAX_OTHERS]]


def second_opinions(ctx: Any, b: Any, rows: list[Row]) -> list[dict[str, Any]]:
    """Run the other strategies on the same stocks over the study years and label each trade."""
    out = []
    syms = [i.symbol for i in b.spec.instruments]
    for sid, name, vid, d in _others(ctx, b):
        try:
            req = BacktestRequest(
                strategy_version_id=vid,
                symbols=syms,
                timeframe=b.spec.timeframe.value,
                start=b.spec.start_ms,
                end=b.split_ms,
                capital=b.spec.capital,
            )
            spec, _ = ctx.backtests.spec_for(d, req)
            theirs = [t for t in run(ctx.cache, spec).trades if t.closed]
        except Exception as exc:  # one strategy that can't run mustn't stop the autopsy
            log.info("Second opinion from strategy %s didn't run: %r", sid, exc)
            continue
        by_sym: dict[tuple[str, str], list[Trade]] = {}
        for t in theirs:
            by_sym.setdefault((t.symbol, str(t.side)), []).append(t)
        for r in rows:
            hit = next(
                (
                    o
                    for o in by_sym.get((r.trade.symbol, str(r.trade.side)), [])
                    if o.entry_ts <= r.trade.entry_ts < o.exit_ts
                    or abs(o.entry_ts - r.trade.entry_ts) <= 3 * 86_400_000
                ),
                None,
            )
            r.agree[sid] = hit is not None
            if hit is not None:
                r.agree_won[sid] = hit.net_pnl > 0
        out.append({"strategy_id": sid, "name": name, "definition": d, "trades": len(theirs)})
    return out


def opinion_lines(rows: Sequence[Row], others: Sequence[dict[str, Any]]) -> list[str]:
    if not others or not rows:
        return []
    ids = [o["strategy_id"] for o in others]
    both_won = sum(1 for r in rows if r.won and any(r.agree_won.get(i) for i in ids))
    all_lost = sum(
        1
        for r in rows
        if not r.won
        and any(r.agree.get(i) for i in ids)
        and not any(r.agree_won.get(i) for i in ids)
    )
    alone = [r for r in rows if not any(r.agree.get(i) for i in ids)]
    joined = [r for r in rows if any(r.agree.get(i) for i in ids)]
    lost_alone = sum(1 for r in alone if not r.won)
    names = ", ".join(f"“{o['name']}”" for o in others)
    lines = [
        f"Second opinions from {names} on the same stocks (study years): of {len(rows)} trades, "
        f"{both_won} were good for this strategy and another one too; {all_lost} lost for every "
        f"strategy that took them (the market turned against everyone: news or the market's "
        f"mood, not the rules); {len(alone)} were taken by this strategy alone, and "
        f"{lost_alone} of those lost (losses only these rules made)."
    ]
    if alone and joined:
        lines.append(
            f"Win rate when another strategy agreed: {_rate(joined) * 100:.0f}% of {len(joined)}; "
            f"alone: {_rate(alone) * 100:.0f}% of {len(alone)}."
        )
    return lines


def _as_filter(part: dict[str, Any]) -> dict[str, Any] | None:
    """A state condition of another strategy ("RSI (14) above 50") as an idea condition; crosses
    are moments, not states, and are left out."""
    if part.get("type") != "compare" or part.get("op") not in (
        "above",
        "below",
        "at_least",
        "at_most",
    ):
        return None
    left, right, op = part["left"], part["right"], part["op"]
    flip = {"above": "below", "below": "above", "at_least": "at_most", "at_most": "at_least"}
    if left.get("kind") == "price" and right.get("kind") == "indicator":
        left, right, op = right, left, flip[op]
    if left.get("kind") != "indicator" or left.get("offset") or left.get("source"):
        return None
    c: dict[str, Any] = {
        "indicator": left["name"],
        "params": {k: float(v) for k, v in (left.get("params") or {}).items()},
        "output": left.get("output"),
        "op": op,
    }
    if left.get("chart"):
        c["chart"] = left["chart"]
    if right.get("kind") == "number":
        c["value"] = float(right["value"])
    elif right.get("kind") == "price" and not right.get("offset") and right.get("times", 1) == 1:
        if right.get("chart") != left.get("chart"):
            return None
        c["price"], c["value"] = right.get("field", "close"), None
    else:
        return None
    return c


def agreement_rule(
    rows: Sequence[Row], other: dict[str, Any], side: str
) -> tuple[Rule, list[dict[str, Any]]] | None:
    """ "Only when the other strategy agrees", chosen and checked like any reading, written as
    that strategy's own state conditions."""
    from backend.metis.diagnose import entry_parts

    sid = other["strategy_id"]
    d = other["definition"]
    if not isinstance(d, VisualDefinition):
        return None
    conds = [c for c in (_as_filter(p) for p in entry_parts(d, side)) if c][:2]
    if not conds:
        return None
    probe = Probe(f"agree#{sid}", None, f"agreement of “{other['name']}”", "opinion")
    for r in rows:
        if sid in r.agree:
            r.values[probe.key] = 1.0 if r.agree[sid] else 0.0
    have = sorted((r for r in rows if probe.key in r.values), key=lambda r: r.trade.entry_ts)
    if len(have) < MIN_TRADES:
        return None
    cut = int(len(have) * TRAIN_SHARE)
    train, val = have[:cut], have[cut:]
    k_t = np.array([r.values[probe.key] > 0 for r in train])
    k_v = np.array([r.values[probe.key] > 0 for r in val])
    if k_t.sum() < 5 or k_v.sum() < max(3, len(val) / 3) or k_v.all():
        return None
    g, vg = _gain(train, k_t), _gain(val, k_v)
    kept = [r for r, k in zip(val, k_v, strict=True) if k]
    if g <= 0 or vg <= 0 or _rate(kept) < _rate(val) + 0.02:
        return None
    good = [r for r in have if r.values[probe.key] > 0]
    bad = [r for r in have if r.values[probe.key] <= 0]
    for c in conds:
        c["probe"] = f"agree:{c['indicator']}"
    return Rule(
        probe,
        side,
        "at_least",
        1.0,
        g,
        vg,
        _rate(good),
        _rate(have),
        len(good),
        len(have),
        _rate(bad),
        len(bad),
    ), conds


# ---------------------------------------------------------------- the market's mood


def market_lines(ctx: Any, b: Any, rows: Sequence[Row]) -> list[str]:
    """How trades did by the benchmark's trend at entry (evidence only: rules read one stock)."""
    m = Market(b.definition.market)
    with ctx.db.session() as s:
        bench = store.find_instrument(s, m, data_service.BENCHMARK[m])
    if bench is None:
        return []
    got = Coach(ctx)._series({bench.symbol: bench}, b.spec.timeframe, b.spec.start_ms, b.split_ms)
    ser = got.get(bench.symbol)
    if ser is None or len(ser) < 60:
        return []
    above = catalog.compute("disparity", ser, {"period": 50.0})["value"]
    for r in rows:
        i = int(np.searchsorted(ser.ts, r.trade.entry_ts)) - 1
        if 0 <= i < len(above) and math.isfinite(float(above[i])):
            r.market["bench_trend"] = float(above[i])
    up = [r for r in rows if r.market.get("bench_trend", 0) > 0]
    down = [r for r in rows if "bench_trend" in r.market and r.market["bench_trend"] <= 0]
    if len(up) < 5 or len(down) < 5:
        return []
    return [
        f"The market's mood ({bench.symbol} against its 50-candle average) at entry: trades "
        f"taken while it was above won {_rate(up) * 100:.0f}% of {len(up)} "
        f"({money(sum(r.trade.net_pnl for r in up), m)}); while it was below, "
        f"{_rate(down) * 100:.0f}% of {len(down)} ({money(sum(r.trade.net_pnl for r in down), m)})."
    ]


# ---------------------------------------------------------------- self-learning


def record(ctx: Any, limit: int = 800) -> dict[str, tuple[int, int]]:
    """For each reading (``probe``), autopsy ideas tested and held up, over the notebook."""
    out: dict[str, list[int]] = {}
    with ctx.db.session() as s:
        rows = s.execute(
            select(MetisIdea.spec, MetisIdea.status)
            .where(MetisIdea.kind == "filter")
            .order_by(MetisIdea.id.desc())
            .limit(limit)
        ).all()
    for spec, status in rows:
        try:
            conds = json.loads(spec or "{}").get("conditions") or []
        except ValueError:
            continue
        for c in conds:
            key = c.get("probe") if isinstance(c, dict) else None
            if not key or status == "untestable":
                continue
            tally = out.setdefault(_family_key(key), [0, 0])
            tally[0] += 1
            tally[1] += int(status in ("held_up", "saved"))
    return {k: (v[0], v[1]) for k, v in out.items()}


def _family_key(probe_key: str) -> str:
    """A reading without its settings ("1w:rsi", "rvol"): what is learned about."""
    chart, _, rest = probe_key.rpartition(":")
    name = rest.split("(")[0].split(".")[0]
    return f"{chart}:{name}" if chart else name


def tried_on(ctx: Any, version_id: int) -> set[str]:
    with ctx.db.session() as s:
        specs = s.scalars(
            select(MetisIdea.spec).where(
                MetisIdea.kind == "filter", MetisIdea.strategy_version_id == version_id
            )
        ).all()
    out = set()
    for spec in specs:
        try:
            for c in json.loads(spec or "{}").get("conditions") or []:
                if isinstance(c, dict) and c.get("probe"):
                    out.add(str(c["probe"]))
        except ValueError:
            continue
    return out


def learned_lines(rec: dict[str, tuple[int, int]]) -> list[str]:
    good = sorted(
        ((k, n, h) for k, (n, h) in rec.items() if n >= 2),
        key=lambda x: -(x[2] + 1) / (x[1] + 2),
    )
    if not good:
        return []
    best = ", ".join(f"{k} ({h} of {n})" for k, n, h in good[:4])
    worst = [f"{k} (0 of {n})" for k, n, h in good if h == 0 and n >= 3][:3]
    line = f"What past autopsies taught (filters that held up, by reading): {best}."
    if worst:
        line += " Rarely useful so far: " + ", ".join(worst) + "."
    return [line]


# ---------------------------------------------------------------- one strategy


@dataclass
class Autopsy:
    lines: list[str]
    seeds: list[dict[str, Any]]
    rules: list[dict[str, Any]] = field(default_factory=list)


_cache: dict[tuple[Any, ...], Autopsy] = {}
_lock = threading.Lock()


def _seed(sid: int, title: str, why: str, conds: list[dict[str, Any]], side: str) -> dict[str, Any]:
    from backend.metis.diagnose import _seed as make

    return make("filter", sid, title[:120], why, conditions=conds, side=side, origin="playbook")


def run_autopsy(ctx: Any, b: Any) -> Autopsy | None:
    """The autopsy of one baseline's study-year trades (cached per version and period: Metis
    works every minute and the evidence only changes with new candles)."""
    others_key = tuple(o[2] for o in _others(ctx, b))
    key = (
        b.version_id,
        b.spec.start_ms // 86_400_000,
        b.split_ms // 86_400_000,
        others_key,
        tuple(i.id for i in b.spec.instruments),
    )
    with _lock:
        hit = _cache.get(key)
    if hit is None:
        hit = _run(ctx, b)
        if hit is None:
            return None
        with _lock:
            if len(_cache) >= CACHE_SIZE:
                _cache.pop(next(iter(_cache)))
            _cache[key] = hit
    # ranking uses the notebook as it is now: it learns between rounds even when cached
    return _ranked(ctx, b, hit)


def _run(ctx: Any, b: Any) -> Autopsy | None:
    trades = [t for t in b.out.trades if t.closed and t.exit_ts < b.split_ms]
    if len(trades) < MIN_TRADES:
        return None
    m = Market(b.definition.market)
    zone = ZoneInfo(MARKET_TZ[m])
    series = Coach(ctx)._series(
        {i.symbol: i for i in b.spec.instruments}, b.spec.timeframe, b.spec.start_ms, b.split_ms
    )
    probes = probes_for(b.definition.timeframe)
    rows = readings(trades, series, probes, zone)
    lines: list[str] = []
    found: list[Rule] = []
    agreements: list[tuple[Rule, list[dict[str, Any]], dict[str, Any]]] = []
    others = []
    try:
        others = second_opinions(ctx, b, rows)
    except Exception:
        log.exception("Metis couldn't get second opinions for strategy %s", b.strategy_id)
    for side in ("long", "short"):
        mine = [r for r in rows if str(r.trade.side) == side]
        if len(mine) < MIN_TRADES:
            continue
        for p in probes:
            rule = search(mine, p, side)
            if rule is not None:
                found.append(rule)
        for o in others:
            got = agreement_rule(mine, o, side)
            if got is not None:
                agreements.append((got[0], got[1], o))
    lines += opinion_lines(rows, others)
    try:
        lines += market_lines(ctx, b, rows)
    except Exception:
        log.exception("Metis couldn't read the market's mood for strategy %s", b.strategy_id)
    losers = [r for r in rows if not r.won]
    lines.insert(
        0,
        f"Trade autopsy of {len(rows)} study-year trades ({len(losers)} lost): each trade's "
        f"readings on its signal candle, on its own chart and the bigger ones"
        f"{', and second opinions from other strategies' if others else ''}. Each pattern below "
        "was found on the earlier study trades and held on the later ones.",
    )
    rules = [
        {
            "probe": r.probe.key,
            "family": r.probe.family,
            "words": r.probe.words(),
            "side": r.side,
            "keep": r.keep,
            "value": r.value,
            "text": r.text(),
            "val_gain": round(r.val_gain, 2),
            "condition": r.condition(),
        }
        for r in sorted(found, key=lambda r: -r.val_gain)[:12]
    ]
    for rule, conds, o in agreements:
        rules.append(
            {
                "probe": rule.probe.key,
                "family": "opinion",
                "side": rule.side,
                "keep": "agree",
                "value": 1.0,
                "text": (
                    f"{rule.side.capitalize()} trades “{o['name']}” didn't agree with won "
                    f"{rule.bad_rate * 100:.0f}% of {rule.bad}; with its agreement "
                    f"{rule.kept_rate * 100:.0f}% of {rule.kept}."
                ),
                "val_gain": round(rule.val_gain, 2),
                "conditions": conds,
                "other": o["name"],
            }
        )
    return Autopsy(lines=lines, seeds=[], rules=rules)


def _ranked(ctx: Any, b: Any, a: Autopsy) -> Autopsy:
    rec = record(ctx)
    done = tried_on(ctx, b.version_id)
    scored = []
    for r in a.rules:
        conds = r.get("conditions") or [r["condition"]]
        if any(c.get("probe") in done for c in conds):
            continue
        n, h = rec.get(_family_key(str(conds[0].get("probe", r["probe"]))), (0, 0))
        trust = (h + 1) / (n + 2)  # Beta(1, 1) average: untried readings start at a half
        scored.append((r["val_gain"] * (0.5 + trust), r, conds))
    scored.sort(key=lambda x: -x[0])
    seeds = []
    m = Market(b.definition.market)
    for _s, r, conds in scored[:MAX_SEEDS]:
        if r["family"] == "opinion":
            title = f"Only when “{r['other']}” agrees"
        else:
            word = "at least" if r["keep"] == "at_least" else "at most"
            title = f"Only trade when the {r['words']} is {word} {_num(r['value'])}"
        seeds.append(
            _seed(
                b.strategy_id,
                title,
                f"Trade autopsy (study years): {r['text']} Skipping them added "
                f"{money(r['val_gain'], m)} on the later study trades.",
                [dict(c) for c in conds],
                r["side"],
            )
        )
    plain = [r for _s, r, _c in scored if r["family"] != "opinion"]
    if (
        len(plain) >= 2
        and plain[0]["family"] != plain[1]["family"]
        and plain[0]["side"] == plain[1]["side"]
    ):
        both = [dict(plain[0]["condition"]), dict(plain[1]["condition"])]
        seeds.append(
            _seed(
                b.strategy_id,
                "Both autopsy filters together",
                f"Trade autopsy (study years): {plain[0]['text']} And: {plain[1]['text']}",
                both,
                plain[0]["side"],
            )
        )
    lines = list(a.lines)
    tops = [r["text"] for _s, r, _c in scored[:4]]
    if tops:
        lines.append("What separated its losers from its winners: " + " ".join(tops))
    elif a.rules:
        lines.append("The autopsy's filters were all tried on this version already.")
    else:
        lines.append(
            "No single reading separated the losers from the winners in a way that held up "
            "on the later study trades."
        )
    lines += learned_lines(rec)
    return Autopsy(lines=lines, seeds=seeds, rules=a.rules)
