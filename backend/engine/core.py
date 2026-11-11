"""The event-driven engine shared by backtests and paper trading (D-04).

The engine only knows "a time step happened and these symbols have a newly closed candle
at index i". A backtest feeds it historical steps on simulated time; paper trading feeds it
live candles as they close; replay feeds fixture candles on a fast clock. Everything else
(fills, costs, stops, limits, square-off, splits, dividends) is identical in all three.

Order of events within one time step (COST_MODEL.md §4):

1. **Open.** Splits adjust held quantities; dividends are credited on the ex-date. Pending
   orders from the previous candle fill at this candle's open ± slippage (exits first, so
   their cash is available). India intraday: entries can't carry into a new day, and at the
   square-off time open trades close at the open. A circuit-locked candle fills nothing.
2. **Intrabar.** Stops, trailing stops, partial exits and targets fill when the candle's
   range crosses them; if a stop and a target are both inside one candle, the stop is
   assumed first. Partial exits (D-125) sell part of the position at each level, nearest
   first, and may move the stop to the entry price; the position is reported as one trade
   when the rest closes.
3. **Close.** Positions are marked to the close; trailing stops move using closed candles
   only; the daily-loss limit is checked; one equity point is recorded.
4. **Decide.** The strategy's ``on_bar`` runs on the closed candle; what it asks for
   becomes pending orders for the next candle (subject to limits and sizing).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from backend.core.types import MARKET_TZ, Bar, Market, Timeframe
from backend.costs.model import Charges, CostModel, slipped
from backend.data.adjust import adjusted
from backend.data.store import InstrumentRef
from backend.engine.types import (
    ChargeTotals,
    EquityPoint,
    ExitReason,
    OrderEvent,
    PendingOrder,
    Position,
    ScaleLevel,
    Trade,
)
from backend.indicators.series import BarSeries, from_bars
from backend.strategy.compiler import Program

if TYPE_CHECKING:
    from backend.kairos.quality import TradeCheck
from backend.core.clock import ms_to_dt
from backend.strategy.runtime import (
    Enter,
    Exit,
    IndicatorProvider,
    PositionView,
    ScaleOut,
    SizeSpec,
    StopRule,
    StrategyContext,
)

EventListener = Callable[[str, dict[str, object]], None]


@dataclass
class EngineConfig:
    market: Market
    product: str  # intraday | delivery | cash
    timeframe: Timeframe
    capital: float
    slippage_bps: float
    volume_cap_pct: float = 5.0
    square_off: str = "15:20"
    max_open_positions: int = 5
    max_daily_loss_pct: float | None = None
    max_position_pct: float | None = None  # the most of the money one trade may take (D-131)
    max_per_group: int | None = None  # the most open trades in one sector (D-168)
    start_ms: int = 0  # the strategy may only trade on candles from here on

    @property
    def intraday_product(self) -> bool:
        return self.market is Market.IN and self.product == "intraday"

    @property
    def shorts_allowed(self) -> bool:
        return not (self.market is Market.IN and self.product == "delivery")


@dataclass
class SymbolState:
    """One symbol's data and trading state during a run."""

    inst: InstrumentRef
    raw: list[Bar]  # raw prices + split factors (what fills and P&L use)
    dividends: dict[str, float] = field(default_factory=dict)  # local ex-date → cash/share
    series: BarSeries | None = None
    ctx: StrategyContext | None = None
    position: Position | None = None
    pending: list[PendingOrder] = field(default_factory=list)
    last_index: int = -1
    last_sell_day: str | None = None
    member: Callable[[int], bool] | None = None  # in the universe on this date? (survivorship)
    group: str = ""  # its sector (or industry) for ``max_per_group``; "" counts alone

    def build_series(self, timeframe: Timeframe) -> BarSeries:
        self.series = from_bars([adjusted(b) for b in self.raw], timeframe, self.inst.market)
        return self.series


class Engine:
    def __init__(
        self,
        config: EngineConfig,
        program: Program,
        costs: CostModel,
        symbols: Iterable[SymbolState],
        *,
        listener: EventListener | None = None,
    ) -> None:
        self.cfg = config
        self.program = program
        self.costs = costs
        self.symbols = sorted(symbols, key=lambda s: s.inst.symbol)
        self.by_id = {s.inst.id: s for s in self.symbols}
        self.tz = ZoneInfo(MARKET_TZ[config.market])
        self.cash = float(config.capital)
        self.trades: list[Trade] = []
        self.orders: list[OrderEvent] = []
        self.equity: list[EquityPoint] = []
        self.charges = ChargeTotals()
        self.logs: list[str] = []
        self.listener = listener
        self._day: str | None = None
        self._day_start_equity = float(config.capital)
        self._entries_paused_day: str | None = None
        self.last_equity = float(config.capital)
        # Paper trading sets this while paused or on late prices: exits still run, but no
        # new trades open (the text is the plain-English reason logged with the rejection).
        self.entry_block: str | None = None
        # Kairos's trade check (KAIROS §16): may skip an entry signal and learns from every
        # closed trade. Same object type in backtests and paper trading (D-04, D-71).
        self.check: TradeCheck | None = None
        for st in self.symbols:
            series = st.series or st.build_series(config.timeframe)
            st.ctx = StrategyContext(
                symbol=st.inst.symbol,
                market=config.market,
                timeframe=config.timeframe.value,
                params=dict(program.params),
                _provider=IndicatorProvider(series),
                _default_size=program.default_size,
            )
        if program.bind is not None:  # rules that compare stocks see them all (D-91)
            program.bind(self.symbols)

    # ------------------------------------------------------------ helpers

    def _local(self, ts: int) -> datetime:
        return ms_to_dt(ts, self.tz)

    def _day_of(self, ts: int) -> str:
        return self._local(ts).strftime("%Y-%m-%d")

    def _clock(self, ts: int) -> str:
        return self._local(ts).strftime("%H:%M")

    def _emit(self, kind: str, data: dict[str, object]) -> None:
        if self.listener is not None:
            self.listener(kind, data)

    def _order(self, ev: OrderEvent) -> None:
        self.orders.append(ev)
        self._emit("order", ev.__dict__)

    def _reject(self, st: SymbolState, ts: int, side: str, qty: float, reason: str) -> None:
        self._order(
            OrderEvent(ts, st.inst.symbol, st.inst.id, "market", side, qty, "rejected", reason)
        )

    def position_value(self) -> tuple[float, float]:
        """(net value of positions, gross exposure) at each symbol's latest close."""
        net = gross = 0.0
        for st in self.symbols:
            p = st.position
            if p is None or st.last_index < 0:
                continue
            close = st.raw[st.last_index].close
            net += p.sign * p.qty * close
            gross += p.qty * close
        return net, gross

    def equity_now(self) -> float:
        return self.cash + self.position_value()[0]

    # ------------------------------------------------------------ portfolio money (D-85)

    def free_cash(self) -> float:
        """Cash no open trade or waiting order needs: what a portfolio may take out. Short
        proceeds stay (they back the short), and orders waiting for the next candle keep
        their money."""
        waiting = 0.0
        for st in self.symbols:
            if st.last_index < 0:
                continue
            close = st.raw[st.last_index].close
            waiting += sum(o.qty * close for o in st.pending if o.kind == "entry")
        shorts = sum(
            st.position.qty * st.raw[st.last_index].close
            for st in self.symbols
            if st.position is not None and st.position.side == "short" and st.last_index >= 0
        )
        return max(0.0, self.cash - shorts - waiting)

    def transfer(self, amount: float, ts: int, note: str = "") -> float:
        """Move money into (+) or out of (−) this account, as a portfolio rebalance does
        (PORTFOLIO §5). Money comes out only up to the free cash; open trades are never cut.
        Returns the amount actually moved."""
        if amount < 0:
            amount = -min(-amount, self.free_cash())
        if amount == 0:
            return 0.0
        self.cash += amount
        self.last_equity += amount
        self._day_start_equity += amount  # moving money isn't a loss for the daily limit
        self.logs.append(note or f"Portfolio moved {amount:+.2f} {'in' if amount > 0 else 'out'}")
        self._emit("transfer", {"ts": ts, "amount": amount, "note": note})
        return amount

    def _charge(self, st: SymbolState, side: str, qty: float, price: float, ts: int) -> Charges:
        first_sell = True
        if side == "sell":
            day = self._day_of(ts)
            first_sell = st.last_sell_day != day
            st.last_sell_day = day
        c = self.costs.order(side, qty, price, ts, first_sell_of_day=first_sell)
        self.charges.add(c)
        return c

    # ------------------------------------------------------------ one time step

    def step(self, ts: int, items: list[tuple[SymbolState, int]]) -> None:
        """Process the candles that opened at ``ts`` (now closed) for these symbols."""
        items = sorted(items, key=lambda x: x[0].inst.symbol)
        day = self._day_of(ts)
        if day != self._day:
            self._day = day
            self._day_start_equity = self.equity_now()
        for st, i in items:
            self._open(st, i)
        for st, i in items:
            self._intrabar(st, i)
        for st, i in items:
            self._close(st, i)
        equity = self._record(ts)
        self._check_daily_loss(equity, day, ts)
        if ts >= self.cfg.start_ms:
            for st, i in items:
                self._decide(st, i, equity)

    # -- 1. open

    def _open(self, st: SymbolState, i: int) -> None:
        bar = st.raw[i]
        prev = st.last_index
        st.last_index = i
        p = st.position
        if p is not None and prev >= 0 and st.raw[prev].split_factor != bar.split_factor:
            ratio = bar.split_factor / st.raw[prev].split_factor
            p.qty *= ratio
            p.entry_price /= ratio
            p.peak /= ratio
            for attr in ("stop", "target", "trail_level", "atr_raw"):
                v = getattr(p, attr)
                if v is not None:
                    setattr(p, attr, v / ratio)
            rescale(p, ratio)
            self.logs.append(f"{st.inst.symbol}: split {ratio:g}-for-1, position adjusted")
        day = self._day_of(bar.ts)
        if (
            p is not None
            and self.cfg.product != "intraday"
            and (prev < 0 or self._day_of(st.raw[prev].ts) != day)
        ):
            amount = st.dividends.get(day)
            if amount:
                cash = p.sign * p.qty * amount
                self.cash += cash
                p.dividends += cash
                self._emit("dividend", {"symbol": st.inst.symbol, "amount": cash, "ts": bar.ts})
        locked = bar.high == bar.low and bar.volume > 0
        intraday_tf = self.cfg.timeframe.is_intraday
        past_square_off = (
            self.cfg.intraday_product and intraday_tf and self._clock(bar.ts) >= self.cfg.square_off
        )
        if past_square_off and st.position is not None and not locked:
            self._close_position(st, bar.ts, i, bar.open, "square_off", slip=True)
        keep: list[PendingOrder] = []
        for o in sorted(st.pending, key=lambda o: o.kind != "exit"):
            if self.cfg.intraday_product and o.kind == "entry":
                # With daily candles an intraday trade is meant for the next day by design.
                if intraday_tf and o.created_day != day:
                    self._reject(
                        st,
                        bar.ts,
                        _buy_sell(o),
                        o.qty,
                        "Intraday orders can't carry over to the next day.",
                    )
                    continue
                if past_square_off:
                    self._reject(
                        st,
                        bar.ts,
                        _buy_sell(o),
                        o.qty,
                        "Too late in the day to open an intraday trade.",
                    )
                    continue
            if locked:
                keep.append(o)  # circuit-locked: nothing fills; try again next candle
                continue
            if o.kind == "exit":
                if st.position is not None:
                    self._close_position(st, bar.ts, i, bar.open, o.exit_kind, slip=True)
            else:
                self._fill_entry(st, o, i)
        st.pending = keep

    def _fill_entry(self, st: SymbolState, o: PendingOrder, i: int) -> None:
        bar = st.raw[i]
        side = _buy_sell(o)
        if st.position is not None:
            return
        # An order bigger than the candle can take buys what it can (D-135): throwing the whole
        # trade away left a short desk's money idle on most signals.
        # No volume on a candle that traded means the source lost it, not that nobody traded:
        # Yahoo drops the first hour's volume on 76% of re-served Indian hourly candles, so every
        # entry there was refused as "too large" (D-221). Go by the candle before.
        volume = bar.volume
        if volume <= 0 and bar.high > bar.low and i > 0:
            volume = st.raw[i - 1].volume
        qty = min(o.qty, math.floor(self.cfg.volume_cap_pct / 100.0 * volume))
        if qty < 1:
            self._reject(st, bar.ts, side, o.qty, "Order too large for this candle's volume.")
            return
        price = slipped(bar.open, self.cfg.slippage_bps, paying=o.side == "long")
        charges = self.costs.order(side, qty, price, bar.ts)
        cost = qty * price
        if o.side == "long":
            if cost + float(charges.total) > self.cash + 1e-9:
                self._reject(st, bar.ts, side, qty, "Not enough cash for this trade.")
                return
        else:
            _, gross = self.position_value()
            if gross + cost > self.equity_now():
                self._reject(
                    st, bar.ts, side, qty, "Short would exceed your account size (no leverage)."
                )
                return
        self.charges.add(charges)
        if side == "sell":
            st.last_sell_day = self._day_of(bar.ts)
        self.cash += -cost if o.side == "long" else cost
        self.cash -= float(charges.total)
        sign = 1 if o.side == "long" else -1
        pos = Position(
            side=o.side,
            qty=qty,
            entry_price=price,
            entry_ts=bar.ts,
            entry_index=i,
            entry_reason=o.reason,
            entry_charges=charges,
            peak=price,
            atr_raw=o.atr_raw,
            trail=o.trailing_stop,
            signal_ts=st.raw[o.created_index].ts if 0 <= o.created_index < len(st.raw) else 0,
        )
        pos.stop = _level(o.stop_loss, price, o.atr_raw, -sign)
        pos.target = _level(o.take_profit, price, o.atr_raw, sign)
        pos.trail_level = _level(o.trailing_stop, price, o.atr_raw, -sign)
        pos.start_qty = qty
        if o.scale_out is not None:
            pos.scale = scale_levels(o.scale_out, price, pos.stop, o.atr_raw, sign, qty)
            pos.scale_breakeven = o.scale_out.breakeven
        st.position = pos
        self._order(
            OrderEvent(
                bar.ts,
                st.inst.symbol,
                st.inst.id,
                "market",
                side,
                qty,
                "filled",
                o.reason,
                price,
                float(charges.total),
                abs(price - bar.open) * qty,
            )
        )

    # -- 2. intrabar

    def _intrabar(self, st: SymbolState, i: int) -> None:
        p = st.position
        bar = st.raw[i]
        if p is None or (bar.high == bar.low and bar.volume > 0):
            return
        stop, reason = _effective_stop(p)
        if p.side == "long":
            hit = stop is not None and bar.low <= stop
        else:
            hit = stop is not None and bar.high >= stop
        if p.scale and not hit:
            self._take_partials(st, i)
            if st.position is None:
                return
        if p.side == "long":
            if stop is not None and bar.low <= stop:
                self._close_position(st, bar.ts, i, min(bar.open, stop), reason, slip=True)
            elif p.target is not None and bar.high >= p.target:
                self._close_position(st, bar.ts, i, max(bar.open, p.target), "target", slip=False)
        else:
            if stop is not None and bar.high >= stop:
                self._close_position(st, bar.ts, i, max(bar.open, stop), reason, slip=True)
            elif p.target is not None and bar.low <= p.target:
                self._close_position(st, bar.ts, i, min(bar.open, p.target), "target", slip=False)

    def _take_partials(self, st: SymbolState, i: int) -> None:
        """Sell part of the position at each partial-exit level the candle reached (a limit
        order: no slippage; a candle that opens past the level fills at its open)."""
        p = st.position
        bar = st.raw[i]
        assert p is not None
        while p.scale:
            level = p.scale[0]
            if p.side == "long" and bar.high < level.price:
                break
            if p.side == "short" and bar.low > level.price:
                break
            p.scale.pop(0)
            fill = max(bar.open, level.price) if p.side == "long" else min(bar.open, level.price)
            qty = min(level.qty, p.qty)
            if qty >= p.qty:
                self._close_position(st, bar.ts, i, fill, "target", slip=False)
                return
            side = "sell" if p.side == "long" else "buy"
            charges = self._charge(st, side, qty, fill, bar.ts)
            self.cash += qty * fill if p.side == "long" else -qty * fill
            self.cash -= float(charges.total)
            p.qty -= qty
            p.partials += 1
            p.sold_qty += qty
            p.sold_value += qty * fill
            p.sold_gross += (fill - p.entry_price) * qty * p.sign
            p.sold_charges = p.sold_charges + charges
            if p.scale_breakeven and p.partials == 1:
                if p.side == "long":
                    p.stop = p.entry_price if p.stop is None else max(p.stop, p.entry_price)
                else:
                    p.stop = p.entry_price if p.stop is None else min(p.stop, p.entry_price)
            self._order(
                OrderEvent(
                    bar.ts,
                    st.inst.symbol,
                    st.inst.id,
                    "limit",
                    side,
                    qty,
                    "filled",
                    f"Partial profit {p.partials} taken",
                    fill,
                    float(charges.total),
                    0.0,
                )
            )

    # -- 3. close

    def _close(self, st: SymbolState, i: int) -> None:
        p = st.position
        bar = st.raw[i]
        if p is None:
            return
        if self.cfg.intraday_product:
            tf = self.cfg.timeframe
            end_clock = self._clock(bar.ts + tf.minutes * 60_000) if tf.is_intraday else "99:99"
            if (
                not tf.is_intraday
                or end_clock > self.cfg.square_off
                or self._clock(bar.ts) > end_clock
            ):
                # Daily candles (or no candle opens at the square-off time): close at the close.
                self._close_position(st, bar.ts, i, bar.close, "square_off", slip=True)
                return
        if p.trail is not None:
            if p.side == "long":
                p.peak = max(p.peak, bar.high)
            else:
                p.peak = min(p.peak, bar.low)
            # the ATR measured at the entry signal (D-119): recomputing it on every candle made
            # paper trading and backtests trail at slightly different prices
            atr = p.atr_raw if p.trail.kind == "atr" else None
            level = _level(p.trail, p.peak, atr, -p.sign)
            if level is not None:
                if p.trail_level is None:
                    p.trail_level = level
                elif p.side == "long":
                    p.trail_level = max(p.trail_level, level)
                else:
                    p.trail_level = min(p.trail_level, level)

    def _record(self, ts: int) -> float:
        net, gross = self.position_value()
        equity = self.cash + net
        self.last_equity = equity
        self.equity.append(
            EquityPoint(ts, equity, self.cash, gross / equity if equity > 0 else 0.0)
        )
        return equity

    def _check_daily_loss(self, equity: float, day: str, ts: int) -> None:
        limit = self.cfg.max_daily_loss_pct
        if limit is None or self._entries_paused_day == day:
            return
        if equity <= self._day_start_equity * (1 - limit / 100.0):
            self._entries_paused_day = day
            msg = f"Daily loss limit ({limit:g}%) reached; no new trades for the rest of the day."
            self.logs.append(msg)
            self._emit("pause", {"ts": ts, "message": msg})

    # -- 4. decide

    def _decide(self, st: SymbolState, i: int, equity: float) -> None:
        ctx = st.ctx
        assert ctx is not None and st.series is not None
        if len(st.series) <= i:
            st.build_series(self.cfg.timeframe)
            ctx._provider.set_series(st.series)
        bar = st.raw[i]
        view = None
        p = st.position
        if p is not None:
            profit = (bar.close / p.entry_price - 1.0) * 100.0 * p.sign
            view = PositionView(p.side, p.qty, p.entry_price, p.entry_ts, i - p.entry_index, profit)
        if self.check is not None:
            self.check.observe(st.inst.id, st.series, i)
        ctx._advance(i, view, equity)
        self.program.on_bar(ctx)
        if ctx._logs:
            self.logs.extend(f"{st.inst.symbol} {ctx.date}: {line}" for line in ctx._logs)
            ctx._logs.clear()
        for intent in ctx._intents:
            if isinstance(intent, Exit):
                if st.position is not None and not any(o.kind == "exit" for o in st.pending):
                    st.pending.append(
                        PendingOrder(
                            "exit",
                            st.position.side,
                            st.position.qty,
                            bar.ts,
                            i,
                            self._day_of(bar.ts),
                            intent.reason,
                            intent.kind,
                        )
                    )
            elif isinstance(intent, Enter):
                self._queue_entry(st, i, intent, equity)

    def _queue_entry(self, st: SymbolState, i: int, e: Enter, equity: float) -> None:
        bar = st.raw[i]
        side = "buy" if e.side == "long" else "sell"
        if st.position is not None or any(o.kind == "entry" for o in st.pending):
            return
        if self.entry_block:
            self._reject(st, bar.ts, side, 0, self.entry_block)
            return
        if st.member is not None and not st.member(bar.ts):
            self._reject(st, bar.ts, side, 0, f"{st.inst.symbol} wasn't in the index on this date.")
            return
        if e.side == "short" and not self.cfg.shorts_allowed:
            self._reject(
                st, bar.ts, side, 0, "Short-selling isn't allowed for India delivery trades."
            )
            return
        if self._entries_paused_day == self._day_of(bar.ts):
            self._reject(st, bar.ts, side, 0, "Daily loss limit reached; no new trades today.")
            return
        if self.check is not None and st.series is not None:
            skip = self.check.check(
                st.inst.id, st.inst.symbol, st.series, i, 1 if e.side == "long" else -1
            )
            if skip:
                self._reject(st, bar.ts, side, 0, skip)
                return
        open_count = sum(1 for s in self.symbols if s.position is not None) + sum(
            1 for s in self.symbols for o in s.pending if o.kind == "entry"
        )
        if open_count >= self.cfg.max_open_positions:
            self._reject(
                st,
                bar.ts,
                side,
                0,
                f"Already at the limit of {self.cfg.max_open_positions} open trades.",
            )
            return
        cap = self.cfg.max_per_group
        if cap is not None and st.group:
            same = sum(
                1
                for s in self.symbols
                if s.group == st.group
                and (s.position is not None or any(o.kind == "entry" for o in s.pending))
            )
            if same >= cap:
                self._reject(st, bar.ts, side, 0, f"Already {same} open trades in {st.group}.")
                return
        needs_atr = [
            r
            for r in (e.stop_loss, e.take_profit, e.trailing_stop)
            if r is not None and r.kind == "atr"
        ]
        if not needs_atr and e.scale_out is not None:
            # partial exits measured in ATRs use ATR(14) at the signal
            needs_atr = [StopRule("atr", 1.0) for x in e.scale_out.steps if x.kind == "atr"][:1]
        atr = self._atr_raw(st, i, needs_atr[0].atr_period) if needs_atr else None
        if needs_atr and (atr is None or not math.isfinite(atr)):
            self._reject(st, bar.ts, side, 0, "Not enough history yet to measure ATR for the stop.")
            return
        size = e.size or self.program.default_size
        qty, problem = _size(size, bar.close, equity, e.stop_loss, atr, self.cfg.max_position_pct)
        if problem:
            self._reject(st, bar.ts, side, 0, problem)
            return
        st.pending.append(
            PendingOrder(
                "entry",
                e.side,
                qty,
                bar.ts,
                i,
                self._day_of(bar.ts),
                e.reason,
                stop_loss=e.stop_loss,
                take_profit=e.take_profit,
                trailing_stop=e.trailing_stop,
                atr_raw=atr,
                scale_out=e.scale_out,
            )
        )

    def _atr_raw(self, st: SymbolState, i: int, period: int) -> float | None:
        """ATR at candle i in raw-price terms (indicators run on split-adjusted prices)."""
        assert st.ctx is not None
        out = st.ctx._provider.compute("atr", {"period": float(period)}, None)["value"]
        if i >= len(out) or math.isnan(out[i]):
            return None
        return float(out[i]) / st.raw[i].split_factor

    # ------------------------------------------------------------ closing positions

    def _close_position(
        self, st: SymbolState, ts: int, i: int, price: float, reason: ExitReason, *, slip: bool
    ) -> None:
        p = st.position
        if p is None:
            return
        side = "sell" if p.side == "long" else "buy"
        fill = slipped(price, self.cfg.slippage_bps, paying=p.side == "short") if slip else price
        charges = self._charge(st, side, p.qty, fill, ts)
        if p.side == "long":
            self.cash += p.qty * fill
        else:
            self.cash -= p.qty * fill
        self.cash -= float(charges.total)
        gross = (fill - p.entry_price) * p.qty * p.sign + p.dividends + p.sold_gross
        total_charges = float(p.entry_charges.total + p.sold_charges.total + charges.total)
        net = gross - total_charges
        whole = p.qty + p.sold_qty
        cost_basis = p.entry_price * whole
        trade = Trade(
            st.inst.symbol,
            st.inst.id,
            p.side,
            whole,
            p.entry_ts,
            p.entry_price,
            ts,
            (p.sold_value + p.qty * fill) / whole if whole else fill,
            gross,
            total_charges,
            net,
            100.0 * net / cost_basis if cost_basis else 0.0,
            i - p.entry_index,
            p.entry_reason,
            reason,
            p.dividends,
            p.partials,
        )
        self.trades.append(trade)
        if self.check is not None and st.series is not None and p.signal_ts:
            self.check.closed(
                st.inst.id,
                st.inst.symbol,
                st.series,
                p.signal_ts,
                p.sign,
                net,
                trade.return_pct,
                trade.bars_held,
                100.0 * total_charges / cost_basis if cost_basis else 0.0,
                ts,
            )
        st.position = None
        st.pending = [o for o in st.pending if o.kind != "exit"]
        otype = (
            "stop"
            if reason in ("stop", "trailing")
            else "limit"
            if reason == "target"
            else "market"
        )
        label = _EXIT_LABEL.get(reason, reason)
        self._order(
            OrderEvent(
                ts,
                st.inst.symbol,
                st.inst.id,
                otype,
                side,
                p.qty,
                "filled",
                label,
                fill,
                float(charges.total),
                abs(fill - price) * p.qty,
            )
        )
        self._emit("trade", trade.__dict__)

    def finish(self) -> None:
        """End of a backtest: open positions are marked to the last close and reported as
        ``end_of_test`` (they count in equity, not in closed-trade statistics)."""
        for st in self.symbols:
            p = st.position
            if p is None or st.last_index < 0:
                continue
            bar = st.raw[st.last_index]
            gross = (bar.close - p.entry_price) * p.qty * p.sign + p.dividends + p.sold_gross
            charges = float(p.entry_charges.total + p.sold_charges.total)
            whole = p.qty + p.sold_qty
            cost_basis = p.entry_price * whole
            self.trades.append(
                Trade(
                    st.inst.symbol,
                    st.inst.id,
                    p.side,
                    whole,
                    p.entry_ts,
                    p.entry_price,
                    bar.ts,
                    (p.sold_value + p.qty * bar.close) / whole if whole else bar.close,
                    gross,
                    charges,
                    gross - charges,
                    100.0 * (gross - charges) / cost_basis if cost_basis else 0.0,
                    st.last_index - p.entry_index,
                    p.entry_reason,
                    "end_of_test",
                    p.dividends,
                    p.partials,
                )
            )


_EXIT_LABEL: dict[str, str] = {
    "stop": "Stop-loss hit",
    "trailing": "Trailing stop hit",
    "target": "Take-profit reached",
    "square_off": "Intraday square-off",
    "signal": "Exit rule",
    "time": "Time exit",
}


def _buy_sell(o: PendingOrder) -> str:
    if o.kind == "entry":
        return "buy" if o.side == "long" else "sell"
    return "sell" if o.side == "long" else "buy"


def _level(rule: StopRule | None, ref: float, atr: float | None, direction: int) -> float | None:
    """A price ``rule`` away from ``ref``: direction −1 below (long stops), +1 above."""
    if rule is None:
        return None
    if rule.kind == "percent":
        return ref * (1.0 + direction * rule.value / 100.0)
    if atr is None or not math.isfinite(atr):
        return None
    return ref + direction * rule.value * atr


def scale_levels(
    rule: ScaleOut, entry: float, stop: float | None, atr: float | None, sign: int, qty: float
) -> list[ScaleLevel]:
    """The partial-exit levels for a new position, nearest first. A step measured in R
    needs a stop-loss (R is the distance to it); one that can't be measured, or that would
    sell less than one share, is left out. At least one share always stays for the rest."""
    risk = abs(entry - stop) if stop is not None else None
    found: list[tuple[float, float]] = []
    for step in rule.steps:
        dist: float | None
        if step.kind == "r":
            dist = step.value * risk if risk else None
        elif step.kind == "percent":
            dist = entry * step.value / 100.0
        else:
            dist = step.value * atr if atr is not None and math.isfinite(atr) else None
        if dist is None or dist <= 0:
            continue
        found.append((dist, step.sell_pct))
    found.sort()
    out: list[ScaleLevel] = []
    left = qty
    for dist, pct in found:
        q = min(float(math.floor(qty * pct / 100.0)), left - 1)
        if q < 1:
            continue
        out.append(ScaleLevel(entry + sign * dist, q))
        left -= q
    return out


def rescale(p: Position, ratio: float) -> None:
    """A split: the partial-exit bookkeeping follows the shares (prices / ratio, shares x)."""
    p.start_qty *= ratio
    p.sold_qty *= ratio
    for lv in p.scale:
        lv.price /= ratio
        lv.qty *= ratio


def _effective_stop(p: Position) -> tuple[float | None, ExitReason]:
    """The tighter of the fixed stop and the trailing stop."""
    stop, trail = p.stop, p.trail_level
    if trail is None:
        return stop, "stop"
    if stop is None:
        return trail, "trailing"
    if p.side == "long":
        return (trail, "trailing") if trail > stop else (stop, "stop")
    return (trail, "trailing") if trail < stop else (stop, "stop")


def _size(
    size: SizeSpec,
    price: float,
    equity: float,
    stop: StopRule | None,
    atr: float | None,
    max_pct: float | None = None,
) -> tuple[float, str | None]:
    if price <= 0:
        return 0, "No valid price to size the trade."
    if size.kind == "fixed_qty":
        qty = math.floor(size.value)
    elif size.kind == "fixed_amount":
        qty = math.floor(size.value / price)
    elif size.kind == "percent_equity":
        qty = math.floor(equity * size.value / 100.0 / price)
    else:
        if stop is None:
            return 0, "Risk-based sizing needs a stop-loss."
        distance = (
            price * stop.value / 100.0
            if stop.kind == "percent"
            else (stop.value * atr if atr else 0.0)
        )
        if distance <= 0:
            return 0, "Couldn't measure the stop distance for risk-based sizing."
        qty = math.floor(min(equity * size.value / 100.0 / distance, equity / price))
    if max_pct is not None:
        qty = min(qty, math.floor(equity * max_pct / 100.0 / price))
    qty = math.floor(qty * size.scale)
    if qty < 1:
        return 0, "The trade size rounds down to zero shares."
    return float(qty), None
