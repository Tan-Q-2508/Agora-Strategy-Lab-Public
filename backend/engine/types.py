"""The engine's records: positions, pending orders, order events, trades, equity points."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from backend.costs.model import ZERO, Charges
from backend.strategy.runtime import ScaleOut, Side, StopRule

ExitReason = Literal["signal", "stop", "target", "trailing", "time", "square_off", "end_of_test"]


@dataclass
class ScaleLevel:
    """A partial exit still waiting: sell ``qty`` once the price reaches ``price`` (raw)."""

    price: float
    qty: float


@dataclass
class Position:
    side: Side
    qty: float
    entry_price: float  # raw price actually paid (adjusted when the stock splits)
    entry_ts: int
    entry_index: int
    entry_reason: str
    entry_charges: Charges = ZERO
    dividends: float = 0.0
    stop: float | None = None
    target: float | None = None
    trail: StopRule | None = None
    trail_level: float | None = None
    peak: float = 0.0  # best price since entry (high for longs, low for shorts), raw
    atr_raw: float | None = None  # ATR at the signal, for ATR-based trailing stops
    signal_ts: int = 0  # the candle whose close gave the signal (Kairos's trade check)
    # Partial exits (D-125). The trade is still reported as one trade when it ends: its
    # quantity is the starting quantity and its exit price the average of every sale.
    start_qty: float = 0.0
    scale: list[ScaleLevel] = field(default_factory=list)
    scale_breakeven: bool = False
    partials: int = 0  # partial exits taken so far
    sold_qty: float = 0.0  # sold by partial exits (raw shares)
    sold_value: float = 0.0  # qty × fill of those sales
    sold_gross: float = 0.0  # their profit or loss before charges
    sold_charges: Charges = ZERO  # their charges

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1


@dataclass
class PendingOrder:
    kind: Literal["entry", "exit"]
    side: Side  # entry: the position side; exit: the side being closed
    qty: float
    created_ts: int
    created_index: int
    created_day: str
    reason: str
    exit_kind: Literal["signal", "time"] = "signal"
    stop_loss: StopRule | None = None
    take_profit: StopRule | None = None
    trailing_stop: StopRule | None = None
    atr_raw: float | None = None
    scale_out: ScaleOut | None = None


@dataclass(frozen=True)
class OrderEvent:
    ts: int
    symbol: str
    instrument_id: int
    type: str  # market | stop | limit
    side: str  # buy | sell
    qty: float
    status: str  # filled | rejected | cancelled
    reason: str
    price: float | None = None
    charges: float = 0.0
    slippage: float = 0.0


@dataclass
class Trade:
    symbol: str
    instrument_id: int
    side: Side
    qty: float
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float
    gross_pnl: float
    charges: float
    net_pnl: float
    return_pct: float
    bars_held: int
    entry_reason: str
    exit_reason: ExitReason
    dividends: float = 0.0
    partials: int = 0  # partial profits taken before the trade ended (D-125)

    @property
    def closed(self) -> bool:
        return self.exit_reason != "end_of_test"


@dataclass(frozen=True)
class EquityPoint:
    ts: int
    equity: float
    cash: float
    exposure: float  # gross position value ÷ equity


@dataclass
class ChargeTotals:
    total: Decimal = Decimal(0)
    by_type: dict[str, Decimal] = field(default_factory=dict)
    schedule_ids: set[int] = field(default_factory=set)

    def add(self, c: Charges) -> None:
        self.total += c.total
        for k, v in c.items.items():
            self.by_type[k] = self.by_type.get(k, Decimal(0)) + v
        self.schedule_ids.update(c.schedule_ids)
