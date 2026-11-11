"""The clock interface.

Everything that needs "now" asks a ``Clock`` instead of calling ``time.time()`` directly,
so backtests, replays and tests can run on simulated time (D-04).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int:
        """Current time as UTC epoch milliseconds."""
        ...


class SystemClock:
    """Wall-clock time; used when Agora runs for real on the laptop."""

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def ms_to_dt(ms: float, tz: tzinfo | None = UTC) -> datetime:
    """Epoch milliseconds as an aware datetime in ``tz``.

    Why not ``datetime.fromtimestamp``: on Windows it raises ``OSError [Errno 22]`` for times
    before 1970, and Yahoo's dividend history for old US stocks goes back to the 1960s.
    """
    return (_EPOCH + timedelta(milliseconds=ms)).astimezone(tz)  # None = the laptop's own zone


def ms_to_utc(ms: int) -> datetime:
    return ms_to_dt(ms, UTC)


def utc_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("Naive datetimes are ambiguous; pass a timezone-aware datetime.")
    return int(dt.timestamp() * 1000)
