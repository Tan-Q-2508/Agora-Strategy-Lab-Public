"""Classic chart patterns, found from swings the way a chartist reads them (KAIROS §3).

Every pattern is described by the geometry of its turning points (tolerances in ATR, so
the same rules work for a ₹100 and a $900 stock, daily or 5-minute), a breakout *trigger*
line, a *stop* (where the idea is proved wrong), a measured-move *target* (the pattern's
height projected from the breakout) and a *status*:

- ``forming``: the shape is there, no breakout yet;
- ``confirmed``: a candle closed beyond the trigger (by 0.1 × ATR);
- ``target``: after confirming, the price reached the measured target;
- ``failed``: the price closed beyond the stop instead;
- ``expired``: no breakout in time (not shown).

Patterns and their direction:

| Pattern | Bias | Turning points |
|---|---|---|
| Double top / bottom | bearish / bullish | two equal peaks (troughs) with a dip (bounce) between |
| Triple top / bottom | bearish / bullish | three equal peaks (troughs) |
| Head and shoulders (+ inverse) | bearish (bullish) | a higher middle peak, two similar shoulders |
| Ascending / descending triangle | bullish / bearish | flat top + rising lows (or the mirror) |
| Symmetrical triangle | either way | falling highs + rising lows |
| Rising / falling wedge | bearish / bullish | both lines slope the same way and converge |
| Rectangle | either way | flat top and flat bottom |
| Broadening formation | either way | highs rising, lows falling |
| Bull / bear flag | bullish / bearish | a steep pole, then a small counter-drifting channel |
| Bull / bear pennant | bullish / bearish | a steep pole, then a small converging triangle |
| Cup and handle | bullish | a rounded bottom between two similar rims, then a shallow dip |

Everything a pattern reports as known at candle *i* uses candles ``0..i`` only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np

from backend.analysis.swings import Swing
from backend.indicators.series import F64

Bias = Literal["bullish", "bearish", "neutral"]
Status = Literal["forming", "confirmed", "target", "failed", "expired"]
BREAK = 0.1  # × ATR a close must clear a trigger by
EQUAL = 0.6  # × ATR: two peaks this close are "equal"
FLAT = 0.75  # × ATR: a boundary moving less than this over the pattern is flat

NAMES: dict[str, tuple[str, Bias]] = {
    "double_top": ("Double top", "bearish"),
    "double_bottom": ("Double bottom", "bullish"),
    "triple_top": ("Triple top", "bearish"),
    "triple_bottom": ("Triple bottom", "bullish"),
    "head_shoulders": ("Head and shoulders", "bearish"),
    "inverse_head_shoulders": ("Inverse head and shoulders", "bullish"),
    "ascending_triangle": ("Ascending triangle", "bullish"),
    "descending_triangle": ("Descending triangle", "bearish"),
    "symmetrical_triangle": ("Symmetrical triangle", "neutral"),
    "rising_wedge": ("Rising wedge", "bearish"),
    "falling_wedge": ("Falling wedge", "bullish"),
    "rectangle": ("Rectangle", "neutral"),
    "broadening": ("Broadening formation", "neutral"),
    "bull_flag": ("Bull flag", "bullish"),
    "bear_flag": ("Bear flag", "bearish"),
    "bull_pennant": ("Bull pennant", "bullish"),
    "bear_pennant": ("Bear pennant", "bearish"),
    "cup_handle": ("Cup and handle", "bullish"),
}


@dataclass(frozen=True)
class Level:
    """A straight line in candle-index space: ``price + slope × (i − index)``."""

    index: int
    price: float
    slope: float = 0.0

    def at(self, i: float) -> float:
        return self.price + self.slope * (i - self.index)


@dataclass(frozen=True)
class Point:
    index: int
    price: float
    label: str


@dataclass(frozen=True)
class ChartPattern:
    key: str
    points: tuple[Point, ...]
    upper: Level | None  # a close above it: bullish breakout (or failure if not allowed)
    lower: Level | None  # a close below it: bearish breakout (or failure)
    allowed: frozenset[int]  # breakout directions that confirm: {+1}, {-1} or both
    height: float  # the measured move
    stop_up: float  # after an upward breakout, a close below this fails it
    stop_down: float  # after a downward breakout, a close above this fails it
    start: int
    end: int  # last turning point
    formed: int  # candle on which the shape was recognisable
    confidence: float
    atr: float
    provisional: bool = False  # the last turning point isn't confirmed yet
    deadline: int | None = None  # no breakout by this candle → expired (e.g. a triangle's apex)
    status: Status = "forming"
    direction: int = 0  # +1 / -1 once confirmed
    event: int | None = None  # candle of the breakout (or failure)
    resolved: int | None = None  # candle the target was reached or the pattern failed
    trigger: float = 0.0  # breakout price (at the event, or at the latest candle)
    target: float = 0.0
    stop: float = 0.0
    volume_confirmed: bool = False
    notes: tuple[str, ...] = field(default=())

    @property
    def name(self) -> str:
        return NAMES[self.key][0]

    @property
    def bias(self) -> Bias:
        if self.direction:
            return "bullish" if self.direction > 0 else "bearish"
        return NAMES[self.key][1]


# ---------------------------------------------------------------- swing-based shapes


def _pattern(
    key: str,
    pts: Sequence[Point],
    *,
    upper: Level | None,
    lower: Level | None,
    allowed: set[int],
    height: float,
    stop_up: float,
    stop_down: float,
    seq: Sequence[Swing],
    atr: float,
    confidence: float,
    last: int,
    deadline: int | None = None,
) -> ChartPattern:
    provisional = seq[-1].confirmed < 0
    formed = _formed(seq, last)
    return ChartPattern(
        key=key,
        points=tuple(pts),
        upper=upper,
        lower=lower,
        allowed=frozenset(allowed),
        height=height,
        stop_up=stop_up,
        stop_down=stop_down,
        start=seq[0].index,
        end=seq[-1].index,
        formed=formed,
        confidence=round(float(min(0.95, confidence * (0.8 if provisional else 1.0))), 3),
        atr=atr,
        provisional=provisional,
        deadline=deadline,
    )


def _formed(seq: Sequence[Swing], last: int) -> int:
    """The candle on which the last turning point was known (``last`` if it isn't yet)."""
    return last if seq[-1].confirmed < 0 else max(s.confirmed for s in seq)


def _double(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    a, p1, mid, p2 = seq
    top = p1.kind == "H"
    sgn = 1.0 if top else -1.0
    if abs(p1.price - p2.price) > EQUAL * atr or p2.index - p1.index < 5:
        return None
    peak = max(p1.price, p2.price) if top else min(p1.price, p2.price)
    depth = sgn * (peak - mid.price)
    if depth < 2.0 * atr or sgn * (p1.price - a.price) < 2.0 * atr:
        return None
    eq = 1.0 - abs(p1.price - p2.price) / (EQUAL * atr)
    conf = (
        0.5
        + 0.2 * eq
        + 0.15 * min(1.0, depth / (4 * atr))
        + (0.1 if sgn * (a.price - mid.price) < 0 else 0)
    )
    neck = Level(mid.index, mid.price)
    word = "Top" if top else "Bottom"
    pts = [
        Point(p1.index, p1.price, f"{word} 1"),
        Point(mid.index, mid.price, "Neckline"),
        Point(p2.index, p2.price, f"{word} 2"),
    ]
    edge = Level(p1.index, peak)
    if top:
        return _pattern(
            "double_top",
            pts,
            upper=edge,
            lower=neck,
            allowed={-1},
            height=depth,
            stop_up=mid.price,
            stop_down=peak,
            seq=seq,
            atr=atr,
            confidence=conf,
            last=last,
        )
    return _pattern(
        "double_bottom",
        pts,
        upper=neck,
        lower=edge,
        allowed={1},
        height=depth,
        stop_up=peak,
        stop_down=mid.price,
        seq=seq,
        atr=atr,
        confidence=conf,
        last=last,
    )


def _triple(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    a, p1, m1, p2, m2, p3 = seq
    top = p1.kind == "H"
    sgn = 1.0 if top else -1.0
    peaks = [p1.price, p2.price, p3.price]
    if max(peaks) - min(peaks) > 0.8 * atr or min(p2.index - p1.index, p3.index - p2.index) < 4:
        return None
    if abs(m1.price - m2.price) <= EQUAL * atr:
        return None  # level dips too: that's a rectangle (a range), not a triple top
    peak = max(peaks) if top else min(peaks)
    neck_price = min(m1.price, m2.price) if top else max(m1.price, m2.price)
    depth = (
        sgn * (min(peaks) - max(m1.price, m2.price))
        if top
        else sgn * (max(peaks) - min(m1.price, m2.price))
    )
    if depth < 1.5 * atr or sgn * (p1.price - a.price) < 2.0 * atr:
        return None
    height = sgn * (peak - neck_price)
    conf = 0.6 + 0.2 * (1.0 - (max(peaks) - min(peaks)) / (0.8 * atr))
    word = "Top" if top else "Bottom"
    pts = [
        Point(p1.index, p1.price, f"{word} 1"),
        Point(m1.index, m1.price, ""),
        Point(p2.index, p2.price, f"{word} 2"),
        Point(m2.index, m2.price, ""),
        Point(p3.index, p3.price, f"{word} 3"),
    ]
    neck = Level(m1.index, neck_price)
    edge = Level(p1.index, peak)
    if top:
        return _pattern(
            "triple_top",
            pts,
            upper=edge,
            lower=neck,
            allowed={-1},
            height=height,
            stop_up=neck_price,
            stop_down=peak,
            seq=seq,
            atr=atr,
            confidence=conf,
            last=last,
        )
    return _pattern(
        "triple_bottom",
        pts,
        upper=neck,
        lower=edge,
        allowed={1},
        height=height,
        stop_up=peak,
        stop_down=neck_price,
        seq=seq,
        atr=atr,
        confidence=conf,
        last=last,
    )


def _head_shoulders(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    a, ls, n1, head, n2, rs = seq
    top = head.kind == "H"
    sgn = 1.0 if top else -1.0
    if sgn * (head.price - ls.price) < 0.5 * atr or sgn * (head.price - rs.price) < 0.5 * atr:
        return None
    slope = (n2.price - n1.price) / (n2.index - n1.index)
    neck = Level(n1.index, n1.price, slope)
    height = sgn * (head.price - neck.at(head.index))
    if height < 2.0 * atr or abs(n2.price - n1.price) > 0.6 * height:
        return None
    if abs(ls.price - rs.price) > max(1.0 * atr, 0.35 * height):
        return None
    if (
        sgn * (ls.price - neck.at(ls.index)) < 1.0 * atr
        or sgn * (rs.price - neck.at(rs.index)) < 1.0 * atr
    ):
        return None
    left, right = head.index - ls.index, rs.index - head.index
    if left <= 0 or right <= 0 or not 1 / 3 <= right / left <= 3:
        return None
    if sgn * (ls.price - a.price) < 1.5 * atr:
        return None
    sym = 1.0 - abs(ls.price - rs.price) / max(1.0 * atr, 0.35 * height)
    timing = 1.0 - abs(np.log(right / left)) / np.log(3)
    conf = 0.55 + 0.2 * sym + 0.15 * timing
    pts = [
        Point(ls.index, ls.price, "Left shoulder"),
        Point(n1.index, n1.price, ""),
        Point(head.index, head.price, "Head"),
        Point(n2.index, n2.price, ""),
        Point(rs.index, rs.price, "Right shoulder"),
    ]
    if top:
        return _pattern(
            "head_shoulders",
            pts,
            upper=Level(rs.index, rs.price),
            lower=neck,
            allowed={-1},
            height=height,
            stop_up=n2.price,
            stop_down=rs.price,
            seq=seq,
            atr=atr,
            confidence=conf,
            last=last,
        )
    return _pattern(
        "inverse_head_shoulders",
        pts,
        upper=neck,
        lower=Level(rs.index, rs.price),
        allowed={1},
        height=height,
        stop_up=rs.price,
        stop_down=n2.price,
        seq=seq,
        atr=atr,
        confidence=conf,
        last=last,
    )


def _boundaries(seq: Sequence[Swing], atr: float, last: int) -> ChartPattern | None:
    """Triangles, wedges, rectangles and broadening formations: two straight boundaries
    through the swing highs and the swing lows."""
    highs = [s for s in seq if s.kind == "H"]
    lows = [s for s in seq if s.kind == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    start, end = seq[0].index, seq[-1].index
    span = end - start
    if span < 10:
        return None
    up = Level(
        highs[0].index,
        highs[0].price,
        (highs[-1].price - highs[0].price) / (highs[-1].index - highs[0].index),
    )
    lo = Level(
        lows[0].index,
        lows[0].price,
        (lows[-1].price - lows[0].price) / (lows[-1].index - lows[0].index),
    )
    fit = max(
        [abs(s.price - up.at(s.index)) for s in highs]
        + [abs(s.price - lo.at(s.index)) for s in lows]
    )
    if fit > 0.6 * atr:
        return None
    w0, w1 = up.at(start) - lo.at(start), up.at(end) - lo.at(end)
    if w0 < 1.5 * atr or w1 <= 0:
        return None
    du, dl = up.slope * span / atr, lo.slope * span / atr
    flat_u, flat_l = abs(du) <= FLAT, abs(dl) <= FLAT
    converging, diverging = w1 < 0.85 * w0, w1 > 1.15 * w0
    key: str | None = None
    if flat_u and dl > FLAT and converging:
        key = "ascending_triangle"
    elif flat_l and du < -FLAT and converging:
        key = "descending_triangle"
    elif du < -FLAT and dl > FLAT and converging:
        key = "symmetrical_triangle"
    elif du > FLAT and dl > FLAT and converging:
        key = "rising_wedge"
    elif du < -FLAT and dl < -FLAT and converging:
        key = "falling_wedge"
    elif flat_u and flat_l and not converging and not diverging:
        key = "rectangle"
    elif du > FLAT and dl < -FLAT and diverging:
        key = "broadening"
    elif du > FLAT and dl > FLAT and not converging and not diverging:
        key = "ascending_channel"
    elif du < -FLAT and dl < -FLAT and not converging and not diverging:
        key = "descending_channel"
    if key is None:
        return None
    deadline: int | None = None
    if converging and up.slope != lo.slope:
        apex = lo.index + (up.at(lo.index) - lo.price) / (lo.slope - up.slope)
        if apex <= _formed(seq, last):
            return None  # the lines had already met: too late to call a breakout
        deadline = int(apex)
    bias = NAMES[key][1]
    allowed = {1, -1} if bias == "neutral" else ({1} if bias == "bullish" else {-1})
    touches = len(highs) + len(lows)
    conf = 0.45 + 0.08 * (touches - 4) + 0.2 * (1.0 - fit / (0.6 * atr))
    if key == "broadening":
        conf -= 0.15
    last_hi, last_lo = highs[-1].price, lows[-1].price
    pts = [Point(s.index, s.price, "") for s in seq]
    return _pattern(
        key,
        pts,
        upper=up,
        lower=lo,
        allowed=allowed,
        height=w0,
        stop_up=last_lo,
        stop_down=last_hi,
        seq=seq,
        atr=atr,
        confidence=conf,
        last=last,
        deadline=deadline,
    )


def _cup(seq: Sequence[Swing], close: F64, atr: float, last: int) -> ChartPattern | None:
    """The last swing is the right rim; look back 20-200 candles for a left rim at about
    the same height with a rounded bottom between and nothing poking above the rims."""
    right = seq[-1]
    if right.kind != "H":
        return None
    for j in range(len(seq) - 3, -1, -1):
        left = seq[j]
        gap = right.index - left.index
        if left.kind != "H" or gap < 20:
            continue
        if gap > 200:
            break
        rim = min(left.price, right.price)
        if abs(left.price - right.price) > max(1.5 * atr, 0.04 * rim):
            continue
        inside = close[left.index + 1 : right.index]
        lows = [w for w in seq[j + 1 : -1] if w.kind == "L"]
        if not len(inside) or not lows or float(inside.max()) > rim + 0.25 * atr:
            continue
        bottom = min(lows, key=lambda w: w.price)
        depth = rim - bottom.price
        if depth < 3.0 * atr or depth > 0.5 * rim:
            continue
        x = np.arange(gap + 1, dtype=np.float64)
        y = close[left.index : right.index + 1]
        a2, a1, a0 = np.polyfit(x, y, 2)
        fitted = a2 * x**2 + a1 * x + a0
        ss = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - float(np.sum((y - fitted) ** 2)) / ss if ss > 0 else 0.0
        vertex = -a1 / (2 * a2) / gap if a2 > 0 else -1.0
        if a2 <= 0 or r2 < 0.5 or not 0.25 <= vertex <= 0.75:
            continue
        top = max(left.price, right.price)
        pts = [
            Point(left.index, left.price, "Left rim"),
            Point(bottom.index, bottom.price, "Cup"),
            Point(right.index, right.price, "Right rim"),
        ]
        conf = 0.5 + 0.3 * min(1.0, (r2 - 0.5) / 0.4)
        sub = [left, bottom, right]
        return _pattern(
            "cup_handle",
            pts,
            upper=Level(right.index, top),
            lower=Level(right.index, rim - depth / 2),
            allowed={1},
            height=depth,
            stop_up=rim - depth / 2,
            stop_down=top,
            seq=sub,
            atr=atr,
            confidence=conf,
            last=last,
        )
    return None


def from_swings(
    seq: Sequence[Swing], close: F64, atr: float, last: int, *, major: bool = False
) -> list[ChartPattern]:
    """Every shape that ends with the last swing of ``seq`` (oldest first)."""
    out: list[ChartPattern] = []
    if atr <= 0 or not np.isfinite(atr):
        return out
    if len(seq) >= 6:
        hs = _head_shoulders(seq[-6:], atr, last)
        if hs:
            out.append(hs)
        else:
            tr = _triple(seq[-6:], atr, last)
            if tr:
                out.append(tr)
    if len(seq) >= 4 and not out:
        d = _double(seq[-4:], atr, last)
        if d:
            out.append(d)
    for k in (6, 5):  # four turning points is a double top/bottom, not a triangle
        if len(seq) >= k:
            b = _boundaries(seq[-k:], atr, last)
            if b:
                out.append(b)
                break
    if not major and len(seq) >= 3:
        c = _cup(seq, close, atr, last)
        if c:
            out.append(c)
    out += _world.from_swings(seq, close, atr, last, major=major)
    return out


# ---------------------------------------------------------------- flags and pennants


def flag_at(high: F64, low: F64, close: F64, atr: F64, i: int) -> ChartPattern | None:
    """A flag or pennant whose consolidation ends at candle ``i`` (and hasn't broken out),
    looking only at candles up to ``i``."""
    for sgn in (1, -1):
        p = _flag(high, low, close, atr, i, sgn)
        if p:
            return p
    return None


def _flag(high: F64, low: F64, close: F64, atr: F64, i: int, sgn: int) -> ChartPattern | None:
    lo_win = max(0, i - 24)
    if i - lo_win < 8:
        return None
    ext = high if sgn > 0 else low
    seg = ext[lo_win : i - 3]
    if not len(seg):
        return None
    t = lo_win + int(np.argmax(seg) if sgn > 0 else np.argmin(seg))
    m = i - t
    if not 4 <= m <= 20 or t < 4:
        return None
    a = float(atr[t])
    if not np.isfinite(a) or a <= 0:
        return None
    base = low if sgn > 0 else high
    s_lo = max(0, t - 15)
    seg2 = base[s_lo : t - 2]
    if not len(seg2):
        return None
    s = s_lo + int(np.argmin(seg2) if sgn > 0 else np.argmax(seg2))
    pole = sgn * (float(ext[t]) - float(base[s]))
    if pole < 3.5 * a or pole / max(t - s, 1) < 0.3 * a:
        return None
    hh, ll = high[t + 1 : i + 1], low[t + 1 : i + 1]
    if sgn > 0:
        if hh.max() > high[t] + 0.1 * a or ll.min() < high[t] - 0.5 * pole:
            return None
    elif ll.min() < low[t] - 0.1 * a or hh.max() > low[t] + 0.5 * pole:
        return None
    if hh.max() - ll.min() > 0.6 * pole:
        return None
    x = np.arange(t + 1, i + 1, dtype=np.float64)
    su, cu = np.polyfit(x, hh, 1)
    sl, cl = np.polyfit(x, ll, 1)
    upper = Level(t + 1, float(cu + su * (t + 1) + np.max(hh - (cu + su * x))), float(su))
    lower = Level(t + 1, float(cl + sl * (t + 1) + np.min(ll - (cl + sl * x))), float(sl))
    # The channel must drift against the pole (or sideways) …
    against = sgn * su <= 0.05 * a and sgn * sl <= 0.05 * a
    parallel = abs(su - sl) <= 0.08 * a
    converging = su < -0.01 * a and sl > 0.01 * a
    if against and parallel:
        key = "bull_flag" if sgn > 0 else "bear_flag"
    elif converging:
        key = "bull_pennant" if sgn > 0 else "bear_pennant"
    else:
        return None
    # … and must not have broken out already.
    if sgn > 0 and close[i] > upper.at(i) + BREAK * a:
        return None
    if sgn < 0 and close[i] < lower.at(i) - BREAK * a:
        return None
    pts = (
        Point(s, float(base[s]), "Pole"),
        Point(t, float(ext[t]), "Flag" if "flag" in key else "Pennant"),
    )
    allowed = {sgn}
    conf = 0.5 + 0.2 * min(1.0, pole / (6 * a)) + (0.1 if m <= 12 else 0.0)
    return ChartPattern(
        key=key,
        points=pts,
        upper=upper,
        lower=lower,
        allowed=frozenset(allowed),
        height=pole,
        stop_up=float(ll.min()),
        stop_down=float(hh.max()),
        start=s,
        end=i,
        formed=i,
        confidence=round(float(min(0.95, conf)), 3),
        atr=a,
        deadline=i + 10,
    )


# ---------------------------------------------------------------- what happened next


def track(
    p: ChartPattern,
    high: F64,
    low: F64,
    close: F64,
    volume: F64 | None,
    last: int,
    expiry: int | None = None,
) -> ChartPattern:
    """Follow a pattern from the candle after it formed up to ``last``: did it break out,
    reach its target, fail, or time out? Uses each candle's close (high/low for targets)."""
    a = p.atr
    limit = expiry if expiry is not None else max(15, p.end - p.start)
    status: Status = "forming"
    direction, event, resolved = 0, None, None
    trigger = target = stop = 0.0
    for k in range(p.formed + 1, last + 1):
        c = float(close[k])
        if direction == 0:
            hit = 0
            if p.upper is not None and c > p.upper.at(k) + BREAK * a:
                hit = 1
            elif p.lower is not None and c < p.lower.at(k) - BREAK * a:
                hit = -1
            if hit and hit in p.allowed:
                direction, event = hit, k
                level = p.upper.at(k) if hit > 0 and p.upper else p.lower.at(k) if p.lower else c
                trigger = level
                target = level + hit * p.height
                stop = p.stop_up if hit > 0 else p.stop_down
                status = "confirmed"
                if hit * (c - target) >= 0:  # the breakout candle already covered the move
                    status, resolved = "target", k
                    break
            elif hit:
                status, event, resolved = "failed", k, k
                break
            elif k - p.formed > limit or (p.deadline is not None and k > p.deadline):
                status = "expired"
                break
        elif direction > 0:
            if high[k] >= target:
                status, resolved = "target", k
                break
            if c < stop:
                status, resolved = "failed", k
                break
        else:
            if low[k] <= target:
                status, resolved = "target", k
                break
            if c > stop:
                status, resolved = "failed", k
                break
    if direction == 0 and status == "forming":
        # Show where the breakout would be today.
        d = 1 if 1 in p.allowed and (p.bias != "bearish") else -1
        if d > 0 and p.upper is not None:
            trigger = p.upper.at(last)
        elif p.lower is not None:
            d, trigger = -1, p.lower.at(last)
        target = trigger + d * p.height
        stop = p.stop_up if d > 0 else p.stop_down
    vol_ok = False
    if event is not None and direction and volume is not None:
        base = volume[max(0, event - 20) : event]
        vol_ok = bool(len(base) and base.mean() > 0 and volume[event] >= 1.3 * base.mean())
    conf = p.confidence * (1.1 if vol_ok else 1.0)
    return replace(
        p,
        status=status,
        direction=direction,
        event=event,
        resolved=resolved,
        trigger=round(float(trigger), 4),
        target=round(float(target), 4),
        stop=round(float(stop), 4),
        volume_confirmed=vol_ok,
        confidence=round(float(min(0.95, conf)), 3),
    )


# ---------------------------------------------------------------- choosing what to show

RANK: dict[str, int] = {
    "head_shoulders": 6,
    "inverse_head_shoulders": 6,
    "cup_handle": 5,
    "triple_top": 4,
    "triple_bottom": 4,
    "ascending_triangle": 4,
    "descending_triangle": 4,
    "symmetrical_triangle": 4,
    "rising_wedge": 4,
    "falling_wedge": 4,
    "rectangle": 4,
    "broadening": 1,
    "double_top": 3,
    "double_bottom": 3,
    "bull_flag": 2,
    "bear_flag": 2,
    "bull_pennant": 2,
    "bear_pennant": 2,
}


def _overlap(a: ChartPattern, b: ChartPattern) -> float:
    lo, hi = max(a.start, b.start), min(a.end, b.end)
    if hi <= lo:
        return 0.0
    return (hi - lo) / max(1, min(a.end - a.start, b.end - b.start))


def select(patterns: list[ChartPattern], *, keep: int = 4) -> list[ChartPattern]:
    """One reading per stretch of chart: when patterns cover mostly the same candles, keep
    one the price hasn't proved wrong, then one whose turns are all confirmed (a shape that
    still depends on today's unfinished swing is a guess), then the more significant shape
    (a triangle built from five turns outranks the double bottom inside it), then the more
    recent, then the more confident one."""
    alive = [p for p in patterns if p.status != "expired"]
    alive.sort(
        key=lambda p: (
            p.status != "failed",
            not p.provisional,
            RANK.get(p.key, 0),
            p.end,
            p.confidence,
        ),
        reverse=True,
    )
    chosen: list[ChartPattern] = []
    for p in alive:
        if all(_overlap(p, q) < 0.5 for q in chosen):
            chosen.append(p)
    chosen.sort(key=lambda p: -(p.resolved or p.event or p.formed))
    return chosen[:keep]


def recent_flags(
    high: F64, low: F64, close: F64, atr: F64, last: int, lookback: int = 30
) -> list[ChartPattern]:
    """Flags/pennants that formed in the last ``lookback`` candles, one per pole (the
    latest, most complete consolidation before any breakout)."""
    by_pole: dict[tuple[int, str], ChartPattern] = {}
    for i in range(max(10, last - lookback), last + 1):
        f = flag_at(high, low, close, atr, i)
        if f is not None:
            by_pole[(f.points[1].index, f.key)] = f
    return list(by_pole.values())


# The Phase 10.3 shapes (harmonics, AB=CD, three drives, rounding top, channels) live in
# their own module; it builds on the definitions above, so it is imported last.
from backend.analysis import chart_patterns_world as _world  # noqa: E402

NAMES.update(_world.NAMES)
RANK.update(_world.RANK)
