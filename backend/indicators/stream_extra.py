"""The Phase 9.1 indicators one candle at a time (twins of ``vector_extra.py``).

``tests/golden/test_indicators.py`` checks each against its whole-history version on the
fixtures, so live paper trading sees exactly the values a backtest saw.
"""

from __future__ import annotations

import math
from collections import deque

from backend.indicators.stream import EMA, RSI, WMA, PreviousDay, Rolling, _NanSMA
from backend.indicators.vector_extra import hma_lengths

NAN = math.nan


class _NanRolling:
    """Highest/lowest of the last n valid values (skips a warming-up input's NaNs)."""

    def __init__(self, n: int, *, is_max: bool) -> None:
        self.inner = Rolling(n, is_max=is_max)

    def update(self, x: float) -> float:
        return NAN if math.isnan(x) else self.inner.update(x)


class DEMA:
    def __init__(self, n: int) -> None:
        self.e1, self.e2 = EMA(n), EMA(n)

    def update(self, x: float) -> float:
        a = self.e1.update(x)
        return 2.0 * a - self.e2.update(a)


class TEMA:
    def __init__(self, n: int) -> None:
        self.e1, self.e2, self.e3 = EMA(n), EMA(n), EMA(n)

    def update(self, x: float) -> float:
        a = self.e1.update(x)
        b = self.e2.update(a)
        return 3.0 * a - 3.0 * b + self.e3.update(b)


class HMA:
    def __init__(self, n: int) -> None:
        half, root = hma_lengths(n)
        self.half, self.full, self.out = WMA(half), WMA(n), WMA(root)

    def update(self, x: float) -> float:
        return self.out.update(2.0 * self.half.update(x) - self.full.update(x))


class VWMA:
    def __init__(self, n: int) -> None:
        self.n = n
        self.win: deque[tuple[float, float]] = deque(maxlen=n)

    def update(self, x: float, v: float) -> float:
        self.win.append((x, v))
        if len(self.win) < self.n:
            return NAN
        vs = sum(w for _, w in self.win)
        if vs > 0:
            return sum(p * w for p, w in self.win) / vs
        return sum(p for p, _ in self.win) / self.n


class KAMA:
    def __init__(self, n: int = 10, fast: int = 2, slow: int = 30) -> None:
        self.n = n
        self.fs, self.ss = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
        self.prices: deque[float] = deque(maxlen=n + 1)
        self.value = NAN

    def update(self, x: float) -> float:
        self.prices.append(x)
        if len(self.prices) < self.n:
            return NAN
        if math.isnan(self.value):
            self.value = x
            return x
        p = list(self.prices)
        vol = sum(abs(p[j] - p[j - 1]) for j in range(1, len(p)))
        er = abs(p[-1] - p[0]) / vol if vol > 0 else 0.0
        sc = (er * (self.fs - self.ss) + self.ss) ** 2
        self.value = self.value + sc * (x - self.value)
        return self.value


class Ichimoku:
    def __init__(self, conv: int = 9, base: int = 26, span: int = 52, shift: int = 26) -> None:
        self.ch, self.cl = Rolling(conv, is_max=True), Rolling(conv, is_max=False)
        self.bh, self.bl = Rolling(base, is_max=True), Rolling(base, is_max=False)
        self.sh, self.sl = Rolling(span, is_max=True), Rolling(span, is_max=False)
        self.shift = shift
        self.queue: deque[tuple[float, float]] = deque(maxlen=shift + 1)

    def update(self, h: float, lo: float) -> tuple[float, float, float, float]:
        tenkan = (self.ch.update(h) + self.cl.update(lo)) / 2.0
        kijun = (self.bh.update(h) + self.bl.update(lo)) / 2.0
        b_now = (self.sh.update(h) + self.sl.update(lo)) / 2.0
        self.queue.append(((tenkan + kijun) / 2.0, b_now))
        if self.shift == 0:
            return tenkan, kijun, self.queue[-1][0], self.queue[-1][1]
        if len(self.queue) <= self.shift:
            return tenkan, kijun, NAN, NAN
        a, b = self.queue[0]
        return tenkan, kijun, a, b


class PSAR:
    def __init__(self, start: float = 0.02, step: float = 0.02, maximum: float = 0.2) -> None:
        self.start, self.step, self.maximum = start, step, maximum
        self.bars: deque[tuple[float, float, float]] = deque(maxlen=3)
        self.up = True
        self.sar = self.ep = NAN
        self.af = start

    def update(self, h: float, lo: float, c: float) -> float:
        self.bars.append((h, lo, c))
        n = len(self.bars)
        if n == 1 and math.isnan(self.sar):
            return NAN
        if math.isnan(self.sar):
            (h0, l0, c0), (h1, l1, c1) = self.bars[0], self.bars[1]
            self.up = c1 >= c0
            self.sar = l0 if self.up else h0
            self.ep = h1 if self.up else l1
            return self.sar
        prev2, prev1 = self.bars[-3], self.bars[-2]
        sar = self.sar + self.af * (self.ep - self.sar)
        if self.up:
            sar = min(sar, prev1[1], prev2[1])
            if lo < sar:
                self.up, sar, self.ep, self.af = False, self.ep, lo, self.start
            elif h > self.ep:
                self.ep, self.af = h, min(self.af + self.step, self.maximum)
        else:
            sar = max(sar, prev1[0], prev2[0])
            if h > sar:
                self.up, sar, self.ep, self.af = True, self.ep, h, self.start
            elif lo < self.ep:
                self.ep, self.af = lo, min(self.af + self.step, self.maximum)
        self.sar = sar
        return sar


class Aroon:
    def __init__(self, n: int = 25) -> None:
        self.n = n
        self.win: deque[tuple[float, float]] = deque(maxlen=n + 1)

    def update(self, h: float, lo: float) -> tuple[float, float, float]:
        self.win.append((h, lo))
        if len(self.win) <= self.n:
            return NAN, NAN, NAN
        newest_first = list(reversed(self.win))
        hi_age = max(range(len(newest_first)), key=lambda i: (newest_first[i][0], -i))
        lo_age = min(range(len(newest_first)), key=lambda i: (newest_first[i][1], i))
        up = 100.0 * (self.n - hi_age) / self.n
        dn = 100.0 * (self.n - lo_age) / self.n
        return up, dn, up - dn


class WilliamsR:
    def __init__(self, n: int = 14) -> None:
        self.hh, self.ll = Rolling(n, is_max=True), Rolling(n, is_max=False)

    def update(self, h: float, lo: float, c: float) -> float:
        hh, ll = self.hh.update(h), self.ll.update(lo)
        if math.isnan(hh):
            return NAN
        return -100.0 * (hh - c) / (hh - ll) if hh - ll > 0 else -50.0


class MFI:
    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.prev_tp = NAN
        self.flows: deque[tuple[float, float]] = deque(maxlen=n)

    def update(self, h: float, lo: float, c: float, v: float) -> float:
        tp = (h + lo + c) / 3.0
        if not math.isnan(self.prev_tp):
            flow = tp * v
            self.flows.append(
                (flow if tp > self.prev_tp else 0.0, flow if tp < self.prev_tp else 0.0)
            )
        self.prev_tp = tp
        if len(self.flows) < self.n:
            return NAN
        ps = sum(p for p, _ in self.flows)
        ns = sum(q for _, q in self.flows)
        if ns > 0:
            return 100.0 - 100.0 / (1.0 + ps / ns)
        return 100.0 if ps > 0 else 50.0


class CMF:
    def __init__(self, n: int = 20) -> None:
        self.n = n
        self.win: deque[tuple[float, float]] = deque(maxlen=n)

    def update(self, h: float, lo: float, c: float, v: float) -> float:
        rng = h - lo
        mult = ((c - lo) - (h - c)) / rng if rng > 0 else 0.0
        self.win.append((mult * v, v))
        if len(self.win) < self.n:
            return NAN
        vs = sum(w for _, w in self.win)
        return sum(m for m, _ in self.win) / vs if vs > 0 else 0.0


class StochRSI:
    def __init__(self, rsi_n: int = 14, stoch_n: int = 14, k: int = 3, d: int = 3) -> None:
        self.rsi = RSI(rsi_n)
        self.hh, self.ll = _NanRolling(stoch_n, is_max=True), _NanRolling(stoch_n, is_max=False)
        self.k, self.d = _NanSMA(k), _NanSMA(d)

    def update(self, x: float) -> tuple[float, float]:
        r = self.rsi.update(x)
        hh, ll = self.hh.update(r), self.ll.update(r)
        if math.isnan(hh):
            raw = NAN
        else:
            raw = 100.0 * (r - ll) / (hh - ll) if hh - ll > 0 else 50.0
        k = self.k.update(raw)
        return k, self.d.update(k)


class Pivots:
    def __init__(self) -> None:
        self.prev = PreviousDay()

    def update(
        self, h: float, lo: float, c: float, session: int
    ) -> tuple[float, float, float, float, float, float, float]:
        ph, pl, pc = self.prev.update(h, lo, c, session)
        p = (ph + pl + pc) / 3.0
        return (
            p,
            2 * p - pl,
            p + (ph - pl),
            ph + 2 * (p - pl),
            2 * p - ph,
            p - (ph - pl),
            pl - 2 * (ph - p),
        )
