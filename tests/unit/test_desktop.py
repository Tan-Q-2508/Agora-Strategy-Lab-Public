"""Agora with no terminal window (D-124): its own window, the supervisor, the tray."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.desktop import supervisor as sv
from backend.desktop import tray, window
from backend.desktop.supervisor import HUNG_CHECKS, Supervisor

# ---------------------------------------------------------------- its own window


def test_the_first_chrome_or_edge_found_opens_an_app_window(tmp_path: Path) -> None:
    missing, edge = tmp_path / "chrome.exe", tmp_path / "msedge.exe"
    edge.write_text("")
    assert window.find_browser([missing, edge]) == edge
    spawned: list[Any] = []
    how = window.open_window(
        "http://localhost:8765",
        browser=edge,
        spawn=lambda cmd, **k: spawned.append(cmd),
        fallback=lambda u: pytest.fail("no tab"),
    )
    assert how == "app"
    assert spawned[0][:2] == [str(edge), "--app=http://localhost:8765"]


def test_without_chrome_or_edge_a_normal_tab_opens(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(window, "find_browser", lambda c=None: None)
    tabs: list[str] = []
    assert window.open_window("http://x", fallback=tabs.append) == "tab" and tabs == ["http://x"]


# ---------------------------------------------------------------- the supervisor


class Proc:
    def __init__(self) -> None:
        self.pid = 42
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code

    def kill(self) -> None:
        self.code = -9


class Http:
    def __init__(self) -> None:
        self.up = False
        self.posts: list[str] = []
        self.proc: Proc | None = None

    def get(self, url: str, timeout: float) -> Any:
        if not self.up:
            raise ConnectionError("down")
        return type("R", (), {"status_code": 200, "json": lambda self: {"tabs": 0}})()

    def post(self, url: str, timeout: float) -> Any:
        self.posts.append(url)
        self.up = False
        if self.proc is not None:
            self.proc.code = 0  # stops cleanly when asked


def _sup(tmp_path: Path, http: Http, procs: list[Proc]) -> sv.Supervisor:
    t = [0.0]

    def popen(cmd: list[str], **k: Any) -> Proc:
        p = Proc()
        procs.append(p)
        http.proc = p
        http.up = True  # the server answers once started
        return p

    def sleep(s: float) -> None:
        t[0] += s

    return sv.Supervisor(
        "http://127.0.0.1:8765",
        tmp_path / "server.log",
        command=["python", "-m", "backend.launch", "--no-browser"],
        popen=popen,
        http=http,
        sleep=sleep,
        clock=lambda: t[0],
    )


def test_it_starts_the_server_out_of_sight_and_stops_it_cleanly(tmp_path: Path) -> None:
    http, procs = Http(), []  # type: ignore[var-annotated]
    sup = _sup(tmp_path, http, procs)
    assert sup.start() and len(procs) == 1 and not sup.attached
    assert sup.tick() == "ok"
    sup.stop()
    assert http.posts == ["http://127.0.0.1:8765/api/system/quit"] and procs[0].code == 0
    assert sup.tick() == "stopped"  # a stop on purpose isn't restarted


def test_it_takes_charge_of_an_agora_already_running(tmp_path: Path) -> None:
    http, procs = Http(), []  # type: ignore[var-annotated]
    http.up = True
    sup = _sup(tmp_path, http, procs)
    assert sup.start() and sup.attached and procs == []


def test_a_crashed_server_is_restarted_but_not_forever(tmp_path: Path) -> None:
    http, procs = Http(), []  # type: ignore[var-annotated]
    sup = _sup(tmp_path, http, procs)
    sup.start()
    results = []
    for _ in range(sv.MAX_RESTARTS_PER_HOUR + 1):
        procs[-1].code = 1  # it crashed
        http.up = False
        results.append(sup.tick())
    assert results == ["restarted"] * sv.MAX_RESTARTS_PER_HOUR + ["gave_up"]


def test_the_server_runs_windowless_on_windows() -> None:
    cmd = sv.server_command()
    assert cmd[1:] == ["-m", "backend.launch", "--no-browser"]


# ---------------------------------------------------------------- the tray


def test_the_icon_is_the_agora_logo() -> None:
    img = tray.draw_icon(64)
    assert img.size == (64, 64)
    assert img.getpixel((32, 2))[:3] == (0x1F, 0x1D, 0x1A)  # the dark square


def test_only_one_tray_runs() -> None:
    first = tray.claim_single_instance()
    if first is None:
        pytest.skip("a real Agora tray is running on this computer")
    try:
        assert tray.claim_single_instance() is None
    finally:
        first.close()


class FakeSup:
    def __init__(self, tabs: int) -> None:
        self._tabs = tabs
        self.ticks = 0

    def start(self) -> bool:
        return True

    def tabs(self) -> int:
        return self._tabs

    def tick(self) -> str:
        self.ticks += 1
        return "ok"


@pytest.mark.parametrize(("tabs", "opened"), [(0, 1), (1, 0)])
def test_the_window_opens_unless_one_reconnects(monkeypatch: Any, tabs: int, opened: int) -> None:
    monkeypatch.setattr(tray, "TAB_WAIT_S", 0.5)
    monkeypatch.setattr(tray, "TICK_S", 0.01)
    windows: list[str] = []
    monkeypatch.setattr(tray, "open_window", windows.append)
    t = tray.Tray(FakeSup(tabs), "logs")  # type: ignore[arg-type]
    import threading

    th = threading.Thread(target=t._watch, daemon=True)
    th.start()
    th.join(2.0)  # the watch loop keeps going; stop it
    t._stop.set()
    th.join(1.0)
    assert len(windows) == opened


def test_stop_agora_route_is_local_only(client: Any) -> None:
    r = client.post("/api/system/quit")
    assert r.status_code == 200 and r.json() == {"stopping": False}  # no server object in tests


def test_the_launchers_start_modules_that_exist() -> None:
    """A typo here fails silently: pythonw has no window to show the error in."""
    import importlib.util
    import re

    root = Path(__file__).resolve().parents[2]
    for name in ("Start Agora.bat", "Start Agora.command"):
        text = (root / name).read_text(encoding="utf-8")
        modules = re.findall(r"-m (backend[\w.]*)", text)
        assert "backend.desktop.tray" in modules, name
        for m in modules:
            assert importlib.util.find_spec(m) is not None, (name, m)


class _Alive:
    pid = 1

    def poll(self) -> None:
        return None


def test_a_frozen_server_is_ended_and_started_again(tmp_path: Any) -> None:
    # D-218: alive isn't working. The tray used to look only at the process, so a frozen server
    # would have run on, answering nobody.
    started = []

    class Quiet:
        def get(self, *_a: Any, **_k: Any) -> Any:
            raise OSError("no answer")

    def popen(*_a: Any, **_k: Any) -> Any:
        started.append(1)
        return _Alive()

    sup = Supervisor(
        "http://x", tmp_path / "s.log", popen=popen, http=Quiet(), sleep=lambda _s: None
    )
    sup.proc = _Alive()
    killed = []
    sup._kill = lambda: killed.append(1)  # type: ignore[method-assign]
    sup.wait_healthy = lambda timeout=0: True  # type: ignore[method-assign]
    assert [sup.tick() for _ in range(HUNG_CHECKS - 1)] == ["ok"] * (HUNG_CHECKS - 1)
    assert sup.tick() == "restarted"
    assert killed == [1] and started == [1]


def test_a_busy_server_that_answers_again_is_left_alone(tmp_path: Any) -> None:
    answers = iter([False] * (HUNG_CHECKS - 1) + [True] + [False] * 3)

    class Slow:
        status_code = 200

        def get(self, *_a: Any, **_k: Any) -> Any:
            if not next(answers):
                raise OSError("busy")
            return self

    sup = Supervisor("http://x", tmp_path / "s.log", http=Slow(), sleep=lambda _s: None)
    sup.proc = _Alive()
    assert all(sup.tick() == "ok" for _ in range(HUNG_CHECKS + 3))
