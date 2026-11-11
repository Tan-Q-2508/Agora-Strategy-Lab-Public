"""A Kairos study in its own process (D-148): progress and result pass through, a failure is
reported, and what Agora cached is forgotten so the new numbers are read."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.kairos import learning, study

CHILD = """
import sys
print("PROGRESS 10.0 Studying RELIANCE…", flush=True)
print("noise the job ignores", flush=True)
print("PROGRESS 100.0 Studied 2 stocks: 5 kinds of signal measured.", flush=True)
print('RESULT {"stocks": 2, "candles": 500, "signals": 5, "horizon": 10}', flush=True)
sys.exit(int(sys.argv[-1] == "1m"))
"""


def _child(tmp_path: Path) -> list[str]:
    f = tmp_path / "child.py"
    f.write_text(CHILD, encoding="utf-8")
    return [sys.executable, str(f)]


def test_a_study_in_its_own_process_reports_progress_and_result(
    ctx: AppContext, tmp_path: Path
) -> None:
    svc = ctx.learning
    svc.study_command = _child(tmp_path)
    svc._judges[("IN", "1d")] = None  # cached before the study
    v = svc.version
    seen: list[tuple[float, str]] = []
    out = svc.train_separately(Market.IN, Timeframe.D1, lambda p, t: seen.append((p, t)))
    assert out == {"stocks": 2, "candles": 500, "signals": 5, "horizon": 10}
    assert seen == [
        (10.0, "Studying RELIANCE…"),
        (100.0, "Studied 2 stocks: 5 kinds of signal measured."),
    ]
    assert ("IN", "1d") not in svc._judges and svc.version > v


def test_a_failed_study_process_is_an_error(ctx: AppContext, tmp_path: Path) -> None:
    ctx.learning.study_command = _child(tmp_path)
    with pytest.raises(RuntimeError, match="code 1"):
        ctx.learning.train_separately(Market.IN, Timeframe.M1)


def test_the_child_command_runs_the_study(
    ctx: AppContext, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_train(m: Market, tf: Timeframe, say: object) -> dict[str, int]:
        calls.append((m.value, tf.value))
        say(50.0, "Studying TCS…")  # type: ignore[operator]
        return {"stocks": 1}

    ctx.learning.train = fake_train  # type: ignore[method-assign]
    assert study.main(["US", "1h"], ctx=ctx) == 0
    out = capsys.readouterr().out.splitlines()
    assert calls == [("US", "1h")]
    assert out == ["PROGRESS 50.0 Studying TCS…", 'RESULT {"stocks": 1}']
    assert study.main(["US"], ctx=ctx) == 2


def test_a_windowless_python_starts_the_console_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pythonw.exe").write_text("")
    (tmp_path / "python.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert learning._python() == str(tmp_path / "python.exe")


def test_studies_wait_for_a_free_slot(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-164: at most ``MAX_STUDIES`` study processes at once, so the laptop stays cool."""
    import threading
    import time

    f = tmp_path / "slow.py"
    f.write_text(
        "import time, sys\ntime.sleep(0.6)\nprint('RESULT {}', flush=True)\n", encoding="utf-8"
    )
    ctx.learning.study_command = [sys.executable, str(f)]
    monkeypatch.setattr(learning, "STUDY_SLOTS", threading.BoundedSemaphore(1))
    waited: list[str] = []
    t0 = time.monotonic()
    jobs = [
        threading.Thread(
            target=ctx.learning.train_separately,
            args=(Market.IN, Timeframe.D1, lambda _p, msg: waited.append(msg)),
        )
        for _ in range(2)
    ]
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()
    assert time.monotonic() - t0 >= 1.1  # one after the other, not side by side
    assert "Waiting for a free study slot…" in waited
