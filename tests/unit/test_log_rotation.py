"""A log that Windows won't let us rename keeps logging (D-158)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from backend.logging_setup import SharedRotatingFileHandler


def test_a_refused_rename_keeps_logging_and_retries_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "agora.log"
    h = SharedRotatingFileHandler(path, maxBytes=1_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    errors: list[logging.LogRecord] = []
    monkeypatch.setattr(h, "handleError", errors.append)
    log = logging.getLogger("test.rotation")
    log.propagate = False
    log.addHandler(h)
    try:

        def refused(_src: str, _dst: str) -> None:
            raise PermissionError(32, "The process cannot access the file")

        monkeypatch.setattr(logging.handlers.os, "rename", refused)
        for k in range(200):
            log.warning("line %03d %s", k, "x" * 20)
        assert errors == []  # the standard handler failed on every record from here
        text = path.read_text(encoding="utf-8")
        assert "line 000" in text and "line 199" in text  # nothing was lost
        assert not (tmp_path / "agora.log.1").exists()
        monkeypatch.undo()
        monkeypatch.setattr(h, "handleError", errors.append)
        for k in range(200, 400):
            log.warning("line %03d %s", k, "x" * 20)
        assert errors == [] and (tmp_path / "agora.log.1").exists()  # rotates once it can
        assert "line 399" in path.read_text(encoding="utf-8")
    finally:
        log.removeHandler(h)
        h.close()
