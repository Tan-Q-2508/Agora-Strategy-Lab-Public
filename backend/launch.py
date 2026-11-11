"""What the double-click launchers run once Python is ready (docs/RUNBOOK.md §1, D-19).

The .bat/.command files only install uv and dependencies; everything else lives here, in
one cross-platform, testable place: check the port, update the database, start the
server, open the browser when it answers, and print plain-English status lines.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
from enum import Enum

import httpx
import uvicorn

from backend.config import HOST, PORT, get_paths
from backend.desktop.window import open_window
from backend.logging_setup import get_logger, setup_logging

log = get_logger("launch")
URL = f"http://localhost:{PORT}"
EXIT_GRACE_S = 10.0  # background work gets this long to finish after the server stops
# open connections (an Agora window, a long request) get this long to finish once a stop is asked
# for; without it the server waited for them forever and never stopped (D-134)
SHUTDOWN_GRACE_S = 10
TAB_WAIT_S = 12.0  # an open tab retries every 3 s (longer when Chrome has it in the background)


_server: uvicorn.Server | None = None


def request_stop() -> bool:
    """Ask the running server to shut down cleanly (the tray's Stop and Restart, D-124):
    paper sessions save their state and background work ends as when the window is closed."""
    if _server is None:
        return False
    _server.should_exit = True
    return True


class PortState(Enum):
    FREE = "free"
    AGORA = "agora"  # Agora is already running: just open the browser
    OTHER = "other"  # some other program has the port


def say(message: str) -> None:
    print(message, flush=True)
    log.info("launcher: %s", message)


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def is_agora(base_url: str, timeout: float = 2.0) -> bool:
    try:
        response = httpx.get(f"{base_url}/api/health", timeout=timeout)
        return response.status_code == 200 and response.json().get("app") == "agora"
    except (httpx.HTTPError, ValueError):
        return False


def check_port(host: str = HOST, port: int = PORT) -> PortState:
    if not port_in_use(host, port):
        return PortState.FREE
    return PortState.AGORA if is_agora(f"http://{host}:{port}") else PortState.OTHER


def wait_until_healthy(base_url: str, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_agora(base_url, timeout=1.0):
            return True
        time.sleep(0.25)
    return False


def open_tabs(base_url: str, timeout: float = 1.0) -> int:
    try:
        response = httpx.get(f"{base_url}/api/tabs", timeout=timeout)
        return int(response.json().get("tabs", 0)) if response.status_code == 200 else 0
    except (httpx.HTTPError, ValueError):
        return 0


def tab_reconnects(base_url: str, wait_s: float = TAB_WAIT_S) -> bool:
    """Does an Agora tab that was already open reconnect within ``wait_s``? Open tabs retry
    every few seconds while Agora is down, then reload themselves (D-111)."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if open_tabs(base_url) > 0:
            return True
        time.sleep(0.5)
    return False


def _open_when_ready(open_browser: bool) -> None:
    base = f"http://{HOST}:{PORT}"
    if wait_until_healthy(base):
        if open_browser:
            if tab_reconnects(base):
                say("Your open Agora tab reconnected; no new tab needed.")
            else:
                open_window(URL)
        say("")
        say(f"Agora is running at {URL}")
        say("Close this window to stop Agora.")
    else:
        say("Agora is taking unusually long to start. Details are in data/logs/agora.log")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start Agora")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args(argv)

    paths = get_paths()
    paths.ensure()
    setup_logging(paths.logs_dir)

    state = check_port()
    if state is PortState.AGORA:
        if open_tabs(f"http://{HOST}:{PORT}") > 0:
            say("Agora is already running and open in your browser.")
        else:
            say("Agora is already running. Opening it in your browser.")
            if not args.no_browser:
                open_window(URL)
        return 0
    if state is PortState.OTHER:
        say(
            "Another program is using Agora's port (8765). "
            "Restart your computer or close that program, then start Agora again."
        )
        return 2

    say("Updating Agora's database...")
    try:
        from backend.db.migrate import upgrade_and_seed

        upgrade_and_seed(paths=paths).engine.dispose()
    except Exception:
        log.exception("Database update failed")
        say(
            "Agora couldn't open its database: the file may be damaged. Nothing was changed. "
            "Your backups are in data/backups, and the details are in data/logs/agora.log."
        )
        return 3

    say("Starting Agora...")
    threading.Thread(target=_open_when_ready, args=(not args.no_browser,), daemon=True).start()
    config = uvicorn.Config(
        "backend.main:create_app",
        factory=True,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
        timeout_graceful_shutdown=SHUTDOWN_GRACE_S,
    )
    server = uvicorn.Server(config)
    # Run as ``python -m backend.launch`` this module is ``__main__``; the quit route imports
    # ``backend.launch``, a second copy. Register the server on that one (D-124).
    from backend import launch as registry

    registry._server = server
    server.run()  # returns after Ctrl+C, the window closing, or request_stop()
    say("Agora has stopped.")
    return 0


def busy_threads() -> list[threading.Thread]:
    """Threads that would keep Python from exiting (thread-pool workers are joined at exit)."""
    me = threading.current_thread()
    return [t for t in threading.enumerate() if t is not me and not t.daemon and t.is_alive()]


def exit_after_stop(code: int, grace_s: float = EXIT_GRACE_S) -> None:
    """End the process once the server has stopped (D-127). A Metis round or a price download
    running on a job thread would otherwise keep Python alive until it finished, minutes later,
    and the tray would not start the new server meanwhile. Everything that must be saved was
    saved when the server stopped; an unfinished round is simply run again next time."""
    deadline = time.monotonic() + grace_s
    while busy_threads() and time.monotonic() < deadline:
        time.sleep(0.2)
    left = busy_threads()
    if left:
        log.info("Ending %d unfinished background task(s): %s", len(left), [t.name for t in left])
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    exit_after_stop(main())
