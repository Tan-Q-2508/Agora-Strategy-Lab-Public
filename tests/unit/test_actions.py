"""The one log of everything Agora does (D-220)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import actions
from backend.actions import ActionLog


def test_an_action_records_who_why_what_came_out_and_how_long(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "a.db")
    a = log.start("metis_round", "Round 1", who="metis", why="discovery", direction="new")
    a.done("3 ideas, 0 kept", kept=0)
    log.flush()
    row = log.search(kind="metis_round")[0]
    assert (row["who"], row["why"], row["status"]) == ("metis", "discovery", "ok")
    assert row["output"] == "3 ideas, 0 kept" and row["ms"] is not None
    assert row["detail"] == {"direction": "new", "kept": 0}
    log.close()


def test_an_exception_marks_the_action_failed(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "a.db")
    with pytest.raises(ValueError), log.start("study", "x"):
        raise ValueError("boom")
    log.flush()
    row = log.search()[0]
    assert row["status"] == "failed" and "boom" in row["output"]
    log.close()


def test_work_cut_off_by_a_stop_is_marked_at_the_next_start(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "a.db")
    log.start("study", "Never finishes")
    log.flush()
    log.close()
    again = ActionLog(tmp_path / "a.db")
    again.boot += 1
    again.close_unfinished()
    again.flush()
    assert again.search()[0]["status"] == "cut_off"
    again.close()


def test_a_research_run_beside_the_app_touches_nothing_of_the_apps(tmp_path: Path) -> None:
    app = ActionLog(tmp_path / "a.db")
    running = app.start("study", "the app's own work")
    app.flush()
    beside = ActionLog(tmp_path / "a.db")  # opened by a research run: it must not close anything
    beside.start("metis_idea", "a research idea").done("tested")
    beside.flush()
    app.flush()
    rows = {r["what"]: r["status"] for r in app.search()}
    assert rows == {"the app's own work": "running", "a research idea": "ok"}
    assert running.id != 0
    beside.close()
    app.close()


def test_a_wrong_output_can_be_judged_later(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "a.db")
    a = log.start("forecast", "Up tomorrow")
    a.done("up")
    a.judge(False, "it fell")
    log.flush()
    row = log.search()[0]
    assert row["status"] == "wrong" and row["correct"] is False and row["correct_why"] == "it fell"
    log.close()


def test_search_and_summary(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "a.db")
    log.start("ai_call", "Asked gemma").done("fine")
    log.start("ai_call", "Asked gemma").failed("no answer")
    log.start("study", "India 1h").done("done")
    log.flush()
    assert len(log.search(q="gemma")) == 2
    assert len(log.search(q="no answer")) == 1
    assert len(log.search(status="failed")) == 1
    s = {r["kind"]: r for r in log.summary(0)}
    assert s["ai_call"]["n"] == 2 and s["ai_call"]["failed"] == 1
    log.close()


def test_with_no_log_open_the_work_still_runs(tmp_path: Path) -> None:
    assert actions.current() is None
    with actions.track("x", "y") as a:
        a.done("fine")
    actions.note("x", "y")
