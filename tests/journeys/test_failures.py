"""What happens when things go wrong (WEEKEND_BRIEF §3). One test per failure the other suites
don't already cover; `docs/DIAGNOSIS.md` maps every journey to its test."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend import actions, launch
from backend.actions import ActionLog
from backend.strategy.templates import template_definition
from backend.uptime import Uptime


def test_a_damaged_database_stops_the_start_with_a_plain_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AGORA_DATA_DIR", str(tmp_path))
    (tmp_path / "agora.db").write_bytes(b"this is not a database" * 500)
    said: list[str] = []
    monkeypatch.setattr(launch, "say", said.append)
    monkeypatch.setattr(launch, "check_port", lambda: launch.PortState.FREE)
    assert launch.main(["--no-browser"]) == 3
    assert any("damaged" in x for x in said), said


def test_a_full_disk_does_not_stop_the_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = Uptime(tmp_path)

    def full(*_a: Any, **_k: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", full)
    u.started_at = 1.0
    u.beat()  # must not raise
    u.shutdown()


def test_the_action_log_survives_its_file_going_away(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "a.db")
    log.start("x", "fine").done("ok")
    log.flush()
    log.close()
    a = log.start("x", "after the writer ended")  # nothing to write to: quietly dropped
    a.done("still no error")


def test_work_in_flight_when_the_app_is_killed_shows_as_cut_off(tmp_path: Path) -> None:
    first = ActionLog(tmp_path / "a.db")
    first.start("metis_round", "Round")
    first.flush()  # killed here: no finish was ever written
    again = ActionLog(tmp_path / "a.db")
    again.boot += 1
    again.close_unfinished()
    again.flush()
    assert [r["status"] for r in again.search()] == ["cut_off"]
    again.close()
    first.close()


def test_a_log_call_can_never_break_the_work(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def start(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("the log is broken")

    monkeypatch.setattr(actions, "_log", Broken())
    with actions.track("x", "y") as a:
        a.done("the work carried on")


def test_a_combined_strategy_has_no_look_ahead() -> None:
    from backend.core.types import Timeframe
    from backend.data.adjust import adjusted
    from backend.fakes.data_source import FakeSource
    from backend.strategy import lookahead as la
    from backend.strategy.definition import CombinedDefinition

    class Forever:
        def now_ms(self) -> int:
            return 2**62

    src = FakeSource(Forever())  # type: ignore[arg-type]
    bars = tuple(adjusted(b) for b in src._all("RELIANCE", Timeframe.D1))
    a = template_definition("ma_crossover", "IN", ["RELIANCE"])
    b = template_definition("rsi_mean_reversion", "IN", ["RELIANCE"])
    d = CombinedDefinition.model_validate(
        {
            **{
                k: getattr(a, k).model_dump()
                if hasattr(getattr(a, k), "model_dump")
                else getattr(a, k)
                for k in ("market", "universe", "sizing", "limits", "timeframe", "product")
            },
            "combine": {"mode": "any"},
            "members": [
                {"name": "a", "definition": a.model_dump(mode="json")},
                {"name": "b", "definition": b.model_dump(mode="json")},
            ],
        }
    )
    r = la.check(d, [la.SymbolBars("RELIANCE", bars, normal_from=300, start=600)], max_steps=6_000)
    assert r["verdict"] == "clean", r
