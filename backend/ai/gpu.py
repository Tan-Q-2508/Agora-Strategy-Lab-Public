"""Keep the AI helper on the graphics card (D-101, the user's request 2026-10-24).

On the user's laptop (RTX 3060 Laptop + AMD integrated graphics) Ollama sometimes starts
before the NVIDIA card has woken up. It then finds only the processor, runs every answer
several times slower, and keeps doing so until Ollama is restarted: its server log says
``inference compute … library=cpu`` and ``total_vram="0 B"``. A fresh start finds the card
(``library=CUDA``).

While Agora is open this guard checks, a little after Agora starts and then every few
minutes: is there an NVIDIA card (``nvidia-smi -L``), and did the running Ollama miss it
(its latest start in the server log found no graphics card, or a loaded model sits 0% on
the card)? If so, and nothing is talking to the AI right now, it quits Ollama and starts it
again (at most twice per Agora run), then loads the model once so the first real question
is fast. Setting ``ai.fix_gpu`` switches it off. It only touches Ollama on this computer
(``localhost``); everything it does goes in the log.

It also keeps Ollama running (the user's request 2026-10-24, D-108): whenever Agora is open,
the AI helper is on and Ollama is installed but not answering, it starts Ollama (Windows and
macOS), at most once every few minutes, and loads the model so Kairos and Metis can think.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from backend.ai.ollama import direct
from backend.logging_setup import get_logger
from backend.settings_store import read_all

log = get_logger("ai.gpu")
FIRST_WAIT_S = 15.0
FIRST_START_WAIT_S = 2.0  # starting a stopped Ollama shouldn't wait for the graphics check
CHECK_S = 60.0
GPU_EVERY_S = 300.0
START_EVERY_S = 300.0
MAX_RESTARTS = 2
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flashes up on Windows


def nvidia_present(run: Callable[..., Any] = subprocess.run) -> bool:
    """Is an NVIDIA graphics card visible to its driver?"""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return False
    try:
        out = run(
            [exe, "-L"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "GPU" in (out.stdout or "")


def server_log() -> Path | None:
    if sys.platform != "win32":
        return None
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "Ollama" / "server.log" if local else None


def log_says_cpu_only(text: str) -> bool | None:
    """From Ollama's server log: did its latest start find only the processor?
    None when the log doesn't say (yet)."""
    starts = [m.start() for m in re.finditer(r'msg="Listening on', text)]
    tail = text[starts[-1] :] if starts else text
    found = re.findall(r'msg="inference compute".*?library=(\S+)', tail)
    if not found:
        return None
    return all(lib.strip('"').lower() == "cpu" for lib in found)


def _localhost(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "[::1]"))


class GpuGuard:
    def __init__(
        self,
        ctx: Any,
        *,
        has_nvidia: Callable[[], bool] = nvidia_present,
        read_log: Callable[[], str | None] | None = None,
        restart: Callable[[], bool] | None = None,
        launch: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ctx = ctx
        self._has_nvidia = has_nvidia
        self._read_log = read_log or self._default_log
        self._restart = restart or self._restart_ollama
        self._launch = launch or self._launch_ollama
        self._sleep = sleep
        self._mono = monotonic
        self._last_start: float | None = None
        self._last_gpu: float | None = None
        self._born = monotonic()
        self.starts = 0
        self.last_start: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.restarts = 0
        self.last: dict[str, Any] = {}
        self._nvidia: bool | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if sys.platform not in ("win32", "darwin") or self.ctx.data_mode != "real":
            return  # the cloud and tests have no Ollama to look after
        self._thread = threading.Thread(target=self._loop, name="ai-gpu", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        if self._stop.wait(FIRST_START_WAIT_S):
            return
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # the optional helper must never take the app down
                log.exception("Ollama check failed")
            if self._stop.wait(CHECK_S):
                return

    def tick(self) -> dict[str, Any]:
        """Every minute: start Ollama if it stopped; every five, the graphics-card check
        (Windows only: Macs use Metal)."""
        started = self.keep_running()
        now = self._mono()
        if (
            sys.platform == "win32"
            and started.get("action") != "started"
            and (self._last_gpu is None or now - self._last_gpu >= GPU_EVERY_S)
        ):
            if self._last_gpu is None and now - self._born < FIRST_WAIT_S:
                return started  # let Ollama settle before judging where it runs
            self._last_gpu = now
            return self.check()
        return started

    # ------------------------------------------------------------ keep Ollama running

    def keep_running(self) -> dict[str, Any]:
        cfg = self._settings_any()
        out: dict[str, Any] = {"at": self.ctx.clock.now_ms(), "action": "none"}
        if not cfg["enabled"] or not _localhost(cfg["url"]):
            out["why"] = "off"
            return out
        state = self.ctx.ai_service.status(fresh=True).get("state")
        if state != "not_running":
            out["why"] = f"Ollama is {state}"
            return out
        now = self._mono()
        if self._last_start is not None and now - self._last_start < START_EVERY_S:
            out["why"] = "Ollama isn't running; tried to start it a moment ago"
            return out
        self._last_start = now
        self.starts += 1
        log.warning("Ollama isn't running; starting it (Agora keeps it on, D-108)")
        ok = self._launch()
        out["action"] = "started" if ok else "start failed"
        if ok:
            self.ctx.ai_service.status(fresh=True)  # screens see "ready" straight away
            self.warm_up(cfg)
        else:
            log.warning("Couldn't start Ollama; will try again in %d min", START_EVERY_S // 60)
        self.last_start = out
        return out

    # ------------------------------------------------------------ the check

    def _settings(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            st = read_all(s)
        return {
            "on": bool(st["ai.fix_gpu"]) and bool(st["ai.enabled"]),
            "url": str(st["ai.base_url"]),
            "model": str(st["ai.model"]),
        }

    def _settings_any(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            st = read_all(s)
        return {
            "enabled": bool(st["ai.enabled"]),
            "url": str(st["ai.base_url"]),
            "model": str(st["ai.model"]),
        }

    def _default_log(self) -> str | None:
        path = server_log()
        if path is None or not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-400_000:]
        except OSError:
            return None

    def busy(self) -> bool:
        """Is anyone using the AI right now? A restart would cut their answer off."""
        metis = self.ctx.services.get("metis")
        kairos = self.ctx.services.get("kairos")
        return bool(getattr(metis, "working", False) or getattr(kairos, "active", 0))

    def nvidia(self) -> bool:
        if self._nvidia is None:
            self._nvidia = self._has_nvidia()
        return self._nvidia

    def on_cpu(self) -> bool:
        st = self.ctx.ai_service.status(fresh=True)
        if st.get("state") != "ready":
            return False
        runs = st.get("runs_on") or {}
        if runs.get("where") == "cpu":
            return True
        text = self._read_log()
        return bool(text and log_says_cpu_only(text))

    def check(self) -> dict[str, Any]:
        cfg = self._settings()
        out: dict[str, Any] = {"at": self.ctx.clock.now_ms(), "action": "none"}
        if not cfg["on"] or not _localhost(cfg["url"]):
            out["why"] = "off"
        elif not self.nvidia():
            out["why"] = "no NVIDIA card"
        elif not self.on_cpu():
            out["why"] = "on the graphics card (or not loaded yet)"
        elif self.restarts >= MAX_RESTARTS:
            out["why"] = "still on the processor after restarting Ollama twice"
        elif self.busy():
            out["why"] = "on the processor; waiting until the AI is idle to restart Ollama"
        else:
            self.restarts += 1
            log.warning(
                "Ollama runs on the processor although an NVIDIA card is present; "
                "restarting Ollama (try %d)",
                self.restarts,
            )
            ok = self._restart()
            out["action"] = "restarted" if ok else "restart failed"
            if ok:
                self.warm_up(cfg)
        self.last = out
        return out

    # ------------------------------------------------------------ Windows actions

    def _restart_ollama(self) -> bool:
        local = os.environ.get("LOCALAPPDATA", "")
        app = Path(local) / "Programs" / "Ollama" / "ollama app.exe"
        if not app.exists():
            log.warning("Can't restart Ollama: %s not found", app)
            return False
        for name in ("ollama app.exe", "ollama.exe"):
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                capture_output=True,
                timeout=30,
                creationflags=NO_WINDOW,
            )
        self._sleep(3)
        subprocess.Popen([str(app)], creationflags=NO_WINDOW, close_fds=True)
        url = direct(self._settings()["url"])
        for _ in range(60):
            self._sleep(2)
            try:
                if httpx.get(f"{url}/api/version", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                continue
        else:
            return False
        for _ in range(30):  # Ollama looks for graphics cards for up to ~25 s after it starts
            self._sleep(2)
            text = self._read_log()
            if text and log_says_cpu_only(text) is not None:
                return not log_says_cpu_only(text)
        return True

    def _launch_ollama(self) -> bool:
        """Start Ollama the way its own shortcut does, then wait until it answers."""
        if sys.platform == "darwin":
            cmd: list[str] | None = ["open", "-a", "Ollama"]
            flags = 0
        else:
            local = os.environ.get("LOCALAPPDATA", "")
            app = Path(local) / "Programs" / "Ollama" / "ollama app.exe"
            exe = shutil.which("ollama")
            cmd = [str(app)] if app.exists() else ([exe, "serve"] if exe else None)
            flags = NO_WINDOW
        if cmd is None:
            log.warning("Can't start Ollama: it isn't installed where Agora looks")
            return False
        try:
            subprocess.Popen(cmd, creationflags=flags, close_fds=True)
        except OSError as exc:
            log.warning("Can't start Ollama: %r", exc)
            return False
        url = direct(self._settings_any()["url"])
        for _ in range(60):
            self._sleep(2)
            try:
                if httpx.get(f"{url}/api/version", timeout=2).status_code == 200:
                    return True
            except httpx.HTTPError:
                continue
        return False

    def warm_up(self, cfg: dict[str, Any]) -> None:
        """Load the model once (the first load compiles graphics-card code and can take a
        minute or two) so the user's first question is quick."""
        try:
            httpx.post(
                f"{direct(cfg['url'])}/api/generate",
                json={"model": cfg["model"], "prompt": "", "keep_alive": "30m"},
                timeout=600,
            )
        except httpx.HTTPError as exc:
            log.info("Warm-up didn't finish: %r", exc)
