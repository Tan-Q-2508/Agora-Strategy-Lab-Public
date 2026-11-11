"""Rotating log files in ``data/logs/``.

The user never reads these; they exist so a support bundle can show a later Claude Code
session exactly what happened. Size-based rotation keeps the folder small forever.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured_dir: Path | None = None


class SharedRotatingFileHandler(RotatingFileHandler):
    """Rotation that survives a file Windows won't let us rename (D-158).

    On Windows a log file open in another process (the tray once shared ``agora.log`` with the
    server; an antivirus or a viewer can hold it too) can't be renamed. The standard handler
    then raised on every record ("--- Logging error ---", 1,073 times on 2026-11-04) and
    nothing more was logged for hours. Here a failed rotation keeps writing to the same file
    and tries again after another tenth of the size limit."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._retry_at = 0

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if self._retry_at and self.stream is not None and self.stream.tell() < self._retry_at:
            return 0
        return super().shouldRollover(record)

    def doRollover(self) -> None:
        try:
            super().doRollover()
            self._retry_at = 0
        except OSError:
            if self.stream is None:
                self.stream = self._open()
            self.stream.seek(0, 2)
            self._retry_at = self.stream.tell() + max(1, self.maxBytes // 10)


def setup_logging(logs_dir: Path, level: int = logging.INFO, name: str = "agora.log") -> None:
    """Attach a rotating file handler (5 x 2 MB) plus console output, once per folder. Each
    process writes its own file (the tray: ``tray.log``), so none renames a file another holds."""
    global _configured_dir
    if _configured_dir == logs_dir:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("agora")
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    file_handler = SharedRotatingFileHandler(
        logs_dir / name, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    console.setLevel(logging.ERROR)  # the launcher window only shows real problems
    root.addHandler(console)
    _configured_dir = logs_dir


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"agora.{name}")
