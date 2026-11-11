"""The Kairos brain: a strategy that trades on the analyst's signals (KAIROS §9, D-60).

It is an ordinary strategy kind (``"kairos"``) compiled to a ``Program`` and run by the
shared engine, so a backtest of Kairos and Kairos's paper desk are the same code (D-04).
It never sees the language model; its decisions are reproducible from the prices and the
signal weights alone.

On each closed candle it scores the chart −100 … +100 the way the chart report does
(trend 30%, chart patterns 25%, momentum 15%, levels 10%, volume 10%, divergences 5%,
candles 5%), except that every signal's say is multiplied by its learned weight (0 … 2).
Besides the chart reader's signals it hears every indicator, classic strategy entries and
quant signals (``indicator_signals.py``, D-138), each weighted by its own record.

- **Enter** long when the score reaches the entry threshold, the trend isn't a strong
  downtrend, and something just happened (a fresh bullish signal, or the score crossing
  the threshold): Kairos doesn't buy a chart that has merely been good for weeks. Short
  the mirror image where short-selling is allowed.
- **Stop** at the signal's own invalidation price or ``stop_atr`` × ATR, whichever is
  tighter, but never closer than 1 ATR. **Target** at the pattern's measured move when it
  offers at least 1.5× the risk, else ``target_r`` × the risk. Size by risk (1% default).
- **Exit early** when the score turns ``exit_score`` against the trade, or after
  ``max_bars`` candles.
- **Live only, the news guard** (``news_guard.py``, D-69) can block an entry, halve its
  size, nudge the score for a company catalyst, or close a long on market-moving or
  red-flag news. Backtests and replays have no guard, so they stay reproducible.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.analysis import indicator_signals as ind
from backend.analysis import mtf
from backend.analysis import signals as sig
from backend.analysis.report import WEIGHTS
from backend.indicators.series import BarSeries
from backend.strategy.definition import KairosDefinition, ParameterDef, resolve_num
from backend.strategy.runtime import SizeSpec, StopRule, StrategyContext, make_scale_out

MIN_STOP_ATR = 1.0
MEASURED_MOVE_MIN_R = 1.5
STRONG_TREND = 60.0
WARMUP = 250

# Which part of the score each signal family feeds.
BUCKET = {
    "pattern": "patterns",
    "level": "levels",
    "line": "levels",
    "divergence": "divergence",
    "candle": "candles",
    "momentum": "momentum",
    "volume": "volume",
    "trend": "trend",
    "setup": "patterns",
    "strategy": "patterns",  # a classic strategy's entry says as much as a setup (D-138)
    "quant": "momentum",
}
# Events nudge a reading that is already a −1 … +1 state by at most this much.
STATE_NUDGE = 0.5
# The indicators' chorus (D-138): their agreement moves a part of the score by at most this
# much, and fewer than CHORUS_MIN voices (counted by freshness) can't reach it.
CHORUS_CAP = 0.6
CHORUS_MIN = 3.0


@dataclass(frozen=True)
class Active:
    event: sig.Event
    age: int
    weight: float
    contribution: float  # signed, in the bucket's −1 … +1 units


@dataclass
class Decision:
    score: float
    components: dict[str, float]
    active: list[Active] = field(default_factory=list)

    def fresh(self, direction: int) -> list[Active]:
        """Signals that just fired (this candle or the one before) the given way. An indicator
        crossing only votes (D-138): with dozens of them one fires on most candles, so it isn't
        "something happened"; a classic strategy's entry is."""
        return [
            a
            for a in self.active
            if a.age <= 1
            and a.event.direction == direction
            and a.contribution * direction > 0
            and (a.event.key not in ind.INFO or a.event.family == "strategy")
        ]

    def reasons(self, direction: int, n: int = 3) -> list[Active]:
        agree = [a for a in self.active if a.contribution * direction > 0]
        return sorted(agree, key=lambda a: -abs(a.contribution))[:n]

    def signal_keys(self) -> list[tuple[str, int]]:
        return [(a.event.key, a.event.direction) for a in self.active]


def decide(ss: sig.SignalSet, i: int, weights: Mapping[str, float]) -> Decision:
    """The brain's reading of candle ``i`` (only events known by then count).

    The chart reader's signals each add their say. Every indicator, classic strategy and quant
    signal (``indicator_signals.py``) instead votes in a chorus per part of the score (D-138):
    their weighted agreement moves that part by at most ``CHORUS_CAP``, so fifty indicators
    saying the same thing count as strong agreement, not fifty separate reasons, and the
    learned weights decide whose vote counts."""
    comp = {
        "trend": float(ss.trend[i]) / 100.0,
        "momentum": float(ss.momentum[i]),
        "volume": float(ss.volume[i]),
        "patterns": 0.0,
        "levels": 0.0,
        "divergence": 0.0,
        "candles": 0.0,
    }
    active: list[Active] = []
    chorus: dict[str, list[tuple[sig.Event, int, float, float]]] = {}
    for e, age in ss.recent(i):
        w = float(weights.get(e.key, 1.0))
        fade = 1.0 - age / sig.WINDOW[e.family]
        bucket = BUCKET[e.family]
        if e.key in ind.INFO:
            chorus.setdefault(bucket, []).append((e, age, w, fade))
            continue
        scale = STATE_NUDGE if bucket in ("trend", "momentum", "volume") else 1.0
        c = e.direction * e.strength * fade * w * scale
        comp[bucket] += c
        active.append(Active(e, age, w, c))
    for bucket, voices in chorus.items():
        scale = STATE_NUDGE if bucket in ("trend", "momentum", "volume") else 1.0
        heard = max(CHORUS_MIN, sum(fade for _, _, _, fade in voices))
        for e, age, w, fade in voices:
            c = CHORUS_CAP * scale * e.direction * e.strength * fade * w / heard
            comp[bucket] += c
            active.append(Active(e, age, w, c))
    comp = {k: float(np.clip(v, -1.0, 1.0)) for k, v in comp.items()}
    score = round(100.0 * sum(WEIGHTS[k] * v for k, v in comp.items()), 1)
    return Decision(score, comp, active)


@dataclass(frozen=True)
class Plan:
    side: int
    stop_pct: float
    target_pct: float
    reason: str


def plan(
    ss: sig.SignalSet, i: int, d: Decision, side: int, stop_atr: float, target_r: float
) -> Plan:
    """Stop and target for a trade opened on candle ``i`` (as % of the price)."""
    close = float(ss.close[i])
    atr = float(ss.atr[i])
    reasons = d.reasons(side)
    dist = stop_atr * atr
    for a in reasons:
        st = a.event.stop
        if st is not None and (close - st) * side > 0:
            dist = min(dist, abs(close - st))
            break
    dist = max(dist, MIN_STOP_ATR * atr)
    target = target_r * dist
    for a in reasons:
        tg = a.event.target
        if tg is not None and (tg - close) * side >= MEASURED_MOVE_MIN_R * dist:
            target = abs(tg - close)
            break
    words = ", ".join(dict.fromkeys(a.event.label for a in reasons)) or "the overall picture"
    sign = "+" if d.score >= 0 else "−"
    reason = f"Kairos {sign}{abs(d.score):.0f}: {words}"
    return Plan(side, 100.0 * dist / close, 100.0 * target / close, reason[:200])


_SHARED: OrderedDict[tuple[Any, ...], sig.SignalSet] = OrderedDict()
_SHARED_LOCK = threading.Lock()
SHARED_SIZE = 64


def shared_signals(series: BarSeries) -> sig.SignalSet:
    """Signals for a series, reused across runs: research and sweeps backtest the same
    stocks many times, and the same prices always give the same signals."""
    n = len(series)
    key = (
        n,
        int(series.ts[0]) if n else 0,
        int(series.ts[-1]) if n else 0,
        hash(series.close.tobytes()),
        hash(series.volume.tobytes()),
        hash(series.high.tobytes()),
    )
    with _SHARED_LOCK:
        hit = _SHARED.get(key)
        if hit is not None:
            _SHARED.move_to_end(key)
            return hit
    ss = sig.compute(series)
    with _SHARED_LOCK:
        _SHARED[key] = ss
        while len(_SHARED) > SHARED_SIZE:
            _SHARED.popitem(last=False)
    return ss


class Brain:
    """One compiled Kairos strategy. Signal sets are cached per stock and recomputed only
    when a new candle arrives (live trading appends candles; a backtest computes once)."""

    def __init__(self, d: KairosDefinition, params: dict[str, float]) -> None:
        k = d.kairos
        self.entry = resolve_num(k.entry_score, params)
        self.exit = resolve_num(k.exit_score, params)
        self.stop_atr = resolve_num(k.stop_atr, params)
        self.target_r = resolve_num(k.target_r, params)
        self.trail_atr = resolve_num(k.trail_atr, params) if k.trail_atr is not None else None
        # partial exit (D-125): book part of the profit at partial_r, the rest can't lose
        partial = resolve_num(k.partial_r, params) if k.partial_r is not None else None
        self.scale = (
            make_scale_out([(partial, resolve_num(k.partial_pct, params))]) if partial else None
        )
        self.partial_pct = resolve_num(k.partial_pct, params)
        self.max_bars = int(resolve_num(k.max_bars, params)) if k.max_bars is not None else None
        self.shorts = k.allow_short and not (d.market == "IN" and d.product == "delivery")
        self.size = SizeSpec(d.sizing.kind, resolve_num(d.sizing.value, params))
        self.weights: dict[str, float] = dict(d.weights)
        # Desk sessions refresh the weights from what Kairos has learned since (D-60): each
        # trading day, and as soon as ``stamp`` says it learned something (a closed trade,
        # D-138); backtests keep the snapshot so they are reproducible.
        self.refresh: Callable[[], Mapping[str, float]] | None = None
        self.stamp: Callable[[], int] | None = None
        self._stamp = 0
        # Live desks only: the exit plan Kairos chose from its record (D-140), read with the
        # weights; None keeps the definition's stops, targets, trailing and partial exits.
        self.exits: Callable[[], Mapping[str, Any] | None] | None = None
        self.exit_words = ""
        # Live desks only: the news guard (D-69). None in backtests and replays.
        self.news: Any | None = None
        # Live desks only: the trade judge (D-145), read with the weights; it may pass on an
        # entry the score allows when, in its tested record, such entries tend to lose.
        self.judge: Callable[[], Any] | None = None
        self.judge_model: Any | None = None
        # Live daily desks only: the candle forecast's nudge for (symbol, candle) (D-175),
        # given only where the forecasts' checked record shows skill; None otherwise.
        self.forecast: Callable[[str, int], float] | None = None
        # Live desks only: a closer look at the smaller chart before an entry (D-177): True
        # when it turned against the trade (symbol, candle, side). None in backtests.
        self.closer: Callable[[str, int, int], bool] | None = None
        self.closer_passed = 0  # entries the smaller chart talked the desk out of
        self.passed = 0  # entries the judge passed on
        self._day = ""
        self._sets: dict[int, tuple[Any, int, sig.SignalSet]] = {}
        # the bigger charts read together (D-132), nearest first; one chart before D-132
        charts: list[str] = list(k.bigger_charts or [])
        if k.bigger_chart and k.bigger_chart not in charts:
            charts.insert(0, k.bigger_chart)
        self.charts: list[str] = charts
        self._big: dict[tuple[int, str], tuple[Any, int, np.ndarray]] = {}

    def use_exits(self, choice: Mapping[str, Any] | None) -> None:
        """Trade with an exit plan (D-140): new entries get its stop, target, trailing stop and
        partial sale; trades already open keep theirs."""
        if not choice:
            return
        p = choice["plan"]
        self.stop_atr, self.target_r, self.trail_atr = p.stop_atr, p.target_r, p.trail_atr
        self.scale = make_scale_out([(p.partial_r, self.partial_pct)]) if p.partial_r else None
        self.exit_words = f"{p.words()} ({choice['why']})"

    def bigger_trend(self, ctx: StrategyContext, chart: str) -> np.ndarray:
        """A bigger chart's trend score (−100 … +100) on its last finished candle, lined
        up with this stock's candles (D-97)."""
        series = ctx._provider.series
        key = (id(ctx._provider), chart)
        hit = self._big.get(key)
        if hit is not None and hit[0] is series and hit[1] == len(series):
            return hit[2]
        frame = ctx._frame(chart).frame
        trend = mtf.trend_line(frame.series)
        arr = mtf.finished(trend, frame.group)
        self._big[key] = (series, len(series), arr)
        return arr

    def charts_say_no(self, ctx: StrategyContext, side: int) -> bool:
        """Every bigger chart together (D-132): the nearest must be known and not against the
        trade; a further one (often too little history on a short desk) says no only when it
        is known and clearly against it."""
        i = ctx.bar_index
        for n, chart in enumerate(self.charts):
            b = float(self.bigger_trend(ctx, chart)[i])
            if not np.isfinite(b):
                if n == 0:
                    return True
                continue
            if b * side <= -mtf.TREND_LINE:
                return True
        return False

    def signals(self, ctx: StrategyContext) -> sig.SignalSet:
        series = ctx._provider.series
        key = id(ctx._provider)
        hit = self._sets.get(key)
        if hit is None or hit[0] is not series or hit[1] != len(series):
            ss = shared_signals(series)
            self._sets[key] = (series, len(series), ss)
            return ss
        return hit[2]

    def decide(self, ctx: StrategyContext) -> Decision:
        return decide(self.signals(ctx), ctx.bar_index, self.weights)

    def on_bar(self, ctx: StrategyContext) -> None:
        if self.refresh is not None:
            stamp = self.stamp() if self.stamp is not None else 0
            if ctx.date != self._day or stamp != self._stamp:
                self._day, self._stamp = ctx.date, stamp
                self.weights = dict(self.refresh())
                if self.exits is not None:
                    self.use_exits(self.exits())
                if self.judge is not None:
                    self.judge_model = self.judge()
        i = ctx.bar_index
        if i < 2:
            return
        ss = self.signals(ctx)
        d = decide(ss, i, self.weights)
        pos = ctx.position
        adv = None
        guard = self.news
        if guard is not None:
            pnl = pos.profit_pct if pos is not None and pos.side == "long" else None
            adv = guard.advise(ctx.symbol, ctx.time, pnl)
            if adv.nudge:
                d.score = round(d.score + adv.nudge, 1)
        if self.forecast is not None:
            try:
                lean = self.forecast(ctx.symbol, ctx.time)
            except Exception:  # a forecast that can't be read never moves a trade
                lean = 0.0
            if lean:
                d.score = round(d.score + lean, 1)
        if pos is None:
            side = self._entry_side(ss, i, d)
            if side and self.charts_say_no(ctx, side):
                return
            if side and guard and adv and (adv.block_long if side > 0 else adv.block_short):
                guard.acted(ctx.symbol, "skip", adv, ctx.date)
                return
            if side and self.judge_says_no(ctx, i, side, d):
                return
            if side and self.closer is not None:
                try:
                    no = self.closer(ctx.symbol, ctx.time, side)
                except Exception:  # a smaller chart that can't be read never blocks a trade
                    no = False
                if no:
                    self.closer_passed += 1
                    return
            if side:
                size = self.size
                if guard and adv and adv.size_factor < 1:
                    size = SizeSpec(size.kind, size.value, size.scale * adv.size_factor)
                    guard.acted(ctx.symbol, "half", adv, ctx.date)
                p = plan(ss, i, d, side, self.stop_atr, self.target_r)
                sl = StopRule("percent", p.stop_pct)
                tp = StopRule("percent", p.target_pct)
                tr = StopRule("atr", self.trail_atr) if self.trail_atr else None
                if side > 0:
                    ctx.buy(size, sl, tp, tr, p.reason, self.scale)
                else:
                    ctx.short(size, sl, tp, tr, p.reason, self.scale)
            return
        if guard and adv and adv.exit_long and pos.side == "long":
            ctx.sell_all(f"News guard: {adv.reason}")
            guard.acted(ctx.symbol, "exit", adv, ctx.date)
            return
        against = -d.score if pos.side == "long" else d.score
        if against >= self.exit:
            word = "bearish" if pos.side == "long" else "bullish"
            ctx.sell_all(f"Kairos: the chart turned {word} (score {d.score:+.0f})")
        elif self.max_bars is not None and pos.bars_held >= self.max_bars:
            ctx.sell_all("Time limit reached", "time")

    def judge_says_no(self, ctx: StrategyContext, i: int, side: int, d: Decision) -> bool:
        """The trade judge's verdict on this entry (D-145): only a judge that earned its place
        on unseen past trades (``active``) can pass on one."""
        m = self.judge_model
        if m is None:
            return False
        if not getattr(m, "active", False):
            return False
        from backend.kairos import judge as jd

        try:
            x = jd.Reader(ctx._provider.series).at(i, side, d)
            if m.take(x):
                return False
        except Exception:  # a judge that can't read this candle never blocks a trade
            return False
        self.passed += 1
        return True

    def _entry_side(self, ss: sig.SignalSet, i: int, d: Decision) -> int:
        trend = float(ss.trend[i])
        for side in (1, -1):
            if side < 0 and not self.shorts:
                continue
            if d.score * side < self.entry or trend * side <= -STRONG_TREND:
                continue
            prev = decide(ss, i - 1, self.weights).score * side
            if d.fresh(side) or prev < self.entry:
                return side
        return 0


def compile_brain(d: KairosDefinition, params: dict[str, float]) -> tuple[Brain, int]:
    brain = Brain(d, params)
    return brain, WARMUP


# ---------------------------------------------------------------- a ready-made definition

PARAMETERS = [
    ParameterDef(
        name="entry_score", label="Entry score", type="int", default=40, min=20, max=70, step=5
    ),
    ParameterDef(
        name="stop_atr", label="Stop (ATRs)", type="float", default=2.0, min=1.0, max=3.5, step=0.5
    ),
    ParameterDef(
        name="target_r",
        label="Target (× risk)",
        type="float",
        default=2.5,
        min=1.5,
        max=4.0,
        step=0.5,
    ),
]


# the most open trades a desk holds in one sector (D-168)
MAX_PER_SECTOR = 3


def definition(
    market: str,
    symbols: list[str],
    *,
    timeframe: str = "1d",
    weights: Mapping[str, float] | None = None,
    trained_at: int | None = None,
    risk_pct: float = 1.0,
    max_positions: int = 10,
    daily_loss_pct: float | None = 3.0,
    product: str | None = None,
    bigger_chart: str | None = None,
    bigger_charts: list[str] | None = None,
    trail_atr: float | None = None,
    partial_r: float | None = None,
) -> KairosDefinition:
    """The Kairos brain over ``symbols`` with its sweepable settings as parameters."""
    prod = product or (
        "cash" if market == "US" else "delivery" if timeframe == "1d" else "intraday"
    )
    return KairosDefinition.model_validate(
        {
            "market": market,
            "timeframe": timeframe,
            "product": prod,
            "universe": {"kind": "symbols", "symbols": symbols},
            "sizing": {"kind": "risk_percent", "value": risk_pct},
            "limits": {
                "max_open_positions": max_positions,
                "max_daily_loss_pct": daily_loss_pct,
                # an equal share each, so a tight stop can't put all the money in one trade (D-131)
                "max_position_pct": round(100.0 / max_positions, 2),
                # one theme can't fill the desk: six trades on the oil price at once (D-168)
                "max_per_group": MAX_PER_SECTOR,
            },
            "parameters": [p.model_dump() for p in PARAMETERS],
            "kairos": {
                "entry_score": "$entry_score",
                "stop_atr": "$stop_atr",
                "target_r": "$target_r",
                "max_bars": 30 if timeframe == "1d" else 60,
                "bigger_chart": bigger_chart,
                "bigger_charts": bigger_charts or None,
                # a trailing stop that follows the best price since entry (D-119)
                "trail_atr": trail_atr or None,
                # sell half at partial_r × the risk, then the stop moves to the entry (D-125)
                "partial_r": partial_r or None,
            },
            "weights": dict(weights or {}),
            "trained_at": trained_at,
        }
    )
