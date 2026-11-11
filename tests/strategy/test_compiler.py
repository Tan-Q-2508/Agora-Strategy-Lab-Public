"""Templates compile, fire on the fixtures, and visual == generated code, signal for signal."""

from __future__ import annotations

from functools import lru_cache

import pytest

from backend.core.types import Market, Timeframe
from backend.data.adjust import adjusted
from backend.fakes.data_source import FakeSource
from backend.indicators.series import BarSeries, from_bars
from backend.strategy.codegen import to_code
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import CodeDefinition
from backend.strategy.signals import trace
from backend.strategy.templates import TEMPLATES, template_definition


class _Forever:
    def now_ms(self) -> int:
        return 2**62


SRC = FakeSource(_Forever())  # type: ignore[arg-type]


@lru_cache(maxsize=32)
def series(symbol: str, tf: str) -> BarSeries:
    timeframe = Timeframe(tf)
    return from_bars(
        [adjusted(b) for b in SRC._all(symbol, timeframe)], timeframe, SRC.market_of(symbol)
    )


def symbols_for(key: str, market: str) -> list[str]:
    if TEMPLATES[key].timeframe == "5m":
        return ["RELIANCE", "INFY"] if market == "IN" else ["AAPL", "SPY"]
    return ["RELIANCE", "TCS", "ITC"] if market == "IN" else ["AAPL", "NVDA", "SPY"]


@pytest.mark.parametrize("key", sorted(TEMPLATES))
@pytest.mark.parametrize("market", ["IN", "US"])
def test_visual_and_code_versions_signal_identically(key: str, market: str) -> None:
    visual = template_definition(key, market)
    code = CodeDefinition(
        market=visual.market,
        universe=visual.universe,
        timeframe=visual.timeframe,
        product=visual.product,
        sizing=visual.sizing,
        limits=visual.limits,
        parameters=visual.parameters,
        code=to_code(visual, TEMPLATES[key].name),
    )
    pv, pc = compile_definition(visual), compile_definition(code)
    total = 0
    for sym in symbols_for(key, market):
        s = series(sym, visual.timeframe)
        a = trace(pv, s, Market(market), sym)
        b = trace(pc, s, Market(market), sym)
        assert a == b, f"{key} {sym}: visual and code differ"
        total += len(a)
    assert total > 0, f"{key} never fired on the fixtures"


def test_parameter_overrides_change_the_rules() -> None:
    d = template_definition("ma_crossover", "IN")
    s = series("RELIANCE", "1d")
    fast = trace(compile_definition(d, {"fast": 5, "slow": 20}), s, Market.IN)
    slow = trace(compile_definition(d), s, Market.IN)
    assert len(fast) > len(slow)


def test_warmup_covers_the_longest_indicator() -> None:
    p = compile_definition(template_definition("rsi_mean_reversion", "IN"))
    assert p.warmup >= 200  # the SMA(200) filter


def test_exit_time_closes_intraday_trades() -> None:
    d = template_definition("opening_range_breakout", "IN")
    sigs = trace(compile_definition(d), series("INFY", "5m"), Market.IN)
    exits = [x for x in sigs if x.action in ("sell", "cover")]
    assert exits and all(
        x.reason in ("Exit time reached", "Sell rule", "Buy-back rule") for x in exits
    )


def test_generated_code_reads_like_python() -> None:
    code = to_code(template_definition("rsi_mean_reversion", "IN"), "RSI mean reversion")
    assert "def on_bar(ctx):" in code
    assert 'ctx.ind.rsi(ctx.close, period=p["rsi_len"])' in code
    assert "ctx.crosses_below(" in code
    compile(code, "<generated>", "exec")
