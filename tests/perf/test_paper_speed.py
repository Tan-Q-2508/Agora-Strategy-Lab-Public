"""Paper trading stays quick per candle, and long sessions don't slow down (SPEC §11)."""

from __future__ import annotations

import time

from backend.context import AppContext
from backend.paper import runner as runner_mod
from tests.paper.test_replay import make_version, start


def test_intraday_session_tick_is_fast_and_memory_is_bounded(ctx: AppContext, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(runner_mod, "KEEP_BARS", 300)
    monkeypatch.setattr(runner_mod, "TRIM_SLACK", 50)
    vid = make_version(ctx, "opening_range_breakout", "IN", ["RELIANCE", "INFY", "TCS", "SBIN"])
    r = start(ctx, vid)
    t0 = time.perf_counter()
    steps = 400
    for _ in range(steps):
        assert r.replay_step()
    per_tick = (time.perf_counter() - t0) / steps
    assert per_tick < 0.25, f"{per_tick:.3f} s per candle"
    assert r.engine is not None
    assert all(len(st.raw) <= 300 + 50 for st in r.engine.symbols)
    assert all(st.last_index == len(st.raw) - 1 for st in r.engine.symbols)
