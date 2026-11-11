"""The indicator catalog: names, plain-English descriptions, parameters and outputs.

The visual builder, the AI helper's strategy schema, the chart overlays and the
strategy compiler all read this one table, so an indicator added here shows up
everywhere with the same name and limits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.indicators import stream as st
from backend.indicators import stream_extra as sx
from backend.indicators import stream_world as sw
from backend.indicators import vector as vx
from backend.indicators import vector_extra as vxx
from backend.indicators import vector_world as vw
from backend.indicators.series import F64, BarSeries

PRICE_FIELDS = ("close", "open", "high", "low", "hl2", "typical", "volume")


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: float
    min: float
    max: float
    integer: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "type": "int" if self.integer else "float",
        }


@dataclass(frozen=True)
class Indicator:
    key: str
    label: str
    description: str
    params: tuple[Param, ...]
    outputs: tuple[tuple[str, str], ...]  # (key, label); the first is the default
    overlay: bool  # drawn on the price chart (True) or in its own pane
    uses_source: bool = False  # can be computed on a chosen price field
    default_source: str = "close"
    intraday_only: bool = False
    compute: Callable[[BarSeries, Mapping[str, float], F64], tuple[F64, ...]] = field(
        default=lambda s, p, x: (x,), repr=False
    )
    streamer: Callable[[Mapping[str, float]], Any] = field(default=lambda p: None, repr=False)
    stream_inputs: str = "source"  # which bar fields the streamer's update() takes
    group: str = ""  # where the builder's picker lists it ("Momentum", "Volume", …)
    warm: Callable[[Mapping[str, float]], int] | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "params": [p.public() for p in self.params],
            "outputs": [{"key": k, "label": label} for k, label in self.outputs],
            "overlay": self.overlay,
            "uses_source": self.uses_source,
            "default_source": self.default_source,
            "intraday_only": self.intraday_only,
            "group": self.group or GROUPS.get(self.key, "Other"),
        }

    def warmup(self, params: Mapping[str, float]) -> int:
        """How many earlier candles to load so values have settled by the test start.
        Smoothed indicators (EMA, RSI, ATR, …) get three times their lengths."""
        if self.key in ("high_52w", "low_52w"):
            return 260
        if self.warm is not None:
            return self.warm({p.name: float(params.get(p.name, p.default)) for p in self.params})
        nums = [int(params.get(p.name, p.default)) for p in self.params if p.integer]
        return 3 * sum(nums) + 1 if nums else 1


def _p(name: str, label: str, default: float, lo: float, hi: float, integer: bool = True) -> Param:
    return Param(name, label, default, lo, hi, integer)


PERIOD = _p("period", "Length (candles)", 14, 1, 500)


def _i(p: Mapping[str, float], k: str) -> int:
    return int(p[k])


def _f(p: Mapping[str, float], k: str) -> float:
    return float(p[k])


INDICATORS: dict[str, Indicator] = {}


def _add(ind: Indicator) -> None:
    INDICATORS[ind.key] = ind


_add(
    Indicator(
        "sma",
        "Simple moving average (SMA)",
        "The average price over the last N candles. Smooths out noise to show the trend.",
        (_p("period", "Length (candles)", 20, 1, 500),),
        (("value", "SMA"),),
        overlay=True,
        uses_source=True,
        compute=lambda s, p, x: (vx.sma(x, _i(p, "period")),),
        streamer=lambda p: st.SMA(int(p["period"])),
    )
)
_add(
    Indicator(
        "ema",
        "Exponential moving average (EMA)",
        "A moving average that reacts faster to recent prices than the SMA.",
        (_p("period", "Length (candles)", 20, 1, 500),),
        (("value", "EMA"),),
        overlay=True,
        uses_source=True,
        compute=lambda s, p, x: (vx.ema(x, _i(p, "period")),),
        streamer=lambda p: st.EMA(int(p["period"])),
    )
)
_add(
    Indicator(
        "wma",
        "Weighted moving average (WMA)",
        "A moving average that gives the newest candles the most weight.",
        (_p("period", "Length (candles)", 20, 1, 500),),
        (("value", "WMA"),),
        overlay=True,
        uses_source=True,
        compute=lambda s, p, x: (vx.wma(x, _i(p, "period")),),
        streamer=lambda p: st.WMA(int(p["period"])),
    )
)
_add(
    Indicator(
        "rsi",
        "Relative strength index (RSI)",
        "Momentum from 0 to 100. Below 30 often means oversold, above 70 overbought.",
        (PERIOD,),
        (("value", "RSI"),),
        overlay=False,
        uses_source=True,
        compute=lambda s, p, x: (vx.rsi(x, _i(p, "period")),),
        streamer=lambda p: st.RSI(int(p["period"])),
    )
)
_add(
    Indicator(
        "macd",
        "MACD",
        "The gap between a fast and a slow EMA, plus its own average (the signal line).",
        (
            _p("fast", "Fast length", 12, 1, 200),
            _p("slow", "Slow length", 26, 2, 400),
            _p("signal", "Signal length", 9, 1, 200),
        ),
        (("macd", "MACD line"), ("signal", "Signal line"), ("histogram", "Histogram")),
        overlay=False,
        uses_source=True,
        compute=lambda s, p, x: vx.macd(x, _i(p, "fast"), _i(p, "slow"), _i(p, "signal")),
        streamer=lambda p: st.MACD(int(p["fast"]), int(p["slow"]), int(p["signal"])),
    )
)
_add(
    Indicator(
        "bollinger",
        "Bollinger Bands",
        "A moving average with bands a set number of standard deviations above and below.",
        (
            _p("period", "Length (candles)", 20, 2, 500),
            _p("mult", "Band width (std devs)", 2.0, 0.1, 10, False),
        ),
        (("middle", "Middle band"), ("upper", "Upper band"), ("lower", "Lower band")),
        overlay=True,
        uses_source=True,
        compute=lambda s, p, x: vx.bollinger(x, _i(p, "period"), _f(p, "mult")),
        streamer=lambda p: st.Bollinger(int(p["period"]), float(p["mult"])),
    )
)
_add(
    Indicator(
        "atr",
        "Average true range (ATR)",
        "How much the price typically moves per candle. Useful for stop-loss distances.",
        (PERIOD,),
        (("value", "ATR"),),
        overlay=False,
        compute=lambda s, p, x: (vx.atr(s.high, s.low, s.close, _i(p, "period")),),
        streamer=lambda p: st.ATR(int(p["period"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "adx",
        "Average directional index (ADX)",
        "Trend strength from 0 to 100 (above 25 is a strong trend), with +DI and −DI direction lines.",
        (PERIOD,),
        (("adx", "ADX"), ("plus_di", "+DI"), ("minus_di", "−DI")),
        overlay=False,
        compute=lambda s, p, x: vx.adx(s.high, s.low, s.close, _i(p, "period")),
        streamer=lambda p: st.ADX(int(p["period"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "stochastic",
        "Stochastic oscillator",
        "Where the close sits in the recent high-low range, 0 to 100. Below 20 oversold, above 80 overbought.",
        (
            _p("k", "%K length", 14, 1, 200),
            _p("smooth", "%K smoothing", 3, 1, 50),
            _p("d", "%D length", 3, 1, 50),
        ),
        (("k", "%K"), ("d", "%D")),
        overlay=False,
        compute=lambda s, p, x: vx.stochastic(
            s.high, s.low, s.close, _i(p, "k"), _i(p, "smooth"), _i(p, "d")
        ),
        streamer=lambda p: st.Stochastic(int(p["k"]), int(p["smooth"]), int(p["d"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "cci",
        "Commodity channel index (CCI)",
        "How far the price is from its average, scaled. Above +100 is strong, below −100 weak.",
        (_p("period", "Length (candles)", 20, 2, 500),),
        (("value", "CCI"),),
        overlay=False,
        compute=lambda s, p, x: (vx.cci(s.high, s.low, s.close, _i(p, "period")),),
        streamer=lambda p: st.CCI(int(p["period"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "vwap",
        "VWAP (volume-weighted average price)",
        "The day's average price weighted by volume. Resets every session. Intraday only.",
        (),
        (("value", "VWAP"),),
        overlay=True,
        intraday_only=True,
        compute=lambda s, p, x: (vx.vwap(s.high, s.low, s.close, s.volume, s.session),),
        streamer=lambda p: st.VWAP(),
        stream_inputs="hlcv_session",
    )
)
_add(
    Indicator(
        "supertrend",
        "Supertrend",
        "A trailing line under the price in uptrends and above it in downtrends, based on ATR.",
        (_p("period", "ATR length", 10, 1, 200), _p("mult", "ATR multiple", 3.0, 0.1, 20, False)),
        (("value", "Supertrend"), ("direction", "Direction (+1 up, −1 down)")),
        overlay=True,
        compute=lambda s, p, x: vx.supertrend(
            s.high, s.low, s.close, _i(p, "period"), _f(p, "mult")
        ),
        streamer=lambda p: st.Supertrend(int(p["period"]), float(p["mult"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "donchian",
        "Donchian Channel",
        "The highest high and lowest low of the last N candles (including the current one).",
        (_p("period", "Length (candles)", 20, 1, 500),),
        (("upper", "Upper"), ("middle", "Middle"), ("lower", "Lower")),
        overlay=True,
        compute=lambda s, p, x: vx.donchian(s.high, s.low, _i(p, "period")),
        streamer=lambda p: st.Donchian(int(p["period"])),
        stream_inputs="hl",
    )
)
_add(
    Indicator(
        "keltner",
        "Keltner Channel",
        "An EMA with bands a multiple of ATR above and below.",
        (
            _p("period", "EMA length", 20, 1, 500),
            _p("mult", "ATR multiple", 2.0, 0.1, 10, False),
            _p("atr_period", "ATR length", 10, 1, 200),
        ),
        (("middle", "Middle"), ("upper", "Upper"), ("lower", "Lower")),
        overlay=True,
        compute=lambda s, p, x: vx.keltner(
            s.high, s.low, s.close, _i(p, "period"), _f(p, "mult"), _i(p, "atr_period")
        ),
        streamer=lambda p: st.Keltner(int(p["period"]), float(p["mult"]), int(p["atr_period"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "obv",
        "On-balance volume (OBV)",
        "Running total of volume: added on up candles, subtracted on down candles.",
        (),
        (("value", "OBV"),),
        overlay=False,
        compute=lambda s, p, x: (vx.obv(s.close, s.volume),),
        streamer=lambda p: st.OBV(),
        stream_inputs="cv",
    )
)
_add(
    Indicator(
        "roc",
        "Rate of change (ROC)",
        "The percentage change versus N candles ago.",
        (_p("period", "Length (candles)", 12, 1, 500),),
        (("value", "ROC %"),),
        overlay=False,
        uses_source=True,
        compute=lambda s, p, x: (vx.roc(x, _i(p, "period")),),
        streamer=lambda p: st.ROC(int(p["period"])),
    )
)
_add(
    Indicator(
        "highest",
        "Highest over N",
        "The highest value of the last N candles (including the current one).",
        (_p("period", "Length (candles)", 20, 1, 1000),),
        (("value", "Highest"),),
        overlay=True,
        uses_source=True,
        default_source="high",
        compute=lambda s, p, x: (vx.rolling_max(x, _i(p, "period")),),
        streamer=lambda p: st.Rolling(int(p["period"]), is_max=True),
    )
)
_add(
    Indicator(
        "lowest",
        "Lowest over N",
        "The lowest value of the last N candles (including the current one).",
        (_p("period", "Length (candles)", 20, 1, 1000),),
        (("value", "Lowest"),),
        overlay=True,
        uses_source=True,
        default_source="low",
        compute=lambda s, p, x: (vx.rolling_min(x, _i(p, "period")),),
        streamer=lambda p: st.Rolling(int(p["period"]), is_max=False),
    )
)
_add(
    Indicator(
        "high_52w",
        "52-week high",
        "The highest price of the past year. Empty until a full year of history exists.",
        (),
        (("value", "52-week high"),),
        overlay=True,
        compute=lambda s, p, x: (vx.high_52w(s.high, s.ts),),
        streamer=lambda p: st.TimeExtreme(is_max=True),
        stream_inputs="h_ts",
    )
)
_add(
    Indicator(
        "low_52w",
        "52-week low",
        "The lowest price of the past year. Empty until a full year of history exists.",
        (),
        (("value", "52-week low"),),
        overlay=True,
        compute=lambda s, p, x: (vx.low_52w(s.low, s.ts),),
        streamer=lambda p: st.TimeExtreme(is_max=False),
        stream_inputs="l_ts",
    )
)
_add(
    Indicator(
        "prev_day",
        "Previous day's high, low and close",
        "Yesterday's levels, often used as support and resistance.",
        (),
        (("high", "Previous high"), ("low", "Previous low"), ("close", "Previous close")),
        overlay=True,
        compute=lambda s, p, x: vx.previous_day(s.high, s.low, s.close, s.session),
        streamer=lambda p: st.PreviousDay(),
        stream_inputs="hlc_session",
    )
)
_add(
    Indicator(
        "opening_range",
        "Opening range",
        "The high and low of the session's first minutes. Intraday only.",
        (_p("minutes", "Range length (minutes)", 15, 1, 240),),
        (("high", "Range high"), ("low", "Range low")),
        overlay=True,
        intraday_only=True,
        compute=lambda s, p, x: vx.opening_range(
            s.high, s.low, s.ts, s.session, s.session_open, s.timeframe.minutes, _i(p, "minutes")
        ),
        streamer=lambda p: _OpeningRangeFactory(int(p["minutes"])),
        stream_inputs="opening_range",
    )
)


# ---------------------------------------------------------------- Phase 9.1 (KAIROS §4)


def _ma(
    key: str, label: str, desc: str, vec: Any, stream: Any, default: int = 20, lo: int = 1
) -> None:
    _add(
        Indicator(
            key,
            label,
            desc,
            (_p("period", "Length (candles)", default, lo, 500),),
            (("value", label.split(" (")[-1].rstrip(")")),),
            overlay=True,
            uses_source=True,
            compute=lambda s, p, x: (vec(x, _i(p, "period")),),
            streamer=lambda p: stream(int(p["period"])),
        )
    )


_ma(
    "dema",
    "Double EMA (DEMA)",
    "An EMA with most of its lag removed: 2 × EMA − EMA of the EMA.",
    vxx.dema,
    sx.DEMA,
)
_ma(
    "tema",
    "Triple EMA (TEMA)",
    "Three EMAs combined to follow the price with very little lag.",
    vxx.tema,
    sx.TEMA,
)
_ma(
    "hma",
    "Hull moving average (HMA)",
    "A fast, smooth moving average built from weighted averages.",
    vxx.hma,
    sx.HMA,
    lo=2,
)
_add(
    Indicator(
        "vwma",
        "Volume-weighted moving average (VWMA)",
        "An average where candles with more trading count more.",
        (_p("period", "Length (candles)", 20, 1, 500),),
        (("value", "VWMA"),),
        overlay=True,
        uses_source=True,
        compute=lambda s, p, x: (vxx.vwma(x, s.volume, _i(p, "period")),),
        streamer=lambda p: sx.VWMA(int(p["period"])),
        stream_inputs="source_v",
    )
)
_add(
    Indicator(
        "kama",
        "Kaufman adaptive moving average (KAMA)",
        "Speeds up when the price trends cleanly and slows down when it's choppy.",
        (
            _p("period", "Efficiency length", 10, 1, 200),
            _p("fast", "Fast length", 2, 1, 50),
            _p("slow", "Slow length", 30, 2, 200),
        ),
        (("value", "KAMA"),),
        overlay=True,
        uses_source=True,
        compute=lambda s, p, x: (vxx.kama(x, _i(p, "period"), _i(p, "fast"), _i(p, "slow")),),
        streamer=lambda p: sx.KAMA(int(p["period"]), int(p["fast"]), int(p["slow"])),
    )
)
_add(
    Indicator(
        "ichimoku",
        "Ichimoku cloud",
        "Japanese trend system: conversion and base lines plus a cloud of support/resistance.",
        (
            _p("conversion", "Conversion length", 9, 1, 200),
            _p("base", "Base length", 26, 1, 200),
            _p("span", "Span B length", 52, 1, 400),
            _p("shift", "Cloud shift (candles)", 26, 0, 200),
        ),
        (
            ("conversion", "Conversion line"),
            ("base", "Base line"),
            ("span_a", "Cloud span A"),
            ("span_b", "Cloud span B"),
        ),
        overlay=True,
        compute=lambda s, p, x: vxx.ichimoku(
            s.high, s.low, _i(p, "conversion"), _i(p, "base"), _i(p, "span"), _i(p, "shift")
        ),
        streamer=lambda p: sx.Ichimoku(
            int(p["conversion"]), int(p["base"]), int(p["span"]), int(p["shift"])
        ),
        stream_inputs="hl",
    )
)
_add(
    Indicator(
        "psar",
        "Parabolic SAR",
        "Dots that trail the price and flip sides when the trend turns; often used as a stop.",
        (
            _p("start", "Start step", 0.02, 0.001, 0.5, integer=False),
            _p("step", "Step", 0.02, 0.001, 0.5, integer=False),
            _p("maximum", "Maximum step", 0.2, 0.01, 1.0, integer=False),
        ),
        (("value", "SAR"),),
        overlay=True,
        compute=lambda s, p, x: (
            vxx.psar(s.high, s.low, s.close, _f(p, "start"), _f(p, "step"), _f(p, "maximum")),
        ),
        streamer=lambda p: sx.PSAR(float(p["start"]), float(p["step"]), float(p["maximum"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "mfi",
        "Money flow index (MFI)",
        "An RSI that also weighs volume, 0 to 100. Above 80 overbought, below 20 oversold.",
        (PERIOD,),
        (("value", "MFI"),),
        overlay=False,
        compute=lambda s, p, x: (vxx.mfi(s.high, s.low, s.close, s.volume, _i(p, "period")),),
        streamer=lambda p: sx.MFI(int(p["period"])),
        stream_inputs="hlcv",
    )
)
_add(
    Indicator(
        "williams_r",
        "Williams %R",
        "Where the close sits in the recent range, 0 (top) to −100 (bottom). Above −20 is "
        "overbought, below −80 oversold.",
        (PERIOD,),
        (("value", "%R"),),
        overlay=False,
        compute=lambda s, p, x: (vxx.williams_r(s.high, s.low, s.close, _i(p, "period")),),
        streamer=lambda p: sx.WilliamsR(int(p["period"])),
        stream_inputs="hlc",
    )
)
_add(
    Indicator(
        "aroon",
        "Aroon",
        "How recently the highest high and lowest low happened, 0 to 100. Up above down means "
        "an uptrend.",
        (_p("period", "Length (candles)", 25, 1, 500),),
        (("up", "Aroon up"), ("down", "Aroon down"), ("oscillator", "Aroon oscillator")),
        overlay=False,
        compute=lambda s, p, x: vxx.aroon(s.high, s.low, _i(p, "period")),
        streamer=lambda p: sx.Aroon(int(p["period"])),
        stream_inputs="hl",
    )
)
_add(
    Indicator(
        "cmf",
        "Chaikin money flow (CMF)",
        "Buying versus selling pressure from where candles close and their volume, −1 to +1.",
        (_p("period", "Length (candles)", 20, 1, 500),),
        (("value", "CMF"),),
        overlay=False,
        compute=lambda s, p, x: (vxx.cmf(s.high, s.low, s.close, s.volume, _i(p, "period")),),
        streamer=lambda p: sx.CMF(int(p["period"])),
        stream_inputs="hlcv",
    )
)
_add(
    Indicator(
        "stoch_rsi",
        "Stochastic RSI",
        "The stochastic of the RSI, 0 to 100: a faster, more sensitive momentum gauge.",
        (
            _p("rsi_period", "RSI length", 14, 1, 200),
            _p("period", "Stochastic length", 14, 1, 200),
            _p("smooth", "%K smoothing", 3, 1, 50),
            _p("d", "%D length", 3, 1, 50),
        ),
        (("k", "%K"), ("d", "%D")),
        overlay=False,
        uses_source=True,
        compute=lambda s, p, x: vxx.stoch_rsi(
            x, _i(p, "rsi_period"), _i(p, "period"), _i(p, "smooth"), _i(p, "d")
        ),
        streamer=lambda p: sx.StochRSI(
            int(p["rsi_period"]), int(p["period"]), int(p["smooth"]), int(p["d"])
        ),
    )
)
_add(
    Indicator(
        "pivots",
        "Pivot points",
        "Support and resistance levels from the previous session's high, low and close.",
        (),
        (
            ("p", "Pivot"),
            ("r1", "Resistance 1"),
            ("r2", "Resistance 2"),
            ("r3", "Resistance 3"),
            ("s1", "Support 1"),
            ("s2", "Support 2"),
            ("s3", "Support 3"),
        ),
        overlay=True,
        compute=lambda s, p, x: vxx.pivots(s.high, s.low, s.close, s.session),
        streamer=lambda p: sx.Pivots(),
        stream_inputs="hlc_session",
    )
)


# ---------------------------------------------------------------- Phase 10.1: the world's list

L = _p("period", "Length (candles)", 14, 1, 500)


def _w(
    key: str,
    label: str,
    desc: str,
    params: tuple[Param, ...],
    outputs: tuple[tuple[str, str], ...],
    compute: Callable[[BarSeries, Mapping[str, float], F64], tuple[F64, ...]],
    streamer: Callable[[Mapping[str, float]], Any],
    *,
    group: str,
    inputs: str = "source",
    overlay: bool = False,
    source: bool = False,
    default_source: str = "close",
    warm: Callable[[Mapping[str, float]], int] | None = None,
    intraday_only: bool = False,
) -> None:
    _add(
        Indicator(
            key,
            label,
            desc,
            params,
            outputs,
            overlay=overlay,
            uses_source=source,
            default_source=default_source,
            intraday_only=intraday_only,
            compute=compute,
            streamer=streamer,
            stream_inputs=inputs,
            group=group,
            warm=warm,
        )
    )


MA = "Moving averages"
MOM = "Momentum"
TREND = "Trend"
VOLA = "Volatility & bands"
VOL = "Volume"
LEVELS = "Levels"

# ---- moving averages
_w(
    "smma",
    "Smoothed moving average (SMMA)",
    "Wilder's smoothing: a slow, steady average used by RSI, ATR and the Alligator.",
    (_p("period", "Length (candles)", 14, 1, 500),),
    (("value", "SMMA"),),
    lambda s, p, x: (vw.smma(x, _i(p, "period")),),
    lambda p: st.RMA(int(p["period"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "zlema",
    "Zero-lag EMA (ZLEMA)",
    "An EMA corrected for lag by adding the recent change back in.",
    (_p("period", "Length (candles)", 20, 1, 500),),
    (("value", "ZLEMA"),),
    lambda s, p, x: (vw.zlema(x, _i(p, "period")),),
    lambda p: sw.ZLEMA(int(p["period"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "alma",
    "Arnaud Legoux moving average (ALMA)",
    "A bell-curve-weighted average: smooth like an SMA, quick like an EMA.",
    (
        _p("period", "Length (candles)", 9, 1, 500),
        _p("offset", "Offset (0 smooth … 1 fast)", 0.85, 0.0, 1.0, False),
        _p("sigma", "Sigma (curve width)", 6.0, 0.5, 20.0, False),
    ),
    (("value", "ALMA"),),
    lambda s, p, x: (vw.alma(x, _i(p, "period"), _f(p, "offset"), _f(p, "sigma")),),
    lambda p: sw.ALMA(int(p["period"]), float(p["offset"]), float(p["sigma"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "t3",
    "Tillson T3",
    "Six EMAs blended into one very smooth line with little lag.",
    (
        _p("period", "Length (candles)", 5, 1, 100),
        _p("vfactor", "Volume factor (0…1)", 0.7, 0.0, 1.0, False),
    ),
    (("value", "T3"),),
    lambda s, p, x: (vw.t3(x, _i(p, "period"), _f(p, "vfactor")),),
    lambda p: sw.T3(int(p["period"]), float(p["vfactor"])),
    group=MA,
    overlay=True,
    source=True,
    warm=lambda p: 18 * int(p["period"]) + 1,
)
_w(
    "mcginley",
    "McGinley Dynamic",
    "A self-adjusting average that hugs the price better than an EMA in fast markets.",
    (_p("period", "Length (candles)", 14, 1, 500),),
    (("value", "McGinley"),),
    lambda s, p, x: (vw.mcginley(x, _i(p, "period")),),
    lambda p: sw.McGinley(int(p["period"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "linreg",
    "Linear regression (LSMA)",
    "The best straight line through the last N candles: its end point, its slope per candle and how well it fits (R², 0 to 1).",
    (_p("period", "Length (candles)", 25, 2, 500),),
    (("value", "Regression value"), ("slope", "Slope per candle"), ("r2", "Fit (R²)")),
    lambda s, p, x: vw.linreg(x, _i(p, "period")),
    lambda p: sw.LinReg(int(p["period"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "vidya",
    "Variable index dynamic average (VIDYA)",
    "An EMA that speeds up when momentum (CMO) is strong and slows down when it fades.",
    (_p("period", "Length (candles)", 14, 1, 500), _p("cmo", "Momentum length", 9, 1, 200)),
    (("value", "VIDYA"),),
    lambda s, p, x: (vw.vidya(x, _i(p, "period"), _i(p, "cmo")),),
    lambda p: sw.VIDYA(int(p["period"]), int(p["cmo"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "trima",
    "Triangular moving average (TRIMA)",
    "An average of an average: weights the middle of the window most, very smooth.",
    (_p("period", "Length (candles)", 20, 1, 500),),
    (("value", "TRIMA"),),
    lambda s, p, x: (vw.trima(x, _i(p, "period")),),
    lambda p: sw.TRIMA(int(p["period"])),
    group=MA,
    overlay=True,
    source=True,
)
_w(
    "envelope",
    "Moving-average envelope",
    "An SMA with bands a fixed percentage above and below.",
    (
        _p("period", "Length (candles)", 20, 1, 500),
        _p("pct", "Band width (%)", 2.5, 0.1, 50.0, False),
    ),
    (("middle", "Middle"), ("upper", "Upper"), ("lower", "Lower")),
    lambda s, p, x: vw.envelope(x, _i(p, "period"), _f(p, "pct")),
    lambda p: sw.Envelope(int(p["period"]), float(p["pct"])),
    group=VOLA,
    overlay=True,
    source=True,
)
_w(
    "alligator",
    "Williams Alligator",
    "Three smoothed averages (jaw, teeth, lips) drawn ahead in time. Lines apart and in order = a trend; tangled = the alligator sleeps.",
    (
        _p("jaw", "Jaw length", 13, 1, 200),
        _p("teeth", "Teeth length", 8, 1, 200),
        _p("lips", "Lips length", 5, 1, 200),
    ),
    (("jaw", "Jaw"), ("teeth", "Teeth"), ("lips", "Lips")),
    lambda s, p, x: vw.alligator(s.high, s.low, _i(p, "jaw"), _i(p, "teeth"), _i(p, "lips")),
    lambda p: sw.Alligator(int(p["jaw"]), int(p["teeth"]), int(p["lips"])),
    group=TREND,
    overlay=True,
    inputs="hl",
)
_w(
    "heikin_ashi",
    "Heikin-Ashi candles",
    "Averaged candles that filter noise: long runs of one colour show a clean trend.",
    (),
    (("close", "HA close"), ("open", "HA open"), ("high", "HA high"), ("low", "HA low")),
    lambda s, p, x: vw.heikin_ashi(s.open, s.high, s.low, s.close),
    lambda p: sw.HeikinAshi(),
    group=TREND,
    overlay=True,
    inputs="ohlc",
)

# ---- momentum
_w(
    "momentum",
    "Momentum",
    "Price now minus price N candles ago. Above 0: higher than then.",
    (_p("period", "Length (candles)", 10, 1, 500),),
    (("value", "Momentum"),),
    lambda s, p, x: (vw.momentum(x, _i(p, "period")),),
    lambda p: sw.Momentum(int(p["period"])),
    group=MOM,
    source=True,
)
_w(
    "cmo",
    "Chande momentum oscillator (CMO)",
    "Gains minus losses over N candles, −100 to +100. Above +50 overbought, below −50 oversold.",
    (L,),
    (("value", "CMO"),),
    lambda s, p, x: (vw.cmo(x, _i(p, "period")),),
    lambda p: sw.CMO(int(p["period"])),
    group=MOM,
    source=True,
)
_w(
    "trix",
    "TRIX",
    "The % change of a triple-smoothed EMA: momentum with the noise filtered out.",
    (_p("period", "Length (candles)", 15, 1, 200), _p("signal", "Signal length", 9, 1, 100)),
    (("value", "TRIX"), ("signal", "Signal")),
    lambda s, p, x: vw.trix(x, _i(p, "period"), _i(p, "signal")),
    lambda p: sw.TRIX(int(p["period"]), int(p["signal"])),
    group=MOM,
    source=True,
)
_w(
    "ppo",
    "Percentage price oscillator (PPO)",
    "MACD expressed in percent, so stocks of any price can be compared.",
    (
        _p("fast", "Fast length", 12, 1, 200),
        _p("slow", "Slow length", 26, 2, 400),
        _p("signal", "Signal length", 9, 1, 200),
    ),
    (("ppo", "PPO"), ("signal", "Signal"), ("histogram", "Histogram")),
    lambda s, p, x: vw.ppo(x, _i(p, "fast"), _i(p, "slow"), _i(p, "signal")),
    lambda p: sw.PPO(int(p["fast"]), int(p["slow"]), int(p["signal"])),
    group=MOM,
    source=True,
)
_w(
    "dpo",
    "Detrended price oscillator (DPO)",
    "Removes the trend to show short price cycles: the price half a window ago minus today's average.",
    (_p("period", "Length (candles)", 20, 1, 500),),
    (("value", "DPO"),),
    lambda s, p, x: (vw.dpo(x, _i(p, "period")),),
    lambda p: sw.DPO(int(p["period"])),
    group=MOM,
    source=True,
)
_w(
    "kst",
    "Know Sure Thing (KST)",
    "Martin Pring's blend of four rates of change. Crossing its signal line marks momentum turns.",
    (_p("signal", "Signal length", 9, 1, 100),),
    (("value", "KST"), ("signal", "Signal")),
    lambda s, p, x: vw.kst(x, _i(p, "signal")),
    lambda p: sw.KST(int(p["signal"])),
    group=MOM,
    source=True,
    warm=lambda p: 3 * (45 + int(p["signal"])) + 1,
)
_w(
    "coppock",
    "Coppock curve",
    "A slow momentum curve; a turn up from below zero is a classic long-term buy signal.",
    (
        _p("long", "Long ROC", 14, 1, 200),
        _p("short", "Short ROC", 11, 1, 200),
        _p("period", "Smoothing (WMA)", 10, 1, 200),
    ),
    (("value", "Coppock"),),
    lambda s, p, x: (vw.coppock(x, _i(p, "long"), _i(p, "short"), _i(p, "period")),),
    lambda p: sw.Coppock(int(p["long"]), int(p["short"]), int(p["period"])),
    group=MOM,
    source=True,
)
_w(
    "ultimate",
    "Ultimate oscillator",
    "Larry Williams' buying pressure over three lengths, 0 to 100. Below 30 oversold, above 70 overbought.",
    (
        _p("short", "Short length", 7, 1, 100),
        _p("medium", "Medium length", 14, 1, 200),
        _p("long", "Long length", 28, 1, 400),
    ),
    (("value", "UO"),),
    lambda s, p, x: (
        vw.ultimate(s.high, s.low, s.close, _i(p, "short"), _i(p, "medium"), _i(p, "long")),
    ),
    lambda p: sw.Ultimate(int(p["short"]), int(p["medium"]), int(p["long"])),
    group=MOM,
    inputs="hlc",
)
_w(
    "awesome",
    "Awesome & Accelerator oscillators",
    "Bill Williams' momentum (fast minus slow average of the mid-price) and its acceleration.",
    (_p("fast", "Fast length", 5, 1, 100), _p("slow", "Slow length", 34, 2, 400)),
    (("ao", "Awesome"), ("ac", "Accelerator")),
    lambda s, p, x: vw.awesome(s.high, s.low, _i(p, "fast"), _i(p, "slow")),
    lambda p: sw.Awesome(int(p["fast"]), int(p["slow"])),
    group=MOM,
    inputs="hl",
)
_w(
    "tsi",
    "True strength index (TSI)",
    "Double-smoothed momentum, −100 to +100, with a signal line.",
    (
        _p("long", "Long length", 25, 1, 200),
        _p("short", "Short length", 13, 1, 200),
        _p("signal", "Signal length", 13, 1, 100),
    ),
    (("value", "TSI"), ("signal", "Signal")),
    lambda s, p, x: vw.tsi(x, _i(p, "long"), _i(p, "short"), _i(p, "signal")),
    lambda p: sw.TSI(int(p["long"]), int(p["short"]), int(p["signal"])),
    group=MOM,
    source=True,
)
_w(
    "rvi",
    "Relative vigor index (RVI)",
    "Do candles close above their opens? Positive and rising = vigorous buying.",
    (_p("period", "Length (candles)", 10, 1, 200),),
    (("value", "RVI"), ("signal", "Signal")),
    lambda s, p, x: vw.rvi(s.open, s.high, s.low, s.close, _i(p, "period")),
    lambda p: sw.RVI(int(p["period"])),
    group=MOM,
    inputs="ohlc",
    warm=lambda p: 3 * int(p["period"]) + 10,
)
_w(
    "fisher",
    "Fisher transform",
    "Ehlers' sharp turning-point indicator: extremes above +2 or below −2 often mark reversals.",
    (_p("period", "Length (candles)", 9, 1, 200),),
    (("value", "Fisher"), ("trigger", "Trigger")),
    lambda s, p, x: vw.fisher(s.high, s.low, _i(p, "period")),
    lambda p: sw.Fisher(int(p["period"])),
    group=MOM,
    inputs="hl",
)
_w(
    "stc",
    "Schaff trend cycle (STC)",
    "A fast MACD-based cycle, 0 to 100: crossing up through 25 is bullish, down through 75 bearish.",
    (
        _p("fast", "Fast length", 23, 1, 200),
        _p("slow", "Slow length", 50, 2, 400),
        _p("cycle", "Cycle length", 10, 2, 100),
        _p("factor", "Smoothing (0…1)", 0.5, 0.05, 1.0, False),
    ),
    (("value", "STC"),),
    lambda s, p, x: (vw.stc(x, _i(p, "fast"), _i(p, "slow"), _i(p, "cycle"), _f(p, "factor")),),
    lambda p: sw.STC(int(p["fast"]), int(p["slow"]), int(p["cycle"]), float(p["factor"])),
    group=MOM,
    source=True,
)
_w(
    "connors_rsi",
    "Connors RSI",
    "Larry Connors' short-term gauge: a 3-day RSI, the up/down streak and today's move ranked against 100 days. Below 10 deeply oversold.",
    (
        _p("rsi", "RSI length", 3, 1, 50),
        _p("streak", "Streak RSI length", 2, 1, 50),
        _p("rank", "Rank length", 100, 2, 500),
    ),
    (("value", "CRSI"),),
    lambda s, p, x: (vw.connors_rsi(x, _i(p, "rsi"), _i(p, "streak"), _i(p, "rank")),),
    lambda p: sw.ConnorsRSI(int(p["rsi"]), int(p["streak"]), int(p["rank"])),
    group=MOM,
    source=True,
)
_w(
    "elder_ray",
    "Elder ray (bull and bear power)",
    "How far the high is above, and the low below, a 13-candle EMA: the strength of buyers and sellers.",
    (_p("period", "EMA length", 13, 1, 200),),
    (("bull", "Bull power"), ("bear", "Bear power")),
    lambda s, p, x: vw.elder_ray(s.high, s.low, s.close, _i(p, "period")),
    lambda p: sw.ElderRay(int(p["period"])),
    group=MOM,
    inputs="hlc",
)
_w(
    "bop",
    "Balance of power",
    "Where candles close within their range, averaged: −1 sellers rule, +1 buyers rule.",
    (L,),
    (("value", "BOP"),),
    lambda s, p, x: (vw.bop(s.open, s.high, s.low, s.close, _i(p, "period")),),
    lambda p: sw.BOP(int(p["period"])),
    group=MOM,
    inputs="ohlc",
)
_w(
    "qstick",
    "Qstick",
    "The average of close minus open: above 0 the candles have mostly closed up.",
    (_p("period", "Length (candles)", 8, 1, 200),),
    (("value", "Qstick"),),
    lambda s, p, x: (vw.qstick(s.open, s.close, _i(p, "period")),),
    lambda p: sw.Qstick(int(p["period"])),
    group=MOM,
    inputs="ohlc",
)
_w(
    "smi",
    "Stochastic momentum index (SMI)",
    "A smoother stochastic centred on zero, −100 to +100. Below −40 oversold, above +40 overbought.",
    (_p("k", "Range length", 10, 1, 200), _p("d", "Smoothing", 3, 1, 50)),
    (("value", "SMI"), ("signal", "Signal")),
    lambda s, p, x: vw.smi(s.high, s.low, s.close, _i(p, "k"), _i(p, "d")),
    lambda p: sw.SMI(int(p["k"]), int(p["d"])),
    group=MOM,
    inputs="hlc",
)
_w(
    "wavetrend",
    "WaveTrend",
    "A popular TradingView oscillator: crosses of its two lines below −60 (or above +60) mark turns.",
    (_p("channel", "Channel length", 10, 1, 200), _p("average", "Average length", 21, 1, 200)),
    (("wt1", "WaveTrend 1"), ("wt2", "WaveTrend 2")),
    lambda s, p, x: vw.wavetrend(s.high, s.low, s.close, _i(p, "channel"), _i(p, "average")),
    lambda p: sw.WaveTrend(int(p["channel"]), int(p["average"])),
    group=MOM,
    inputs="hlc",
)
_w(
    "elder_impulse",
    "Elder impulse system",
    "+1 when the EMA and MACD histogram both rise (green), −1 when both fall (red), 0 otherwise.",
    (
        _p("period", "EMA length", 13, 1, 200),
        _p("fast", "MACD fast", 12, 1, 200),
        _p("slow", "MACD slow", 26, 2, 400),
        _p("signal", "MACD signal", 9, 1, 200),
    ),
    (("value", "Impulse"),),
    lambda s, p, x: (
        vw.elder_impulse(x, _i(p, "period"), _i(p, "fast"), _i(p, "slow"), _i(p, "signal")),
    ),
    lambda p: sw.ElderImpulse(int(p["period"]), int(p["fast"]), int(p["slow"]), int(p["signal"])),
    group=TREND,
    source=True,
)

# ---- trend
_w(
    "vortex",
    "Vortex indicator",
    "Upward versus downward movement: VI+ crossing above VI− starts an uptrend.",
    (L,),
    (("plus", "VI+"), ("minus", "VI−")),
    lambda s, p, x: vw.vortex(s.high, s.low, s.close, _i(p, "period")),
    lambda p: sw.Vortex(int(p["period"])),
    group=TREND,
    inputs="hlc",
)
_w(
    "adxr",
    "ADX rating (ADXR)",
    "The average of today's ADX and the ADX a window ago: a steadier trend-strength reading.",
    (L,),
    (("value", "ADXR"),),
    lambda s, p, x: (vw.adxr(s.high, s.low, s.close, _i(p, "period")),),
    lambda p: sw.ADXR(int(p["period"])),
    group=TREND,
    inputs="hlc",
    warm=lambda p: 5 * int(p["period"]) + 1,
)
_w(
    "chop",
    "Choppiness index",
    "Is the market trending or chopping? Above 61.8 choppy, below 38.2 trending.",
    (_p("period", "Length (candles)", 14, 2, 500),),
    (("value", "CHOP"),),
    lambda s, p, x: (vw.chop(s.high, s.low, s.close, _i(p, "period")),),
    lambda p: sw.Chop(int(p["period"])),
    group=TREND,
    inputs="hlc",
)
_w(
    "fractals",
    "Williams fractals",
    "The latest confirmed swing high and swing low (a candle with two lower highs, or higher lows, on each side).",
    (),
    (("up", "Last fractal high"), ("down", "Last fractal low")),
    lambda s, p, x: vw.fractals(s.high, s.low),
    lambda p: sw.Fractals(),
    group=LEVELS,
    overlay=True,
    inputs="hl",
    warm=lambda p: 60,
)

# ---- volatility and bands
_w(
    "stdev",
    "Standard deviation",
    "How spread out prices have been over the last N candles.",
    (_p("period", "Length (candles)", 20, 1, 500),),
    (("value", "Std dev"),),
    lambda s, p, x: (vx.stdev(x, _i(p, "period")),),
    lambda p: st.StdDev(int(p["period"])),
    group=VOLA,
    source=True,
)
_w(
    "natr",
    "Normalised ATR (ATR %)",
    "ATR as a percentage of the price, so volatility can be compared across stocks.",
    (L,),
    (("value", "ATR %"),),
    lambda s, p, x: (vw.natr(s.high, s.low, s.close, _i(p, "period")),),
    lambda p: sw.NATR(int(p["period"])),
    group=VOLA,
    inputs="hlc",
)
_w(
    "hv",
    "Historical volatility",
    "The annualised standard deviation of daily returns, in %. 20% is calm for a large stock, 40%+ is wild.",
    (
        _p("period", "Length (candles)", 20, 2, 500),
        _p("per_year", "Candles per year", 252, 1, 100000),
    ),
    (("value", "HV %"),),
    lambda s, p, x: (vw.hv(x, _i(p, "period"), _i(p, "per_year")),),
    lambda p: sw.HV(int(p["period"]), int(p["per_year"])),
    group=VOLA,
    source=True,
    warm=lambda p: 3 * int(p["period"]) + 1,
)
_w(
    "ulcer",
    "Ulcer index",
    "How deep and long the recent drawdowns have been: a measure of pain, not just movement.",
    (L,),
    (("value", "Ulcer"),),
    lambda s, p, x: (vw.ulcer(x, _i(p, "period")),),
    lambda p: sw.Ulcer(int(p["period"])),
    group=VOLA,
    source=True,
)
_w(
    "mass_index",
    "Mass index",
    "Range expansion: a rise above 27 then a fall below 26.5 (a 'reversal bulge') warns of a trend change.",
    (_p("ema", "EMA length", 9, 1, 100), _p("total", "Sum length", 25, 1, 200)),
    (("value", "Mass index"),),
    lambda s, p, x: (vw.mass_index(s.high, s.low, _i(p, "ema"), _i(p, "total")),),
    lambda p: sw.MassIndex(int(p["ema"]), int(p["total"])),
    group=VOLA,
    inputs="hl",
)
_w(
    "chandelier",
    "Chandelier exit",
    "Trailing stops hung a multiple of ATR from the highest high (for longs) or lowest low (for shorts).",
    (
        _p("period", "Length (candles)", 22, 1, 500),
        _p("mult", "ATR multiple", 3.0, 0.1, 20.0, False),
    ),
    (("long", "Long stop"), ("short", "Short stop")),
    lambda s, p, x: vw.chandelier(s.high, s.low, s.close, _i(p, "period"), _f(p, "mult")),
    lambda p: sw.Chandelier(int(p["period"]), float(p["mult"])),
    group=VOLA,
    overlay=True,
    inputs="hlc",
)
_w(
    "squeeze",
    "Squeeze (TTM-style)",
    "Bollinger Bands inside the Keltner Channel = a squeeze (1): volatility is coiled. The momentum line shows which way it is leaning.",
    (
        _p("period", "Length (candles)", 20, 2, 500),
        _p("bb", "Bollinger width (std devs)", 2.0, 0.1, 10.0, False),
        _p("kc", "Keltner width (ATRs)", 1.5, 0.1, 10.0, False),
    ),
    (("momentum", "Squeeze momentum"), ("on", "Squeeze on (1/0)")),
    lambda s, p, x: vw.squeeze(s.high, s.low, s.close, _i(p, "period"), _f(p, "bb"), _f(p, "kc")),
    lambda p: sw.Squeeze(int(p["period"]), float(p["bb"]), float(p["kc"])),
    group=VOLA,
    inputs="hlc",
)
_w(
    "zscore",
    "Z-score",
    "How many standard deviations the price is from its average. Beyond ±2 is stretched.",
    (_p("period", "Length (candles)", 20, 2, 500),),
    (("value", "Z-score"),),
    lambda s, p, x: (vw.zscore(x, _i(p, "period")),),
    lambda p: sw.ZScore(int(p["period"])),
    group=VOLA,
    source=True,
)
_w(
    "bollinger_pct",
    "Bollinger %B and bandwidth",
    "%B: where the price sits between the bands (0 lower, 1 upper). Bandwidth: how wide the bands are, in %.",
    (
        _p("period", "Length (candles)", 20, 2, 500),
        _p("mult", "Band width (std devs)", 2.0, 0.1, 10.0, False),
    ),
    (("pct_b", "%B"), ("bandwidth", "Bandwidth %")),
    lambda s, p, x: vw.bollinger_pct(x, _i(p, "period"), _f(p, "mult")),
    lambda p: sw.BollingerPct(int(p["period"]), float(p["mult"])),
    group=VOLA,
    source=True,
)
_w(
    "disparity",
    "Disparity index",
    "How far the price is from its moving average, in %.",
    (L,),
    (("value", "Disparity %"),),
    lambda s, p, x: (vw.disparity(x, _i(p, "period")),),
    lambda p: sw.Disparity(int(p["period"])),
    group=VOLA,
    source=True,
)

# ---- volume
_w(
    "rvol",
    "Relative volume (RVOL)",
    "Today's volume divided by the average of the previous N candles. 2 = twice the usual trading.",
    (_p("period", "Length (candles)", 20, 1, 500),),
    (("value", "RVOL"),),
    lambda s, p, x: (vw.rvol(s.volume, _i(p, "period")),),
    lambda p: sw.RVOL(int(p["period"])),
    group=VOL,
    inputs="cv",
)
_w(
    "pvo",
    "Percentage volume oscillator (PVO)",
    "Whether volume is expanding (above 0) or drying up, compared with its own longer average.",
    (
        _p("fast", "Fast length", 12, 1, 200),
        _p("slow", "Slow length", 26, 2, 400),
        _p("signal", "Signal length", 9, 1, 200),
    ),
    (("pvo", "PVO"), ("signal", "Signal"), ("histogram", "Histogram")),
    lambda s, p, x: vw.pvo(s.volume, _i(p, "fast"), _i(p, "slow"), _i(p, "signal")),
    lambda p: sw.PVO(int(p["fast"]), int(p["slow"]), int(p["signal"])),
    group=VOL,
    inputs="cv",
)
_w(
    "ad_line",
    "Accumulation/distribution line",
    "A running total of volume weighted by where each candle closes in its range. Rising = accumulation.",
    (),
    (("value", "A/D"),),
    lambda s, p, x: (vw.ad_line(s.high, s.low, s.close, s.volume),),
    lambda p: sw.ADLine(),
    group=VOL,
    inputs="hlcv",
)
_w(
    "chaikin_osc",
    "Chaikin oscillator",
    "The momentum of the accumulation/distribution line (fast EMA minus slow EMA).",
    (_p("fast", "Fast length", 3, 1, 100), _p("slow", "Slow length", 10, 2, 200)),
    (("value", "Chaikin osc"),),
    lambda s, p, x: (
        vw.chaikin_osc(s.high, s.low, s.close, s.volume, _i(p, "fast"), _i(p, "slow")),
    ),
    lambda p: sw.ChaikinOsc(int(p["fast"]), int(p["slow"])),
    group=VOL,
    inputs="hlcv",
)
_w(
    "force_index",
    "Force index",
    "Alexander Elder's price change × volume, smoothed: the force behind a move.",
    (_p("period", "Length (candles)", 13, 1, 200),),
    (("value", "Force"),),
    lambda s, p, x: (vw.force_index(s.close, s.volume, _i(p, "period")),),
    lambda p: sw.ForceIndex(int(p["period"])),
    group=VOL,
    inputs="cv",
)
_w(
    "eom",
    "Ease of movement (EOM)",
    "How easily the price moves: high when it rises on light volume.",
    (L,),
    (("value", "EOM"),),
    lambda s, p, x: (vw.eom(s.high, s.low, s.volume, _i(p, "period")),),
    lambda p: sw.EOM(int(p["period"])),
    group=VOL,
    inputs="hlcv",
)
_w(
    "klinger",
    "Klinger volume oscillator",
    "Volume flowing with the trend (fast minus slow EMA of signed volume) with a signal line.",
    (
        _p("fast", "Fast length", 34, 1, 200),
        _p("slow", "Slow length", 55, 2, 400),
        _p("signal", "Signal length", 13, 1, 100),
    ),
    (("value", "KVO"), ("signal", "Signal")),
    lambda s, p, x: vw.klinger(
        s.high, s.low, s.close, s.volume, _i(p, "fast"), _i(p, "slow"), _i(p, "signal")
    ),
    lambda p: sw.Klinger(int(p["fast"]), int(p["slow"]), int(p["signal"])),
    group=VOL,
    inputs="hlcv",
)
_w(
    "nvi",
    "Negative volume index (NVI)",
    "Follows the price only on quieter days, where informed buyers are said to act. Above its long EMA = bullish.",
    (_p("signal", "Signal EMA length", 255, 1, 500),),
    (("value", "NVI"), ("signal", "Signal")),
    lambda s, p, x: vw.nvi(s.close, s.volume, _i(p, "signal")),
    lambda p: sw.VolumeIndex(int(p["signal"]), negative=True),
    group=VOL,
    inputs="cv",
)
_w(
    "pvi",
    "Positive volume index (PVI)",
    "Follows the price only on busier days, where the crowd acts.",
    (_p("signal", "Signal EMA length", 255, 1, 500),),
    (("value", "PVI"), ("signal", "Signal")),
    lambda s, p, x: vw.pvi(s.close, s.volume, _i(p, "signal")),
    lambda p: sw.VolumeIndex(int(p["signal"]), negative=False),
    group=VOL,
    inputs="cv",
)
_w(
    "pvt",
    "Price-volume trend (PVT)",
    "A running total of volume × the % price change: like OBV, but sized by how far the price moved.",
    (),
    (("value", "PVT"),),
    lambda s, p, x: (vw.pvt(s.close, s.volume),),
    lambda p: sw.PVT(),
    group=VOL,
    inputs="cv",
)

# ---- levels
_PIV = (
    ("p", "Pivot"),
    ("r1", "Resistance 1"),
    ("r2", "Resistance 2"),
    ("r3", "Resistance 3"),
    ("s1", "Support 1"),
    ("s2", "Support 2"),
    ("s3", "Support 3"),
)
_w(
    "pivots_fib",
    "Fibonacci pivot points",
    "Pivot levels spaced at 38.2%, 61.8% and 100% of the previous session's range.",
    (),
    _PIV,
    lambda s, p, x: vw.pivots_fib(s.high, s.low, s.close, s.session),
    lambda p: sw.PivotsFib(),
    group=LEVELS,
    overlay=True,
    inputs="hlc_session",
)
_w(
    "pivots_camarilla",
    "Camarilla pivot points",
    "Tight intraday levels around the previous close: fade moves to R3/S3, follow breaks of R4/S4.",
    (),
    (
        ("r1", "R1"),
        ("r2", "R2"),
        ("r3", "R3"),
        ("r4", "R4"),
        ("s1", "S1"),
        ("s2", "S2"),
        ("s3", "S3"),
        ("s4", "S4"),
    ),
    lambda s, p, x: vw.pivots_camarilla(s.high, s.low, s.close, s.session),
    lambda p: sw.PivotsCamarilla(),
    group=LEVELS,
    overlay=True,
    inputs="hlc_session",
)
_w(
    "pivots_woodie",
    "Woodie pivot points",
    "Floor pivots that give the previous close double weight.",
    (),
    _PIV,
    lambda s, p, x: vw.pivots_woodie(s.high, s.low, s.close, s.session),
    lambda p: sw.PivotsWoodie(),
    group=LEVELS,
    overlay=True,
    inputs="hlc_session",
)

GROUPS: dict[str, str] = {
    **{k: MA for k in ("sma", "ema", "wma", "dema", "tema", "hma", "vwma", "kama")},
    **{
        k: MOM
        for k in ("rsi", "macd", "stochastic", "cci", "roc", "mfi", "williams_r", "stoch_rsi")
    },
    **{k: TREND for k in ("adx", "supertrend", "ichimoku", "psar", "aroon")},
    **{k: VOLA for k in ("bollinger", "atr", "keltner", "donchian")},
    **{k: VOL for k in ("obv", "vwap", "cmf")},
    **{
        k: LEVELS
        for k in ("highest", "lowest", "high_52w", "low_52w", "prev_day", "opening_range", "pivots")
    },
}


class _OpeningRangeFactory:
    """The streaming opening range needs the bar length, known only at the first bar."""

    def __init__(self, minutes: int) -> None:
        self.minutes = minutes
        self.inner: st.OpeningRange | None = None

    def update(
        self, h: float, lo: float, ts: int, session: int, session_open: int, bar_minutes: int
    ) -> tuple[float, float]:
        if self.inner is None:
            self.inner = st.OpeningRange(bar_minutes, self.minutes)
        return self.inner.update(h, lo, ts, session, session_open)


# ---------------------------------------------------------------- helpers


class UnknownIndicator(KeyError):
    pass


def get(key: str) -> Indicator:
    try:
        return INDICATORS[key]
    except KeyError:
        raise UnknownIndicator(key) from None


def resolve_params(ind: Indicator, params: Mapping[str, Any] | None) -> dict[str, float]:
    """Defaults filled in, values checked against each parameter's range."""
    params = dict(params or {})
    out: dict[str, float] = {}
    for p in ind.params:
        v = params.pop(p.name, p.default)
        if isinstance(v, bool) or not isinstance(v, int | float) or not np.isfinite(v):
            raise ValueError(f"{ind.label}: '{p.label}' must be a number")
        if p.integer and float(v) != int(v):
            raise ValueError(f"{ind.label}: '{p.label}' must be a whole number")
        if not p.min <= v <= p.max:
            raise ValueError(f"{ind.label}: '{p.label}' must be between {p.min:g} and {p.max:g}")
        out[p.name] = float(v)
    if params:
        raise ValueError(f"{ind.label} has no setting called '{next(iter(params))}'")
    return out


def compute(
    key: str,
    series: BarSeries,
    params: Mapping[str, Any] | None = None,
    source: str | F64 | None = None,
) -> dict[str, F64]:
    """All outputs of one indicator over the whole series, keyed by output name."""
    ind = get(key)
    p = resolve_params(ind, params)
    if source is None:
        x = series.field(ind.default_source)
    elif isinstance(source, str):
        x = series.field(source)
    else:
        x = np.asarray(source, dtype=np.float64)
    arrays = ind.compute(series, p, x)
    return {k: arr for (k, _), arr in zip(ind.outputs, arrays, strict=True)}


def catalog() -> list[dict[str, Any]]:
    return [ind.public() for ind in INDICATORS.values()]


@dataclass(frozen=True)
class BarInput:
    """One closed bar, as the streaming indicators need it (adjusted prices)."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    session: int
    session_open: int
    bar_minutes: int

    def field(self, name: str) -> float:
        if name == "hl2":
            return (self.high + self.low) / 2.0
        if name in ("typical", "hlc3"):
            return (self.high + self.low + self.close) / 3.0
        value: float = getattr(self, name)
        return value


class StreamIndicator:
    """A catalog indicator updated one bar at a time; ``update`` returns every output."""

    def __init__(
        self, key: str, params: Mapping[str, Any] | None = None, source: str | None = None
    ):
        self.ind = get(key)
        self.params = resolve_params(self.ind, params)
        self.source = source or self.ind.default_source
        self.impl = self.ind.streamer(self.params)

    def update(self, b: BarInput) -> dict[str, float]:
        kind = self.ind.stream_inputs
        impl = self.impl
        if kind == "source":
            raw = impl.update(b.field(self.source))
        elif kind == "hlc":
            raw = impl.update(b.high, b.low, b.close)
        elif kind == "hl":
            raw = impl.update(b.high, b.low)
        elif kind == "cv":
            raw = impl.update(b.close, b.volume)
        elif kind == "source_v":
            raw = impl.update(b.field(self.source), b.volume)
        elif kind == "hlcv":
            raw = impl.update(b.high, b.low, b.close, b.volume)
        elif kind == "hlcv_session":
            raw = impl.update(b.high, b.low, b.close, b.volume, b.session)
        elif kind == "hlc_session":
            raw = impl.update(b.high, b.low, b.close, b.session)
        elif kind == "h_ts":
            raw = impl.update(b.high, b.ts)
        elif kind == "l_ts":
            raw = impl.update(b.low, b.ts)
        elif kind == "ohlc":
            raw = impl.update(b.open, b.high, b.low, b.close)
        elif kind == "opening_range":
            raw = impl.update(b.high, b.low, b.ts, b.session, b.session_open, b.bar_minutes)
        else:  # pragma: no cover - a catalog bug
            raise RuntimeError(f"unknown stream input kind {kind}")
        values = raw if isinstance(raw, tuple) else (raw,)
        return {k: float(v) for (k, _), v in zip(self.ind.outputs, values, strict=True)}


def bar_inputs(series: BarSeries) -> list[BarInput]:
    return [
        BarInput(
            int(series.ts[i]),
            float(series.open[i]),
            float(series.high[i]),
            float(series.low[i]),
            float(series.close[i]),
            float(series.volume[i]),
            int(series.session[i]),
            int(series.session_open[i]),
            series.timeframe.minutes,
        )
        for i in range(len(series))
    ]
