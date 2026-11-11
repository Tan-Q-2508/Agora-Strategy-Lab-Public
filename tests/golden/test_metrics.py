"""Golden metric tests (D-11) on tiny equity curves worked out by hand."""

from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import pytest

from backend.engine.types import EquityPoint, Trade
from backend.metrics import performance as pm

UTC = ZoneInfo("UTC")
DAY = 86_400_000


def curve(values: list[float], exposure: float = 1.0) -> list[EquityPoint]:
    return [EquityPoint(i * DAY, v, v, exposure) for i, v in enumerate(values)]


def trade(net: float, gross: float | None = None, closed: bool = True, days: int = 2) -> Trade:
    return Trade(
        "X",
        1,
        "long",
        10,
        0,
        100.0,
        days * DAY,
        100.0,
        gross if gross is not None else net,
        0.0,
        net,
        net / 10,
        days,
        "",
        "signal" if closed else "end_of_test",
    )


def test_returns_sharpe_sortino() -> None:
    # equity 100 → 110 → 99 → 108.9 (start capital 100)
    # daily returns: +10%, −10%, +10%;  mean 0.033333, sample sd = 0.11547
    pts = curve([110.0, 99.0, 108.9])
    rets = pm.returns([p.equity for p in pts], 100.0)
    assert rets == pytest.approx([0.10, -0.10, 0.10])
    assert pm.sharpe(rets) == pytest.approx(0.0333333 / 0.1154701 * math.sqrt(252), rel=1e-5)
    # downside deviation = sqrt((0 + 0.01 + 0)/3) = 0.057735
    assert pm.sortino(rets) == pytest.approx(0.0333333 / 0.0577350 * math.sqrt(252), rel=1e-5)


def test_drawdown_depth_dates_and_duration() -> None:
    # peak 120 on day 1, trough 90 on day 3 (−25%), recovers to 121 on day 5
    pts = [(i * DAY, v) for i, v in enumerate([100.0, 120.0, 100.0, 90.0, 110.0, 121.0, 115.0])]
    dd = pm.drawdown(pts, 100.0)
    assert dd.max_dd == pytest.approx(0.25)
    assert (dd.peak_ts, dd.trough_ts, dd.recovered_ts) == (1 * DAY, 3 * DAY, 5 * DAY)
    assert dd.longest_days == pytest.approx(4.0)  # underwater from day 1 until day 5


def test_cagr_uses_calendar_time() -> None:
    # doubling over two years (730.5 days) → √2 − 1 = 41.42% a year
    assert pm.cagr(100.0, 200.0, 730.5) == pytest.approx(math.sqrt(2) - 1)


def test_trade_stats_ignore_open_trades() -> None:
    trades = [trade(300.0), trade(-100.0), trade(200.0), trade(-50.0), trade(999.0, closed=False)]
    st = pm.trade_stats(trades)
    # closed: +300, −100, +200, −50 → win rate 50%, profit factor 500/150, expectancy 87.5
    assert st["trades"] == 4 and st["open_at_end"] == 1
    assert st["win_rate"] == 0.5
    assert st["profit_factor"] == pytest.approx(500 / 150)
    assert st["expectancy"] == pytest.approx(87.5)
    assert (st["avg_win"], st["avg_loss"]) == (250.0, -75.0)
    assert (st["largest_win"], st["largest_loss"]) == (300.0, -100.0)


def test_monthly_returns() -> None:
    daily = [("2024-01-31", 110.0), ("2024-02-15", 99.0), ("2024-02-29", 121.0)]
    out = pm.monthly_returns(daily, 100.0)
    # January: 110/100 − 1 = +10%; February: 121/110 − 1 = +10%
    assert out == pytest.approx({"2024-01": 0.10, "2024-02": 0.10})


def test_compute_headline_and_benchmark() -> None:
    pts = curve([100.0, 105.0, 102.0, 110.0], exposure=0.5)
    m = pm.compute(
        pts,
        [trade(10.0, gross=12.0)],
        100.0,
        UTC,
        charges_total=2.0,
        traded_notional=400.0,
        benchmark=[(0, 100.0), (3 * DAY, 104.0)],
    )
    assert m["total_return"] == pytest.approx(0.10)
    assert m["benchmark"]["total_return"] == pytest.approx(0.04)
    assert m["vs_benchmark"] == pytest.approx(0.06)
    assert m["charges_pct_of_gross_profit"] == pytest.approx(2.0 / 12.0)
    assert m["time_in_market"] == 1.0 and m["avg_exposure"] == 0.5
    assert m["max_drawdown"] == pytest.approx(1 - 102 / 105)
