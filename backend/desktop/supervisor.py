"""Runs Agora's server out of sight for the tray icon (D-124).

The tray is a small process of its own; the server runs as a child process with no window
(``pythonw`` on Windows), its output going to ``data/logs/server.log``. A separate process means
**Restart** really loads new code, and a crash in the server can't take the tray with it: if the
server stops on its own, the supervisor starts it again (at most 3 times an hour, so a server
that can't start isn't restarted forever). A server that is alive but stops answering is treated the
same way after two minutes of silence (D-218). **Stop** asks the server to shut down cleanly first
(``POST /api/system/quit``) and only ends it by force if it hasn't stopped after 30 seconds.

If Agora is already running when the tray starts (an older window, a second double-click), the
tray takes charge of that one instead of starting another.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from backend.logging_setup import get_logger

log = get_logger("desktop.supervisor")
NO_WINDOW = 0x08000000
MAX_RESTARTS_PER_HOUR = 3
STOP_WAIT_S = 30.0
# silent for this many checks in a row (the tray checks every 10 s) = frozen, not just busy
HUNG_CHECKS = 12


def server_command() -> list[str]:
    """The same Python, windowless on Windows, running the launcher without opening a tab."""
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.name.lower() == "python.exe":
        windowless = exe.with_name("pythonw.exe")
        if windowless.exists():
            exe = windowless
    return [str(exe), "-m", "backend.launch", "--no-browser"]


class Supervisor:
    def __init__(
        self,
        base_url: str,
        log_path: Path,
        *,
        command: list[str] | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        http: Any = httpx,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base = base_url
        self.log_path = log_path
        self.command = command or server_command()
        self._popen = popen
        self._http = http
        self._sleep = sleep
        self._clock = clock
        self.proc: Any = None
        self.attached = False  # managing an Agora this tray didn't start
        self.stopping = False
        self._restarts: list[float] = []
        self._silent = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ asking the server

    def healthy(self) -> bool:
        try:
            r = self._http.get(f"{self.base}/api/tabs", timeout=2.0)
            return bool(r.status_code == 200)
        except Exception:
            return False

    def tabs(self) -> int:
        try:
            r = self._http.get(f"{self.base}/api/tabs", timeout=2.0)
            return int(r.json().get("tabs", 0)) if r.status_code == 200 else 0
        except Exception:
            return 0

    def wait_healthy(self, timeout: float = 120.0) -> bool:
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            if self.healthy():
                return True
            if self.proc is not None and self.proc.poll() is not None:
                return False  # the server stopped while starting
            self._sleep(0.5)
        return False

    # ------------------------------------------------------------ start, stop, restart

    def start(self) -> bool:
        """Start the server (or take charge of one already running) and wait until it answers."""
        with self._lock:
            self.stopping = False
            if self.healthy():
                self.attached = True
                log.info("Agora was already running; the tray takes charge of it")
                return True
            self.attached = False
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            out = self.log_path.open("ab")
            flags = NO_WINDOW if sys.platform == "win32" else 0
            self.proc = self._popen(
                self.command, stdout=out, stderr=subprocess.STDOUT, creationflags=flags
            )
            log.info("Started Agora's server (process %s)", getattr(self.proc, "pid", "?"))
        return self.wait_healthy()

    def stop(self) -> None:
        """Shut the server down cleanly; by force only if it doesn't stop in time."""
        with self._lock:
            self.stopping = True
            with contextlib.suppress(Exception):
                self._http.post(f"{self.base}/api/system/quit", timeout=5.0)
            deadline = self._clock() + STOP_WAIT_S
            while self._clock() < deadline:
                if self.proc is not None:
                    if self.proc.poll() is not None:
                        break
                elif not self.healthy():
                    break
                self._sleep(0.5)
            else:
                log.warning("Agora's server didn't stop in time; ending it")
                self._kill()
            self.proc = None
            self.attached = False

    def _kill(self) -> None:
        if self.proc is None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                capture_output=True,
                creationflags=NO_WINDOW,
            )
        else:
            self.proc.kill()

    def restart(self) -> bool:
        self.stop()
        return self.start()

    # ------------------------------------------------------------ keeping it running

    def tick(self) -> str:
        """Called every few seconds by the tray: "ok", "restarted", "gave_up" or "stopped"."""
        if self.stopping:
            return "stopped"
        alive = self.proc.poll() is None if self.proc is not None else self.healthy()
        if alive and self.proc is not None:
            # alive isn't working: a frozen server kept running and answered nobody (D-218)
            self._silent = 0 if self.healthy() else self._silent + 1
            alive = self._silent < HUNG_CHECKS
        if alive:
            return "ok"
        now = self._clock()
        self._restarts = [t for t in self._restarts if now - t < 3600]
        if len(self._restarts) >= MAX_RESTARTS_PER_HOUR:
            return "gave_up"
        self._restarts.append(now)
        self._silent = 0
        if self.proc is not None and self.proc.poll() is None:
            log.warning("Agora's server stopped answering; ending it and starting it again")
            self._kill()
        else:
            log.warning("Agora's server stopped on its own; starting it again")
        self.proc = None
        return "restarted" if self.start() else "gave_up"
