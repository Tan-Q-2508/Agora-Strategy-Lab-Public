"""The fake implementations behave like the real interfaces promise (no look-ahead!)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.ai_provider import AIProvider, ChatMessage
from backend.core.clock import Clock, SystemClock, ms_to_utc, utc_to_ms
from backend.core.data_source import DataSource
from backend.core.types import Market, Timeframe
from backend.fakes.ai_provider import DEFAULT_REPLY, FakeAIProvider
from backend.fakes.clock import FakeClock
from backend.fakes.data_source import FakeSource

FAR_FUTURE = utc_to_ms(datetime(2030, 1, 1, tzinfo=UTC))


def _dt(ms: int) -> datetime:
    return ms_to_utc(ms)


def test_protocols_are_satisfied() -> None:
    clock: Clock = FakeClock()
    source: DataSource = FakeSource(clock)
    ai: AIProvider = FakeAIProvider()
    real: Clock = SystemClock()
    assert source.name == "fake" and ai.status().state == "ready" and real.now_ms() > 0


def test_fake_clock_moves_forward_only() -> None:
    c = FakeClock(1000)
    c.advance(500)
    assert c.now_ms() == 1500
    c.set(2000)
    with pytest.raises(ValueError):
        c.set(10)
    with pytest.raises(ValueError):
        c.advance(-1)


def test_naive_datetimes_rejected() -> None:
    with pytest.raises(ValueError):
        utc_to_ms(datetime(2024, 1, 1))


def test_supports() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    assert src.supports(Market.IN, Timeframe.D1)
    assert src.supports(Market.US, Timeframe.M5)
    assert not src.supports(Market.US, Timeframe.M15)


def test_fetch_bars_range_and_aliases() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 2, 1, tzinfo=UTC)
    bars = src.fetch_bars("RELIANCE.NS", Timeframe.D1, start, end)
    assert bars == src.fetch_bars("RELIANCE", Timeframe.D1, start, end)
    assert 18 <= len(bars) <= 23
    assert all(utc_to_ms(start) <= b.ts < utc_to_ms(end) for b in bars)
    assert all(b.source == "fake" and b.is_final for b in bars)


def test_unknown_symbol() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    with pytest.raises(KeyError):
        src.fetch_bars("NOPE", Timeframe.D1, _dt(0), _dt(FAR_FUTURE))


def test_unsupported_timeframe_is_empty() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    assert src.fetch_bars("TCS", Timeframe.M5, _dt(0), _dt(FAR_FUTURE)) == []


def test_never_returns_the_future() -> None:
    all_bars = FakeSource(FakeClock(FAR_FUTURE)).fetch_bars(
        "AAPL", Timeframe.M5, _dt(0), _dt(FAR_FUTURE)
    )
    mid = all_bars[100]
    # 2 minutes into bar #100: it has started but not closed.
    clock = FakeClock(mid.ts + 120_000)
    src = FakeSource(clock)
    final = src.fetch_bars("AAPL", Timeframe.M5, _dt(0), _dt(FAR_FUTURE))
    assert final[-1] == all_bars[99]
    latest = src.latest_bars(["AAPL"], Timeframe.M5)["AAPL"]
    forming = latest[-1]
    assert forming.ts == mid.ts and not forming.is_final
    assert forming.close == mid.open  # nothing about the future leaks into a forming bar
    clock.set(mid.ts + 300_000)  # bar #100 has closed and bar #101 has just opened
    latest = src.latest_bars(["AAPL"], Timeframe.M5)["AAPL"]
    assert latest[-2] == mid and latest[-1].ts == all_bars[101].ts


def test_daily_bar_final_only_after_session_close() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    day = src.fetch_bars("TCS", Timeframe.D1, _dt(0), _dt(FAR_FUTURE))[-1]
    close = src.bar_end_ms("TCS", Timeframe.D1, day.ts)
    assert close - day.ts == (6 * 60 + 15) * 60_000  # 09:15 → 15:30 IST
    src.clock = FakeClock(close - 1)
    assert src.latest_bars(["TCS"], Timeframe.D1)["TCS"][-1].is_final is False
    src.clock = FakeClock(close)
    assert src.latest_bars(["TCS"], Timeframe.D1)["TCS"][-1].is_final is True


def test_early_close_bar_end() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    start = datetime(2025, 11, 28, tzinfo=UTC)
    day = src.fetch_bars("SPY", Timeframe.D1, start, _dt(FAR_FUTURE))[0]
    assert src.bar_end_ms("SPY", Timeframe.D1, day.ts) - day.ts == 210 * 60_000  # 09:30→13:00


def test_last_hourly_bar_is_cut_at_close() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    bars = src.fetch_bars("RELIANCE", Timeframe.H1, _dt(0), _dt(FAR_FUTURE))
    last = bars[-1]  # 15:15 IST bar
    assert src.bar_end_ms("RELIANCE", Timeframe.H1, last.ts) - last.ts == 15 * 60_000


def test_corporate_actions_respect_clock() -> None:
    src = FakeSource(FakeClock(FAR_FUTURE))
    acts = src.fetch_corporate_actions("NVDA")
    assert [(a.kind, a.ratio) for a in acts] == [("split", 4.0)]
    src.clock = FakeClock(acts[0].ex_date - 1)
    assert src.fetch_corporate_actions("NVDA") == []


def test_fake_ai_scripted_replies_and_streaming() -> None:
    ai = FakeAIProvider(replies=["first reply", '{"ok": true}'])
    msgs = [ChatMessage("user", "hi")]
    assert "".join(ai.chat(msgs, model="m")) == "first reply"
    assert ai.chat(msgs, model="m", stream=False, format={"type": "object"}) == '{"ok": true}'
    assert ai.chat(msgs, model="m", stream=False) == DEFAULT_REPLY
    assert ai.calls[1]["format"] == {"type": "object"}


def test_fake_ai_states_and_pull() -> None:
    ai = FakeAIProvider(state="model_missing", models=[])
    with pytest.raises(RuntimeError):
        ai.chat([ChatMessage("user", "hi")], model="qwen3.5:4b")
    steps = list(ai.pull("qwen3.5:4b"))
    assert steps[-1].status == "success"
    assert ai.status().state == "ready" and "qwen3.5:4b" in ai.status().models
    assert FakeAIProvider(state="not_installed").status().version is None
