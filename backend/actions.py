"""One log of everything Agora does (WEEKEND_BRIEF §8, D-220).

The user: "if there is an action in Agora then there must be a log of that, to diagnose if the
initiation, process and output were correct or not." Every entry answers: who or what started it
and why, what it did, what came out, whether that was right, and how long it took.

It lives in its own small database, ``data/actions.db``, not in ``agora.db``: the log must keep
working when the main database is locked or damaged, which is when it matters most, and it must
not add writes to a database that trading depends on. Writing never blocks the caller and never
raises: a queue and one thread do the work, because a log must not be able to stop a trade.

Use ``track`` around work, or ``note`` for something that happened at once::

    with actions.track("metis_round", "Metis round 412", who="metis", why="discovery") as a:
        ...
        a.done("3 ideas tested, 0 kept", tested=3, kept=0)

An exception leaving the block marks the action failed. Reading is ``search`` and ``summary``; the
same data is on the Logs page, and a Claude session can read it with ``scripts/actions.py``.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from backend.logging_setup import get_logger

log = get_logger("actions")

KEEP_DAYS = 90
STATUSES = ("running", "ok", "failed", "skipped", "wrong", "cut_off")

SCHEMA = """
create table if not exists actions (
    id integer primary key,
    boot integer not null,
    started_at integer not null,
    ended_at integer,
    ms integer,
    kind text not null,
    what text not null,
    who text not null default 'system',
    why text not null default '',
    status text not null default 'running',
    output text not null default '',
    correct integer,
    correct_why text not null default '',
    detail text not null default '{}'
);
create index if not exists actions_started on actions(started_at);
create index if not exists actions_kind on actions(kind, started_at);
create index if not exists actions_status on actions(status, started_at);
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


class Action:
    """One piece of work under way."""

    def __init__(self, store: ActionLog | None, aid: int, started: int) -> None:
        self.store = store
        self.id = aid
        self.started = started
        self.finished = False

    def done(self, output: str = "", *, status: str = "ok", **detail: Any) -> None:
        if self.finished:
            return
        self.finished = True
        if self.store is not None:
            self.store._finish(self, status, output, detail)

    def failed(self, output: str, **detail: Any) -> None:
        self.done(output, status="failed", **detail)

    def skipped(self, output: str, **detail: Any) -> None:
        self.done(output, status="skipped", **detail)

    def judge(self, correct: bool, why: str = "") -> None:
        """Say whether the output was right (a check, or later evidence such as a forecast)."""
        if self.store is not None:
            self.store.judge(self.id, correct, why)

    def __enter__(self) -> Action:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if exc is not None:
            self.failed(f"{kind.__name__ if kind else 'Error'}: {exc}"[:500])
        else:
            self.done()


_opened = itertools.count()


class ActionLog:
    def __init__(self, file: Path, clock_ms: Callable[[], int] = _now_ms) -> None:
        self.file = file
        self.clock = clock_ms
        self.boot = clock_ms()
        # several processes write here (research runs beside the app), so each numbers its own:
        # seconds since 2024, then the process, then a counter
        who = (os.getpid() + next(_opened)) % 1000
        base = (self.boot // 1000 - 1_704_067_200) * 10**10 + who * 10**7
        self._ids = itertools.count(base + 1)
        self._queue: queue.Queue[tuple[str, tuple[Any, ...]] | None] = queue.Queue(maxsize=100_000)
        self._closed = threading.Event()
        file.parent.mkdir(parents=True, exist_ok=True)
        c = self._connect()
        c.executescript(SCHEMA)
        c.execute("delete from actions where started_at < ?", (self.boot - KEEP_DAYS * 86_400_000,))
        c.commit()
        c.close()
        self._writer = threading.Thread(target=self._write_loop, name="agora-actions", daemon=True)
        self._writer.start()

    def close_unfinished(self) -> None:
        """Agora itself is starting: whatever was running when it last ended never finished.
        Only the app does this; a research run beside it would cut off the app's own work."""
        self._put(
            "update actions set status='cut_off', ended_at=?, "
            "output='Agora stopped before this finished' where status='running' and boot < ?",
            (self.boot, self.boot),
        )

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.file, timeout=10)
        c.execute("pragma journal_mode=wal")
        c.execute("pragma synchronous=normal")
        return c

    # ------------------------------------------------------------ writing

    def _put(self, sql: str, args: tuple[Any, ...]) -> None:
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait((sql, args))

    def _write_loop(self) -> None:
        c = self._connect()
        while True:
            item = self._queue.get()
            if item is None:
                break
            batch = [item]
            with contextlib.suppress(queue.Empty):
                while len(batch) < 500:
                    nxt = self._queue.get_nowait()
                    if nxt is None:
                        self._closed.set()
                        break
                    batch.append(nxt)
            try:
                for sql, args in batch:
                    c.execute(sql, args)
                c.commit()
            except sqlite3.Error:
                log.warning("Couldn't write %d log entries", len(batch), exc_info=True)
            if self._closed.is_set():
                break
        c.close()

    def start(
        self, kind: str, what: str, *, who: str = "system", why: str = "", **detail: Any
    ) -> Action:
        aid = next(self._ids)
        now = self.clock()
        self._put(
            "insert into actions (id, boot, started_at, kind, what, who, why, detail) "
            "values (?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, self.boot, now, kind, what[:500], who, why[:500], _json(detail)),
        )
        return Action(self, aid, now)

    def _finish(self, a: Action, status: str, output: str, detail: dict[str, Any]) -> None:
        now = self.clock()
        self._put(
            "update actions set ended_at=?, ms=?, status=?, output=?, "
            "detail=case when ?='{}' then detail else json_patch(detail, ?) end where id=?",
            (now, now - a.started, status, output[:2000], _json(detail), _json(detail), a.id),
        )

    def judge(self, aid: int, correct: bool, why: str = "") -> None:
        self._put(
            "update actions set correct=?, correct_why=?, "
            "status=case when ?=0 and status='ok' then 'wrong' else status end where id=?",
            (int(correct), why[:500], int(correct), aid),
        )

    def close(self) -> None:
        self._queue.put(None)
        self._writer.join(timeout=5)

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until what has been written so far is saved (tests and the diagnosis)."""
        end = time.time() + timeout
        while not self._queue.empty() and time.time() < end:
            time.sleep(0.01)
        time.sleep(0.05)

    # ------------------------------------------------------------ reading

    def _read(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.file, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def search(
        self,
        q: str = "",
        kind: str = "",
        status: str = "",
        who: str = "",
        since_ms: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        where, args = ["started_at >= ?"], [since_ms]  # type: list[str], list[Any]
        if q:
            like = f"%{q}%"
            where.append("(what like ? or why like ? or output like ? or detail like ?)")
            args += [like, like, like, like]
        for col, val in (("kind", kind), ("status", status), ("who", who)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = f"select * from actions where {' and '.join(where)} order by id desc limit ?"
        c = self._read()
        try:
            rows = c.execute(sql, [*args, min(limit, 5000)]).fetchall()
        finally:
            c.close()
        return [_row(r) for r in rows]

    def summary(self, since_ms: int) -> list[dict[str, Any]]:
        """For each kind of work: how much, how much failed, what is stuck, the last time."""
        c = self._read()
        try:
            rows = c.execute(
                """select kind, count(*) n,
                          sum(status='ok') ok, sum(status='failed') failed,
                          sum(status='wrong') wrong, sum(status='cut_off') cut_off,
                          sum(status='running') running, sum(status='skipped') skipped,
                          avg(ms) avg_ms, max(ms) max_ms, max(started_at) last_at
                   from actions where started_at >= ? group by kind order by n desc""",
                (since_ms,),
            ).fetchall()
        finally:
            c.close()
        return [dict(r) for r in rows]


def _json(detail: dict[str, Any]) -> str:
    try:
        return json.dumps(detail, default=str)
    except (TypeError, ValueError):
        return "{}"


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["detail"] = json.loads(d.get("detail") or "{}")
    except ValueError:
        d["detail"] = {}
    d["correct"] = None if d["correct"] is None else bool(d["correct"])
    return d


# ---------------------------------------------------------------- the one log of the running app

_log: ActionLog | None = None


def open_log(file: Path) -> ActionLog:
    global _log
    _log = ActionLog(file)
    return _log


def close_log() -> None:
    global _log
    if _log is not None:
        _log.close()
    _log = None


def current() -> ActionLog | None:
    return _log


def track(kind: str, what: str, *, who: str = "system", why: str = "", **detail: Any) -> Action:
    """Start an action; with no log open (tests) it does nothing, cheaply."""
    if _log is None:
        return Action(None, 0, 0)
    try:
        return _log.start(kind, what, who=who, why=why, **detail)
    except Exception:  # a log must never stop the work it is logging
        return Action(None, 0, 0)


def note(
    kind: str,
    what: str,
    output: str = "",
    *,
    who: str = "system",
    why: str = "",
    status: str = "ok",
    **detail: Any,
) -> Action:
    """Something that happened at once."""
    a = track(kind, what, who=who, why=why, **detail)
    a.done(output, status=status)
    return a
