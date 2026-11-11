"""SQLite engine with crash-safe settings.

WAL mode lets the UI read while a backtest writes and survives crashes without corrupting
saved runs (SPEC §11). ``foreign_keys`` is off by default in SQLite, so we turn it on for
every connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.config import database_url, get_paths


def _on_connect(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


def make_engine(url: str | None = None) -> Engine:
    if url is None:
        get_paths().ensure()
        url = database_url()
    if url.startswith("sqlite") and ":memory:" not in url:
        # Many threads work at once while Agora is open (downloads, desks, Kairos, Metis,
        # the screens): the default 5 + 10 connections ran out (D-102).
        engine = create_engine(
            url, connect_args={"check_same_thread": False}, pool_size=20, max_overflow=30
        )
    else:
        engine = create_engine(url, connect_args={"check_same_thread": False})
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _on_connect)
    return engine


class Database:
    """Owns one engine + session factory; the app keeps a single instance."""

    def __init__(self, url: str | None = None) -> None:
        self.engine = make_engine(url)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
