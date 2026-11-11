"""The look-ahead check (D-88): templates pass, a leaky indicator and history-dependent code are
caught, shift() can't look forward, and the check runs end to end through the API."""

from __future__ import annotations

import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.types import Bar, Market, Timeframe
from backend.data.adjust import adjusted
from backend.fakes.data_source import FakeSource
from backend.indicators import catalog
from backend.indicators.series import BarSeries, from_bars
from backend.strategy import lookahead as la
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import CodeDefinition
from backend.strategy.sandbox import SandboxError
from backend.strategy.signals import trace
from backend.strategy.templates import TEMPLATES, template_definition


class _Forever:
    def now_ms(self) -> int:
        return 2**62


SRC = FakeSource(_Forever())  # type: ignore[arg-type]
DAILY = sorted(k for k, t in TEMPLATES.items() if t.timeframe == "1d")


@lru_cache(maxsize=8)
def _bars(symbol: str) -> tuple[Bar, ...]:
    return tuple(adjusted(b) for b in SRC._all(symbol, Timeframe.D1))


def data(
    *symbols: str, normal_from: int = 300, start: int = 600, upto: int | None = None
) -> list[la.SymbolBars]:
    return [
        la.SymbolBars(s, _bars(s)[:upto], normal_from=normal_from, start=start) for s in symbols
    ]


def code_def(body: str) -> CodeDefinition:
    base = template_definition("ma_crossover", "IN", ["RELIANCE"])
    return CodeDefinition(
        market=base.market,
        universe=base.universe,
        timeframe=base.timeframe,
        product=base.product,
        sizing=base.sizing,
        limits=base.limits,
        code=body,
    )


@pytest.mark.parametrize("key", DAILY)
def test_every_daily_template_passes(key: str) -> None:
    d = template_definition(key, "IN", ["RELIANCE", "TCS"])
    r = la.check(d, data("RELIANCE", "TCS"), max_steps=12_000)
    assert r["verdict"] == "clean", (key, r["lookahead"]["findings"], r["history"]["findings"])
    assert r["lookahead"]["slices"] >= 4 and r["lookahead"]["indicators_checked"] > 0
    assert r["history"]["extra_candles"] == 300


def test_a_leaky_indicator_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """An SMA that secretly uses tomorrow's value: the signals and the indicator differ once
    later candles are hidden."""
    real = catalog.compute

    def leaky(
        key: str, series: BarSeries, params: Mapping[str, float], source: Any
    ) -> dict[str, Any]:
        out = real(key, series, params, source)
        if key != "sma":
            return out
        shifted = {}
        for name, arr in out.items():
            s = np.full_like(arr, np.nan)
            s[:-1] = arr[1:]
            shifted[name] = s
        return shifted

    monkeypatch.setattr(catalog, "compute", leaky)
    d = template_definition("ma_crossover", "IN", ["RELIANCE"])
    r = la.check(d, data("RELIANCE"), max_steps=20_000)
    assert r["verdict"] == "lookahead"
    kinds = {f["kind"] for f in r["lookahead"]["findings"]}
    assert kinds == {"signal", "indicator"}
    assert any(x.startswith("SMA (") for x in r["lookahead"]["leaky_indicators"])
    assert "hadn't closed" in r["title"]
    sig = next(f for f in r["lookahead"]["findings"] if f["kind"] == "signal")
    assert sig["text"].startswith("RELIANCE, ") and "with them hidden" in sig["text"]


def test_rules_that_depend_on_history_length_are_caught() -> None:
    """An average of 'all prices so far' changes with how much history is loaded."""
    d = code_def(
        "import statistics\n"
        "def on_bar(ctx):\n"
        "    m = statistics.mean(ctx.close.to_list())\n"
        "    if ctx.close[-1] > m * 1.05 and not ctx.position:\n"
        "        ctx.buy()\n"
        "    elif ctx.close[-1] < m and ctx.position:\n"
        "        ctx.sell_all()\n"
    )
    r = la.check(d, data("RELIANCE", start=450, upto=800), max_steps=1_500)
    assert r["verdict"] == "history", r
    assert r["history"]["findings"][0]["text"].startswith("RELIANCE, ")
    assert "ctx.close.to_list()" in r["text"]


def test_fixed_window_code_passes() -> None:
    d = code_def(
        "def on_bar(ctx):\n"
        "    fast = ctx.ind.sma(ctx.close, 10)\n"
        "    slow = ctx.ind.sma(ctx.close, 30)\n"
        "    if ctx.crosses_above(fast, slow):\n"
        "        ctx.buy()\n"
        "    elif ctx.crosses_below(fast, slow):\n"
        "        ctx.sell_all()\n"
    )
    r = la.check(d, data("INFY"), max_steps=4_000)
    assert r["verdict"] == "clean" and r["signals"] > 3


def test_shift_cannot_look_forward() -> None:
    d = code_def(
        "def on_bar(ctx):\n    if ctx.close.shift(-1)[-1] > ctx.close[-1]:\n        ctx.buy()\n"
    )
    series = from_bars(list(_bars("RELIANCE")[:50]), Timeframe.D1, Market.IN)
    with pytest.raises(SandboxError) as err:
        trace(compile_definition(d), series, Market.IN, "RELIANCE")
    assert err.value.line == 2 and "only looks back" in err.value.message
    ok = code_def("def on_bar(ctx):\n    if ctx.close.shift(2)[-1] > 0:\n        ctx.buy()\n")
    assert trace(compile_definition(ok), series, Market.IN, "RELIANCE")


def test_slices_cover_signals_and_spread_within_budget() -> None:
    cuts = la._pick_slices([120, 130, 500, 999], 100, 1000, budget=10_000)
    assert {120, 130, 500} <= set(cuts) and 999 not in cuts
    assert min(cuts) == 100 and all(100 <= c < 999 for c in cuts)
    small = la._pick_slices(list(range(100, 999, 3)), 100, 1000, budget=2_000)
    assert 4 <= len(small) <= 8
    assert la._pick_slices([], 50, 50, budget=1000) == []


def test_indicator_labels_read_plainly() -> None:
    assert la.indicator_label("sma", {"period": 20}, None, "value") == "SMA (20)"
    assert la.indicator_label("adx", {"period": 14}, None, "plus_di") == "ADX (14) +DI"
    assert la.indicator_label("ema", {"period": 50}, "high", "value") == "EMA (50) of high"


def wait_job(client: TestClient, job_id: str, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_check_through_the_api(client: TestClient) -> None:
    r = client.post(
        "/api/strategies",
        json={"name": "Check me", "market": "IN", "template_key": "rsi_mean_reversion"},
    )
    sid = r.json()["strategy"]["id"]
    job = client.post(
        f"/api/strategies/{sid}/lookahead", json={"symbols": ["RELIANCE", "TCS"]}
    ).json()["job_id"]
    j = wait_job(client, job)
    assert j["status"] == "done", j
    res = j["result"]
    assert res["verdict"] == "clean" and res["version"] == 1
    assert res["result"]["symbols"] == ["RELIANCE", "TCS"]
    listed = client.get(f"/api/strategies/{sid}/checks", params={"kind": "lookahead"}).json()
    assert listed["checks"][0]["id"] == res["id"] and listed["checks"][0]["version"] == 1
    assert client.get("/api/strategies/9999/checks").status_code == 404
    assert client.post("/api/strategies/9999/lookahead", json={}).status_code == 404


def test_a_ranking_passes() -> None:
    from backend.strategy.ranking import ranking_definition

    d = ranking_definition("momentum_fast", "IN", ["RELIANCE", "TCS", "INFY", "ITC", "SBIN", "LT"])
    r = la.check(d, data("RELIANCE", "TCS", normal_from=200, start=400), max_steps=6_000)
    assert r["verdict"] == "clean", r
