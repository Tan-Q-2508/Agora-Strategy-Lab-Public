"""Alembic environment: uses the same database URL and SQLite pragmas as the app."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from backend.db.engine import make_engine
from backend.db.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = config.attributes.get("url") or config.get_main_option("sqlalchemy.url") or None
    engine = make_engine(url)
    with engine.connect() as connection:
        # Batch mode rebuilds a table by copying it and dropping the old one; with foreign
        # keys on, SQLite refuses to drop a table other rows point at. Off for the
        # migration only (a PRAGMA outside any transaction), checked again afterwards.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()  # end SQLAlchemy's implicit transaction so Alembic owns its own
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite can't ALTER most things; batch mode rebuilds tables
        )
        with context.begin_transaction():
            context.run_migrations()
        broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"Migration left broken references: {broken[:5]}")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    engine.dispose()


run_migrations_online()
