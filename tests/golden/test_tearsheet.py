"""The tear sheet (D-89), with the arithmetic worked by hand in the comments."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from backend.metrics import tearsheet as ts

UTC_ZONE = ZoneInfo("UTC")


def test_drawdown_periods_by_hand() -> None:
    # start 100 → 110 (high) → 99 (−10%) → 110 recovered; → 120 (high) → 90 (−25%) → 96 → 121
    # recovered and a new high → 115 (−4.96%, not recovered)
    days = [f"2024-01-{d:02d}" for d in range(1, 10)]
    values = [100, 110, 99, 110, 120, 90, 96, 121, 115]
    p = ts.drawdown_periods(days, values, 100.0)
    assert [x["depth"] for x in p] == [0.25, 0.1, round(1 - 115 / 121, 6)]
    deep = p[0]
    assert (deep["peak"], deep["trough"], deep["recovered"]) == (
        "2024-01-05",
        "2024-01-06",
        "2024-01-08",
    )
    assert deep["days_falling"] == 1 and deep["days_recovering"] == 2
    assert p[2]["recovered"] is None and p[2]["days_recovering"] is None
    assert len(ts.drawdown_periods(days, values, 100.0, top=1)) == 1


def test_rolling_sharpe_by_hand() -> None:
    # windows of 2: [0.01, −0.01] → mean 0 → 0; [−0.01, 0.02] → mean 0.005, sd 0.0212132 →
    # 0.235702 × √252 = 3.7417; [0.02, 0] → mean 0.01, sd 0.0141421 → 0.707107 × √252 = 11.2250
    r = ts.rolling_sharpe([0.01, -0.01, 0.02, 0.0], window=2)
    assert math.isnan(r[0])
    assert r[1] == pytest.approx(0.0)
    assert r[2] == pytest.approx(3.7417, abs=1e-4)
    assert r[3] == pytest.approx(11.2250, abs=1e-4)
    assert math.isnan(ts.rolling_sharpe([0.01, 0.01, 0.01], window=2)[2])  # flat: no Sharpe


def test_value_at_risk_and_tail_by_hand() -> None:
    r = [-0.05, -0.03, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    # level 80%: k = ⌈10 × 0.2⌉ = 2 → VaR = 2nd worst = 3%; CVaR = (5% + 3%) / 2 = 4%;
    # tail ratio = 2nd best 5% ÷ 2nd worst 3% = 1.6667
    t = ts.tail(r, level=0.8)
    assert t["var"] == pytest.approx(0.03)
    assert t["cvar"] == pytest.approx(0.04)
    assert t["tail_ratio"] == pytest.approx(5 / 3)
    # level 90%: k = 1 → the worst day, 5%, both
    t90 = ts.tail(r, level=0.9)
    assert t90["var"] == pytest.approx(0.05) and t90["cvar"] == pytest.approx(0.05)
    assert ts.tail([])["var"] == 0.0


def test_resamples_keep_blocks_and_repeat() -> None:
    r = np.arange(100, dtype=float)
    m = ts.resamples(r, 50, mean_block=10.0, seed=3)
    assert m.shape == (50, 100) and set(np.unique(m)) <= set(r)
    # inside a block the next day follows the previous one (wrapping round at the end)
    steps = (np.diff(m, axis=1) % 100 == 1).mean()
    assert 0.85 < steps < 0.95  # a new block starts on about 1 day in 10
    assert np.array_equal(m, ts.resamples(r, 50, mean_block=10.0, seed=3))


def test_band_and_outcomes_of_a_steady_series() -> None:
    # The same return every day: every resample is identical, so the bands collapse.
    flat = [0.001] * 60
    o = ts.outcomes(flat)
    assert o["return_p5"] == pytest.approx(o["return_p95"]) == pytest.approx(1.001**252 - 1)
    assert o["drop_p95"] == 0.0
    rng = np.random.default_rng(5)
    noisy = rng.normal(0.001, 0.01, 500)
    b = ts.sharpe_band(noisy)
    assert b["p5"] < b["p50"] < b["p95"]
    assert ts.outcomes(noisy[:10]) == {}


def _points(values: list[float]) -> list[tuple[int, float]]:
    t0 = int(datetime(2023, 1, 2, 10, tzinfo=UTC).timestamp() * 1000)
    return [(t0 + k * 86_400_000, v) for k, v in enumerate(values)]


def test_the_whole_sheet() -> None:
    rng = np.random.default_rng(1)
    values = list(100_000 * np.cumprod(1 + rng.normal(0.0008, 0.01, 400)))
    pnls = list(rng.normal(50, 400, 60))
    sheet = ts.compute(_points(values), pnls, 100_000.0, UTC_ZONE, n_trials=12)
    assert sheet["days"] == 400
    sh = sheet["sharpe"]
    assert sh["band"]["p5"] < sh["value"] < sh["band"]["p95"]
    assert 0.0 <= sh["dsr"] <= sh["psr"] <= 1.0  # the luck check is stricter
    assert sheet["trade_order"]["trades"] == 60
    assert sheet["rolling"]["window"] == 126 and len(sheet["rolling"]["points"]) <= 301
    assert sheet["underwater"]["periods"][0]["depth"] >= sheet["underwater"]["periods"][-1]["depth"]
    assert [y["year"] for y in sheet["years"]] == ["2023", "2024"]
    assert sheet["risk"]["worst_day"] < 0 < sheet["risk"]["best_day"]
    assert any("luck check" in line for line in sheet["summary"])
    assert sheet["summary"][0].startswith("Sharpe ratio ")
    # Same inputs, same sheet (seeded).
    assert ts.compute(_points(values), pnls, 100_000.0, UTC_ZONE, n_trials=12) == sheet
    # One try: no luck check line.
    assert ts.compute(_points(values), pnls, 100_000.0, UTC_ZONE)["sharpe"]["dsr"] is None
    short = ts.compute(_points(values[:10]), [], 100_000.0, UTC_ZONE)
    assert short["empty"] is True
