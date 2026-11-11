"""The full chart report on the practice data: complete, JSON-safe, fast and honest."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from itertools import pairwise

import pytest

from backend.analysis.report import Analysis, analyze, future_times, price
from backend.core.types import Market
from backend.indicators.series import BarSeries
from tests.analysis.helpers import path
from tests.golden.test_indicators import DAILY, INTRA


@pytest.mark.parametrize(
    ("series", "market"), [(DAILY, Market.IN), (INTRA, Market.IN)], ids=["daily", "5m"]
)
def test_report_is_complete_and_json_safe(series: BarSeries, market: Market) -> None:
    r = analyze(series, market, "RELIANCE")
    text = json.dumps(r, allow_nan=False)  # no NaN/inf can reach the browser
    assert len(text) < 40_000
    assert -100 <= r["score"] <= 100
    assert r["bias"] in ("bullish", "bearish", "neutral")
    assert r["summary"] and r["summary"][-1].startswith("Overall:")
    assert set(r["components"]) == {
        "trend",
        "patterns",
        "momentum",
        "levels",
        "volume",
        "divergence",
        "candles",
    }
    assert len(r["future"]) == 15 and r["future"][0] > r["as_of"]
    for z in r["zones"]:
        assert z["low"] <= z["center"] <= z["high"]
    for p in r["patterns"]:
        assert p["explanation"].startswith(p["name"])


def test_report_speed() -> None:
    # The chart toggle must feel instant: well under a second for 800 candles.
    s = DAILY.upto(800)
    start = time.perf_counter()
    for _ in range(3):
        analyze(s, Market.IN, "RELIANCE")
    assert (time.perf_counter() - start) / 3 < 0.25


def test_idea_has_a_sane_stop_and_target() -> None:
    r = analyze(path([(0, 100), (40, 140), (50, 132), (60, 150)]), Market.US, "UP")
    idea = r["idea"]
    assert r["bias"] == "bullish" and idea is not None
    assert idea["stop"] < idea["entry"] < idea["target"]
    if idea["quality"] != "poor":
        assert idea["reward_risk"] >= 1.5
    assert "not advice" in idea["text"] or "No good trade" in idea["text"]


def test_india_ideas_never_suggest_short_selling_delivery() -> None:
    r = analyze(path([(0, 150), (40, 110), (50, 118), (60, 100)]), Market.IN, "DOWN")
    if r["idea"] is not None:
        assert r["idea"]["action"] != "Sell short"


def test_future_times_skip_weekends() -> None:
    days = [datetime.fromtimestamp(t / 1000, UTC).weekday() for t in future_times(DAILY, 15)]
    assert all(d < 5 for d in days)
    intra = future_times(INTRA, 30)
    assert all(b > a for a, b in pairwise(intra))


def test_price_format() -> None:
    assert price(2640.5, Market.IN) == "₹2,640.50"
    assert price(-3.2, Market.US) == "−$3.20"


def test_too_short_history_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 30 candles"):
        analyze(DAILY.upto(10), Market.IN, "X")


def test_stats_are_attached_to_findings() -> None:
    def stats(key: str) -> dict[str, float] | None:
        return {"n": 40, "hit_rate": 0.6} if key.startswith("pattern:") else None

    s = path([(0, 100), (15, 120), (25, 110), (35, 120), (50, 95)])
    r = Analysis(s, Market.US, "X").report(stats)
    assert r["patterns"][0]["stats"] == {"n": 40, "hit_rate": 0.6}
