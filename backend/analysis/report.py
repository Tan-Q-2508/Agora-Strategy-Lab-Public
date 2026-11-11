"""The chart report: everything Kairos sees on one chart, scored and explained (KAIROS §3).

``analyze`` runs every analyst module on a symbol's candles and returns a JSON-ready dict:
the verdict (score −100 … +100, bias, confidence), plain-English sentences, the findings
(trend, momentum, volume, levels, trendlines, chart patterns, candlesticks, divergences,
Fibonacci), an educational trade idea with a stop and target, and every drawing the chart
needs (with timestamps, including a few future candles to extend lines into).

The overall score weighs: trend 30%, chart patterns 25%, momentum 15%, support/resistance
10%, volume 10%, divergences 5%, candlesticks 5%. Each part is first scored −1 … +1.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, timedelta
from typing import Any

import numpy as np

from backend.analysis import candles as cdl
from backend.analysis import chart_patterns as cp
from backend.analysis import chart_patterns_world as cpw
from backend.analysis import divergence as dv
from backend.analysis import fibonacci as fb
from backend.analysis import levels as lv
from backend.analysis import setups as stp
from backend.analysis import trendlines as tl
from backend.analysis.swings import MAJOR, MINOR, Swing, find_swings, reversal_size
from backend.analysis.trend import MomentumArrays, TrendArrays
from backend.analysis.volume import VolumeArrays
from backend.core.clock import ms_to_dt
from backend.core.types import Market
from backend.indicators.series import BarSeries

WEIGHTS = {
    "trend": 0.30,
    "patterns": 0.25,
    "momentum": 0.15,
    "levels": 0.10,
    "volume": 0.10,
    "divergence": 0.05,
    "candles": 0.05,
}
FUTURE = 15  # future candles returned for extending lines and the forecast
StatsLookup = Callable[[str], Mapping[str, Any] | None]


def price(value: float, market: Market) -> str:
    sym = "₹" if market is Market.IN else "$"
    return f"{'−' if value < 0 else ''}{sym}{abs(value):,.2f}"


def _none(_: str) -> None:
    return None


class Analysis:
    """All the analyst's arrays for one series; ``report()`` reads them at the last candle."""

    def __init__(self, series: BarSeries, market: Market, symbol: str, name: str = "") -> None:
        self.s = series
        self.market = market
        self.symbol = symbol
        self.name = name or symbol
        h, lo, c = series.high, series.low, series.close
        self.last = len(series) - 1
        self.atr = reversal_size(h, lo, c)
        self.minor = find_swings(h, lo, c, MINOR, self.atr)
        self.major = find_swings(h, lo, c, MAJOR, self.atr)
        self.trend = TrendArrays(h, lo, c)
        self.mom = MomentumArrays(h, lo, c)
        self.vol = VolumeArrays(h, lo, c, series.volume)
        self.candle_flags = cdl.detect(series.open, h, lo, c)
        self.setup_flags = stp.detect(series.open, h, lo, c, series.volume)

    # ------------------------------------------------------------ pieces

    def patterns(self, window: int = 500, scan: int = 8) -> list[cp.ChartPattern]:
        s = self.s
        last = self.last
        first = max(0, last - window)
        found: list[cp.ChartPattern] = []
        for swings, major in ((self.minor, False), (self.major, True)):
            seq = [w for w in swings.with_pending() if w.index >= first]
            for e in range(max(2, len(seq) - scan), len(seq)):
                end = seq[e]
                at = end.index if end.confirmed < 0 else end.confirmed
                a = float(self.atr[min(at, last)])
                found += cp.from_swings(seq[: e + 1], s.close, a, last, major=major)
        found += cp.recent_flags(s.high, s.low, s.close, self.atr, last)
        tracked = [cp.track(p, s.high, s.low, s.close, s.volume, last) for p in found]
        recent = [
            p
            for p in tracked
            if p.status == "forming"
            or (p.status == "confirmed" and last - (p.event or 0) <= 40)
            or (p.status in ("target", "failed") and last - (p.resolved or 0) <= 10)
        ]
        return cp.select(recent)

    def zones(self, window: int = 500) -> list[lv.Zone]:
        c = float(self.s.close[self.last])
        a = float(self.atr[self.last])
        return lv.find_zones(
            list(self.minor.swings),
            list(self.major.swings),
            c,
            a,
            self.last,
            self.s.volume,
            lookback=window,
        )

    def lines(self) -> list[tl.TrendLine]:
        return tl.find_lines(list(self.minor.swings), self.s.close, self.atr, self.last)

    def divergences(self, recent: int = 30) -> list[dv.Divergence]:
        """Recent divergences, the latest of each kind only (older ones are stale news)."""
        all_div = dv.find(list(self.minor.swings), self.mom.rsi, self.mom.hist)
        latest: dict[str, dv.Divergence] = {}
        for d in all_div:
            if self.last - d.known_at <= recent:
                latest[d.kind] = d
        return sorted(latest.values(), key=lambda d: d.known_at)

    def candles(self, recent: int = 10) -> list[cdl.CandleHit]:
        return cdl.label_candles(self.candle_flags, self.last - recent + 1, self.last)

    def setups(self, recent: int = 10) -> list[tuple[int, str]]:
        """(candle, setup key) for the setups of the last ``recent`` candles, oldest first."""
        first = max(0, self.last - recent + 1)
        hits = [
            (i, k)
            for k, flags in self.setup_flags.items()
            for i in range(first, self.last + 1)
            if flags[i]
        ]
        return sorted(hits)

    # ------------------------------------------------------------ the report

    def report(self, stats: StatsLookup = _none, window: int = 500) -> dict[str, Any]:
        return _Builder(self, stats, window).build()


class _Builder:
    def __init__(self, an: Analysis, stats: StatsLookup, window: int) -> None:
        self.an = an
        self.stats = stats
        self.window = window
        self.s = an.s
        self.i = an.last
        self.m = an.market
        self.close = float(self.s.close[self.i])
        self.a = float(an.atr[self.i])
        self.future = future_times(self.s, FUTURE)

    def ts(self, i: float) -> int:
        """Timestamp of candle ``i`` (future candles use the projected times)."""
        k = round(i)
        if k <= self.i:
            return int(self.s.ts[max(0, k)])
        return int(self.future[min(k - self.i - 1, len(self.future) - 1)])

    def px(self, v: float) -> str:
        return price(v, self.m)

    def pt(self, i: float, v: float, label: str = "") -> dict[str, Any]:
        d: dict[str, Any] = {"ts": self.ts(i), "value": round(float(v), 4)}
        if label:
            d["label"] = label
        return d

    def stat(self, key: str) -> dict[str, Any] | None:
        st = self.stats(key)
        return dict(st) if st else None

    # ------------------------------------------------------------ build

    def build(self) -> dict[str, Any]:
        an, i = self.an, self.i
        trend = an.trend.state(i, list(an.minor.known_at(i)))
        mom = an.mom.state(i)
        vol = an.vol.state(i)
        zones_all = an.zones(self.window)
        zones = lv.key_zones(zones_all)
        lines = an.lines()
        channel = tl.find_channel(lines, self.a)
        patterns = an.patterns(self.window)
        divs = an.divergences()
        candles = an.candles()
        setups = an.setups()
        fib = fb.from_swings(an.major.with_pending(), self.close, self.a)

        comp = {
            "trend": trend.score / 100.0,
            "momentum": mom.score,
            "patterns": float(
                np.clip(self._pattern_score(patterns) + self._setup_score(setups), -1.0, 1.0)
            ),
            "levels": self._level_score(zones),
            "volume": vol.score if vol.has_volume else 0.0,
            "divergence": self._divergence_score(divs),
            "candles": self._candle_score(candles),
        }
        score = round(100.0 * sum(WEIGHTS[k] * v for k, v in comp.items()), 1)
        bias = "bullish" if score >= 20 else "bearish" if score <= -20 else "neutral"
        signs = [np.sign(v) for k, v in comp.items() if abs(v) >= 0.15]
        agree = sum(1 for x in signs if x == np.sign(score)) / len(signs) if signs and score else 0
        confidence = (
            "high"
            if abs(score) >= 45 and agree >= 0.75
            else "medium"
            if abs(score) >= 25 and agree >= 0.6
            else "low"
        )
        prev = float(self.s.close[i - 1]) if i > 0 else self.close
        out: dict[str, Any] = {
            "symbol": an.symbol,
            "name": an.name,
            "market": an.market.value,
            "timeframe": self.s.timeframe.value,
            "as_of": int(self.s.ts[i]),
            "close": round(self.close, 4),
            "change_pct": round(100.0 * (self.close / prev - 1.0), 2) if prev else 0.0,
            "atr": round(self.a, 4),
            "score": score,
            "bias": bias,
            "confidence": confidence,
            "components": {k: round(float(v), 3) for k, v in comp.items()},
            "trend": _trend_json(trend),
            "momentum": {
                "score": mom.score,
                "rsi": mom.rsi,
                "rsi_state": mom.rsi_state,
                "macd_above_signal": mom.macd_above_signal,
                "macd_hist_rising": mom.macd_hist_rising,
                "stoch_k": mom.stoch_k,
                "notes": list(mom.notes),
            },
            "volume": {
                "has_volume": vol.has_volume,
                "rvol": vol.rvol if vol.has_volume else None,
                "spikes": [self.ts(k) for k in vol.spikes],
                "accumulation_days": vol.accumulation_days,
                "distribution_days": vol.distribution_days,
                "obv_divergence": vol.obv_divergence,
                "cmf": vol.cmf,
                "notes": list(vol.notes),
            },
            "zones": [self._zone(z) for z in zones],
            "lines": [self._line(ln) for ln in lines],
            "channel": channel.kind if channel else None,
            "patterns": [self._pattern(p) for p in patterns],
            "candles": [self._candle(c) for c in candles],
            "setups": [self._setup(i, k) for i, k in setups],
            "divergences": [self._divergence(d) for d in divs],
            "fibonacci": self._fib(fib),
            "future": self.future,
        }
        idea = self._idea(bias, patterns, zones)
        out["idea"] = idea
        out["invalidation"] = self._invalidation(bias, idea, zones)
        out["headline"] = self._headline(trend.regime, patterns, bias)
        out["_setup_hits"] = setups
        out["summary"] = self._summary(out, trend, patterns, zones, divs, candles)
        del out["_setup_hits"]
        return out

    # ------------------------------------------------------------ component scores

    def _pattern_score(self, ps: list[cp.ChartPattern]) -> float:
        total = 0.0
        for p in ps:
            d = 1.0 if p.bias == "bullish" else -1.0 if p.bias == "bearish" else 0.0
            if p.status == "confirmed":
                age = self.i - (p.event or self.i)
                total += d * p.confidence * max(0.3, 1.0 - age / 40.0)
            elif p.status == "forming":
                total += 0.5 * d * p.confidence
            elif p.status == "failed":
                total -= 0.4 * (p.direction or d) * p.confidence
        return float(np.clip(total, -1.0, 1.0))

    def _setup_score(self, hits: list[tuple[int, str]]) -> float:
        """Setups count like a pattern breakout that fades over five candles (half weight:
        they are smaller events)."""
        total = 0.0
        for i, k in hits:
            age = self.i - i
            if age < 5:
                total += 0.5 * stp.INFO[k].bias * (1.0 - age / 5.0)
        return float(np.clip(total, -1.0, 1.0))

    def _level_score(self, zones: list[lv.Zone]) -> float:
        total = 0.0
        for z in zones:
            if z.role == "support" and z.distance_atr <= 1.0:
                total += (z.strength / 100.0) * (1.0 - z.distance_atr) * 0.8
            elif z.role == "resistance" and z.distance_atr <= 1.0:
                total -= (z.strength / 100.0) * (1.0 - z.distance_atr) * 0.8
        return float(np.clip(total, -1.0, 1.0))

    def _divergence_score(self, ds: list[dv.Divergence]) -> float:
        total = 0.0
        for d in ds:
            w = (1.0 if d.strong else 0.6) * (1.0 if d.kind.startswith("regular") else 0.5)
            total += w if d.bullish else -w
        return float(np.clip(total, -1.0, 1.0))

    def _candle_score(self, cs: list[cdl.CandleHit]) -> float:
        total = 0.0
        for c in cs:
            age = self.i - c.index
            if age > 2:
                continue
            w = 1.0 - age / 3.0
            if c.info.bias == "bullish":
                total += w
            elif c.info.bias == "bearish":
                total -= w
        return float(np.clip(total, -1.0, 1.0))

    # ------------------------------------------------------------ findings as JSON

    def _zone(self, z: lv.Zone) -> dict[str, Any]:
        what = {"support": "Support", "resistance": "Resistance", "testing": "Testing"}[z.role]
        return {
            "low": round(z.low, 4),
            "high": round(z.high, 4),
            "center": round(z.center, 4),
            "role": z.role,
            "strength": z.strength,
            "touches": z.count,
            "flipped": z.flipped,
            "from_ts": self.ts(z.first_index),
            "label": f"{what} {self.px(z.center)} ({z.count} touch{'es' if z.count != 1 else ''})",
        }

    def _line(self, ln: tl.TrendLine) -> dict[str, Any]:
        end = ln.broken_at if ln.broken_at is not None else self.i + 5
        word = "support" if ln.kind == "support" else "resistance"
        label = f"{ln.direction.capitalize()} {word} line ({ln.touches} touches)"
        if ln.broken_at is not None:
            label += ", broken"
        return {
            "kind": ln.kind,
            "from": self.pt(ln.i1, ln.p1),
            "to": self.pt(end, ln.value_at(end)),
            "touches": ln.touches,
            "broken": ln.broken_at is not None,
            "broken_ts": self.ts(ln.broken_at) if ln.broken_at is not None else None,
            "value_now": round(ln.value_at(self.i), 4),
            "label": label,
        }

    def _bound(self, lvl: cp.Level | None, start: int, end: int) -> dict[str, Any] | None:
        if lvl is None:
            return None
        return {"from": self.pt(start, lvl.at(start)), "to": self.pt(end, lvl.at(end))}

    def _pattern(self, p: cp.ChartPattern) -> dict[str, Any]:
        stop_draw = (
            p.resolved if p.resolved is not None else min(self.i + 5, (p.event or self.i) + 5)
        )
        start = p.start
        d = 1 if p.bias == "bullish" else -1 if p.bias == "bearish" else 0
        direction = "up" if d > 0 else "down"
        key = f"pattern:{p.key}:{direction}"
        return {
            "key": p.key,
            "name": p.name,
            "bias": p.bias,
            "status": p.status,
            "confidence": p.confidence,
            "provisional": p.provisional,
            "points": [self.pt(q.index, q.price, q.label) for q in p.points],
            "upper": self._bound(p.upper, start, stop_draw),
            "lower": self._bound(p.lower, start, stop_draw),
            "trigger": p.trigger,
            "target": p.target,
            "stop": p.stop,
            "start_ts": self.ts(start),
            "event_ts": self.ts(p.event) if p.event is not None else None,
            "resolved_ts": self.ts(p.resolved) if p.resolved is not None else None,
            "volume_confirmed": p.volume_confirmed,
            "explanation": self._explain(p),
            "stats": self.stat(key),
        }

    def _explain(self, p: cp.ChartPattern) -> str:
        what = {
            "double_top": "two peaks at about the same price",
            "double_bottom": "two lows at about the same price",
            "triple_top": "three peaks at about the same price",
            "triple_bottom": "three lows at about the same price",
            "head_shoulders": "a higher peak between two lower, similar peaks",
            "inverse_head_shoulders": "a deeper low between two shallower, similar lows",
            "ascending_triangle": "a flat ceiling with rising lows pressing up into it",
            "descending_triangle": "a flat floor with falling highs pressing down on it",
            "symmetrical_triangle": "falling highs and rising lows squeezing together",
            "rising_wedge": "a rising, narrowing channel (buyers tiring)",
            "falling_wedge": "a falling, narrowing channel (sellers tiring)",
            "rectangle": "a flat range between a ceiling and a floor",
            "broadening": "swings getting wider in both directions",
            "bull_flag": "a sharp rise (the pole) and a small drift lower",
            "bear_flag": "a sharp drop (the pole) and a small drift higher",
            "bull_pennant": "a sharp rise and a small narrowing pause",
            "bear_pennant": "a sharp drop and a small narrowing pause",
            "cup_handle": "a rounded bottom between two similar highs",
        }.get(p.key) or cpw.explain(p.key)
        text = f"{p.name}: {what}."
        if p.status == "forming":
            way = "above" if p.bias != "bearish" else "below"
            text += f" Not confirmed yet: it needs a close {way} {self.px(p.trigger)}."
            if p.provisional:
                text += " The last turn is still forming."
        elif p.status == "confirmed":
            way = "up" if p.direction > 0 else "down"
            vol = " on strong volume" if p.volume_confirmed else ""
            text += f" It broke {way}{vol} at {self.px(p.trigger)}."
        elif p.status == "target":
            text += f" It broke out and reached its target of {self.px(p.target)}."
        elif p.status == "failed":
            text += (
                " It failed: the price moved against the pattern, which often leads to a"
                " fast move the other way."
            )
        if p.status in ("forming", "confirmed"):
            text += (
                f" Measured target {self.px(p.target)}; the idea is wrong below {self.px(p.stop)}."
                if p.bias != "bearish"
                else f" Measured target {self.px(p.target)}; the idea is wrong above "
                f"{self.px(p.stop)}."
            )
        return text

    def _setup(self, i: int, key: str) -> dict[str, Any]:
        info = stp.INFO[key]
        return {
            "ts": self.ts(i),
            "key": key,
            "name": info.name,
            "bias": "bullish" if info.bias > 0 else "bearish",
            "meaning": info.meaning,
            "price": round(float(self.s.close[i]), 4),
            "stats": self.stat(f"setup:{key}"),
        }

    def _candle(self, c: cdl.CandleHit) -> dict[str, Any]:
        info = c.info
        return {
            "ts": self.ts(c.index),
            "key": info.key,
            "name": info.name,
            "bias": info.bias,
            "meaning": info.meaning,
            "high": round(float(self.s.high[c.index]), 4),
            "low": round(float(self.s.low[c.index]), 4),
            "stats": self.stat(f"candle:{info.key}"),
        }

    def _divergence(self, d: dv.Divergence) -> dict[str, Any]:
        return {
            "kind": d.kind,
            "label": d.label,
            "bullish": d.bullish,
            "strong": d.strong,
            "from": self.pt(d.a.index, d.a.price),
            "to": self.pt(d.b.index, d.b.price),
            "rsi_from": d.rsi_a,
            "rsi_to": d.rsi_b,
            "known_ts": self.ts(d.known_at),
            "stats": self.stat(f"divergence:{d.kind}"),
        }

    def _fib(self, f: fb.Fibonacci | None) -> dict[str, Any] | None:
        if f is None:
            return None
        return {
            "up": f.up,
            "from": self.pt(f.start.index, f.start.price),
            "to": self.pt(f.end.index, f.end.price),
            "levels": [
                {"ratio": x.ratio, "price": round(x.price, 4), "label": x.label} for x in f.levels
            ],
            "nearest": f.nearest.label if f.nearest else None,
        }

    # ------------------------------------------------------------ the idea

    def _idea(
        self, bias: str, ps: list[cp.ChartPattern], zones: list[lv.Zone]
    ) -> dict[str, Any] | None:
        """An educational trade plan. If buying here offers less than 1.5× the risk, try the
        entry a patient trader would wait for (a dip to support / a bounce to resistance);
        if that isn't good either, say there's no trade rather than force one."""
        if bias == "neutral" or self.a <= 0:
            return None
        d = 1 if bias == "bullish" else -1
        main = next(
            (
                p
                for p in ps
                if p.status in ("forming", "confirmed")
                and (1 if p.bias == "bullish" else -1 if p.bias == "bearish" else 0) == d
            ),
            None,
        )
        entry, wait = self.close, "now"
        if main is not None and main.status == "forming" and d * (main.trigger - self.close) > 0:
            entry, wait = main.trigger, "breakout"
        plan = self._plan(d, entry, wait, main, zones)
        if plan["reward_risk"] < 1.5 and wait == "now":
            side = "support" if d > 0 else "resistance"
            near = [z for z in zones if z.role == side and 0 < z.distance_atr <= 3]
            if near:
                z = min(near, key=lambda z: z.distance_atr)
                alt = self._plan(d, z.high if d > 0 else z.low, "pullback", main, zones)
                if alt["reward_risk"] >= 1.5:
                    plan = alt
        if plan["reward_risk"] < 1.5:
            plan["quality"] = "poor"
            plan["text"] = (
                f"No good trade right now: the nearest target ({self.px(plan['target'])}) is too "
                f"close for a sensible stop ({self.px(plan['stop'])}). Waiting is a position too."
            )
        return plan

    def _plan(
        self,
        d: int,
        entry: float,
        wait: str,
        main: cp.ChartPattern | None,
        zones: list[lv.Zone],
    ) -> dict[str, Any]:
        stops: list[float] = []
        if main is not None and main.stop and d * (entry - main.stop) > 0:
            stops.append(main.stop)
        side = "support" if d > 0 else "resistance"
        below = [
            z for z in zones if z.role == side and d * (entry - (z.low if d > 0 else z.high)) > 0
        ]
        if below:
            z = min(below, key=lambda z: abs(entry - z.center))
            stops.append(z.low - 0.25 * self.a if d > 0 else z.high + 0.25 * self.a)
        if stops:
            stop = max(stops) if d > 0 else min(stops)
        else:
            stop = entry - d * 2.0 * self.a
        risk = d * (entry - stop)
        if risk < 1.0 * self.a:
            stop, risk = entry - d * 1.0 * self.a, 1.0 * self.a
        elif risk > 4.0 * self.a:
            stop, risk = entry - d * 2.5 * self.a, 2.5 * self.a
        targets: list[float] = []
        if main is not None and d * (main.target - entry) > 0:
            targets.append(main.target)
        other = "resistance" if d > 0 else "support"
        ahead = [
            z for z in zones if z.role == other and d * ((z.low if d > 0 else z.high) - entry) > 0
        ]
        if ahead:
            z = min(ahead, key=lambda z: abs(z.center - entry))
            lvl = z.low if d > 0 else z.high
            if d * (lvl - entry) >= 1.5 * risk or not targets:
                targets.append(lvl)
        target = min(targets, key=lambda t: d * (t - entry)) if targets else entry + d * 2.5 * risk
        rr = d * (target - entry) / risk if risk > 0 else 0.0
        can_short = self.m is Market.US
        action = "Buy" if d > 0 else ("Sell short" if can_short else "Sell or avoid")
        if wait == "breakout":
            how = f"on a close {'above' if d > 0 else 'below'} {self.px(entry)}"
        elif wait == "pullback":
            how = f"on a {'dip' if d > 0 else 'bounce'} to {self.px(entry)}"
        else:
            how = f"near {self.px(entry)}"
        return {
            "direction": "long" if d > 0 else "short",
            "action": action,
            "entry": round(entry, 4),
            "wait": wait,
            "stop": round(stop, 4),
            "target": round(target, 4),
            "reward_risk": round(rr, 2),
            "risk_pct": round(100.0 * risk / entry, 2) if entry else 0.0,
            "quality": "good" if rr >= 2 else "fair",
            "text": (
                f"{action} {how}, stop {self.px(stop)}, target {self.px(target)} "
                f"(reward {rr:.1f}× the risk). An educational idea, not advice."
            ),
        }

    def _invalidation(
        self, bias: str, idea: dict[str, Any] | None, zones: list[lv.Zone]
    ) -> str | None:
        if idea is not None and idea.get("quality") != "poor":
            way = "below" if bias == "bullish" else "above"
            return f"A close {way} {self.px(idea['stop'])} would cancel this view."
        sup = [z for z in zones if z.role == "support"]
        res = [z for z in zones if z.role == "resistance"]
        if sup and res:
            s = min(sup, key=lambda z: z.distance_atr)
            r = min(res, key=lambda z: z.distance_atr)
            return (
                f"Waiting for a direction: a close above {self.px(r.high)} or below "
                f"{self.px(s.low)} would decide it."
            )
        return None

    # ------------------------------------------------------------ words

    def _headline(self, regime: str, ps: list[cp.ChartPattern], bias: str) -> str:
        lead = regime.capitalize()
        if ps:
            p = ps[0]
            state = {
                "forming": "forming",
                "confirmed": "confirmed",
                "target": "completed",
                "failed": "failed",
            }.get(p.status, p.status)
            return f"{lead} · {p.name.lower()} {state}"
        return f"{lead} · {bias}"

    def _summary(
        self,
        out: dict[str, Any],
        trend: Any,
        ps: list[cp.ChartPattern],
        zones: list[lv.Zone],
        divs: list[dv.Divergence],
        candles: list[cdl.CandleHit],
    ) -> list[str]:
        lines: list[str] = []
        sym = self.an.symbol
        bits: list[str] = []
        if np.isfinite(trend.sma200) and trend.sma200:
            bits.append(
                ("above" if self.close > trend.sma200 else "below") + " its 200-candle average"
            )
        if trend.structure > 0:
            bits.append("making higher highs and higher lows")
        elif trend.structure < 0:
            bits.append("making lower highs and lower lows")
        tail = f": {', '.join(bits)}" if bits else ""
        lines.append(f"{sym} is in a {trend.regime} (trend score {trend.score:+.0f}){tail}.")
        for p in ps[:2]:
            lines.append(self._explain(p))
        sup = sorted((z for z in zones if z.role == "support"), key=lambda z: z.distance_atr)
        res = sorted((z for z in zones if z.role == "resistance"), key=lambda z: z.distance_atr)
        test = [z for z in zones if z.role == "testing"]
        lv_bits: list[str] = []
        if test:
            lv_bits.append(
                f"it is testing {self.px(test[0].low)}–{self.px(test[0].high)} right now"
            )
        if sup:
            lv_bits.append(
                f"nearest support {self.px(sup[0].low)}–{self.px(sup[0].high)} "
                f"({sup[0].count} touches)"
            )
        if res:
            lv_bits.append(
                f"nearest resistance {self.px(res[0].low)}–{self.px(res[0].high)} "
                f"({res[0].count} touches)"
            )
        if lv_bits:
            text = "; ".join(lv_bits)
            lines.append(text[0].upper() + text[1:] + ".")
        mom = out["momentum"]
        side = "above" if mom["macd_above_signal"] else "below"
        mtxt = f"RSI {mom['rsi']:.0f} ({mom['rsi_state']}); MACD {side} its signal line"
        lines.append(mtxt + ".")
        lines += [n + "." for n in out["volume"]["notes"][:2]]
        if divs:
            d = divs[-1]
            lines.append(f"{d.label}: price and RSI disagree ({d.rsi_a:.0f} → {d.rsi_b:.0f}).")
        for i, k in out.get("_setup_hits", [])[-2:]:
            info = stp.INFO[k]
            when = "today" if i == self.i else f"{self.i - i} candles ago"
            lines.append(f"Setup {when}: {info.name.lower()}. {info.meaning}")
        if candles and self.i - candles[-1].index <= 1 and candles[-1].info.bias != "neutral":
            c = candles[-1].info
            lines.append(f"Latest candle: {c.name.lower()}. {c.meaning}")
        conf = out["confidence"]
        lines.append(
            f"Overall: {out['bias']} (score {out['score']:+.0f} of 100, {conf} confidence)."
        )
        return lines


def _trend_json(t: Any) -> dict[str, Any]:
    def f(x: float) -> float | None:
        return None if not np.isfinite(x) else x

    return {
        "score": t.score,
        "regime": t.regime,
        "ma_stack": t.ma_stack,
        "structure": t.structure,
        "slope_atr": t.slope_atr,
        "adx": f(t.adx),
        "ema20": f(t.ema20),
        "sma50": f(t.sma50),
        "sma200": f(t.sma200),
        "atr": t.atr,
        "atr_pct": t.atr_pct,
        "volatility": t.volatility,
    }


def future_times(series: BarSeries, count: int) -> list[int]:
    """Approximate timestamps of the next ``count`` candles (weekdays only; holidays and
    clock changes ignored) so lines and forecasts can be drawn to the right of today."""
    if len(series) == 0:
        return []
    ts = int(series.ts[-1])
    tf = series.timeframe
    if not tf.is_intraday:
        out: list[int] = []
        t = ms_to_dt(ts, UTC)
        while len(out) < count:
            t += timedelta(days=1)
            if t.weekday() < 5:
                out.append(int(t.timestamp() * 1000))
        return out
    step = tf.minutes * 60_000
    sess_open = int(series.session_open[-1])
    # Session length from the last complete session (or this one).
    sess = series.session
    prev_mask = sess == sess[-1] - 1
    ref = series.ts[prev_mask] if prev_mask.any() else series.ts[sess == sess[-1]]
    ref_open = int(series.session_open[prev_mask][0]) if prev_mask.any() else sess_open
    length = int(ref.max()) - ref_open if len(ref) else 6 * 3_600_000
    out = []
    t_ms = ts
    while len(out) < count:
        t_ms += step
        if t_ms - sess_open > length:
            d = ms_to_dt(sess_open, UTC)
            d += timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            sess_open = int(d.timestamp() * 1000)
            t_ms = sess_open
        out.append(t_ms)
    return out


def analyze(
    series: BarSeries,
    market: Market,
    symbol: str,
    *,
    name: str = "",
    stats: StatsLookup = _none,
    window: int = 500,
) -> dict[str, Any]:
    """The full chart report for the latest candle of ``series`` (≥ 30 candles)."""
    if len(series) < 30:
        raise ValueError("Kairos needs at least 30 candles to read a chart.")
    return Analysis(series, market, symbol, name).report(stats, window)


__all__ = ["Analysis", "Swing", "analyze", "future_times", "price"]
