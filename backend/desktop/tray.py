"""Agora's tray icon: Agora with no terminal window (the user's request 2026-10-25, D-124).

``Start Agora`` runs this with ``pythonw`` (no console). It starts the server out of sight
(``supervisor.py``), opens Agora in its own window (``window.py``) unless a window that was already
open reconnects, and puts the Agora logo by the clock with a menu:

- **Open Agora** (also a double-click on the icon): a new Agora window.
- **Restart Agora**: stops the server cleanly and starts it again (new code, a fresh start).
- **Open the log folder**: where ``agora.log`` and ``server.log`` are, for when something is wrong.
- **Stop Agora**: stops the server cleanly and removes the icon. Nothing runs after that (D-06).

A second double-click on Start Agora while the tray runs just opens a window (one tray only).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from backend.config import HOST, PORT, get_paths
from backend.desktop.supervisor import Supervisor
from backend.desktop.window import open_window
from backend.logging_setup import get_logger, setup_logging

log = get_logger("desktop.tray")
URL = f"http://localhost:{PORT}"
BASE = f"http://{HOST}:{PORT}"
SINGLE_PORT = PORT + 1  # held by the running tray, so a second one knows it isn't needed
TICK_S = 10.0
TAB_WAIT_S = 12.0


def draw_icon(size: int = 64) -> Any:
    """The Agora logo (frontend/public/favicon.svg) drawn with Pillow: a dark rounded square, a
    light "A" and the orange candle."""
    from PIL import Image, ImageDraw

    k = size / 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(7.5 * k), fill="#1F1D1A")
    d.line(
        [(7.6 * k, 25 * k), (16 * k, 6.6 * k), (24.4 * k, 25 * k)],
        fill="#FAF9F6",
        width=max(2, int(3.2 * k)),
        joint="curve",
    )
    d.line([(16 * k, 12 * k), (16 * k, 25 * k)], fill="#F07A3E", width=max(1, int(2 * k)))
    d.rounded_rectangle(
        (13.9 * k, 16.4 * k, 18.1 * k, 22.2 * k), radius=max(1, int(1 * k)), fill="#F07A3E"
    )
    return img


def claim_single_instance() -> socket.socket | None:
    """Hold a local port while this tray runs; ``None`` if another tray already holds it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return None
    return s


def desktop_dir() -> Path:
    """The Desktop Windows really shows (often in OneDrive, not the profile's own Desktop)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=0x08000000,
        ).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(os.environ.get("USERPROFILE", "")) / "Desktop"


def ensure_shortcut(root: Path, assets: Path) -> Path | None:
    """Windows: an "Agora" shortcut on the Desktop with the Agora logo, made once. It starts
    ``Start Agora.bat`` minimised, so even the short "getting ready" window stays out of sight.
    Deleting it is harmless; it isn't made again once made (a marker file remembers)."""
    if sys.platform != "win32":
        return None
    marker = assets / "shortcut-made"
    desktop = desktop_dir()
    link = desktop / "Agora.lnk"
    if marker.exists() or not desktop.is_dir():
        return None
    assets.mkdir(parents=True, exist_ok=True)
    ico = assets / "agora.ico"
    draw_icon(256).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    target = root / "Start Agora.bat"

    def q(p: Path) -> str:  # a PowerShell single-quoted string
        return "'" + str(p).replace("'", "''") + "'"

    script = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({q(link)});"
        f"$s.TargetPath={q(target)};$s.WorkingDirectory={q(root)};$s.IconLocation={q(ico)};"
        "$s.WindowStyle=7;$s.Description='Start Agora';$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=30,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.SubprocessError):
        log.info("Couldn't make the Desktop shortcut", exc_info=True)
        return None
    if not link.exists():
        log.info("The Desktop shortcut wasn't made")
        return None
    marker.write_text("made")
    return link


def open_folder(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class Tray:
    def __init__(self, sup: Supervisor, logs_dir: str) -> None:
        self.sup = sup
        self.logs_dir = logs_dir
        self.icon: Any = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ menu actions

    def open(self, *_: Any) -> None:
        open_window(URL)

    def restart(self, *_: Any) -> None:
        def work() -> None:
            self._title("Agora · restarting…")
            ok = self.sup.restart()
            self._title("Agora · running" if ok else "Agora · couldn't start (see the log)")
            if not ok:
                self._notify("Agora couldn't start again. Open the log folder for details.")

        threading.Thread(target=work, name="tray-restart", daemon=True).start()

    def show_logs(self, *_: Any) -> None:
        open_folder(self.logs_dir)

    def quit(self, *_: Any) -> None:
        # a stop someone asked for must say so (8 Nov: Agora stopped cleanly at 21:31 and no log
        # said who; only this menu stops the tray too)
        log.info("Stop Agora chosen from the tray")
        self._title("Agora · stopping…")
        self._stop.set()
        self.sup.stop()
        if self.icon is not None:
            self.icon.stop()

    # ------------------------------------------------------------ status

    def _title(self, text: str) -> None:
        if self.icon is not None:
            self.icon.title = text

    def _notify(self, text: str) -> None:
        try:
            if self.icon is not None:
                self.icon.notify(text, "Agora")
        except Exception:  # notifications are a nicety
            log.info("Tray notification failed", exc_info=True)

    def _watch(self) -> None:
        """Start the server, open the window, then keep an eye on it."""
        self._title("Agora · starting…")
        if not self.sup.start():
            self._title("Agora · couldn't start (see the log)")
            self._notify("Agora couldn't start. Open the log folder from this icon for details.")
        else:
            self._title("Agora · running")
            waited = 0.0
            while waited < TAB_WAIT_S and self.sup.tabs() == 0 and not self._stop.is_set():
                self._stop.wait(0.5)
                waited += 0.5
            if self.sup.tabs() == 0 and not self._stop.is_set():
                self.open()
        told = False
        while not self._stop.wait(TICK_S):
            state = self.sup.tick()
            if state == "restarted":
                self._notify("Agora stopped unexpectedly and was started again.")
            elif state == "gave_up":
                self._title("Agora · stopped (see the log)")
                if not told:  # once, not every ten seconds
                    told = True
                    self._notify("Agora stopped and won't start again. Open the log folder.")
            if state == "ok":
                told = False

    # ------------------------------------------------------------ run

    def run(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Open Agora", self.open, default=True),
            pystray.MenuItem("Restart Agora", self.restart),
            pystray.MenuItem("Open the log folder", self.show_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Stop Agora", self.quit),
        )
        self.icon = pystray.Icon("Agora", draw_icon(), "Agora · starting…", menu)
        threading.Thread(target=self._watch, name="tray-watch", daemon=True).start()
        self.icon.run()  # until Stop Agora


def main() -> int:
    paths = get_paths()
    paths.ensure()
    # its own file: the server rotates agora.log, which Windows refuses while another
    # process has it open (D-158)
    setup_logging(paths.logs_dir, name="tray.log")
    holder = claim_single_instance()
    if holder is None:  # a tray is already running: just show Agora
        log.info("The tray is already running; opening a window")
        open_window(URL)
        return 0
    sup = Supervisor(BASE, paths.logs_dir / "server.log")
    root = Path(__file__).resolve().parents[2]
    try:
        ensure_shortcut(root, paths.data_dir / "desktop")
    except Exception:  # a shortcut is a convenience; never stop Agora starting
        log.info("Desktop shortcut failed", exc_info=True)
    try:
        Tray(sup, str(paths.logs_dir)).run()
    finally:
        holder.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
