from __future__ import annotations

import threading
import time

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import store
from backend.data.accumulator import IntradayAccumulator
from backend.errors import AgoraError
from backend.events import EventBus
from backend.fakes.data_source import FakeSource
from backend.jobs import JobContext, JobManager


def _wait(mgr: JobManager, jid: str) -> str:
    for _ in range(500):
        job = mgr.get(jid)
        assert job is not None
        if job.status in ("done", "failed", "cancelled"):
            return job.status
        time.sleep(0.01)
    raise AssertionError("job stuck")


def test_job_lifecycle_progress_cancel_and_errors() -> None:
    mgr = JobManager(EventBus())

    def ok(job: JobContext) -> int:
        job.progress(50, "half")
        return 7

    j = mgr.submit("t", "Test", ok)
    assert _wait(mgr, j.id) == "done" and j.result == 7 and j.pct == 100

    gate = threading.Event()

    def slow(job: JobContext) -> None:
        gate.wait(5)
        job.check()

    j2 = mgr.submit("t", "Slow", slow)
    assert mgr.cancel(j2.id)
    gate.set()
    assert _wait(mgr, j2.id) == "cancelled"

    def plain(job: JobContext) -> None:
        raise AgoraError("X", "Plain words.", "Do this.")

    j3 = mgr.submit("t", "Plain", plain)
    assert _wait(mgr, j3.id) == "failed" and j3.error and j3.error["message"] == "Plain words."

    def boom(job: JobContext) -> None:
        raise RuntimeError("bug")

    j4 = mgr.submit("t", "Boom", boom)
    assert _wait(mgr, j4.id) == "failed"
    assert j4.error and "unexpected" in j4.error["message"] and "RuntimeError" in j4.error["detail"]
    mgr.shutdown()


def test_accumulator_saves_once_per_closed_session(
    ctx: AppContext, fake_source: FakeSource
) -> None:
    acc = IntradayAccumulator(ctx.db, ctx.cache, ctx.calendar)
    saved = acc.run_once()
    assert saved > 0
    with ctx.db.session() as s:
        aapl = store.find_instrument(s, Market.US, "AAPL")
        assert aapl is not None
        stored = store.stored_ts(s, aapl.id, Timeframe.M5, 0, 2**62)
    window = ctx.clock.now_ms() - 59 * 86_400_000
    fixture = [b for b in fake_source._all("AAPL", Timeframe.M5) if b.ts >= window]
    assert sorted(stored) == [b.ts for b in fixture]
    assert acc.run_once() == 0  # same session: nothing to do
    assert set(acc.done_for) == {Market.IN, Market.US}


def test_a_chat_job_doesnt_wait_behind_busy_lanes() -> None:
    """D-115: downloads and chat jobs have their own lanes."""
    import threading

    from backend.events import EventBus
    from backend.jobs import JobManager

    mgr = JobManager(EventBus(), workers=1, io_workers=1)
    gate = threading.Event()
    mgr.submit("backtest", "long sweep", lambda jc: gate.wait(10))
    mgr.submit("data_refresh", "all prices", lambda jc: gate.wait(10))
    quick = mgr.submit("backtest", "Kairos's backtest", lambda jc: "done", priority=True)
    dl = mgr.submit("ai_pull", "model", lambda jc: "queued behind the download")
    assert _wait(mgr, quick.id) == "done"
    assert mgr.get(dl.id).status == "queued"  # same lane as the long download
    gate.set()
    assert _wait(mgr, dl.id) == "done"
    mgr.shutdown()


def test_a_second_click_joins_the_running_task() -> None:
    """D-116: ``single`` jobs of the same kind and key aren't started twice."""
    import threading

    from backend.events import EventBus
    from backend.jobs import JobManager

    mgr = JobManager(EventBus())
    gate = threading.Event()
    a = mgr.submit("world_learn", "Learn", lambda jc: gate.wait(10), single=True)
    b = mgr.submit("world_learn", "Learn", lambda jc: gate.wait(10), single=True)
    c = mgr.submit("kairos_train", "IN", lambda jc: gate.wait(10), key="IN:1d", single=True)
    d = mgr.submit("kairos_train", "US", lambda jc: gate.wait(10), key="US:1d", single=True)
    assert a.id == b.id and c.id != d.id
    gate.set()
    assert _wait(mgr, a.id) == "done"
    e = mgr.submit("world_learn", "Learn", lambda jc: 1, single=True)
    assert e.id != a.id  # finished: a new click starts a new one
    mgr.shutdown()
