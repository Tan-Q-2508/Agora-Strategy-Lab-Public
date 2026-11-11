"""The heartbeat: a stop nobody saw is written down by the next start (D-218)."""

from __future__ import annotations

from pathlib import Path

from backend.uptime import GAP_S, Uptime


class Clock:
    now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make(tmp_path: Path, clock: Clock) -> Uptime:
    (tmp_path / "logs").mkdir(exist_ok=True)
    return Uptime(tmp_path, clock)


def test_a_clean_stop_records_nothing(tmp_path: Path) -> None:
    clock = Clock()
    u = make(tmp_path, clock)
    u.start()
    u.shutdown()
    clock.now += 5000
    v = make(tmp_path, clock)
    v.start()
    v.shutdown()
    assert v.outages() == []


def test_a_stop_nobody_saw_is_written_down_by_the_next_start(tmp_path: Path) -> None:
    clock = Clock()
    u = make(tmp_path, clock)
    u.start()  # no shutdown: Windows ended it (6 Nov)
    clock.now += 2400
    v = make(tmp_path, clock)
    v.start()
    v.shutdown()
    out = v.outages()
    assert [(e["kind"], e["minutes"]) for e in out] == [("stopped_unseen", 40)]


def test_a_long_gap_between_beats_is_a_sleep_or_a_freeze(tmp_path: Path) -> None:
    clock = Clock()
    u = make(tmp_path, clock)
    u.start()
    clock.now += GAP_S + 60
    u.beat()
    clock.now += 30
    u.beat()
    u.shutdown()
    assert [e["kind"] for e in u.outages()] == ["gap"]


def test_a_damaged_heartbeat_file_does_not_stop_a_start(tmp_path: Path) -> None:
    clock = Clock()
    (tmp_path / "heartbeat.json").write_text("{half", encoding="utf-8")
    u = make(tmp_path, clock)
    u.start()
    u.shutdown()
    assert u.outages() == []
