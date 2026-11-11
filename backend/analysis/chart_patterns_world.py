"""More chart patterns, found from the same swings (Phase 10.3).

**Harmonic patterns** (Gartley 1935; Carney, Pesavento, Gilmore; Oglesbee's Cypher) are
five-point zig-zags X-A-B-C-D whose legs stand in Fibonacci ratios. Ratios used (absolute
leg lengths, the same for bullish and bearish shapes; each range widened by 3% for swing
measurement):

| Pattern | B (of XA) | C (of AB) | D | CD (of BC) |
|---|---|---|---|---|
| Gartley | 0.618 | 0.382–0.886 | 0.786 of XA | 1.272–1.618 |
| Bat | 0.382–0.50 | 0.382–0.886 | 0.886 of XA | 1.618–2.618 |
| Alternate bat | ≤ 0.382 | 0.382–0.886 | 1.13 of XA | 2.0–3.618 |
| Butterfly | 0.786 | 0.382–0.886 | 1.27–1.618 of XA | 1.618–2.618 |
| Crab | 0.382–0.618 | 0.382–0.886 | 1.618 of XA | 2.24–3.618 |
| Deep crab | 0.886 | 0.382–0.886 | 1.618 of XA | 2.0–3.618 |
| Cypher | 0.382–0.618 | C beyond A: 1.272–1.414 of XA (from X) | 0.786 of XC | — |
| Shark | 0.382–0.886 | C beyond A: 1.13–1.618 of AB | 0.886–1.13 of XC | 1.618–2.24 |

Single values get ±0.05. Sources: capital.com's harmonic table, LuxAlgo's Cypher, 5-0,
AB=CD and three-drives pages (read 2026-10-22); they agree on every value they share.

A harmonic completes at D, the "potential reversal zone". It is *confirmed* when a close
moves 1 ATR (or 23.6% of CD, whichever is more) back from D; it *fails* on a close 1 ATR
beyond D. The usual first target is a 61.8% retracement of AD.

**AB=CD**: a four-point zig-zag whose CD leg equals AB (±10%), or extends it 1.272× or
1.618×, after a 38.2–88.6% BC retracement. **Three drives**: three pushes in one direction,
each 1.13–1.9× the pullback before it, pullbacks retracing 50–88.6%; it signals
exhaustion. **Rounding top**: the mirror of the cup, a dome between two similar lows.

Everything a pattern reports as known at candle *i* uses candles ``0..i`` only.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from backend.analysis import chart_patterns as cp
from backend.analysis.chart_patterns import ChartPattern, Level, Point
from backend.analysis.swings import Swing
from backend.indicators.series import F64

SLACK = 0.03  # published ratio ranges are widened by 3%
SINGLE = 0.05  # a single published value gets ± this

NAMES: dict[str, tuple[str, cp.Bias]] = {
    "gartley_bull": ("Bullish Gartley", "bullish"),
    "gartley_bear": ("Bearish Gartley", "bearish"),
    "bat_bull": ("Bullish bat", "bullish"),
    "bat_bear": ("Bearish bat", "bearish"),
    "alt_bat_bull": ("Bullish alternate bat", "bullish"),
    "alt_bat_bear": ("Bearish alternate bat", "bearish"),
    "butterfly_bull": ("Bullish butterfly", "bullish"),
    "butterfly_bear": ("Bearish butterfly", "bearish"),
    "crab_bull": ("Bullish crab", "bullish"),
    "crab_bear": ("Bearish crab", "bearish"),
    "deep_crab_bull": ("Bullish deep crab", "bullish"),
    "deep_crab_bear": ("Bearish deep crab", "bearish"),
    "cypher_bull": ("Bullish cypher", "bullish"),
    "cypher_bear": ("Bearish cypher", "bearish"),
    "shark_bull": ("Bullish shark", "bullish"),
    "shark_bear": ("Bearish shark", "bearish"),
    "abcd_bull": ("Bullish AB=CD", "bullish"),
    "abcd_bear": ("Bearish AB=CD", "bearish"),
    "three_drives_bull": ("Three drives bottom", "bullish"),
    "three_drives_bear": ("Three drives top", "bearish"),
    "rounding_top": ("Rounding top", "bearish"),
    "ascending_channel": ("Rising channel", "neutral"),
    "descending_channel": ("Falling channel", "neutral"),
}
RANK: dict[str, int] = {k: 4 for k in NAMES}
# A wedge or triangle with three pushes is often also a three-drives shape: the classic name
# wins where both fit, as it does over the AB=CD and channel readings inside bigger shapes.
RANK.update(
    {
        "abcd_bull": 3,
        "abcd_bear": 3,
        "three_drives_bull": 3,
        "three_drives_bear": 3,
        "rounding_top": 5,
        "ascending_channel": 3,
        "descending_channel": 3,
    }
)
EXPLAIN: dict[str, str] = {
    "gartley": "a five-point zig-zag whose B retraces 61.8% and D 78.6% of the first leg (Gartley)",
    "bat": "a five-point zig-zag whose B retraces 38.2–50% and D 88.6% of the first leg (bat)",
    "alt_bat": "a five-point zig-zag whose D overshoots the start by 13% (alternate bat)",
    "butterfly": "a five-point zig-zag whose D extends 127–162% beyond the first leg (butterfly)",
    "crab": "a five-point zig-zag whose D extends to 161.8% of the first leg (crab)",
    "deep_crab": "a crab with a deep 88.6% B point",
    "cypher": "a zig-zag whose C overshoots A and D retraces 78.6% of X to C (cypher)",
    "shark": "a zig-zag whose C overshoots A and D returns to the start of the move (shark)",
    "abcd": "two equal legs separated by a pullback (AB=CD)",
    "three_drives": "three pushes one way, each a Fibonacci extension of the pullback before it",
    "rounding_top": "a slow dome between two similar lows",
    "ascending_channel": "price climbing between two parallel rising lines",
    "descending_channel": "price falling between two parallel falling lines",
}


def explain(key: str) -> str:
    base = key.removesuffix("_bull").removesuffix("_bear")
    return EXPLAIN.get(key) or EXPLAIN[base]


def _in(v: float, lo: float, hi: float) -> bool:
    if lo == hi:
        return lo - SINGLE <= v <= hi + SINGLE
    return lo * (1 - SLACK) <= v <= hi * (1 + SLACK)


def _miss(v: float, lo: float, hi: float) -> float:
    """0 at the centre of the range, 1 at its widened edge."""
    half = (hi - lo) / 2 if hi > lo else SINGLE
    centre = (hi + lo) / 2
    return float(min(1.0, abs(v - centre) / max(half * (1 + SLACK), 1e-9)))


# (key, B of XA, D of XA, CD of BC); C of AB is 0.382–0.886 for all.
XABCD: tuple[tuple[str, tuple[float, float], tuple[float, float], tuple[float, float]], ...] = (
    ("gartley", (0.618, 0.618), (0.786, 0.786), (1.272, 1.618)),
    ("bat", (0.382, 0.50), (0.886, 0.886), (1.618, 2.618)),
    ("alt_bat", (0.25, 0.382), (1.13, 1.13), (2.0, 3.618)),
    ("butterfly", (0.786, 0.786), (1.27, 1.618), (1.618, 2.618)),
    ("crab", (0.382, 0.618), (1.618, 1.618), (2.24, 3.618)),
    ("deep_crab", (0.886, 0.886), (1.618, 1.618), (2.0, 3.618)),
)


def _reversal_pattern(
    key: str,
    pts: Sequence[Point],
    seq: Sequence[Swing],
    d: Swing,
    sgn: int,
    target: float,
    atr: float,
    conf: float,
    last: int,
    span: float,
) -> ChartPattern:
    """A pattern that completes at ``d`` and trades a reversal from it (``sgn`` +1 = up)."""
    trig = d.price + sgn * max(1.0 * atr, 0.236 * span)
    fail = d.price - sgn * 1.0 * atr
    height = sgn * (target - trig)
    if height <= 0.5 * atr:
        height = max(0.5 * atr, 0.382 * abs(target - d.price))
    formed = cp._formed(seq, last)
    upper, lower = (Level(d.index, trig), Level(d.index, fail))
    if sgn < 0:
        upper, lower = Level(d.index, fail), Level(d.index, trig)
    return cp._pattern(
        key,
        pts,
        upper=upper,
        lower=lower,
        allowed={sgn},
        height=height,
        stop_up=fail,
        stop_down=fail,
        seq=seq,
        atr=atr,
        confidence=conf,
        last=last,
        deadline=formed + 20,
    )


def harmonic(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    x, a, b, c, d = seq
    bull = d.kind == "L"
    sgn = 1 if bull else -1
    xa, ab = abs(a.price - x.price), abs(b.price - a.price)
    bc, cd = abs(c.price - b.price), abs(d.price - c.price)
    if xa < 3.0 * atr or min(ab, bc, cd) < 1.0 * atr:
        return None
    rb, rc, rcd = ab / xa, bc / ab, cd / bc
    beyond_a = sgn * (a.price - c.price) < 0  # bullish: C above A
    found: tuple[str, float] | None = None
    if beyond_a:
        xc = abs(c.price - x.price)
        rxc, rdc = xc / xa, cd / xc
        if _in(rb, 0.382, 0.618) and _in(rxc, 1.272, 1.414) and _in(rdc, 0.786, 0.786):
            miss = (
                _miss(rb, 0.382, 0.618) + _miss(rxc, 1.272, 1.414) + _miss(rdc, 0.786, 0.786)
            ) / 3
            found = ("cypher", miss)
        elif (
            _in(rb, 0.382, 0.886)
            and _in(rc, 1.13, 1.618)
            and _in(rdc, 0.886, 1.13)
            and _in(rcd, 1.618, 2.24)
        ):
            miss = (_miss(rc, 1.13, 1.618) + _miss(rdc, 0.886, 1.13) + _miss(rcd, 1.618, 2.24)) / 3
            found = ("shark", miss)
    elif _in(rc, 0.382, 0.886):
        rd = abs(a.price - d.price) / xa
        for key, (b0, b1), (d0, d1), (e0, e1) in XABCD:
            if _in(rb, b0, b1) and _in(rd, d0, d1) and _in(rcd, e0, e1):
                found = (key, (_miss(rb, b0, b1) + _miss(rd, d0, d1) + _miss(rcd, e0, e1)) / 3)
                break
    if found is None:
        return None
    name, miss = found
    key = f"{name}_{'bull' if bull else 'bear'}"
    pts = [
        Point(x.index, x.price, "X"),
        Point(a.index, a.price, "A"),
        Point(b.index, b.price, "B"),
        Point(c.index, c.price, "C"),
        Point(d.index, d.price, "D"),
    ]
    target = d.price + sgn * 0.618 * abs(a.price - d.price)
    conf = 0.5 + 0.3 * (1.0 - miss)
    return _reversal_pattern(key, pts, seq, d, sgn, target, atr, conf, last, cd)


AB_CD = ((0.9, 1.1), (1.2, 1.35), (1.55, 1.7))  # CD ≈ AB, or 1.272× / 1.618× AB


def abcd(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    a, b, c, d = seq
    bull = d.kind == "L"
    sgn = 1 if bull else -1
    ab, bc, cd = abs(b.price - a.price), abs(c.price - b.price), abs(d.price - c.price)
    if ab < 2.0 * atr or cd < 2.0 * atr or not _in(bc / ab, 0.382, 0.886):
        return None
    if sgn * (b.price - d.price) <= 0:  # D must go beyond B
        return None
    ratio = cd / ab
    band = next(((lo, hi) for lo, hi in AB_CD if lo <= ratio <= hi), None)
    if band is None:
        return None
    pts = [
        Point(a.index, a.price, "A"),
        Point(b.index, b.price, "B"),
        Point(c.index, c.price, "C"),
        Point(d.index, d.price, "D"),
    ]
    conf = 0.45 + 0.25 * (1.0 - _miss(ratio, *band))
    target = d.price + sgn * 0.618 * abs(a.price - d.price)
    key = "abcd_bull" if bull else "abcd_bear"
    return _reversal_pattern(key, pts, seq, d, sgn, target, atr, conf, last, cd)


def three_drives(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    s0, d1, r1, d2, r2, d3 = seq
    bull = d3.kind == "L"  # three drives down → a bottom
    sgn = 1 if bull else -1
    # drives move the -sgn way: each new extreme beyond the last
    if not (sgn * (d1.price - d2.price) > 0 and sgn * (d2.price - d3.price) > 0):
        return None
    leg0 = abs(s0.price - d1.price)
    back1, push2 = abs(r1.price - d1.price), abs(r1.price - d2.price)
    back2, push3 = abs(r2.price - d2.price), abs(r2.price - d3.price)
    if min(leg0, push2, push3) < 2.0 * atr or min(back1, back2) < 1.0 * atr:
        return None
    rets = (back1 / leg0, back2 / push2)
    exts = (push2 / back1, push3 / back2)
    if not all(_in(v, 0.5, 0.886) for v in rets) or not all(_in(v, 1.13, 1.9) for v in exts):
        return None
    miss = sum(_miss(v, 0.5, 0.886) for v in rets) + sum(_miss(v, 1.13, 1.9) for v in exts)
    pts = [
        Point(d1.index, d1.price, "Drive 1"),
        Point(r1.index, r1.price, ""),
        Point(d2.index, d2.price, "Drive 2"),
        Point(r2.index, r2.price, ""),
        Point(d3.index, d3.price, "Drive 3"),
    ]
    conf = 0.5 + 0.3 * (1.0 - miss / 4)
    key = "three_drives_bull" if bull else "three_drives_bear"
    return _reversal_pattern(key, pts, seq, d3, sgn, r2.price, atr, conf, last, push3)


def rounding_top(seq: Sequence[Swing], close: F64, atr: float, last: int) -> ChartPattern | None:
    """The mirror of the cup: the last swing is the right low; look back 20-200 candles for
    a left low at about the same price, with a dome-shaped rise and fall between and
    nothing closing below the two lows."""
    right = seq[-1]
    if right.kind != "L":
        return None
    for j in range(len(seq) - 3, -1, -1):
        left = seq[j]
        gap = right.index - left.index
        if left.kind != "L" or gap < 20:
            continue
        if gap > 200:
            break
        rim = max(left.price, right.price)
        if abs(left.price - right.price) > max(1.5 * atr, 0.04 * rim):
            continue
        inside = close[left.index + 1 : right.index]
        highs = [w for w in seq[j + 1 : -1] if w.kind == "H"]
        if not len(inside) or not highs or float(inside.min()) < rim - 0.25 * atr:
            continue
        peak = max(highs, key=lambda w: w.price)
        depth = peak.price - rim
        if depth < 3.0 * atr or depth > 0.5 * rim:
            continue
        x = np.arange(gap + 1, dtype=np.float64)
        y = close[left.index : right.index + 1]
        a2, a1, a0 = np.polyfit(x, y, 2)
        fitted = a2 * x**2 + a1 * x + a0
        ss = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - float(np.sum((y - fitted) ** 2)) / ss if ss > 0 else 0.0
        vertex = -a1 / (2 * a2) / gap if a2 < 0 else -1.0
        if a2 >= 0 or r2 < 0.5 or not 0.25 <= vertex <= 0.75:
            continue
        floor = min(left.price, right.price)
        pts = [
            Point(left.index, left.price, "Left low"),
            Point(peak.index, peak.price, "Dome"),
            Point(right.index, right.price, "Right low"),
        ]
        conf = 0.5 + 0.3 * min(1.0, (r2 - 0.5) / 0.4)
        return cp._pattern(
            "rounding_top",
            pts,
            upper=Level(right.index, rim + depth / 2),
            lower=Level(right.index, floor),
            allowed={-1},
            height=depth,
            stop_up=floor,
            stop_down=rim + depth / 2,
            seq=[left, peak, right],
            atr=atr,
            confidence=conf,
            last=last,
        )
    return None


def from_swings(
    seq: Sequence[Swing], close: F64, atr: float, last: int, *, major: bool = False
) -> list[ChartPattern]:
    """The Phase 10.3 shapes that end with the last swing of ``seq``."""
    out: list[ChartPattern] = []
    if len(seq) >= 5:
        hm = harmonic(seq[-5:], atr, last)
        if hm:
            out.append(hm)
    if not out and len(seq) >= 4:
        ad = abcd(seq[-4:], atr, last)
        if ad:
            out.append(ad)
    if len(seq) >= 6:
        td = three_drives(seq[-6:], atr, last)
        if td:
            out.append(td)
    if not major and len(seq) >= 3:
        rt = rounding_top(seq, close, atr, last)
        if rt:
            out.append(rt)
    return out
