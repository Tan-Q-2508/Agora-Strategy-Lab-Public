"""Bigger charts in strategies (D-97): weekly candles built by hand, only finished bigger candles
are visible, visual == code, the look-ahead check passes, and wrong charts are refused."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from backend.analysis import mtf
from backend.core.types import Bar, Market, Timeframe
from backend.data.adjust import adjusted
from backend.fakes.data_source import FakeSource
from backend.indicators.series import BarSeries, from_arrays, from_bars
from backend.strategy import lookahead as la
from backend.strategy.codegen import to_code
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import CodeDefinition, VisualDefinition
from backend.strategy.runtime import IndicatorProvider, StrategyContext
from backend.strategy.signals import trace
from backend.strategy.validator import validate
from backend.strategy.words import operand

IST = ZoneInfo("Asia/Kolkata")


class _Forever:
    def now_ms(self) -> int:
        return 2**62


SRC = FakeSource(_Forever())  # type: ignore[arg-type]


@lru_cache(maxsize=4)
def _bars(symbol: str) -> tuple[Bar, ...]:
    return tuple(adjusted(b) for b in SRC._all(symbol, Timeframe.D1))


def _series(symbol: str) -> BarSeries:
    return from_bars(list(_bars(symbol)), Timeframe.D1, SRC.market_of(symbol))


def _days(*ds: date) -> list[int]:
    return [int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000) for d in ds]


# Mon 5 Jan … Fri 16 Jan 2026 and Mon 19, Tue 20 Jan: two full weeks and a started one.
DAYS = [date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20)]
CLOSE = [10, 11, 12, 11, 13, 14, 13, 12, 15, 16, 17, 18]
HIGH = [c + 1 for c in CLOSE]
LOW = [c - 1 for c in CLOSE]
OPEN = [c - 0.5 for c in CLOSE]


def test_weekly_candles_by_hand() -> None:
    s = from_arrays(CLOSE, high=HIGH, low=LOW, open_=OPEN, volume=[1.0] * 12, ts=_days(*DAYS))
    w, group = mtf.resample(s, "1w", IST)
    assert list(group) == [0] * 5 + [1] * 5 + [2] * 2
    assert list(w.open) == [9.5, 13.5, 16.5]
    assert list(w.high) == [14, 17, 19]
    assert list(w.low) == [9, 11, 16]
    assert list(w.close) == [13, 16, 18]
    assert list(w.volume) == [5, 5, 2]


def test_only_finished_bigger_candles_are_seen() -> None:
    s = from_arrays(CLOSE, high=HIGH, low=LOW, open_=OPEN, ts=_days(*DAYS))
    ctx = StrategyContext("X", Market.IN, "1d", {}, IndicatorProvider(s))
    weekly = ctx.chart("1w")
    seen = []
    for i in range(len(s)):
        ctx._advance(i, None, 0.0)
        seen.append(weekly.close[-1])
    # Week 1 is unknown until week 2 starts; Friday 16 Jan still shows week 1's close.
    assert np.isnan(seen[:5]).all()
    assert seen[5:10] == [13.0] * 5
    assert seen[10:] == [16.0, 16.0]


def test_monthly_and_intraday_buckets() -> None:
    s = _series("RELIANCE")
    m, group = mtf.resample(s, "1mo", IST)
    assert len(m) < len(s) / 15 and group[-1] == len(m) - 1
    hourly = SRC._all("RELIANCE", Timeframe.M5)
    ss = from_bars([adjusted(b) for b in hourly[:300]], Timeframe.M5, Market.IN)
    h, g = mtf.resample(ss, "1h", IST)
    # 09:15 starts each hour of an NSE session: 12 five-minute candles per full hour
    counts = np.bincount(g)
    assert counts.max() == 12 and h.timeframe is Timeframe.H1
    d, gd = mtf.resample(ss, "1d", IST)
    assert len(d) == len(set(ss.session.tolist())) and gd[-1] == len(d) - 1


def mtf_definition(**extra: object) -> VisualDefinition:
    """Buy when RSI(14) crosses up through 40 while the weekly close is above its 20-week
    average; sell when the close drops below the 50-day average."""
    return VisualDefinition.model_validate(
        {
            "market": "IN",
            "universe": {"kind": "symbols", "symbols": ["RELIANCE", "TCS"]},
            "timeframe": "1d",
            "product": "delivery",
            "entry": {
                "long": {
                    "type": "all",
                    "conditions": [
                        {
                            "type": "compare",
                            "left": {"kind": "indicator", "name": "rsi", "params": {"period": 14}},
                            "op": "crosses_above",
                            "right": {"kind": "number", "value": 40},
                        },
                        {
                            "type": "compare",
                            "left": {"kind": "price", "field": "close", "chart": "1w"},
                            "op": "above",
                            "right": {
                                "kind": "indicator",
                                "name": "sma",
                                "params": {"period": 20},
                                "chart": "1w",
                            },
                        },
                    ],
                }
            },
            "exit": {
                "long": {
                    "type": "compare",
                    "left": {"kind": "price", "field": "close"},
                    "op": "below",
                    "right": {"kind": "indicator", "name": "sma", "params": {"period": 50}},
                }
            },
            **extra,
        }
    )


def test_visual_and_code_agree_with_a_bigger_chart() -> None:
    visual = mtf_definition()
    code = CodeDefinition(
        market=visual.market,
        universe=visual.universe,
        timeframe=visual.timeframe,
        product=visual.product,
        code=to_code(visual, "Weekly filter"),
    )
    assert 'ctx.chart("1w").ind.sma("close", period=20)' in code.code
    pv, pc = compile_definition(visual), compile_definition(code)
    assert pv.warmup >= 22 * 5
    fired = 0
    for sym in ("RELIANCE", "TCS"):
        s = _series(sym)
        a, b = trace(pv, s, Market.IN, sym), trace(pc, s, Market.IN, sym)
        assert a == b
        fired += len(a)
    assert fired > 0


def test_the_bigger_chart_filter_removes_signals() -> None:
    with_filter = compile_definition(mtf_definition())
    d = mtf_definition().model_dump(mode="json")
    d["entry"]["long"]["conditions"] = d["entry"]["long"]["conditions"][:1]
    without = compile_definition(VisualDefinition.model_validate(d))
    s = _series("RELIANCE")
    a = [x for x in trace(with_filter, s, Market.IN, "RELIANCE") if x.action == "buy"]
    b = [x for x in trace(without, s, Market.IN, "RELIANCE") if x.action == "buy"]
    assert len(a) < len(b)


def test_lookahead_check_passes() -> None:
    d = mtf_definition()
    data = [la.SymbolBars("RELIANCE", _bars("RELIANCE"), normal_from=300, start=600)]
    r = la.check(d, data, max_steps=12_000)
    assert r["verdict"] == "clean", r["lookahead"]["findings"]


def test_wrong_charts_are_refused_plainly() -> None:
    d = mtf_definition().model_dump(mode="json")
    d["entry"]["long"]["conditions"][1]["left"]["chart"] = "1h"
    report = validate(d)
    assert not report.ok
    assert any("can't read the hourly chart" in i.message for i in report.errors)
    ctx = StrategyContext("X", Market.IN, "1d", {}, IndicatorProvider(_series("RELIANCE")))
    with pytest.raises(ValueError, match="bigger charts"):
        ctx.chart("5m")


def test_plain_words() -> None:
    assert operand({"kind": "price", "field": "close", "chart": "1w"}) == (
        "close on the weekly chart"
    )
