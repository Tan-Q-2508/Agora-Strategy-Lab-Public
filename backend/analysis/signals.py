"""Signals on every candle, as a trader would have seen them then (KAIROS §8, D-60).

The chart report (``report.py``) reads a chart *as of today*. Training, the Kairos brain and
the learning loop need the same findings *on every past candle*. ``compute`` walks the whole
history once and records each finding on the candle it became known (that candle's close),
using only that candle and earlier ones:

| Family | Event | Known on |
|---|---|---|
| ``pattern`` | a chart pattern breaks out (or fails the wrong way) | the breakout candle |
| ``candle`` | a candlestick pattern completes | its last candle |
| ``divergence`` | price and RSI disagree at two swings | the candle confirming the 2nd swing |
| ``level`` | a close through the last major high/low; a bounce/rejection at a swing | that candle |
| ``line`` | a close through a trendline drawn on confirmed swings | that candle |
| ``momentum`` | RSI leaves oversold/overbought; MACD crosses its signal line | that candle |
| ``volume`` | a 2× volume spike on a rising or falling candle | that candle |
| ``trend`` | the trend score turns up through +25 or down through −25 | that candle |
| ``setup`` | a named setup (gaps, NR7, springs, crosses, …; ``setups.py``) | that candle |
| ``momentum`` / ``trend`` / ``volume`` | every indicator's own signal (D-138) | that candle |
| ``strategy`` | a classic strategy's entry (Turtle, RSI-2, VWAP, …) | that candle |
| ``quant`` | a statistical signal (z-score snap-back, 12-1 momentum, …) | that candle |

The last three rows come from ``indicator_signals.py``.

Every event has a direction (+1 bullish, −1 bearish); patterns and levels also carry the
price that would prove them wrong (``stop``) and patterns their measured target. Alongside
the events, three per-candle readings (trend −100…+100, momentum and volume −1…+1) use the
same formulas as the chart report.

Because every step only looks backwards, computing on a shorter history gives the same
events and readings for the candles both histories share (tested). That is what lets a
backtest of the Kairos brain and its live paper trading see the same signals.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from backend.analysis import candles as cdl
from backend.analysis import chart_patterns as cp
from backend.analysis import divergence as dv
from backend.analysis import indicator_signals as ind
from backend.analysis import setups as st
from backend.analysis import trendlines as tl
from backend.analysis.swings import MAJOR, MINOR, Swing, find_swings, reversal_size
from backend.analysis.trend import MomentumArrays, TrendArrays, structure
from backend.analysis.volume import VolumeArrays
from backend.indicators.series import F64, BarSeries

# How many candles an event keeps influencing the brain's score (it fades over this time).
WINDOW: dict[str, int] = {
    "pattern": 10,
    "candle": 3,
    "divergence": 10,
    "level": 5,
    "line": 5,
    "momentum": 3,
    "volume": 3,
    "trend": 5,
    "setup": 5,
    "strategy": 5,
    "quant": 5,
}
LEVEL_LOOKBACK = 250  # candles: swing levels older than this are forgotten
LEVELS_KEPT = 6  # most recent swing highs/lows that count as levels

LABELS: dict[str, str] = {
    "level:breakout": "Broke above the last major high",
    "level:breakdown": "Broke below the last major low",
    "level:support_bounce": "Bounced off support",
    "level:resistance_reject": "Turned down at resistance",
    "line:break_up": "Closed above a falling trendline",
    "line:break_down": "Closed below a rising trendline",
    "momentum:rsi_oversold_exit": "RSI climbed back above 30",
    "momentum:rsi_overbought_exit": "RSI dropped back below 70",
    "momentum:macd_cross_up": "MACD crossed above its signal line",
    "momentum:macd_cross_down": "MACD crossed below its signal line",
    "volume:spike_up": "Volume spike on a rising candle",
    "volume:spike_down": "Volume spike on a falling candle",
    "trend:turn_up": "The trend turned up",
    "trend:turn_down": "The trend turned down",
    "pattern:failed:up": "A bearish pattern failed (price broke up instead)",
    "pattern:failed:down": "A bullish pattern failed (price broke down instead)",
}
DIRECTION: dict[str, int] = {
    k: -1 if k.endswith((":down", "breakdown", "reject", "overbought_exit", "_down")) else 1
    for k in LABELS
}
for _k, _info in st.INFO.items():
    LABELS[f"setup:{_k}"] = _info.name
    DIRECTION[f"setup:{_k}"] = _info.bias
for _k, (_label, _d) in ind.INFO.items():
    LABELS[_k] = _label
    DIRECTION[_k] = _d


@dataclass(frozen=True)
class Event:
    key: str  # e.g. "pattern:bull_flag:up", "candle:hammer", "level:breakout"
    index: int  # candle it became known on
    direction: int  # +1 bullish, −1 bearish
    label: str
    strength: float = 1.0  # 0 … 1 (a pattern's confidence)
    stop: float | None = None  # price that proves it wrong
    target: float | None = None  # measured target (patterns)

    @property
    def family(self) -> str:
        return self.key.split(":", 1)[0]


@dataclass
class SignalSet:
    """Everything ``compute`` found, indexed by candle."""

    n: int
    close: F64
    atr: F64
    trend: F64  # −100 … +100 per candle
    momentum: F64  # −1 … +1
    volume: F64  # −1 … +1 (0 when the series has no volume)
    events: list[Event]
    by_index: dict[int, list[Event]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        idx: dict[int, list[Event]] = defaultdict(list)
        for e in self.events:
            idx[e.index].append(e)
        self.by_index = dict(idx)

    def at(self, i: int) -> list[Event]:
        """Events that became known on candle ``i``."""
        return self.by_index.get(i, [])

    def recent(self, i: int) -> list[tuple[Event, int]]:
        """Events still in play on candle ``i``, with their age in candles (0 = today)."""
        out: list[tuple[Event, int]] = []
        for age in range(max(WINDOW.values())):
            for e in self.by_index.get(i - age, []):
                if age < WINDOW[e.family]:
                    out.append((e, age))
        return out


def compute(series: BarSeries) -> SignalSet:
    o, h, lo, c, v = series.open, series.high, series.low, series.close, series.volume
    n = len(c)
    atr = reversal_size(h, lo, c)
    minor = find_swings(h, lo, c, MINOR, atr)
    major = find_swings(h, lo, c, MAJOR, atr)
    ta = TrendArrays(h, lo, c)
    ma = MomentumArrays(h, lo, c)
    va = VolumeArrays(h, lo, c, v)
    trend = _trend_scores(ta, list(minor.swings), n)
    momentum = np.array([ma.score(i) for i in range(n)], dtype=np.float64)
    volume = volume_scores(va)
    events: list[Event] = []
    events += _candle_events(o, h, lo, c)
    events += _momentum_events(ma)
    events += _volume_events(va)
    events += _trend_events(trend)
    events += _divergence_events(list(minor.swings), ma)
    events += _level_events(o, h, lo, c, atr, list(minor.swings), list(major.swings))
    events += _line_events(c, atr, list(minor.swings))
    events += _pattern_events(h, lo, c, v, atr, minor.swings, major.swings)
    events += setup_events(o, h, lo, c, v)
    events += [
        Event(k, i, d, LABELS[k], strength=ind.STRENGTH[k.split(":", 1)[0]])
        for k, i, d in ind.detect(series)
    ]
    events.sort(key=lambda e: (e.index, e.key))
    return SignalSet(n, c, atr, trend, momentum, volume, events)


# ---------------------------------------------------------------- readings per candle


def _trend_scores(ta: TrendArrays, swings: list[Swing], n: int) -> F64:
    """The chart report's trend score on every candle, with swing structure built from the
    swings confirmed by then (swings are confirmed in order, so one pointer walks them)."""
    out = np.zeros(n, dtype=np.float64)
    known: list[Swing] = []
    p = 0
    for i in range(n):
        while p < len(swings) and swings[p].confirmed <= i:
            known.append(swings[p])
            p += 1
        out[i] = ta.score(i, structure(known[-4:]))
    return out


def volume_scores(va: VolumeArrays) -> F64:
    """``VolumeArrays.state(i).score`` for every candle at once."""
    n = len(va.close)
    if n == 0:
        return np.zeros(0)

    def trailing_sum(x: F64, k: int) -> F64:
        cs = np.concatenate([[0.0], np.cumsum(x)])
        idx = np.arange(n)
        out: F64 = cs[idx + 1] - cs[np.maximum(0, idx - k + 1)]
        return out

    acc = trailing_sum(va.acc.astype(np.float64), 25)
    dist = trailing_sum(va.dist.astype(np.float64), 25)
    has = trailing_sum(np.nan_to_num(va.volume), 51) > 0
    cmf = np.nan_to_num(va.cmf, nan=0.0)
    ps, os_ = va.price_slope, va.obv_slope
    ok = np.isfinite(ps) & np.isfinite(os_)
    div = np.where(ok & (ps < 0) & (os_ > 0), 1.0, np.where(ok & (ps > 0) & (os_ < 0), -1.0, 0.0))
    parts = (np.clip((acc - dist) / 5.0, -1.0, 1.0) + np.clip(cmf / 0.2, -1.0, 1.0) + div) / 3.0
    return np.where(has, np.round(parts, 3), 0.0)


# ---------------------------------------------------------------- simple events


def _candle_events(o: F64, h: F64, lo: F64, c: F64) -> list[Event]:
    flags = cdl.detect(o, h, lo, c)
    out: list[Event] = []
    for hit in cdl.label_candles(flags, 0, len(c) - 1):
        info = hit.info
        if info.bias == "neutral":
            continue
        d = 1 if info.bias == "bullish" else -1
        out.append(Event(f"candle:{info.key}", hit.index, d, info.name))
    return out


def setup_events(o: F64, h: F64, lo: F64, c: F64, v: F64) -> list[Event]:
    out: list[Event] = []
    for key, flags in st.detect(o, h, lo, c, v).items():
        info = st.INFO[key]
        for i in np.flatnonzero(flags):
            k = int(i)
            stop = st.stop_for(key, k, h, lo)
            out.append(Event(f"setup:{key}", k, info.bias, info.name, strength=0.8, stop=stop))
    return out


def _crosses(x: F64, level: float) -> tuple[np.ndarray, np.ndarray]:
    """Indices where ``x`` moves above / below ``level`` (from at-or-below / at-or-above)."""
    prev = np.concatenate([[np.nan], x[:-1]])
    with np.errstate(invalid="ignore"):
        up = np.flatnonzero((x > level) & (prev <= level))
        down = np.flatnonzero((x < level) & (prev >= level))
    return up, down


def _momentum_events(ma: MomentumArrays) -> list[Event]:
    out: list[Event] = []
    up30, _ = _crosses(ma.rsi, 30.0)
    _, down70 = _crosses(ma.rsi, 70.0)
    for i in up30:
        out.append(_simple("momentum:rsi_oversold_exit", int(i), 1))
    for i in down70:
        out.append(_simple("momentum:rsi_overbought_exit", int(i), -1))
    with np.errstate(invalid="ignore"):
        diff = ma.macd - ma.signal
    up, down = _crosses(diff, 0.0)
    for i in up:
        out.append(_simple("momentum:macd_cross_up", int(i), 1))
    for i in down:
        out.append(_simple("momentum:macd_cross_down", int(i), -1))
    return out


def _volume_events(va: VolumeArrays) -> list[Event]:
    out: list[Event] = []
    r, c = va.rvol, va.close
    for i in range(1, len(c)):
        if np.isfinite(r[i]) and r[i] >= 2.0 and c[i] != c[i - 1]:
            up = c[i] > c[i - 1]
            out.append(
                _simple("volume:spike_up" if up else "volume:spike_down", i, 1 if up else -1)
            )
    return out


def _trend_events(trend: F64) -> list[Event]:
    up, _ = _crosses(trend, 25.0 - 1e-9)
    _, down = _crosses(trend, -25.0 + 1e-9)
    out = [_simple("trend:turn_up", int(i), 1) for i in up]
    out += [_simple("trend:turn_down", int(i), -1) for i in down]
    return out


def _simple(key: str, i: int, d: int) -> Event:
    return Event(key, i, d, LABELS[key])


def _divergence_events(swings: list[Swing], ma: MomentumArrays) -> list[Event]:
    out: list[Event] = []
    for d in dv.find(swings, ma.rsi, ma.hist):
        out.append(
            Event(
                f"divergence:{d.kind}",
                d.known_at,
                1 if d.bullish else -1,
                d.label,
                strength=1.0 if d.strong else 0.6,
                stop=d.b.price,
            )
        )
    return out


# ---------------------------------------------------------------- levels and lines


def _level_events(
    o: F64, h: F64, lo: F64, c: F64, atr: F64, minor: list[Swing], major: list[Swing]
) -> list[Event]:
    """Break of the last major swing high/low, and bounces/rejections at recent swing levels."""
    out: list[Event] = []
    n = len(c)
    swings = sorted(minor + major, key=lambda s: s.confirmed)
    highs: list[Swing] = []
    lows: list[Swing] = []
    major_hi: Swing | None = None
    major_lo: Swing | None = None
    major_set = set(major)
    fired: set[tuple[str, int]] = set()
    last_touch: dict[tuple[str, int], int] = {}
    p = 0
    for i in range(1, n):
        while p < len(swings) and swings[p].confirmed < i:
            s = swings[p]
            (highs if s.is_high else lows).append(s)
            if s in major_set:
                if s.is_high:
                    major_hi = s
                else:
                    major_lo = s
            p += 1
        a = float(atr[i])
        if not np.isfinite(a) or a <= 0:
            continue
        ci, cprev = float(c[i]), float(c[i - 1])
        if major_hi is not None and i - major_hi.index <= LEVEL_LOOKBACK:
            lvl = major_hi.price + 0.1 * a
            if ci > lvl >= cprev and ("hi", major_hi.index) not in fired:
                fired.add(("hi", major_hi.index))
                stop = lows[-1].price if lows else None
                out.append(Event("level:breakout", i, 1, LABELS["level:breakout"], stop=stop))
        if major_lo is not None and i - major_lo.index <= LEVEL_LOOKBACK:
            lvl = major_lo.price - 0.1 * a
            if ci < lvl <= cprev and ("lo", major_lo.index) not in fired:
                fired.add(("lo", major_lo.index))
                stop = highs[-1].price if highs else None
                out.append(Event("level:breakdown", i, -1, LABELS["level:breakdown"], stop=stop))
        up_candle, down_candle = ci > float(o[i]), ci < float(o[i])
        if up_candle:
            support = [s for s in lows[-LEVELS_KEPT:] if i - s.index <= LEVEL_LOOKBACK]
            for s in sorted(support, key=lambda s: -s.price):
                if s.price > ci:
                    continue
                if (
                    s.price - 0.5 * a <= float(lo[i]) <= s.price + 0.3 * a
                    and ci >= s.price + 0.5 * a
                ):
                    k = ("S", s.index)
                    if i - last_touch.get(k, -99) > 5:
                        out.append(
                            Event(
                                "level:support_bounce",
                                i,
                                1,
                                LABELS["level:support_bounce"],
                                stop=s.price - 0.5 * a,
                            )
                        )
                    last_touch[k] = i
                break
        elif down_candle:
            resist = [s for s in highs[-LEVELS_KEPT:] if i - s.index <= LEVEL_LOOKBACK]
            for s in sorted(resist, key=lambda s: s.price):
                if s.price < ci:
                    continue
                if (
                    s.price - 0.3 * a <= float(h[i]) <= s.price + 0.5 * a
                    and ci <= s.price - 0.5 * a
                ):
                    k = ("R", s.index)
                    if i - last_touch.get(k, -99) > 5:
                        out.append(
                            Event(
                                "level:resistance_reject",
                                i,
                                -1,
                                LABELS["level:resistance_reject"],
                                stop=s.price + 0.5 * a,
                            )
                        )
                    last_touch[k] = i
                break
    return out


def _line_events(c: F64, atr: F64, swings: list[Swing]) -> list[Event]:
    """Each time a swing high (low) is confirmed, draw the best resistance (support) lines
    from the swings known then, exactly as the chart report does; the first later close
    through a line, before the next swing of that kind, is a break (each line breaks once)."""
    out: list[Event] = []
    n = len(c)
    seen: set[tuple[str, int, int]] = set()
    for kind in ("H", "L"):
        side = [s for s in swings if s.kind == kind]
        for k, s in enumerate(side):
            at = s.confirmed
            nxt = side[k + 1].confirmed if k + 1 < len(side) else n - 1
            # Lines are drawn through the last 8 turns, so older swings can't change them.
            recent = side[max(0, k + 1 - tl.CANDIDATES) : k + 1]
            for ln in tl.find_lines(recent, c, atr, at):
                ident = (ln.kind, ln.i1, ln.i2)
                if ln.broken_at is not None or ident in seen:
                    continue
                idx = np.arange(at + 1, nxt + 1)
                if not len(idx):
                    continue
                line = ln.p1 + ln.slope * (idx - ln.i1)
                tol = tl.SLACK * atr[idx]
                seg = c[idx]
                bad = seg < line - tol if ln.kind == "support" else seg > line + tol
                if not bad.any():
                    continue
                seen.add(ident)
                i = int(idx[int(np.argmax(bad))])
                if ln.kind == "support" and ln.slope >= 0:
                    out.append(
                        Event(
                            "line:break_down", i, -1, LABELS["line:break_down"], stop=float(c[at])
                        )
                    )
                elif ln.kind == "resistance" and ln.slope <= 0:
                    out.append(
                        Event("line:break_up", i, 1, LABELS["line:break_up"], stop=float(c[at]))
                    )
    return out


# ---------------------------------------------------------------- chart patterns


def _pattern_events(
    h: F64,
    lo: F64,
    c: F64,
    v: F64,
    atr: F64,
    minor: tuple[Swing, ...],
    major: tuple[Swing, ...],
) -> list[Event]:
    """Every pattern the report could have drawn from confirmed swings (and every flag),
    followed to its breakout. Several shapes breaking out on the same candle in the same
    direction are one event: the most significant shape."""
    n = len(c)
    found: list[cp.ChartPattern] = []
    for swings, is_major in ((minor, False), (major, True)):
        for e in range(2, len(swings)):
            at = swings[e].confirmed
            seq = swings[max(0, e - 30) : e + 1]
            found += cp.from_swings(seq, c, float(atr[at]), at, major=is_major)
    # A consolidation that keeps going is re-recognised every candle (with slightly
    # different lines); each pole's flag breaks out once, the first time any reading broke.
    flags: dict[tuple[int, str], cp.ChartPattern] = {}
    for f in _flags(h, lo, c, atr):
        cap = min(n - 1, f.formed + max(15, f.end - f.start) + 1)
        t = cp.track(f, h, lo, c, v, cap) if cap > f.formed else f
        if t.event is None:
            continue
        pole = (f.points[1].index, f.key)
        if pole not in flags or (t.event or 0) < (flags[pole].event or 0):
            flags[pole] = t
    best: dict[tuple[int, int, bool], tuple[tuple[int, float], Event]] = {}
    for p in [*found, *flags.values()]:
        if p.event is not None:
            t = p  # a flag, already followed
        else:
            cap = min(n - 1, p.formed + max(15, p.end - p.start) + 1)
            if cap <= p.formed:
                continue
            t = cp.track(p, h, lo, c, v, cap)
        if t.event is None or (t.status == "target" and t.resolved == t.event):
            continue  # no breakout, or one that covered the whole move in a single candle
        if t.direction:
            way = "up" if t.direction > 0 else "down"
            name = t.name + (" breakout" if t.direction > 0 else " breakdown")
            ev = Event(
                f"pattern:{t.key}:{way}",
                t.event,
                t.direction,
                name,
                strength=t.confidence,
                stop=t.stop,
                target=t.target,
            )
            failed = False
        else:  # broke the way the pattern said it shouldn't
            d = 1 if float(c[t.event]) > (p.upper.at(t.event) if p.upper else -np.inf) else -1
            ev = Event(
                f"pattern:failed:{'up' if d > 0 else 'down'}",
                t.event,
                d,
                f"{t.name} failed",
                strength=t.confidence,
            )
            failed = True
        rank = (cp.RANK.get(t.key, 0), t.confidence)
        k = (ev.index, ev.direction, failed)
        if k not in best or rank > best[k][0]:
            best[k] = (rank, ev)
    return [ev for _, ev in best.values()]


def _flags(h: F64, lo: F64, c: F64, atr: F64) -> list[cp.ChartPattern]:
    """Flags and pennants on every candle, skipping candles with no pole in reach
    (a pole is at least 3.5 × ATR, so a quieter 40-candle stretch can't hold one)."""
    n = len(c)
    out: list[cp.ChartPattern] = []
    if n < 12:
        return out
    win = 40
    hi = np.array([h[max(0, i - win) : i + 1].max() for i in range(n)])
    low = np.array([lo[max(0, i - win) : i + 1].min() for i in range(n)])
    room = (hi - low) >= 3.5 * np.nan_to_num(atr, nan=np.inf) * 0.5
    for i in range(10, n):
        if room[i]:
            f = cp.flag_at(h, lo, c, atr, i)
            if f is not None:
                out.append(f)
    return out
