"""The launcher's decisions: free port, Agora already running, or another program."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend import launch


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve(body: bytes) -> Iterator[int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield int(server.server_address[1])
    server.shutdown()
    server.server_close()


@pytest.fixture
def agora_port() -> Iterator[int]:
    yield from _serve(b'{"app": "agora", "status": "ok"}')


@pytest.fixture
def other_port() -> Iterator[int]:
    yield from _serve(b'{"hello": "world"}')


def test_free_port() -> None:
    assert launch.check_port("127.0.0.1", _free_port()) is launch.PortState.FREE


def test_agora_already_running(agora_port: int) -> None:
    assert launch.check_port("127.0.0.1", agora_port) is launch.PortState.AGORA


def test_other_program_on_port(other_port: int) -> None:
    assert launch.check_port("127.0.0.1", other_port) is launch.PortState.OTHER


def test_main_exits_with_plain_message_when_port_taken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(launch, "check_port", lambda: launch.PortState.OTHER)
    assert launch.main(["--no-browser"]) == 2
    assert "Another program is using Agora's port" in capsys.readouterr().out


def test_main_just_opens_browser_when_already_running(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launch, "check_port", lambda: launch.PortState.AGORA)
    monkeypatch.setattr(launch, "open_window", opened.append)
    monkeypatch.setattr(launch, "open_tabs", lambda base: 0)
    assert launch.main([]) == 0
    assert opened == [launch.URL]
    assert "already running" in capsys.readouterr().out
    monkeypatch.setattr(launch, "open_tabs", lambda base: 1)  # a tab is open: no new one (D-111)
    assert launch.main([]) == 0
    assert opened == [launch.URL]
    assert "open in your browser" in capsys.readouterr().out


def test_main_starts_server_after_migrating(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: list[bool] = []
    configs: list[object] = []

    class FakeServer:
        def __init__(self, config: object) -> None:
            configs.append(config)

        def run(self) -> None:
            started.append(True)

    monkeypatch.setattr(launch, "check_port", lambda: launch.PortState.FREE)
    monkeypatch.setattr(launch.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(launch, "_open_when_ready", lambda open_browser: None)
    assert launch.main(["--no-browser"]) == 0
    assert started == [True]
    # an open window or a long request can't keep a stopping server alive (D-134)
    assert getattr(configs[0], "timeout_graceful_shutdown", None) == launch.SHUTDOWN_GRACE_S
    assert launch.get_paths().db_file.exists()
    assert "Agora has stopped." in capsys.readouterr().out


def test_wait_until_healthy(agora_port: int) -> None:
    assert launch.wait_until_healthy(f"http://127.0.0.1:{agora_port}", timeout_s=5)
    assert not launch.wait_until_healthy(f"http://127.0.0.1:{_free_port()}", timeout_s=0.5)


def test_the_launcher_reuses_a_tab_that_reconnects() -> None:
    """D-111: an open tab that reconnects means no new tab; none means open one."""
    for body, expected in (
        (b'{"tabs": 1, "boot_id": 5}', True),
        (b'{"tabs": 0, "boot_id": 5}', False),
    ):
        gen = _serve(body)
        port = next(gen)
        try:
            assert launch.tab_reconnects(f"http://127.0.0.1:{port}", wait_s=0.6) is expected
        finally:
            next(gen, None)


def test_a_busy_background_thread_doesnt_keep_agora_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-127: after the server stops, a still-running job thread gets a short grace, then the
    process ends anyway so the tray can start the new server."""
    import threading
    import time

    from backend import launch

    exits: list[int] = []
    monkeypatch.setattr(launch.os, "_exit", exits.append)
    monkeypatch.setattr(launch.logging, "shutdown", lambda: None)
    release = threading.Event()
    busy = threading.Thread(target=release.wait, name="agora-job-test")  # not a daemon
    busy.start()
    try:
        started = time.monotonic()
        launch.exit_after_stop(0, grace_s=0.3)
        waited = time.monotonic() - started
    finally:
        release.set()
        busy.join()
    assert exits == [0]
    assert 0.3 <= waited < 3.0
