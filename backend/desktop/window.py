"""Agora in its own window: no tabs, no address bar (the user's request 2026-10-25, D-124).

Chrome and Edge open any page as an "app window" with ``--app=<url>``: a plain window with
Agora's icon and title, like a desktop program, while it is still the same local web app
underneath (nothing to install, updates as before). Chrome is tried first (the user's
browser), then Edge (always on Windows); without either, the normal browser opens a tab.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flashes up on Windows


def _windows_candidates() -> list[Path]:
    out: list[Path] = []
    for base in (
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        if base:
            out.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for base in (
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
    ):
        out.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return out


MAC_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
]


def find_browser(candidates: Sequence[Path] | None = None) -> Path | None:
    """The first Chrome or Edge on this computer that can open an app window."""
    if candidates is None:
        if sys.platform == "win32":
            candidates = _windows_candidates()
        elif sys.platform == "darwin":
            candidates = MAC_CANDIDATES
        else:
            found = [
                shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "msedge")
            ]
            candidates = [Path(f) for f in found if f]
    return next((p for p in candidates if p.exists()), None)


def app_command(browser: Path, url: str) -> list[str]:
    return [str(browser), f"--app={url}", "--window-size=1440,900"]


def open_window(
    url: str,
    *,
    browser: Path | None = None,
    spawn: Callable[..., object] = subprocess.Popen,
    fallback: Callable[[str], object] = webbrowser.open,
) -> str:
    """Open Agora in its own window; returns how ("app" or "tab")."""
    exe = browser or find_browser()
    if exe is None:
        fallback(url)
        return "tab"
    flags = NO_WINDOW if sys.platform == "win32" else 0
    try:
        spawn(app_command(exe, url), creationflags=flags, close_fds=True)
    except OSError:
        fallback(url)
        return "tab"
    return "app"
