"""SPEC §11 speed targets on fixture data sized like the real thing.

Targets (on the user's laptop): 1 symbol × 10 years daily < 2 s; Nifty 50 × 10 years daily
< 30 s; 1 symbol × 60 days of 5-minute candles < 5 s. The cloud machine is usually slower
than the laptop, so passing here leaves headroom.
"""

from __future__ import annotations

import time

from backend.backtest.run import RunSpec, execute
from backend.core.types import Market, Timeframe
from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.data.store import InstrumentRef
from backend.engine.core import SymbolState
from backend.fakes.data_source import FakeSource
from backend.strategy.compiler import compile_definition
from backend.strategy.templates import template_definition

IN_SYMBOLS = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "LT",
    "BHARTIARTL",
    "MARUTI",
]


class _Forever:
    def now_ms(self) -> int:
        return 2**62


SRC = FakeSource(_Forever())  # type: ignore[arg-type]


def states(symbols: list[str], copies: int, tf: Timeframe, market: Market) -> list[SymbolState]:
    out = []
    n = 0
    for k in range(copies):
        for sym in symbols:
            n += 1
            inst = InstrumentRef(n, market, f"{sym}{k}", sym, sym, "equity")
            out.append(SymbolState(inst, list(SRC._all(sym, tf))))
    return out


def timed(template: str, market: Market, sts: list[SymbolState], tf: Timeframe) -> float:
    d = template_definition(template, market.value)
    d = d.model_copy(update={"timeframe": tf.value})
    program = compile_definition(d)
    first = min(st.raw[0].ts for st in sts)
    last = max(st.raw[-1].ts for st in sts)
    spec = RunSpec(
        definition=d,
        instruments=[st.inst for st in sts],
        timeframe=tf,
        start_ms=first + (400 * 86_400_000 if tf is Timeframe.D1 else 0),
        end_ms=last + 1,
        capital=1_000_000,
        brokerage_rules={},
        slippage_bps=5,
    )
    costs = CostModel(market.value, d.product, {}, ChargeTable([]))
    t0 = time.perf_counter()
    execute(sts, spec, program, costs)
    return time.perf_counter() - t0


def test_one_symbol_ten_years_daily_under_two_seconds() -> None:
    assert (
        timed(
            "rsi_mean_reversion",
            Market.IN,
            states(["RELIANCE"], 1, Timeframe.D1, Market.IN),
            Timeframe.D1,
        )
        < 2.0
    )


def test_nifty_fifty_ten_years_daily_under_thirty_seconds() -> None:
    sts = states(IN_SYMBOLS, 5, Timeframe.D1, Market.IN)  # 50 symbols × 10 years
    assert len(sts) == 50
    assert timed("macd_momentum", Market.IN, sts, Timeframe.D1) < 30.0


def test_one_symbol_sixty_days_five_minute_under_five_seconds() -> None:
    sts = states(["RELIANCE"], 1, Timeframe.M5, Market.IN)
    assert timed("opening_range_breakout", Market.IN, sts, Timeframe.M5) < 5.0
