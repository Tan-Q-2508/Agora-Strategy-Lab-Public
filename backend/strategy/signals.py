"""Where a strategy's rules fire, without simulating fills (for the builder's preview
chart and for tests that compare visual and code strategies).

Positions open and close instantly at the signal candle's close; stops and targets are
not simulated. The real engine (Phase 4) fills at the next open with costs.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.types import Market
from backend.indicators.series import BarSeries
from backend.strategy.compiler import Program
from backend.strategy.runtime import Enter, IndicatorProvider, PositionView, StrategyContext


@dataclass(frozen=True)
class Signal:
    index: int
    ts: int
    action: str  # "buy" | "short" | "sell" | "cover"
    reason: str
    price: float


def trace(program: Program, series: BarSeries, market: Market, symbol: str = "") -> list[Signal]:
    return trace_with(program, series, market, symbol)[0]


def trace_with(
    program: Program, series: BarSeries, market: Market, symbol: str = "", *, start: int = 0
) -> tuple[list[Signal], IndicatorProvider]:
    """``trace``, also handing back the indicators the rules worked out (the look-ahead check
    compares them between runs). With ``start``, the rules run from that candle on, as the
    engine only decides from a backtest's first candle (earlier candles are warm-up)."""
    provider = IndicatorProvider(series)
    ctx = StrategyContext(
        symbol=symbol,
        market=market,
        timeframe=series.timeframe.value,
        params=dict(program.params),
        _provider=provider,
        _default_size=program.default_size,
    )
    out: list[Signal] = []
    pos: tuple[str, float, int, int] | None = None  # side, entry price, entry index, ts
    for i in range(start, len(series)):
        close = float(series.close[i])
        view = None
        if pos is not None:
            side, entry, at, ts = pos
            pct = (close / entry - 1.0) * 100.0 * (1 if side == "long" else -1)
            view = PositionView(side, 1.0, entry, ts, i - at, pct)  # type: ignore[arg-type]
        ctx._advance(i, view, 0.0)
        program.on_bar(ctx)
        for intent in ctx._intents:
            if isinstance(intent, Enter):
                if pos is None:
                    pos = (intent.side, close, i, int(series.ts[i]))
                    action = "buy" if intent.side == "long" else "short"
                    out.append(Signal(i, int(series.ts[i]), action, intent.reason, close))
            elif pos is not None:
                action = "sell" if pos[0] == "long" else "cover"
                out.append(Signal(i, int(series.ts[i]), action, intent.reason, close))
                pos = None
    return out, provider
