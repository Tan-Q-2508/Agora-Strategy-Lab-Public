"""Long-running jobs (data downloads, backtests, model pulls) on background threads.

Each job gets a ``JobContext`` to report progress and to check for cancellation. Progress
is pushed over the WebSocket (``job.progress``) and readable with ``GET /api/jobs/{id}``,
so the UI stays responsive (SPEC §6.1). Jobs live only in memory: the things they produce
(candles, backtest runs) are saved in the database as they go.
"""

from __future__ import annotations

import itertools
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from backend import actions
from backend.errors import AgoraError
from backend.events import EventBus
from backend.logging_setup import get_logger

log = get_logger("jobs")
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: JobStatus = "queued"
    pct: float = 0.0
    message: str = "Waiting to start…"
    eta_s: float | None = None
    result: Any = None
    error: dict[str, str] | None = None
    key: str | None = None  # what the job is about ("strategy:12"), so a screen can find it again
    created: float = field(default_factory=time.monotonic)
    created_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)
    started: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "title": self.title,
            "key": self.key,
            "created_at": self.created_ms,
            "status": self.status,
            "pct": round(self.pct, 1),
            "eta_s": None if self.eta_s is None else round(self.eta_s),
            "message": self.message,
            "result": self.result,
            "error": self.error,
        }


class JobContext:
    def __init__(self, job: Job, manager: JobManager) -> None:
        self._job = job
        self._mgr = manager
        self._last_push = 0.0

    @property
    def cancel_event(self) -> threading.Event:
        return self._job.cancel_event

    @property
    def cancelled(self) -> bool:
        return self._job.cancel_event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise JobCancelled()

    def progress(self, pct: float, message: str | None = None) -> None:
        job = self._job
        job.pct = max(0.0, min(100.0, pct))
        if message is not None:
            job.message = message
        if job.started is not None and 1.0 < job.pct < 100.0:
            elapsed = time.monotonic() - job.started
            job.eta_s = elapsed * (100.0 - job.pct) / job.pct
        now = time.monotonic()
        if now - self._last_push >= 0.25 or job.pct >= 100.0:  # don't flood the socket
            self._last_push = now
            self._mgr.events.publish("job.progress", job.public())


JobFn = Callable[[JobContext], Any]
# Jobs that mostly wait on the network get their own lanes, so an hour-long download never
# holds a number-crunching slot (D-115).
IO_KINDS = {"data_refresh", "ai_pull", "live_test"}


class JobManager:
    """Three lanes: number crunching (``workers``), downloads (``io_workers``), and one for
    what Kairos starts while the user is chatting (``priority=True``), so a chat never waits
    behind sweeps, scans and downloads (D-115)."""

    def __init__(self, events: EventBus, workers: int = 3, io_workers: int = 3) -> None:
        self.events = events
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="agora-job")
        self._io = ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="agora-io")
        self._chat = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agora-chat")
        self._jobs: dict[str, Job] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        title: str,
        fn: JobFn,
        *,
        job_id: str | None = None,
        key: str | None = None,
        priority: bool = False,
        single: bool = False,
    ) -> Job:
        """``single``: if the same kind of job (with the same ``key``) is already queued or
        running, return that one instead of starting a copy: a second click on "Scan now" or
        "Learn now" joins the first (D-116)."""
        with self._lock:
            if single:
                for other in self._jobs.values():
                    if (
                        other.kind == kind
                        and other.key == key
                        and other.status in ("queued", "running")
                    ):
                        return other
            jid = job_id or f"{kind}-{next(self._ids)}"
            job = Job(id=jid, kind=kind, title=title, key=key)
            self._jobs[jid] = job
            self._prune()
        lane = self._chat if priority else self._io if kind in IO_KINDS else self._pool
        lane.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: JobFn) -> None:
        if job.cancel_event.is_set():
            job.status, job.message = "cancelled", "Cancelled."
            self.events.publish("job.failed", job.public())
            return
        job.status, job.started, job.message = "running", time.monotonic(), "Starting…"
        ctx = JobContext(job, self)
        act = actions.track(job.kind, job.title, why=f"job {job.id}")
        self.events.publish("job.progress", job.public())
        try:
            job.result = fn(ctx)
            job.status, job.pct, job.eta_s = "done", 100.0, 0
            if job.message in ("Starting…", ""):
                job.message = "Done."
            act.done(job.message)
            self.events.publish("job.done", job.public())
        except JobCancelled:
            job.status, job.message = "cancelled", "Cancelled."
            act.skipped("Cancelled.")
            self.events.publish("job.failed", job.public())
        except AgoraError as exc:
            job.status = "failed"
            job.error = {
                "code": exc.code,
                "message": exc.message,
                "action": exc.action,
                "detail": exc.detail,
            }
            job.message = exc.message
            act.failed(exc.message, code=exc.code, detail=exc.detail)
            self.events.publish("job.failed", job.public())
        except Exception as exc:
            log.exception("Job %s failed", job.id)
            job.status = "failed"
            job.error = {
                "code": "JOB_FAILED",
                "message": f"{job.title} stopped because of an unexpected problem.",
                "action": "Try again. If it keeps happening, create a support bundle in "
                "Settings → Diagnostics.",
                "detail": "".join(traceback.format_exception_only(type(exc), exc)).strip(),
            }
            job.message = job.error["message"]
            act.failed(job.error["detail"])
            self.events.publish("job.failed", job.public())

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(
        self, kind: str | None = None, *, active: bool = False, key: str | None = None
    ) -> list[Job]:
        """Newest first. ``active`` keeps queued and running jobs: a screen that was left while
        its job ran uses it to show the progress again when it is opened (the user's request
        2026-10-24, D-107)."""
        kinds = set(kind.split(",")) if kind else None
        out = [
            j
            for j in list(self._jobs.values())
            if (kinds is None or j.kind in kinds)
            and (not active or j.status in ("queued", "running"))
            and (key is None or j.key == key)
        ]
        return sorted(out, key=lambda j: j.created, reverse=True)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status in ("done", "failed", "cancelled"):
            return False
        job.cancel_event.set()
        return True

    def _prune(self, keep: int = 200) -> None:
        finished = [j for j in self._jobs.values() if j.status in ("done", "failed", "cancelled")]
        for j in sorted(finished, key=lambda j: j.created)[:-keep]:
            self._jobs.pop(j.id, None)

    def shutdown(self) -> None:
        for job in self._jobs.values():
            job.cancel_event.set()
        for lane in (self._pool, self._io, self._chat):
            lane.shutdown(wait=False, cancel_futures=True)
