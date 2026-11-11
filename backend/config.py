"""Filesystem locations Agora uses.

Everything the app writes lives under one ``data/`` folder next to the code, so the user
can find (or back up) it in one place and git never picks it up. Tests point
``AGORA_DATA_DIR`` at a temporary folder so they never touch the real database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
PORT = 8765


@dataclass(frozen=True)
class Paths:
    data_dir: Path

    @property
    def db_file(self) -> Path:
        return self.data_dir / "agora.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def frontend_dist(self) -> Path:
        return REPO_ROOT / "frontend" / "dist"

    def ensure(self) -> None:
        for folder in (self.data_dir, self.logs_dir, self.backups_dir):
            folder.mkdir(parents=True, exist_ok=True)


def get_paths() -> Paths:
    override = os.environ.get("AGORA_DATA_DIR")
    return Paths(Path(override) if override else REPO_ROOT / "data")


def database_url(paths: Paths | None = None) -> str:
    override = os.environ.get("AGORA_DATABASE_URL")
    if override:
        return override
    p = paths or get_paths()
    return f"sqlite:///{p.db_file.as_posix()}"
