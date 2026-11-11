"""The Phase 10.1 indicators one candle at a time (twins of ``vector_world.py``).

``tests/golden/test_indicators.py`` checks each against its whole-history version on the
fixtures, so live paper trading sees exactly the values a backtest saw.
"""

from __future__ import annotations

import math
from collections import deque

from backend.indicators.stream import (
    ADX,
    ATR,
    EMA,
    MACD,
    RMA,
    ROC,
    RSI,
    SMA,
    WMA,
    Bollinger,
    PreviousDay,
    Rolling,
    StdDev,
    TrueRange,
    _NanSMA,
)
from backend.indicators.vector_world import (
    CAMARILLA,
    EOM_SCALE,
    KST_ROC,
    KST_SMA,
    alma_weights,
    t3_coefficients,
    trima_lengths,
)

NAN = math.nan


def _nan(*xs: float) -> bool:
    return any(math.isnan(x) for x in xs)


def _div(a: float, b: float, fill: float) -> float:
    if _nan(a, b):
        return NAN
    return a / b if b != 0 else fill


class _Lag:
    """The value from ``k`` updates ago (NaN until there is one)."""

    def __init__(self, k: int) -> None:
        self.win: deque[float] = deque(maxlen=k + 1)
        self.k = k

    def update(self, x: float) -> float:
        self.win.append(x)
        return self.win[0] if len(self.win) == self.k + 1 else NAN


class _NanSum:
    """Sum of the last n valid values (skips a warming-up input's leading NaNs)."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        if math.isnan(x) and not self.win:
            return NAN
        self.win.append(x)
        return sum(self.win) if len(self.win) == self.n else NAN


# ---------------------------------------------------------------- moving averages


class ZLEMA:
    def __init__(self, n: int) -> None:
        self.lag = (n - 1) // 2
        self.win: deque[float] = deque(maxlen=self.lag + 1)
        self.ema = EMA(n)

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) <= self.lag:
            return self.ema.update(NAN)
        return self.ema.update(2.0 * x - self.win[0])


class ALMA:
    def __init__(self, n: int = 9, offset: float = 0.85, sigma: float = 6.0) -> None:
        self.n = n
        self.w = [float(v) for v in alma_weights(n, offset, sigma)]
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) < self.n:
            return NAN
        return sum(w * v for w, v in zip(self.w, self.win, strict=True))


class T3:
    def __init__(self, n: int = 5, v: float = 0.7) -> None:
        self.e = [EMA(n) for _ in range(6)]
        self.c = t3_coefficients(v)

    def update(self, x: float) -> float:
        vals = []
        for e in self.e:
            x = e.update(x)
            vals.append(x)
        c1, c2, c3, c4 = self.c
        return c1 * vals[5] + c2 * vals[4] + c3 * vals[3] + c4 * vals[2]


class McGinley:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.seed: list[float] = []
        self.md = NAN

    def update(self, x: float) -> float:
        if math.isnan(self.md):
            self.seed.append(x)
            if len(self.seed) == self.n:
                self.md = sum(self.seed) / self.n
            return self.md
        md = self.md
        self.md = md + (x - md) / (self.n * (x / md) ** 4) if md > 0 and x > 0 else x
        return self.md


class LinReg:
    def __init__(self, n: int = 25) -> None:
        self.n = n
        self.tc = [i - (n - 1) / 2.0 for i in range(n)]
        self.sxx = sum(t * t for t in self.tc)
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> tuple[float, float, float]:
        self.win.append(x)
        if len(self.win) < self.n:
            return NAN, NAN, NAN
        ym = sum(self.win) / self.n
        yc = [v - ym for v in self.win]
        sxy = sum(a * b for a, b in zip(yc, self.tc, strict=True))
        syy = sum(a * a for a in yc)
        b = sxy / self.sxx
        r2 = sxy * sxy / (self.sxx * syy) if syy > 0 else 0.0
        if _nan(syy):
            r2 = NAN
        return ym + b * self.tc[-1], b, r2


class TRIMA:
    def __init__(self, n: int = 20) -> None:
        a, b = trima_lengths(n)
        self.a, self.b = SMA(a), _NanSMA(b)

    def update(self, x: float) -> float:
        return self.b.update(self.a.update(x))


class Envelope:
    def __init__(self, n: int = 20, pct: float = 2.5) -> None:
        self.sma, self.k = SMA(n), pct / 100.0

    def update(self, x: float) -> tuple[float, float, float]:
        m = self.sma.update(x)
        return m, m * (1.0 + self.k), m * (1.0 - self.k)


class CMO:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.prev = NAN
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        if math.isnan(self.prev):
            self.prev = x
            return NAN
        self.win.append(x - self.prev)
        self.prev = x
        if len(self.win) < self.n:
            return NAN
        up = sum(d for d in self.win if d > 0)
        dn = sum(-d for d in self.win if d < 0)
        tot = up + dn
        return 100.0 * (up - dn) / tot if tot > 0 else 0.0


class VIDYA:
    def __init__(self, n: int = 14, cmo_n: int = 9) -> None:
        self.cmo = CMO(cmo_n)
        self.alpha = 2.0 / (n + 1.0)
        self.v = NAN

    def update(self, x: float) -> float:
        c = self.cmo.update(x)
        if math.isnan(c):
            return NAN
        if math.isnan(self.v):
            self.v = x
        else:
            k = self.alpha * abs(c) / 100.0
            self.v = k * x + (1.0 - k) * self.v
        return self.v


# ---------------------------------------------------------------- momentum


class Momentum:
    def __init__(self, n: int = 10) -> None:
        self.lag = _Lag(n)

    def update(self, x: float) -> float:
        return x - self.lag.update(x)


class TRIX:
    def __init__(self, n: int = 15, signal: int = 9) -> None:
        self.e = [EMA(n), EMA(n), EMA(n)]
        self.prev = NAN
        self.sig = EMA(signal)

    def update(self, x: float) -> tuple[float, float]:
        for e in self.e:
            x = e.update(x)
        t = _div(100.0 * (x - self.prev), self.prev, 0.0)
        self.prev = x
        return t, self.sig.update(t)


class PPO:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.f, self.s, self.sig = EMA(fast), EMA(slow), EMA(signal)

    def update(self, x: float) -> tuple[float, float, float]:
        f, s = self.f.update(x), self.s.update(x)
        line = _div(100.0 * (f - s), s, 0.0)
        sg = self.sig.update(line)
        return line, sg, line - sg


class PVO:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.ppo = PPO(fast, slow, signal)

    def update(self, c: float, v: float) -> tuple[float, float, float]:
        return self.ppo.update(v)


class DPO:
    def __init__(self, n: int = 20) -> None:
        self.sma, self.lag = SMA(n), _Lag(n // 2 + 1)

    def update(self, x: float) -> float:
        return self.lag.update(x) - self.sma.update(x)


class KST:
    def __init__(self, signal: int = 9) -> None:
        self.parts = [(ROC(r), _NanSMA(s)) for r, s in zip(KST_ROC, KST_SMA, strict=True)]
        self.sig = _NanSMA(signal)

    def update(self, x: float) -> tuple[float, float]:
        p = [s.update(r.update(x)) for r, s in self.parts]
        k = p[0] + 2.0 * p[1] + 3.0 * p[2] + 4.0 * p[3]
        return k, self.sig.update(k)


class Coppock:
    def __init__(self, long: int = 14, short: int = 11, n: int = 10) -> None:
        self.a, self.b, self.w = ROC(long), ROC(short), WMA(n)

    def update(self, x: float) -> float:
        return self.w.update(self.a.update(x) + self.b.update(x))


class Ultimate:
    def __init__(self, a: int = 7, b: int = 14, c: int = 28) -> None:
        self.lens = ((a, 4.0), (b, 2.0), (c, 1.0))
        self.m = max(a, b, c)
        self.win: deque[tuple[float, float]] = deque(maxlen=self.m)
        self.prev = NAN

    def update(self, h: float, lo: float, c: float) -> float:
        pc, self.prev = self.prev, c
        if math.isnan(pc):
            return NAN
        self.win.append((c - min(lo, pc), max(h, pc) - min(lo, pc)))
        if len(self.win) < self.m:
            return NAN
        rows = list(self.win)
        total = 0.0
        for k, w in self.lens:
            sb = sum(r[0] for r in rows[-k:])
            st = sum(r[1] for r in rows[-k:])
            total += w * (sb / st if st > 0 else 0.5)
        return 100.0 * total / 7.0


class Awesome:
    def __init__(self, fast: int = 5, slow: int = 34) -> None:
        self.f, self.s, self.ac = SMA(fast), SMA(slow), _NanSMA(fast)

    def update(self, h: float, lo: float) -> tuple[float, float]:
        m = (h + lo) / 2.0
        ao = self.f.update(m) - self.s.update(m)
        return ao, ao - self.ac.update(ao)


class TSI:
    def __init__(self, long: int = 25, short: int = 13, signal: int = 13) -> None:
        self.n1, self.n2 = EMA(long), EMA(short)
        self.d1, self.d2 = EMA(long), EMA(short)
        self.sig = EMA(signal)
        self.prev = NAN

    def update(self, x: float) -> tuple[float, float]:
        pc = x - self.prev
        self.prev = x
        num = self.n2.update(self.n1.update(pc))
        den = self.d2.update(self.d1.update(abs(pc)))
        t = _div(100.0 * num, den, 0.0)
        return t, self.sig.update(t)


class _Sym4:
    def __init__(self) -> None:
        self.win: deque[float] = deque(maxlen=4)

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) < 4:
            return NAN
        a, b, c, d = self.win  # oldest first
        return (d + 2.0 * c + 2.0 * b + a) / 6.0


class RVI:
    def __init__(self, n: int = 10) -> None:
        self.sn, self.sd = _Sym4(), _Sym4()
        self.mn, self.md = _NanSMA(n), _NanSMA(n)
        self.sig = _Sym4()

    def update(self, o: float, h: float, lo: float, c: float) -> tuple[float, float]:
        num = self.mn.update(self.sn.update(c - o))
        den = self.md.update(self.sd.update(h - lo))
        r = _div(num, den, 0.0)
        return r, self.sig.update(r)


class Fisher:
    def __init__(self, n: int = 9) -> None:
        self.hh, self.ll = Rolling(n, is_max=True), Rolling(n, is_max=False)
        self.val = self.f = 0.0
        self.prev = NAN

    def update(self, h: float, lo: float) -> tuple[float, float]:
        m = (h + lo) / 2.0
        hh, ll = self.hh.update(m), self.ll.update(m)
        if math.isnan(hh):
            return NAN, NAN
        rng = hh - ll
        pos = ((m - ll) / rng - 0.5) if rng > 0 else 0.0
        self.val = min(max(0.66 * pos + 0.67 * self.val, -0.999), 0.999)
        self.f = 0.5 * math.log((1.0 + self.val) / (1.0 - self.val)) + 0.5 * self.f
        trig, self.prev = self.prev, self.f
        return self.f, trig


class STCCore:
    """The Schaff trend cycle's double stochastic, fed one MACD value at a time (the
    whole-history version runs this same loop)."""

    def __init__(self, cycle: int = 10, factor: float = 0.5) -> None:
        self.cycle, self.factor = cycle, factor
        self.mw: deque[float] = deque(maxlen=cycle)
        self.pw: deque[float] = deque(maxlen=cycle)
        self.f1 = self.f2 = 0.0
        self.pf = self.pff = NAN

    def update(self, m: float) -> float:
        if math.isnan(m):
            return NAN
        self.mw.append(m)
        v1 = min(self.mw)
        v2 = max(self.mw) - v1
        if v2 > 0:
            self.f1 = (m - v1) / v2 * 100.0
        self.pf = self.f1 if math.isnan(self.pf) else self.pf + self.factor * (self.f1 - self.pf)
        self.pw.append(self.pf)
        v3 = min(self.pw)
        v4 = max(self.pw) - v3
        if v4 > 0:
            self.f2 = (self.pf - v3) / v4 * 100.0
        self.pff = (
            self.f2 if math.isnan(self.pff) else self.pff + self.factor * (self.f2 - self.pff)
        )
        return self.pff if len(self.mw) == self.cycle else NAN


class STC:
    def __init__(self, fast: int = 23, slow: int = 50, cycle: int = 10, factor: float = 0.5):
        self.f, self.s = EMA(fast), EMA(slow)
        self.core = STCCore(cycle, factor)

    def update(self, x: float) -> float:
        return self.core.update(self.f.update(x) - self.s.update(x))


class ConnorsRSI:
    def __init__(self, n: int = 3, streak: int = 2, rank: int = 100) -> None:
        self.r_close, self.r_streak = RSI(n), RSI(streak)
        self.rank = rank
        self.prev = NAN
        self.streak = 0.0
        self.rocs: deque[float] = deque(maxlen=rank + 1)

    def update(self, x: float) -> float:
        pc, self.prev = self.prev, x
        if not math.isnan(pc):
            if x > pc:
                self.streak = self.streak + 1 if self.streak > 0 else 1.0
            elif x < pc:
                self.streak = self.streak - 1 if self.streak < 0 else -1.0
            else:
                self.streak = 0.0
            self.rocs.append(_div(100.0 * (x - pc), pc, 0.0))
        a = self.r_close.update(x)
        b = self.r_streak.update(self.streak)
        if len(self.rocs) == self.rank + 1:
            *before, today = self.rocs
            pr = 100.0 * sum(1 for v in before if v < today) / self.rank
        else:
            pr = NAN
        return (a + b + pr) / 3.0


class ElderRay:
    def __init__(self, n: int = 13) -> None:
        self.ema = EMA(n)

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        e = self.ema.update(c)
        return h - e, lo - e


class BOP:
    def __init__(self, n: int = 14) -> None:
        self.sma = SMA(n)

    def update(self, o: float, h: float, lo: float, c: float) -> float:
        return self.sma.update(_div(c - o, h - lo, 0.0))


class Qstick:
    def __init__(self, n: int = 8) -> None:
        self.sma = SMA(n)

    def update(self, o: float, h: float, lo: float, c: float) -> float:
        return self.sma.update(c - o)


class SMI:
    def __init__(self, k: int = 10, d: int = 3) -> None:
        self.hh, self.ll = Rolling(k, is_max=True), Rolling(k, is_max=False)
        self.n1, self.n2, self.d1, self.d2 = EMA(d), EMA(d), EMA(d), EMA(d)
        self.sig = EMA(d)

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        hh, ll = self.hh.update(h), self.ll.update(lo)
        num = self.n2.update(self.n1.update(c - (hh + ll) / 2.0))
        den = self.d2.update(self.d1.update(hh - ll)) / 2.0
        s = _div(100.0 * num, den, 0.0)
        return s, self.sig.update(s)


class WaveTrend:
    def __init__(self, n1: int = 10, n2: int = 21) -> None:
        self.esa, self.d, self.t = EMA(n1), EMA(n1), EMA(n2)
        self.wt2 = _NanSMA(4)

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        ap = (h + lo + c) / 3.0
        esa = self.esa.update(ap)
        dd = self.d.update(abs(ap - esa))
        ci = _div(ap - esa, 0.015 * dd, 0.0)
        wt1 = self.t.update(ci)
        return wt1, self.wt2.update(wt1)


# ---------------------------------------------------------------- trend


class Vortex:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.prev: tuple[float, float, float] | None = None
        self.win: deque[tuple[float, float, float]] = deque(maxlen=n)

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        if self.prev is None:
            self.prev = (h, lo, c)
            return NAN, NAN
        ph, pl, pc = self.prev
        self.prev = (h, lo, c)
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        self.win.append((abs(h - pl), abs(lo - ph), tr))
        if len(self.win) < self.n:
            return NAN, NAN
        st = sum(r[2] for r in self.win)
        if st <= 0:
            return 0.0, 0.0
        return sum(r[0] for r in self.win) / st, sum(r[1] for r in self.win) / st


class ADXR:
    def __init__(self, n: int = 14) -> None:
        self.adx, self.lag = ADX(n), _Lag(n - 1)

    def update(self, h: float, lo: float, c: float) -> float:
        a = self.adx.update(h, lo, c)[0]
        return (a + self.lag.update(a)) / 2.0


class Alligator:
    def __init__(self, jaw: int = 13, teeth: int = 8, lips: int = 5) -> None:
        self.parts = [(RMA(jaw), _Lag(8)), (RMA(teeth), _Lag(5)), (RMA(lips), _Lag(3))]

    def update(self, h: float, lo: float) -> tuple[float, float, float]:
        m = (h + lo) / 2.0
        a, b, c = (lag.update(r.update(m)) for r, lag in self.parts)
        return a, b, c


class ElderImpulse:
    def __init__(self, n: int = 13, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.ema, self.macd = EMA(n), MACD(fast, slow, signal)
        self.pe = self.ph = NAN

    def update(self, x: float) -> float:
        e, hist = self.ema.update(x), self.macd.update(x)[2]
        de, dh = e - self.pe, hist - self.ph
        self.pe, self.ph = e, hist
        if _nan(de, dh):
            return NAN
        if de > 0 and dh > 0:
            return 1.0
        if de < 0 and dh < 0:
            return -1.0
        return 0.0


class HeikinAshi:
    def __init__(self) -> None:
        self.ho = self.hc = NAN

    def update(self, o: float, h: float, lo: float, c: float) -> tuple[float, float, float, float]:
        ho = (o + c) / 2.0 if math.isnan(self.ho) else (self.ho + self.hc) / 2.0
        hc = (o + h + lo + c) / 4.0
        self.ho, self.hc = ho, hc
        return hc, ho, max(h, ho, hc), min(lo, ho, hc)


class Fractals:
    def __init__(self) -> None:
        self.h: deque[float] = deque(maxlen=5)
        self.lo: deque[float] = deque(maxlen=5)
        self.up = self.dn = NAN

    def update(self, h: float, lo: float) -> tuple[float, float]:
        self.h.append(h)
        self.lo.append(lo)
        if len(self.h) == 5:
            hs, ls = list(self.h), list(self.lo)
            if hs[2] > max(hs[0], hs[1], hs[3], hs[4]):
                self.up = hs[2]
            if ls[2] < min(ls[0], ls[1], ls[3], ls[4]):
                self.dn = ls[2]
        return self.up, self.dn


# ---------------------------------------------------------------- volatility


class MassIndex:
    def __init__(self, n: int = 9, total: int = 25) -> None:
        self.e1, self.e2 = EMA(n), EMA(n)
        self.sum = _NanSum(total)

    def update(self, h: float, lo: float) -> float:
        a = self.e1.update(h - lo)
        b = self.e2.update(a)
        return self.sum.update(_div(a, b, 1.0))


class Chop:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.tr = TrueRange()
        self.sum = _NanSum(n)
        self.hh, self.ll = Rolling(n, is_max=True), Rolling(n, is_max=False)

    def update(self, h: float, lo: float, c: float) -> float:
        st = self.sum.update(self.tr.update(h, lo, c))
        ratio = _div(st, self.hh.update(h) - self.ll.update(lo), 0.0)
        if math.isnan(ratio):
            return NAN
        return 100.0 * math.log10(ratio) / math.log10(self.n) if ratio > 0 else 100.0


class Ulcer:
    def __init__(self, n: int = 14) -> None:
        self.mx, self.sma = Rolling(n, is_max=True), _NanSMA(n)

    def update(self, x: float) -> float:
        m = self.mx.update(x)
        dd = _div(100.0 * (x - m), m, 0.0)
        return math.sqrt(self.sma.update(dd * dd))


class HV:
    def __init__(self, n: int = 20, per_year: int = 252) -> None:
        self.n = n
        self.k = math.sqrt(per_year) * 100.0
        self.prev = NAN
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        pc, self.prev = self.prev, x
        if math.isnan(pc):
            return NAN
        self.win.append(math.log(x / pc) if x > 0 and pc > 0 else 0.0)
        if len(self.win) < self.n:
            return NAN
        m = sum(self.win) / self.n
        return math.sqrt(sum((v - m) ** 2 for v in self.win) / (self.n - 1)) * self.k


class NATR:
    def __init__(self, n: int = 14) -> None:
        self.atr = ATR(n)

    def update(self, h: float, lo: float, c: float) -> float:
        return _div(100.0 * self.atr.update(h, lo, c), c, 0.0)


class Chandelier:
    def __init__(self, n: int = 22, mult: float = 3.0) -> None:
        self.atr = ATR(n)
        self.hh, self.ll = Rolling(n, is_max=True), Rolling(n, is_max=False)
        self.mult = mult

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        a = self.atr.update(h, lo, c)
        return self.hh.update(h) - self.mult * a, self.ll.update(lo) + self.mult * a


class Squeeze:
    def __init__(self, n: int = 20, bb: float = 2.0, kc: float = 1.5) -> None:
        self.bb = Bollinger(n, bb)
        self.ema, self.atr, self.kc = EMA(n), ATR(n), kc
        self.hh, self.ll = Rolling(n, is_max=True), Rolling(n, is_max=False)
        self.lr = LinReg(max(2, n))

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        mid, up, dn = self.bb.update(c)
        km, a = self.ema.update(c), self.atr.update(h, lo, c)
        if _nan(up, a, km):
            on = NAN
        else:
            on = 1.0 if (up < km + self.kc * a and dn > km - self.kc * a) else 0.0
        d = c - ((self.hh.update(h) + self.ll.update(lo)) / 2.0 + mid) / 2.0
        return self.lr.update(d)[0], on


class ZScore:
    def __init__(self, n: int = 20) -> None:
        self.sma, self.sd = SMA(n), StdDev(n)

    def update(self, x: float) -> float:
        return _div(x - self.sma.update(x), self.sd.update(x), 0.0)


class BollingerPct:
    def __init__(self, n: int = 20, mult: float = 2.0) -> None:
        self.bb = Bollinger(n, mult)

    def update(self, x: float) -> tuple[float, float]:
        mid, up, dn = self.bb.update(x)
        return _div(x - dn, up - dn, 0.5), _div(100.0 * (up - dn), mid, 0.0)


class Disparity:
    def __init__(self, n: int = 14) -> None:
        self.sma = SMA(n)

    def update(self, x: float) -> float:
        m = self.sma.update(x)
        return _div(100.0 * (x - m), m, 0.0)


# ---------------------------------------------------------------- volume


class ADLine:
    def __init__(self) -> None:
        self.total = 0.0

    def update(self, h: float, lo: float, c: float, v: float) -> float:
        self.total += _div((c - lo) - (h - c), h - lo, 0.0) * v
        return self.total


class ChaikinOsc:
    def __init__(self, fast: int = 3, slow: int = 10) -> None:
        self.ad, self.f, self.s = ADLine(), EMA(fast), EMA(slow)

    def update(self, h: float, lo: float, c: float, v: float) -> float:
        a = self.ad.update(h, lo, c, v)
        return self.f.update(a) - self.s.update(a)


class ForceIndex:
    def __init__(self, n: int = 13) -> None:
        self.ema, self.prev = EMA(n), NAN

    def update(self, c: float, v: float) -> float:
        raw = (c - self.prev) * v
        self.prev = c
        return self.ema.update(raw)


class EOM:
    def __init__(self, n: int = 14) -> None:
        self.sma, self.prev = _NanSMA(n), NAN

    def update(self, h: float, lo: float, c: float, v: float) -> float:
        m = (h + lo) / 2.0
        pm, self.prev = self.prev, m
        if math.isnan(pm):
            return NAN
        return self.sma.update(_div(EOM_SCALE * (m - pm) * (h - lo), v, 0.0))


class Klinger:
    def __init__(self, fast: int = 34, slow: int = 55, signal: int = 13) -> None:
        self.f, self.s, self.sig = EMA(fast), EMA(slow), EMA(signal)
        self.prev = NAN

    def update(self, h: float, lo: float, c: float, v: float) -> tuple[float, float]:
        tp = (h + lo + c) / 3.0
        ptp, self.prev = self.prev, tp
        sv = NAN if math.isnan(ptp) else (v if tp - ptp >= 0 else -v)
        k = self.f.update(sv) - self.s.update(sv)
        return k, self.sig.update(k)


class VolumeIndex:
    def __init__(self, signal: int = 255, *, negative: bool) -> None:
        self.negative = negative
        self.val = NAN
        self.prev: tuple[float, float] | None = None
        self.sig = EMA(signal)

    def update(self, c: float, v: float) -> tuple[float, float]:
        if self.prev is None:
            self.val = 1000.0
        else:
            pc, pv = self.prev
            moved = v < pv if self.negative else v > pv
            if moved and pc != 0:
                self.val = self.val * c / pc
        self.prev = (c, v)
        return self.val, self.sig.update(self.val)


class PVT:
    def __init__(self) -> None:
        self.total = 0.0
        self.prev = NAN

    def update(self, c: float, v: float) -> float:
        if not math.isnan(self.prev):
            self.total += _div(v * (c - self.prev), self.prev, 0.0)
        self.prev = c
        return self.total


class RVOL:
    def __init__(self, n: int = 20) -> None:
        self.sma, self.prev_avg = SMA(n), NAN

    def update(self, c: float, v: float) -> float:
        out = _div(v, self.prev_avg, 1.0)
        self.prev_avg = self.sma.update(v)
        return out


# ---------------------------------------------------------------- pivot variants


class PivotsFib:
    def __init__(self) -> None:
        self.prev = PreviousDay()

    def update(
        self, h: float, lo: float, c: float, session: int
    ) -> tuple[float, float, float, float, float, float, float]:
        ph, pl, pc = self.prev.update(h, lo, c, session)
        p = (ph + pl + pc) / 3.0
        r = ph - pl
        return p, p + 0.382 * r, p + 0.618 * r, p + r, p - 0.382 * r, p - 0.618 * r, p - r


class PivotsCamarilla:
    def __init__(self) -> None:
        self.prev = PreviousDay()

    def update(self, h: float, lo: float, c: float, session: int) -> tuple[float, ...]:
        ph, pl, pc = self.prev.update(h, lo, c, session)
        r = ph - pl
        return (*(pc + k * r for k in CAMARILLA), *(pc - k * r for k in CAMARILLA))


class PivotsWoodie:
    def __init__(self) -> None:
        self.prev = PreviousDay()

    def update(
        self, h: float, lo: float, c: float, session: int
    ) -> tuple[float, float, float, float, float, float, float]:
        ph, pl, pc = self.prev.update(h, lo, c, session)
        p = (ph + pl + 2.0 * pc) / 4.0
        return (
            p,
            2 * p - pl,
            p + (ph - pl),
            ph + 2 * (p - pl),
            2 * p - ph,
            p - (ph - pl),
            pl - 2 * (ph - p),
        )
