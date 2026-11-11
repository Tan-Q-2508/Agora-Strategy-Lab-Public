"""A clock that only moves when told to, for tests and fast replays."""

from __future__ import annotations


class FakeClock:
    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def set(self, ms: int) -> None:
        if ms < self._now:
            raise ValueError("FakeClock cannot move backwards.")
        self._now = ms

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("FakeClock cannot move backwards.")
        self._now += ms
