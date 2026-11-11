"""Golden engine tests (D-11): hand-made candles with known answers for every fill rule in
COST_MODEL.md §4, plus splits, dividends, shorts, limits and square-off.

Strategies here are tiny Python functions that act on a given candle index, so each test
reads as "on candle 2, buy 10 shares; expect the fill at candle 3's open"."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.core.types import Bar, Market, Timeframe
from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.data.store import InstrumentRef
from backend.engine.core import Engine, EngineConfig, SymbolState
from backend.strategy.compiler import Program
from backend.strategy.runtime import SizeSpec, StopRule, StrategyContext

ET = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")
OHLCV = tuple[float, float, float, float, float]


def daily_bars(
    rows: list[OHLCV], tz: ZoneInfo = ET, factors: list[float] | None = None
) -> list[Bar]:
    out, d = [], date(2024, 1, 2)
    open_t = time(9, 30) if tz is ET else time(9, 15)
    for k, (o, h, low, c, v) in enumerate(rows):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ts = int(datetime.combine(d, open_t, tz).timestamp() * 1000)
        out.append(Bar(ts, o, h, low, c, v, "test", True, factors[k] if factors else 1.0))
        d += timedelta(days=1)
    return out


def flat(n: int, price: float = 100.0, vol: float = 1e6) -> list[OHLCV]:
    return [(price, price + 1, price - 1, price, vol)] * n


Action = Callable[[StrategyContext], None]


def program(actions: dict[int, Action], size: SizeSpec | None = None) -> Program:
    def on_bar(ctx: StrategyContext) -> None:
        act = actions.get(ctx.bar_index)
        if act:
            act(ctx)

    return Program(on_bar, {}, size or SizeSpec("fixed_qty", 10), warmup=1, kind="visual")


def buy(**kw: object) -> Action:
    return lambda ctx: ctx.buy(**kw)  # type: ignore[arg-type]


def short(**kw: object) -> Action:
    return lambda ctx: ctx.short(**kw)  # type: ignore[arg-type]


def sell() -> Action:
    return lambda ctx: ctx.sell_all("Exit rule")


def inst(symbol: str = "TEST", market: Market = Market.US, iid: int = 1) -> InstrumentRef:
    return InstrumentRef(iid, market, symbol, symbol, symbol, "equity")


def run(
    bars: list[Bar] | dict[str, list[Bar]],
    prog: Program,
    *,
    market: Market = Market.US,
    product: str = "cash",
    timeframe: Timeframe = Timeframe.D1,
    capital: float = 100_000.0,
    slippage: float = 0.0,
    max_positions: int = 5,
    daily_loss: float | None = None,
    max_position_pct: float | None = None,
    max_per_group: int | None = None,
    groups: dict[str, str] | None = None,
    dividends: dict[str, float] | None = None,
    costs: CostModel | None = None,
) -> Engine:
    if isinstance(bars, list):
        bars = {"TEST": bars}
    states = [
        SymbolState(inst(sym, market, n + 1), b, dividends=dividends or {})
        for n, (sym, b) in enumerate(bars.items())
    ]
    for st in states:
        st.group = (groups or {}).get(st.inst.symbol, "")
    cfg = EngineConfig(
        market=market,
        product=product,
        timeframe=timeframe,
        capital=capital,
        slippage_bps=slippage,
        max_open_positions=max_positions,
        max_daily_loss_pct=daily_loss,
        max_position_pct=max_position_pct,
        max_per_group=max_per_group,
    )
    engine = Engine(
        cfg, prog, costs or CostModel(market.value, product, {}, ChargeTable([])), states
    )
    steps: dict[int, list[tuple[SymbolState, int]]] = {}
    for st in engine.symbols:
        for i, b in enumerate(st.raw):
            steps.setdefault(b.ts, []).append((st, i))
    for ts in sorted(steps):
        engine.step(ts, steps[ts])
    engine.finish()
    return engine


def rejected(e: Engine) -> list[str]:
    return [o.reason for o in e.orders if o.status == "rejected"]


# ---------------------------------------------------------------- market orders


def test_signal_on_close_fills_at_next_open() -> None:
    rows = flat(5)
    rows[1] = (101.0, 103, 100, 102, 1e6)
    rows[3] = (104.0, 105, 103, 104, 1e6)
    e = run(daily_bars(rows), program({0: buy(), 2: sell()}))
    (t,) = e.trades
    # buy signalled on candle 0's close → filled at candle 1's open (101)
    # sell signalled on candle 2's close → filled at candle 3's open (104)
    assert (t.entry_price, t.exit_price, t.qty, t.exit_reason) == (101.0, 104.0, 10, "signal")
    assert t.gross_pnl == pytest.approx(30.0)
    assert e.equity[-1].equity == pytest.approx(100_030.0)


def test_slippage_moves_both_fills_against_the_trader() -> None:
    rows = flat(4)
    e = run(daily_bars(rows), program({0: buy(), 1: sell()}), slippage=10)
    (t,) = e.trades
    # 10 bps: buy 100 × 1.001 = 100.10; sell 100 × 0.999 = 99.90 → −0.20 × 10 shares
    assert t.entry_price == pytest.approx(100.10) and t.exit_price == pytest.approx(99.90)
    assert t.gross_pnl == pytest.approx(-2.0)


# ---------------------------------------------------------------- stops and targets


def test_gap_through_stop_fills_at_the_open() -> None:
    rows = flat(5)
    rows[2] = (90.0, 91, 88, 89, 1e6)  # opens below the 95 stop
    e = run(daily_bars(rows), program({0: buy(stop_loss=StopRule("percent", 5))}))
    (t,) = e.trades
    # entry 100 → stop 95; the next candle opens at 90 → filled at min(open 90, stop 95) = 90
    assert (t.exit_price, t.exit_reason) == (90.0, "stop")


def test_stop_and_target_in_one_candle_assumes_the_stop() -> None:
    rows = flat(5)
    rows[2] = (100.0, 111, 94, 105, 1e6)  # touches both 95 and 110
    e = run(
        daily_bars(rows),
        program({0: buy(stop_loss=StopRule("percent", 5), take_profit=StopRule("percent", 10))}),
    )
    (t,) = e.trades
    assert (t.exit_price, t.exit_reason) == (95.0, "stop")


def test_target_fills_at_the_target_without_slippage() -> None:
    rows = flat(5)
    rows[2] = (105.0, 112, 104, 111, 1e6)
    e = run(daily_bars(rows), program({0: buy(take_profit=StopRule("percent", 10))}), slippage=10)
    (t,) = e.trades
    # entry 100 × 1.001 = 100.10 → target 110.11; filled at max(open 105, 110.11) = 110.11
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(110.11)


def test_trailing_stop_uses_closed_candles() -> None:
    rows = flat(6)
    rows[1] = (100.0, 101, 99, 100, 1e6)  # entry candle
    rows[2] = (110.0, 120, 109, 118, 1e6)  # new high 120 → trail at 108 from the next candle
    rows[3] = (112.0, 113, 107, 108, 1e6)  # low 107 crosses 108 → exit at min(open 112, 108)
    e = run(daily_bars(rows), program({0: buy(trailing_stop=StopRule("percent", 10))}))
    (t,) = e.trades
    assert (t.exit_reason, t.exit_price) == ("trailing", 108.0)


def test_atr_stop_distance() -> None:
    rows = [(100.0, 102, 98, 100, 1e6)] * 20  # true range 4 every candle → ATR(14) = 4
    rows[16] = (100.0, 100.5, 91, 95, 1e6)
    e = run(daily_bars(rows), program({15: buy(stop_loss=StopRule("atr", 2, 14))}))
    (t,) = e.trades
    # entry 100 at candle 16's open; stop 100 − 2 × 4 = 92; low 91 → filled at 92
    assert (t.exit_reason, t.exit_price) == ("stop", 92.0)


# ---------------------------------------------------------------- rejections


def test_volume_cap_shrinks_large_orders_to_what_the_candle_takes() -> None:
    rows = flat(4, vol=10_000)  # 5% = 500 shares
    e = run(daily_bars(rows), program({0: buy()}, SizeSpec("fixed_qty", 1000)))
    (t,) = e.trades
    assert t.qty == 500 and rejected(e) == []  # D-135: buys what it can, not nothing


def test_volume_cap_rejects_when_not_one_share_fits() -> None:
    rows = flat(4, vol=10)  # 5% = half a share
    e = run(daily_bars(rows), program({0: buy()}, SizeSpec("fixed_qty", 1000)))
    assert e.trades == []
    assert rejected(e) == ["Order too large for this candle's volume."]


def test_circuit_locked_candle_delays_the_fill() -> None:
    rows = flat(5)
    rows[1] = (105.0, 105, 105, 105, 5e5)  # locked: high == low == close with volume
    rows[2] = (106.0, 107, 105, 106, 1e6)
    e = run(daily_bars(rows), program({0: buy()}))
    (t,) = e.trades
    assert t.entry_price == 106.0 and t.entry_ts == daily_bars(rows)[2].ts


def test_not_enough_cash() -> None:
    e = run(daily_bars(flat(3)), program({0: buy()}, SizeSpec("fixed_qty", 2000)), capital=100_000)
    assert rejected(e) == ["Not enough cash for this trade."]


def test_max_open_positions_across_symbols() -> None:
    bars = {"AAA": daily_bars(flat(4)), "BBB": daily_bars(flat(4))}
    e = run(bars, program({0: buy()}), max_positions=1)
    assert [t.symbol for t in e.trades] == ["AAA"]
    assert rejected(e) == ["Already at the limit of 1 open trades."]


def test_size_rounds_down_to_whole_shares() -> None:
    e = run(daily_bars(flat(3, price=300.0)), program({0: buy()}, SizeSpec("percent_equity", 10)))
    # 10% of 100,000 = 10,000 ÷ 300 = 33.3 → 33 shares
    assert e.trades[0].qty == 33


def test_tight_stop_risk_sizing_is_capped_at_a_share_of_the_money() -> None:
    # 1% risk with a 0.5% stop wants 200% of the money; it gets 100% without a cap (D-131)
    rows = daily_bars(flat(3, price=100.0))
    prog = program({0: buy(stop_loss=StopRule("percent", 0.5))}, SizeSpec("risk_percent", 1))
    assert run(rows, prog).trades[0].qty == 1000  # 100,000 ÷ 100
    # capped at 20%: 20,000 ÷ 100 = 200 shares
    assert run(rows, prog, max_position_pct=20).trades[0].qty == 200


# ---------------------------------------------------------------- shorts and products


def test_us_short_round_trip() -> None:
    rows = flat(5)
    rows[3] = (90.0, 91, 89, 90, 1e6)
    e = run(daily_bars(rows), program({0: short(), 2: sell()}))
    (t,) = e.trades
    assert t.side == "short" and t.entry_price == 100.0 and t.exit_price == 90.0
    assert t.gross_pnl == pytest.approx(100.0)  # (100 − 90) × 10


def test_india_delivery_cannot_short() -> None:
    e = run(daily_bars(flat(3), IST), program({0: short()}), market=Market.IN, product="delivery")
    assert rejected(e) == ["Short-selling isn't allowed for India delivery trades."]


def test_daily_candles_with_intraday_product_close_the_same_day() -> None:
    rows = flat(4)
    rows[1] = (100.0, 104, 99, 103, 1e6)
    e = run(daily_bars(rows, IST), program({0: buy()}), market=Market.IN, product="intraday")
    (t,) = e.trades
    assert (t.entry_price, t.exit_price, t.exit_reason) == (100.0, 103.0, "square_off")


def five_minute(day: date, rows: list[OHLCV], start: time = time(9, 15)) -> list[Bar]:
    t0 = datetime.combine(day, start, IST)
    return [
        Bar(int((t0 + timedelta(minutes=5 * k)).timestamp() * 1000), o, h, low, c, v, "test")
        for k, (o, h, low, c, v) in enumerate(rows)
    ]


def test_india_intraday_square_off_at_1520() -> None:
    day = date(2024, 1, 2)
    rows = flat(75)  # a full 09:15–15:30 session of 5-minute candles
    rows[73] = (101.0, 102, 100, 101, 1e6)  # the 15:20 candle (09:15 + 73 × 5 min)
    bars = five_minute(day, rows)
    e = run(
        bars, program({10: buy()}), market=Market.IN, product="intraday", timeframe=Timeframe.M5
    )
    (t,) = e.trades
    assert t.exit_reason == "square_off"
    assert datetime.fromtimestamp(t.exit_ts / 1000, IST).strftime("%H:%M") == "15:20"
    assert t.exit_price == 101.0


def test_india_intraday_orders_never_carry_overnight() -> None:
    d1 = five_minute(date(2024, 1, 2), flat(3), start=time(15, 15))  # 15:15, 15:20, 15:25
    d2 = five_minute(date(2024, 1, 3), flat(3))
    e = run(
        d1 + d2, program({2: buy()}), market=Market.IN, product="intraday", timeframe=Timeframe.M5
    )
    assert e.trades == []
    assert rejected(e) == ["Intraday orders can't carry over to the next day."]


# ---------------------------------------------------------------- corporate actions


def test_split_doubles_quantity_and_keeps_value() -> None:
    rows = flat(6)
    rows[3] = (50.0, 51, 49, 50, 2e6)  # 2-for-1 split: raw price halves
    rows[4] = (50.0, 51, 49, 50, 2e6)
    rows[5] = (50.0, 51, 49, 50, 2e6)
    factors = [0.5, 0.5, 0.5, 1.0, 1.0, 1.0]
    e = run(daily_bars(rows, factors=factors), program({0: buy(), 4: sell()}))
    (t,) = e.trades
    # 10 shares at 100 become 20 at 50; sold at 50 → no gain, no loss
    assert t.qty == 20 and t.entry_price == 50.0 and t.exit_price == 50.0
    assert t.gross_pnl == pytest.approx(0.0)
    assert [round(p.equity) for p in e.equity] == [100_000] * 6


def test_dividend_is_credited_on_the_ex_date() -> None:
    bars = daily_bars(flat(5))
    ex = datetime.fromtimestamp(bars[3].ts / 1000, ET).strftime("%Y-%m-%d")
    e = run(bars, program({0: buy(), 3: sell()}), dividends={ex: 2.5})
    (t,) = e.trades
    assert t.dividends == pytest.approx(25.0) and t.gross_pnl == pytest.approx(25.0)


# ---------------------------------------------------------------- end of test, limits, costs


def test_open_position_at_the_end_is_marked_not_closed() -> None:
    rows = flat(4)
    rows[3] = (100.0, 111, 99, 110, 1e6)
    e = run(daily_bars(rows), program({0: buy()}))
    (t,) = e.trades
    assert t.exit_reason == "end_of_test" and not t.closed
    assert t.exit_price == 110.0 and t.gross_pnl == pytest.approx(100.0)
    assert e.equity[-1].equity == pytest.approx(100_100.0)


def test_daily_loss_limit_pauses_new_entries() -> None:
    bars = {"AAA": daily_bars([(100.0, 101, 99, 100, 1e6), (100.0, 101, 50, 50, 1e6), *flat(3)])}
    prog = program({0: buy(), 1: buy()}, SizeSpec("fixed_qty", 500))
    e = run(bars, prog, daily_loss=10.0)
    assert any("Daily loss limit" in line for line in e.logs)


def test_charges_reduce_cash_and_net_pnl(db: object) -> None:
    from backend.db.engine import Database

    assert isinstance(db, Database)
    with db.session() as s:
        table = ChargeTable.load(s, "US")
    costs = CostModel("US", "cash", {"cash": {"flat": 1.0}}, table)  # $1 per order
    rows = flat(4)
    e = run(daily_bars(rows), program({0: buy(), 1: sell()}), costs=costs)
    (t,) = e.trades
    # $1 commission each way; 2024 SEC $8.00/M × $1,000 = $0.008 → $0.01 (rounded up);
    # FINRA 10 × 0.000166 = $0.00166 → $0.00
    assert t.charges == pytest.approx(2.01)
    assert t.net_pnl == pytest.approx(-2.01)
    assert e.equity[-1].equity == pytest.approx(100_000 - 2.01)


# ---------------------------------------------------------------- partial exits (D-125)


def test_partial_exit_then_breakeven_stop_is_one_trade() -> None:
    rows = flat(6)
    rows[1] = (100.0, 101, 99, 100, 1e6)  # entry at 100; stop 95 → 1R = 5
    rows[2] = (103.0, 106, 102, 104, 1e6)  # high 106 ≥ 105 (1R): sell 5 of 10 at 105
    rows[3] = (102.0, 103, 99, 100, 1e6)  # stop moved to 100 (breakeven): the rest out at 100
    plan = ctx_scale([(1, 50)])
    e = run(
        daily_bars(rows),
        program({0: lambda ctx: ctx.buy(stop_loss=StopRule("percent", 5), scale_out=plan(ctx))}),
    )
    (t,) = e.trades  # one trade, not two
    assert t.qty == 10 and t.partials == 1 and t.exit_reason == "stop"
    assert t.exit_price == pytest.approx((5 * 105 + 5 * 100) / 10)  # average of both sales
    assert t.gross_pnl == pytest.approx(5 * 5 + 5 * 0)  # +25: the rest couldn't lose
    fills = [(o.qty, o.price, o.reason) for o in e.orders if o.status == "filled"]
    assert fills[1] == (5, 105.0, "Partial profit 1 taken")
    assert e.cash == pytest.approx(100_000 + 25)


def test_thirds_on_a_short_and_target_for_the_rest() -> None:
    rows = flat(6)
    rows[1] = (100.0, 101, 99, 100, 1e6)  # short 9 at 100; stop 102 → 1R = 2
    rows[2] = (99.0, 99.5, 97.5, 98, 1e6)  # low 97.5 ≤ 98 (1R): buy back 3 at 98
    rows[3] = (97.0, 97.5, 95.5, 96, 1e6)  # low 95.5 ≤ 96 (2R): 3 more at 96
    rows[4] = (95.0, 95.5, 93, 94, 1e6)  # target 6% = 94: the last 3 at 94
    plan = ctx_scale([(1, 33.4), (2, 33.4)])
    e = run(
        daily_bars(rows),
        program(
            {
                0: lambda ctx: ctx.short(
                    stop_loss=StopRule("percent", 2),
                    take_profit=StopRule("percent", 6),
                    scale_out=plan(ctx),
                )
            },
            SizeSpec("fixed_qty", 9),
        ),
    )
    (t,) = e.trades
    assert (t.qty, t.partials, t.exit_reason) == (9, 2, "target")
    assert t.gross_pnl == pytest.approx(3 * 2 + 3 * 4 + 3 * 6)


def test_partial_in_r_without_a_stop_is_skipped() -> None:
    rows = flat(5)
    plan = ctx_scale([(1, 50)])
    e = run(daily_bars(rows), program({0: lambda ctx: ctx.buy(scale_out=plan(ctx))}))
    (t,) = e.trades
    assert t.partials == 0 and t.exit_reason == "end_of_test"


def ctx_scale(steps: list[tuple[float, float]]) -> Callable[[StrategyContext], object]:
    return lambda ctx: ctx.scale_out(steps)


def test_at_most_n_open_trades_in_one_sector() -> None:
    """D-168: a desk held six trades on the oil price at once; a sector cap stops that, and a
    stock with no sector counts alone."""
    bars = {s: daily_bars(flat(5)) for s in ("EOG", "CVX", "COP", "BNO", "MRNA")}
    groups = {"EOG": "Energy", "CVX": "Energy", "COP": "Energy", "MRNA": "Health Care"}
    e = run(bars, program({1: buy()}), max_per_group=2, groups=groups)
    held = {t.symbol for t in e.trades} | {
        st.inst.symbol for st in e.symbols if st.position is not None
    }
    assert len(held & {"EOG", "CVX", "COP"}) == 2  # the third Energy trade waits
    assert {"BNO", "MRNA"} <= held  # no sector, and another sector: unaffected
    assert rejected(e) == ["Already 2 open trades in Energy."]
