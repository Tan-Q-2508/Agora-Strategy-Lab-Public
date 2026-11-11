"""The same indicators, one bar at a time (used by live paper trading).

Each class takes the newest closed bar's inputs in ``update`` and returns the newest
value(s), NaN during warm-up. ``tests/golden/test_indicators.py`` proves every one matches
its whole-history twin in ``vector.py`` on the fixtures and on random data.
"""

from __future__ import annotations

import math
from collections import deque

NAN = math.nan
YEAR_MS = 365 * 86_400_000


class SMA:
    def __init__(self, n: int) -> None:
        self.n = n
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) < self.n:
            return NAN
        return sum(self.win) / self.n


class _Seeded:
    """Base for EMA/RMA: average the first n valid values, then smooth."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.seed: list[float] = []
        self.value = NAN

    def _step(self, x: float) -> float:
        raise NotImplementedError

    def update(self, x: float) -> float:
        if math.isnan(x):
            return NAN if not self.seed and math.isnan(self.value) else self.value
        if math.isnan(self.value):
            self.seed.append(x)
            if len(self.seed) == self.n:
                self.value = sum(self.seed) / self.n
            return self.value
        self.value = self._step(x)
        return self.value


class EMA(_Seeded):
    def _step(self, x: float) -> float:
        a = 2.0 / (self.n + 1.0)
        return a * x + (1.0 - a) * self.value


class RMA(_Seeded):
    def _step(self, x: float) -> float:
        return (self.value * (self.n - 1) + x) / self.n


class WMA:
    def __init__(self, n: int) -> None:
        self.n = n
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) < self.n:
            return NAN
        return sum((i + 1) * v for i, v in enumerate(self.win)) / (self.n * (self.n + 1) / 2)


class RSI:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.prev = NAN
        self.gains: list[float] = []
        self.losses: list[float] = []
        self.ag = NAN
        self.al = NAN

    def update(self, x: float) -> float:
        if math.isnan(self.prev):
            self.prev = x
            return NAN
        d = x - self.prev
        self.prev = x
        g, loss = (d, 0.0) if d > 0 else (0.0, -d if d < 0 else 0.0)
        if math.isnan(self.ag):
            self.gains.append(g)
            self.losses.append(loss)
            if len(self.gains) < self.n:
                return NAN
            self.ag = sum(self.gains) / self.n
            self.al = sum(self.losses) / self.n
        else:
            self.ag = (self.ag * (self.n - 1) + g) / self.n
            self.al = (self.al * (self.n - 1) + loss) / self.n
        if self.al == 0.0:
            return 50.0 if self.ag == 0.0 else 100.0
        return 100.0 - 100.0 / (1.0 + self.ag / self.al)


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast, self.slow, self.sig = EMA(fast), EMA(slow), EMA(signal)

    def update(self, x: float) -> tuple[float, float, float]:
        line = self.fast.update(x) - self.slow.update(x)
        s = self.sig.update(line)
        return line, s, line - s


class TrueRange:
    def __init__(self) -> None:
        self.prev_close = NAN

    def update(self, h: float, lo: float, c: float) -> float:
        tr = (
            h - lo
            if math.isnan(self.prev_close)
            else max(h - lo, abs(h - self.prev_close), abs(lo - self.prev_close))
        )
        self.prev_close = c
        return tr


class ATR:
    def __init__(self, n: int = 14) -> None:
        self.tr, self.rma = TrueRange(), RMA(n)

    def update(self, h: float, lo: float, c: float) -> float:
        return self.rma.update(self.tr.update(h, lo, c))


class StdDev:
    def __init__(self, n: int) -> None:
        self.n = n
        self.win: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) < self.n:
            return NAN
        m = sum(self.win) / self.n
        return math.sqrt(sum((v - m) ** 2 for v in self.win) / self.n)


class Bollinger:
    def __init__(self, n: int = 20, k: float = 2.0) -> None:
        self.sma, self.sd, self.k = SMA(n), StdDev(n), k

    def update(self, x: float) -> tuple[float, float, float]:
        m, s = self.sma.update(x), self.sd.update(x)
        return m, m + self.k * s, m - self.k * s


class Keltner:
    def __init__(self, n: int = 20, k: float = 2.0, atr_n: int = 10) -> None:
        self.ema, self.atr, self.k = EMA(n), ATR(atr_n), k

    def update(self, h: float, lo: float, c: float) -> tuple[float, float, float]:
        m, a = self.ema.update(c), self.atr.update(h, lo, c)
        return m, m + self.k * a, m - self.k * a


class Rolling:
    def __init__(self, n: int, *, is_max: bool) -> None:
        self.n = n
        self.win: deque[float] = deque(maxlen=n)
        self.is_max = is_max

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) < self.n:
            return NAN
        return max(self.win) if self.is_max else min(self.win)


class Donchian:
    def __init__(self, n: int = 20) -> None:
        self.hi, self.lo = Rolling(n, is_max=True), Rolling(n, is_max=False)

    def update(self, h: float, lo: float) -> tuple[float, float, float]:
        up, dn = self.hi.update(h), self.lo.update(lo)
        return up, (up + dn) / 2.0, dn


class Stochastic:
    def __init__(self, k: int = 14, smooth: int = 3, d: int = 3) -> None:
        self.hh, self.ll = Rolling(k, is_max=True), Rolling(k, is_max=False)
        self.k_sma = _NanSMA(smooth)
        self.d_sma = _NanSMA(d)

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        hh, ll = self.hh.update(h), self.ll.update(lo)
        if math.isnan(hh):
            raw = NAN
        else:
            raw = 100.0 * (c - ll) / (hh - ll) if hh - ll > 0 else 50.0
        k = self.k_sma.update(raw)
        return k, self.d_sma.update(k)


class _NanSMA:
    """SMA that ignores the leading NaNs of a warming-up input."""

    def __init__(self, n: int) -> None:
        self.sma = SMA(n)

    def update(self, x: float) -> float:
        return NAN if math.isnan(x) else self.sma.update(x)


class CCI:
    def __init__(self, n: int = 20) -> None:
        self.n = n
        self.win: deque[float] = deque(maxlen=n)

    def update(self, h: float, lo: float, c: float) -> float:
        tp = (h + lo + c) / 3.0
        self.win.append(tp)
        if len(self.win) < self.n:
            return NAN
        m = sum(self.win) / self.n
        md = sum(abs(v - m) for v in self.win) / self.n
        return (tp - m) / (0.015 * md) if md > 0 else 0.0


class ROC:
    def __init__(self, n: int = 12) -> None:
        self.win: deque[float] = deque(maxlen=n + 1)
        self.n = n

    def update(self, x: float) -> float:
        self.win.append(x)
        if len(self.win) <= self.n:
            return NAN
        old = self.win[0]
        return 100.0 * (x / old - 1.0) if old != 0 else 0.0


class ADX:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.prev: tuple[float, float, float] | None = None
        self.tr, self.p, self.m, self.dx = RMA(n), RMA(n), RMA(n), RMA(n)

    def update(self, h: float, lo: float, c: float) -> tuple[float, float, float]:
        if self.prev is None:
            self.prev = (h, lo, c)
            return NAN, NAN, NAN
        ph, pl, pc = self.prev
        self.prev = (h, lo, c)
        up, dn = h - ph, pl - lo
        pdm = up if (up > dn and up > 0) else 0.0
        mdm = dn if (dn > up and dn > 0) else 0.0
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        s_tr, s_p, s_m = self.tr.update(tr), self.p.update(pdm), self.m.update(mdm)
        if math.isnan(s_tr):
            return NAN, NAN, NAN
        pdi = 100.0 * s_p / s_tr if s_tr > 0 else 0.0
        mdi = 100.0 * s_m / s_tr if s_tr > 0 else 0.0
        tot = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / tot if tot > 0 else 0.0
        return self.dx.update(dx), pdi, mdi


class Supertrend:
    def __init__(self, n: int = 10, mult: float = 3.0) -> None:
        self.atr, self.mult = ATR(n), mult
        self.fu = self.fd = NAN
        self.dir = 0.0
        self.prev_close = NAN

    def update(self, h: float, lo: float, c: float) -> tuple[float, float]:
        a = self.atr.update(h, lo, c)
        prev_close, self.prev_close = self.prev_close, c
        if math.isnan(a):
            return NAN, NAN
        hl2 = (h + lo) / 2.0
        up_b, dn_b = hl2 + self.mult * a, hl2 - self.mult * a
        if self.dir == 0.0:
            self.fu, self.fd = up_b, dn_b
            self.dir = 1.0 if c > hl2 else -1.0
        else:
            nfu = up_b if (up_b < self.fu or prev_close > self.fu) else self.fu
            nfd = dn_b if (dn_b > self.fd or prev_close < self.fd) else self.fd
            if self.dir < 0:
                self.dir = 1.0 if c > nfu else -1.0
            else:
                self.dir = -1.0 if c < nfd else 1.0
            self.fu, self.fd = nfu, nfd
        return (self.fd if self.dir > 0 else self.fu), self.dir


class OBV:
    def __init__(self) -> None:
        self.prev = NAN
        self.value = 0.0

    def update(self, c: float, v: float) -> float:
        if not math.isnan(self.prev):
            if c > self.prev:
                self.value += v
            elif c < self.prev:
                self.value -= v
        self.prev = c
        return self.value


class VWAP:
    def __init__(self) -> None:
        self.session: int | None = None
        self.pv = self.vol = 0.0

    def update(self, h: float, lo: float, c: float, v: float, session: int) -> float:
        if session != self.session:
            self.session, self.pv, self.vol = session, 0.0, 0.0
        tp = (h + lo + c) / 3.0
        self.pv += tp * v
        self.vol += v
        return self.pv / self.vol if self.vol > 0 else tp


class TimeExtreme:
    """52-week high (``is_max``) or low over a rolling time window."""

    def __init__(self, *, is_max: bool, window_ms: int = YEAR_MS) -> None:
        self.is_max = is_max
        self.window_ms = window_ms
        self.q: deque[tuple[int, float]] = deque()
        self.t0: int | None = None

    def update(self, x: float, ts: int) -> float:
        if self.t0 is None:
            self.t0 = ts
        while self.q and (self.q[-1][1] <= x if self.is_max else self.q[-1][1] >= x):
            self.q.pop()
        self.q.append((ts, x))
        while self.q[0][0] <= ts - self.window_ms:
            self.q.popleft()
        if ts - self.t0 >= self.window_ms - 86_400_000:
            return self.q[0][1]
        return NAN


class PreviousDay:
    def __init__(self) -> None:
        self.session: int | None = None
        self.cur = (-math.inf, math.inf, NAN)
        self.prev: tuple[float, float, float] | None = None

    def update(self, h: float, lo: float, c: float, session: int) -> tuple[float, float, float]:
        if session != self.session:
            if self.session is not None:
                self.prev = self.cur
            self.session = session
            self.cur = (-math.inf, math.inf, NAN)
        self.cur = (max(self.cur[0], h), min(self.cur[1], lo), c)
        return self.prev if self.prev is not None else (NAN, NAN, NAN)


class OpeningRange:
    def __init__(self, bar_minutes: int, minutes: int = 15) -> None:
        self.bar = bar_minutes * 60_000
        self.span = minutes * 60_000
        self.daily = bar_minutes >= 1440
        self.session: int | None = None
        self.hi, self.lo, self.done = -math.inf, math.inf, False

    def update(
        self, h: float, lo: float, ts: int, session: int, session_open: int
    ) -> tuple[float, float]:
        if self.daily:
            return NAN, NAN
        if session != self.session:
            self.session = session
            self.hi, self.lo, self.done = -math.inf, math.inf, False
        if ts < session_open + self.span:
            self.hi, self.lo = max(self.hi, h), min(self.lo, lo)
            if ts + self.bar >= session_open + self.span:
                self.done = True
        elif not self.done and self.hi > -math.inf:
            self.done = True
        return (self.hi, self.lo) if self.done else (NAN, NAN)
