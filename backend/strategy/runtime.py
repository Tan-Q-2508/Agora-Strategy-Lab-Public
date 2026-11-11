"""What a strategy sees and does on each closed candle: the ``ctx`` object.

Visual strategies are compiled into an ``on_bar(ctx)`` function and code strategies write
their own, so both run through exactly the same API (that is what makes "visual and code
versions of the same logic produce identical signals" true by construction).

Safety: code strategies run in a sandbox (``sandbox.py``) that blocks any name starting
with ``_``. Everything a strategy can reach here is therefore either a plain Python value
(float, str, list, dict) or one of the small classes below, whose internals are all
underscore-named. No numpy object ever leaks out (numpy scalars can write files).

No look-ahead: a ``SeriesView`` ends at the current candle, so ``[-1]`` is the latest
closed candle and nothing later is reachable.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

import numpy as np

from backend.analysis import mtf
from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market
from backend.indicators import catalog
from backend.indicators.series import F64, BarSeries

NAN = math.nan
Side = Literal["long", "short"]


# ---------------------------------------------------------------- series


class SeriesView:
    """Read-only history of one series, newest last. Out-of-range reads give NaN
    ("not a number"), and any comparison with NaN is False, so rules simply don't fire
    until there is enough history."""

    __slots__ = ("_arr", "_end", "_scale")

    def __init__(self, arr: F64, end: int, scale: float = 1.0) -> None:
        self._arr = arr
        self._end = end
        self._scale = scale

    def __len__(self) -> int:
        return max(0, self._end)

    def _at(self, idx: int) -> float:
        if 0 <= idx < self._end and idx < len(self._arr):
            return float(self._arr[idx]) * self._scale
        return NAN

    def __getitem__(self, i: int | slice) -> Any:
        if isinstance(i, slice):
            return [self._at(j) for j in range(*i.indices(len(self)))]
        return self._at(self._end + i if i < 0 else i)

    def __iter__(self) -> Iterator[float]:
        return (self._at(j) for j in range(len(self)))

    def ago(self, k: int = 0) -> float:
        """The value ``k`` candles ago (0 = the latest)."""
        return self._at(self._end - 1 - int(k))

    @property
    def last(self) -> float:
        return self._at(self._end - 1)

    def shift(self, k: int) -> SeriesView:
        """The same series as it was ``k`` candles ago. Only backwards: a negative ``k`` would
        read candles that haven't closed yet (look-ahead), so it is refused."""
        if int(k) < 0:
            raise ValueError(
                "shift() only looks back: use 0 or more candles ago. A negative number would "
                "read candles that haven't closed yet."
            )
        return SeriesView(self._arr, self._end - int(k), self._scale)

    def times(self, m: float) -> SeriesView:
        """The series multiplied by ``m`` (e.g. 1.02 = two percent above)."""
        return SeriesView(self._arr, self._end, self._scale * float(m))

    def to_list(self, n: int | None = None) -> list[float]:
        """The last ``n`` values (all if omitted), oldest first."""
        start = 0 if n is None else max(0, self._end - int(n))
        return [self._at(j) for j in range(start, self._end)]

    def __repr__(self) -> str:
        return f"<series, latest {self.last:.4g}, {len(self)} values>"


class Lines:
    """The several lines of one indicator, e.g. ``bb.upper``, ``bb.lower``."""

    __slots__ = ("_lines",)

    def __init__(self, lines: dict[str, SeriesView]) -> None:
        self._lines = lines

    def __getattr__(self, name: str) -> SeriesView:
        try:
            return self._lines[name]
        except KeyError:
            names = ", ".join(self._lines)
            raise AttributeError(f"This indicator has no line '{name}'. Lines: {names}") from None

    def __repr__(self) -> str:
        return f"<lines {', '.join(self._lines)}>"


Value = SeriesView | float | int


def _now(x: Value) -> float:
    return x.last if isinstance(x, SeriesView) else float(x)


def _prev(x: Value) -> float:
    return x.ago(1) if isinstance(x, SeriesView) else float(x)


# ---------------------------------------------------------------- orders a strategy asks for


@dataclass(frozen=True)
class SizeSpec:
    kind: Literal["percent_equity", "fixed_qty", "fixed_amount", "risk_percent"]
    value: float
    # a share of the finished size, taken after every cap (D-214: halving the risk did nothing
    # when the per-trade cap was already the smaller number)
    scale: float = 1.0


@dataclass(frozen=True)
class StopRule:
    kind: Literal["percent", "atr"]
    value: float
    atr_period: int = 14


ScaleKind = Literal["r", "percent", "atr"]


@dataclass(frozen=True)
class ScaleStep:
    """One partial exit: sell ``sell_pct`` percent of the starting position once the price
    has moved ``value`` in the trade's favour. ``kind`` "r" measures that move in multiples
    of the stop distance (1R = as far as the stop-loss is), "percent" in percent of the entry
    price, "atr" in ATRs measured at the signal."""

    kind: ScaleKind
    value: float
    sell_pct: float


@dataclass(frozen=True)
class ScaleOut:
    """Partial exits (D-125): take some profit at each step and let the rest run to the
    target, the trailing stop or the exit rule. ``breakeven``: after the first partial the
    stop moves up to the entry price, so the rest of the trade can no longer lose."""

    steps: tuple[ScaleStep, ...]
    breakeven: bool = True


@dataclass(frozen=True)
class Enter:
    side: Side
    size: SizeSpec | None
    stop_loss: StopRule | None
    take_profit: StopRule | None
    trailing_stop: StopRule | None
    reason: str
    scale_out: ScaleOut | None = None


@dataclass(frozen=True)
class Exit:
    reason: str
    kind: Literal["signal", "time"] = "signal"


Intent = Enter | Exit


class _SizeHelpers:
    """``ctx.size.percent_equity(10)`` and friends."""

    __slots__ = ()

    def percent_equity(self, pct: float) -> SizeSpec:
        return SizeSpec("percent_equity", float(pct))

    def fixed_qty(self, qty: float) -> SizeSpec:
        return SizeSpec("fixed_qty", float(qty))

    def fixed_amount(self, amount: float) -> SizeSpec:
        return SizeSpec("fixed_amount", float(amount))

    def risk_percent(self, pct: float) -> SizeSpec:
        return SizeSpec("risk_percent", float(pct))


class _StopHelpers:
    """``ctx.stop.percent(2)`` or ``ctx.stop.atr(2, 14)``."""

    __slots__ = ()

    def percent(self, pct: float) -> StopRule:
        return StopRule("percent", float(pct))

    def atr(self, multiple: float, period: int = 14) -> StopRule:
        return StopRule("atr", float(multiple), int(period))


SIZE = _SizeHelpers()
STOP = _StopHelpers()


def make_scale_out(steps: Any, breakeven: bool = True) -> ScaleOut | None:
    """``[(1, 50), (2, 25)]`` → sell 50% at 1R and 25% more at 2R. A step may also be
    ``("percent", 3, 33)`` or ``("atr", 2, 33)``. Steps are sorted nearest first; nothing
    when the list is empty."""
    out: list[ScaleStep] = []
    for step in steps or ():
        if isinstance(step, ScaleStep):
            out.append(step)
            continue
        parts = tuple(step)
        if len(parts) == 2:
            kind, value, pct = "r", parts[0], parts[1]
        elif len(parts) == 3:
            kind, value, pct = parts
        else:
            raise TypeError("each partial exit is (R multiple, percent to sell)")
        if kind not in ("r", "percent", "atr"):
            raise TypeError('a partial exit is measured in "r", "percent" or "atr"')
        if float(value) <= 0 or not 0 < float(pct) < 100:
            raise ValueError("a partial exit needs a distance above 0 and a percent from 1 to 99")
        out.append(ScaleStep(cast(ScaleKind, kind), float(value), float(pct)))
    if not out:
        return None
    return ScaleOut(tuple(out), bool(breakeven))


def _stop_rule(x: StopRule | float | int | None) -> StopRule | None:
    if x is None or isinstance(x, StopRule):
        return x
    return StopRule("percent", float(x))  # a bare number means "percent"


# ---------------------------------------------------------------- position


@dataclass(frozen=True)
class PositionView:
    side: Side
    qty: float
    entry_price: float
    entry_time: int
    bars_held: int
    profit_pct: float  # unrealised, after the latest close; negative when losing

    def __bool__(self) -> bool:
        return True


# ---------------------------------------------------------------- indicators


class IndicatorProvider:
    """Computes catalog indicators over a symbol's known history, once per series.

    Backtests know the whole history up front; live paper trading appends candles, and
    the cache is keyed by length so values are recomputed when a candle arrives. Value
    ``i`` only depends on candles ``0..i``, so the extra future values a backtest holds
    are never visible through a ``SeriesView``."""

    def __init__(self, series: BarSeries) -> None:
        self.series = series
        self._cache: dict[tuple[Any, ...], dict[str, F64]] = {}
        self._frames: dict[str, _BiggerFrame] = {}

    def set_series(self, series: BarSeries) -> None:
        if len(series) != len(self.series) or series is not self.series:
            self.series = series
            self._cache.clear()
            self._frames.clear()

    def frame(self, bigger: str, zone: ZoneInfo) -> _BiggerFrame:
        """The bigger chart built from these candles (D-97), made once per series."""
        hit = self._frames.get(bigger)
        if hit is None:
            hit = self._frames[bigger] = _BiggerFrame(mtf.Frame.build(self.series, bigger, zone))
        return hit

    def field(self, name: str) -> F64:
        key = ("field", name)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._cache[key] = {"value": self.series.field(name)}
        return hit["value"]

    def compute(
        self, key: str, params: Mapping[str, float], source: str | F64 | None
    ) -> dict[str, F64]:
        src_key: Any = source if source is None or isinstance(source, str) else id(source)
        ck = (key, tuple(sorted(params.items())), src_key)
        hit = self._cache.get(ck)
        if hit is None:
            hit = self._cache[ck] = catalog.compute(key, self.series, params, source)
            if not isinstance(source, str | None):
                # Hold a reference so ``id(source)`` can't be reused by a new array.
                self._cache[("keep", id(source))] = {"value": source}
        return hit

    def computed(self) -> list[tuple[str, dict[str, float], str | None, dict[str, F64]]]:
        """Every indicator worked out so far on a named price (or its default), as (key,
        settings, source, lines). Indicators of a custom series are left out: they have no
        name to match between two runs. Used by the look-ahead check."""
        out: list[tuple[str, dict[str, float], str | None, dict[str, F64]]] = []
        for ck, lines in self._cache.items():
            if len(ck) != 3 or not (ck[2] is None or isinstance(ck[2], str)):
                continue
            out.append((str(ck[0]), dict(ck[1]), ck[2], lines))
        return out


class _BiggerFrame:
    """A bigger chart's candles, its indicators, and every value lined up with the strategy's
    own candles as of the bigger chart's last finished candle (no look-ahead)."""

    def __init__(self, frame: mtf.Frame) -> None:
        self.frame = frame
        self.provider = IndicatorProvider(frame.series)
        self.price_ids: dict[int, str] = {}

    def price(self, name: str) -> F64:
        arr = self.frame.line(("field", name), self.provider.field(name))
        self.price_ids[id(arr)] = name
        return arr

    def lines(self, key: str, params: Mapping[str, float], source: str | None) -> dict[str, F64]:
        raw = self.provider.compute(key, params, source)
        ck = (key, tuple(sorted(params.items())), source)
        return {name: self.frame.line((ck, name), arr) for name, arr in raw.items()}


class _IndicatorAPI:
    """``ctx.ind.rsi(ctx.close, 14)``: every catalog indicator as a method.

    Positional arguments: the source series first (only for indicators that take one),
    then the settings in catalog order. Keyword arguments use the setting names.
    ``ctx.chart("1w").ind`` is the same on the bigger chart (pass its prices, e.g.
    ``ctx.chart("1w").close`` or simply ``"close"``)."""

    __slots__ = ("_ctx", "_tf")

    def __init__(self, ctx: StrategyContext, tf: str | None = None) -> None:
        self._ctx = ctx
        self._tf = tf

    def __getattr__(self, key: str) -> Callable[..., SeriesView | Lines]:
        try:
            ind = catalog.get(key)
        except catalog.UnknownIndicator:
            raise AttributeError(f"Agora has no indicator called '{key}'.") from None
        ctx = self._ctx

        def call(*args: Any, **kwargs: Any) -> SeriesView | Lines:
            rest = list(args)
            source: str | F64 | None = None
            if ind.uses_source:
                if rest and isinstance(rest[0], SeriesView | str):
                    source = _source_of(rest.pop(0))
                if "source" in kwargs:
                    source = _source_of(kwargs.pop("source"))
            elif rest and isinstance(rest[0], SeriesView | str):
                raise TypeError(f"{ind.label} uses the whole candle; don't pass a price series.")
            if len(rest) > len(ind.params):
                raise TypeError(f"{ind.label} takes at most {len(ind.params)} settings.")
            params: dict[str, Any] = {p.name: v for p, v in zip(ind.params, rest, strict=False)}
            params.update(kwargs)
            return ctx._indicator(key, params, source, self._tf)

        call.__doc__ = ind.description
        return call

    def __dir__(self) -> list[str]:
        return sorted(catalog.INDICATORS)


def _source_of(x: SeriesView | str) -> str | F64:
    if isinstance(x, str):
        if x not in catalog.PRICE_FIELDS:
            raise ValueError(f"'{x}' isn't a price. Use one of: {', '.join(catalog.PRICE_FIELDS)}")
        return x
    if x._scale != 1.0:
        return x._arr * x._scale
    return x._arr


class BiggerChart:
    """``ctx.chart("1w")``: a bigger timeframe of the same stock (D-97). Its prices and
    indicators are lined up with your candles and show the bigger chart's **last finished**
    candle, so ``ctx.chart("1w").close[-1]`` is last week's close, never this unfinished
    week's."""

    __slots__ = ("_ctx", "_tf", "ind")

    def __init__(self, ctx: StrategyContext, tf: str) -> None:
        self._ctx = ctx
        self._tf = tf
        self.ind = _IndicatorAPI(ctx, tf)

    def price(self, name: str) -> SeriesView:
        return self._ctx._view(self._ctx._frame(self._tf).price(name))

    @property
    def open(self) -> SeriesView:
        return self.price("open")

    @property
    def high(self) -> SeriesView:
        return self.price("high")

    @property
    def low(self) -> SeriesView:
        return self.price("low")

    @property
    def close(self) -> SeriesView:
        return self.price("close")

    @property
    def volume(self) -> SeriesView:
        return self.price("volume")

    @property
    def hl2(self) -> SeriesView:
        return self.price("hl2")

    @property
    def typical(self) -> SeriesView:
        return self.price("typical")

    def __repr__(self) -> str:
        return f"<the {mtf.LABEL[self._tf]} chart>"


# ---------------------------------------------------------------- the context


@dataclass
class StrategyContext:
    """One per symbol per run. The engine moves ``_index`` forward and refreshes the
    position before each ``on_bar`` call, then reads ``_intents``."""

    symbol: str
    market: Market
    timeframe: str
    params: dict[str, float]
    _provider: IndicatorProvider
    _default_size: SizeSpec | None = None
    _index: int = -1
    _position: PositionView | None = None
    _intents: list[Intent] = field(default_factory=list)
    _logs: list[str] = field(default_factory=list)
    _equity: float = 0.0
    _tz: ZoneInfo | None = None

    def __post_init__(self) -> None:
        self._tz = ZoneInfo(MARKET_TZ[self.market])
        self.ind = _IndicatorAPI(self)
        self.size = SIZE
        self.stop = STOP

    # -- engine side

    def _advance(self, index: int, position: PositionView | None, equity: float) -> None:
        self._index = index
        self._position = position
        self._equity = equity
        self._intents.clear()

    def _view(self, arr: F64) -> SeriesView:
        return SeriesView(arr, self._index + 1)

    def _frame(self, tf: str) -> _BiggerFrame:
        assert self._tz is not None
        return self._provider.frame(tf, self._tz)

    def chart(self, timeframe: str) -> BiggerChart:
        """A bigger timeframe of this stock, e.g. ``ctx.chart("1w")`` on a daily strategy."""
        tf = str(timeframe)
        if not mtf.allowed(self.timeframe, tf):
            options = ", ".join(f'"{t}"' for t in mtf.BIGGER.get(self.timeframe, ()))
            raise ValueError(
                f"A {mtf.LABEL.get(self.timeframe, self.timeframe)} strategy can read these "
                f"bigger charts: {options or 'none'}."
            )
        return BiggerChart(self, tf)

    def _indicator(
        self,
        key: str,
        params: Mapping[str, Any],
        source: str | F64 | None,
        tf: str | None = None,
    ) -> SeriesView | Lines:
        ind = catalog.get(key)
        resolved = catalog.resolve_params(ind, params)
        if tf is not None:
            frame = self._frame(tf)
            if source is not None and not isinstance(source, str):
                name = frame.price_ids.get(id(source))
                if name is None:
                    raise ValueError(
                        "On a bigger chart, give the indicator one of that chart's prices, "
                        'e.g. ctx.chart("1w").close or "close".'
                    )
                source = name
            lines = frame.lines(key, resolved, source)
            if len(lines) == 1:
                return self._view(next(iter(lines.values())))
            return Lines({k: self._view(v) for k, v in lines.items()})
        out = self._provider.compute(key, resolved, source)
        if len(out) == 1:
            return self._view(next(iter(out.values())))
        return Lines({k: self._view(v) for k, v in out.items()})

    def _line(
        self,
        key: str,
        params: Mapping[str, float],
        source: str | None,
        output: str | None,
        tf: str | None = None,
    ) -> SeriesView:
        """One indicator line (used by compiled visual strategies), optionally on a bigger
        chart."""
        name = output or catalog.get(key).outputs[0][0]
        if tf is not None:
            return self._view(self._frame(tf).lines(key, params, source)[name])
        out = self._provider.compute(key, params, source)
        return self._view(out[name])

    # -- prices

    @property
    def open(self) -> SeriesView:
        return self._view(self._provider.field("open"))

    @property
    def high(self) -> SeriesView:
        return self._view(self._provider.field("high"))

    @property
    def low(self) -> SeriesView:
        return self._view(self._provider.field("low"))

    @property
    def close(self) -> SeriesView:
        return self._view(self._provider.field("close"))

    @property
    def volume(self) -> SeriesView:
        return self._view(self._provider.field("volume"))

    @property
    def hl2(self) -> SeriesView:
        return self._view(self._provider.field("hl2"))

    @property
    def typical(self) -> SeriesView:
        return self._view(self._provider.field("typical"))

    def price(self, name: str, tf: str | None = None) -> SeriesView:
        if tf is not None:
            return self._view(self._frame(tf).price(name))
        return self._view(self._provider.field(name))

    # -- time and state

    @property
    def bar_index(self) -> int:
        return self._index

    @property
    def time(self) -> int:
        """The latest candle's open time (UTC milliseconds)."""
        return int(self._provider.series.ts[self._index])

    @property
    def clock(self) -> str:
        """The latest candle's open time in the market's local time, as "HH:MM"."""
        return ms_to_dt(self.time, self._tz).strftime("%H:%M")

    @property
    def date(self) -> str:
        return ms_to_dt(self.time, self._tz).strftime("%Y-%m-%d")

    @property
    def position(self) -> PositionView | None:
        return self._position

    @property
    def equity(self) -> float:
        return self._equity

    # -- rule helpers (NaN-safe: anything compared with NaN is False)

    def above(self, a: Value, b: Value) -> bool:
        return _now(a) > _now(b)

    def below(self, a: Value, b: Value) -> bool:
        return _now(a) < _now(b)

    def at_least(self, a: Value, b: Value) -> bool:
        return _now(a) >= _now(b)

    def at_most(self, a: Value, b: Value) -> bool:
        return _now(a) <= _now(b)

    def crosses_above(self, a: Value, b: Value) -> bool:
        """True on the candle where ``a`` moves from at-or-below ``b`` to above it."""
        return _now(a) > _now(b) and _prev(a) <= _prev(b)

    def crosses_below(self, a: Value, b: Value) -> bool:
        return _now(a) < _now(b) and _prev(a) >= _prev(b)

    def between(self, x: Value, lower: Value, upper: Value) -> bool:
        return _now(lower) <= _now(x) <= _now(upper)

    def time_between(self, after: str | None = None, before: str | None = None) -> bool:
        """True when the latest candle opened at or after ``after`` and before ``before``."""
        t = self.clock
        return (after is None or t >= after) and (before is None or t < before)

    # -- actions

    def buy(
        self,
        size: SizeSpec | None = None,
        stop_loss: StopRule | float | None = None,
        take_profit: StopRule | float | None = None,
        trailing_stop: StopRule | float | None = None,
        reason: str = "Buy signal",
        scale_out: ScaleOut | None = None,
    ) -> None:
        """Open a long position at the next candle's open (ignored if already in one).
        ``scale_out``: partial exits from ``ctx.scale_out([(1, 50)])``."""
        self._enter("long", size, stop_loss, take_profit, trailing_stop, reason, scale_out)

    def short(
        self,
        size: SizeSpec | None = None,
        stop_loss: StopRule | float | None = None,
        take_profit: StopRule | float | None = None,
        trailing_stop: StopRule | float | None = None,
        reason: str = "Short signal",
        scale_out: ScaleOut | None = None,
    ) -> None:
        """Open a short position (US, or India intraday only)."""
        self._enter("short", size, stop_loss, take_profit, trailing_stop, reason, scale_out)

    def _enter(
        self,
        side: Side,
        size: SizeSpec | None,
        sl: StopRule | float | None,
        tp: StopRule | float | None,
        ts: StopRule | float | None,
        reason: str,
        scale_out: ScaleOut | None = None,
    ) -> None:
        if size is not None and not isinstance(size, SizeSpec):
            raise TypeError("size must come from ctx.size, e.g. ctx.size.percent_equity(10)")
        if scale_out is not None and not isinstance(scale_out, ScaleOut):
            raise TypeError("scale_out must come from ctx.scale_out, e.g. ctx.scale_out([(1, 50)])")
        self._intents.append(
            Enter(
                side,
                size or self._default_size,
                _stop_rule(sl),
                _stop_rule(tp),
                _stop_rule(ts),
                str(reason)[:200],
                scale_out,
            )
        )

    def scale_out(self, steps: Any, breakeven: bool = True) -> ScaleOut | None:
        """Partial exits: ``ctx.scale_out([(1, 50), (2, 25)])`` sells half the position once
        the price has moved as far as the stop distance (1R) and a quarter more at 2R; the
        rest rides the target, trailing stop or exit rule. With ``breakeven`` the stop moves
        to the entry price after the first partial."""
        return make_scale_out(steps, breakeven)

    def sell_all(
        self, reason: str = "Exit signal", kind: Literal["signal", "time"] = "signal"
    ) -> None:
        """Close the open position (long or short) at the next candle's open."""
        self._intents.append(Exit(str(reason)[:200], "time" if kind == "time" else "signal"))

    exit = sell_all

    def log(self, *parts: Any) -> None:
        """Write a line to this run's strategy log (shown under the results)."""
        if len(self._logs) < 2000:
            self._logs.append(" ".join(str(p) for p in parts)[:500])


def as_float_array(values: list[float]) -> F64:
    return np.asarray(values, dtype=np.float64)
