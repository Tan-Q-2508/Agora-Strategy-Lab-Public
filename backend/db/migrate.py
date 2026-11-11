"""Bring a database up to date: run Alembic migrations, then seed reference data.

The launcher calls this on every start (docs/RUNBOOK.md §1), so pulling a new version
upgrades the user's database automatically. Before a migration touches an existing
database, a copy is saved to ``data/backups/`` (RUNBOOK §3: never lose user data).

Run by hand with:  uv run python -m backend.db.migrate
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from backend.config import REPO_ROOT, Paths, database_url, get_paths
from backend.core.clock import Clock, SystemClock
from backend.db.engine import Database
from backend.db.seed import seed
from backend.logging_setup import get_logger, setup_logging

log = get_logger("migrate")


def _alembic_config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def revisions(db: Database, cfg: Config) -> tuple[str | None, str | None]:
    """(current, head). ``current`` is None for a brand-new database."""
    with db.engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, ScriptDirectory.from_config(cfg).get_current_head()


def backup(paths: Paths) -> None:
    if not paths.db_file.exists() or paths.db_file.stat().st_size == 0:
        return
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = paths.backups_dir / f"agora-{stamp}.db"
    # Use SQLite's online backup so a WAL-mode database is copied consistently.
    with sqlite3.connect(paths.db_file) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    log.info("Backed up database to %s", target)
    _prune_backups(paths)


def _prune_backups(paths: Paths, keep: int = 10) -> None:
    old = sorted(paths.backups_dir.glob("agora-*.db"))[:-keep]
    for f in old:
        f.unlink(missing_ok=True)


def upgrade_and_seed(
    url: str | None = None, clock: Clock | None = None, paths: Paths | None = None
) -> Database:
    paths = paths or get_paths()
    url = url or database_url(paths)
    db = Database(url)
    cfg = _alembic_config(url)
    current, head = revisions(db, cfg)
    if current != head:
        if current is not None and url.startswith("sqlite:///"):
            backup(paths)  # only an existing database has anything worth saving
        command.upgrade(cfg, "head")
        log.info("Database migrated to head")
    with db.session() as s:
        seed(s, clock or SystemClock())
    return db


def main() -> None:
    paths = get_paths()
    paths.ensure()
    setup_logging(paths.logs_dir)
    upgrade_and_seed(paths=paths)
    print(f"Database ready: {paths.db_file}")


if __name__ == "__main__":
    main()
