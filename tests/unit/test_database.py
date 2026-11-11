from __future__ import annotations

import itertools
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from backend.config import Paths
from backend.db.engine import Database
from backend.db.migrate import upgrade_and_seed
from backend.db.models import (
    ALL_TABLES,
    BrokerageProfile,
    Candle,
    ChargeSchedule,
    Instrument,
    Universe,
    UniverseMember,
)
from backend.db.seed import read_nifty50
from backend.fakes.clock import FakeClock


def test_all_documented_tables_exist(db: Database) -> None:
    with db.engine.connect() as conn:
        names = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert set(ALL_TABLES) <= names
    # 30 in v3.0 + paper_trades (D-46) + 8 for Kairos (KAIROS §12) + 2 for learning (§16)
    # + 2 for Metis (METIS §9) + 4 for opportunities and portfolios (PORTFOLIO §8)
    # + strategy_checks (Phase 16, D-88, D-90) + 6 for watchlists, sectors and the world (D-93..96)
    # + lab_tests (Phase 25, D-143)
    assert len(ALL_TABLES) == 55


def test_wal_and_foreign_keys_enabled(db: Database) -> None:
    with db.engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_candles_table_is_without_rowid(db: Database, paths: Paths) -> None:
    con = sqlite3.connect(paths.db_file)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='candles'").fetchone()[0]
    con.close()
    assert "WITHOUT ROWID" in sql


def test_migrations_match_models(db: Database) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from backend.db.models import Base

    with db.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], "Models changed without a migration: run alembic revision --autogenerate"


def test_check_constraints_reject_bad_enums(db: Database) -> None:
    with pytest.raises(IntegrityError), db.session() as s:
        inst = s.scalar(select(Instrument).limit(1))
        assert inst is not None
        s.add(
            Candle(
                instrument_id=inst.id,
                timeframe="3m",
                ts=0,
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
                source="fake",
                fetched_at=0,
            )
        )


def test_seed_nifty50(db: Database) -> None:
    with db.session() as s:
        nifty = s.scalar(select(Universe).where(Universe.name == "NIFTY50"))
        assert nifty is not None
        members = s.scalar(select(func.count()).where(UniverseMember.universe_id == nifty.id))
        assert members == 50 == len(read_nifty50())
        rel = s.scalar(select(Instrument).where(Instrument.symbol == "RELIANCE"))
        assert rel is not None and rel.yahoo_symbol == "RELIANCE.NS"
        index = s.scalar(select(Instrument).where(Instrument.symbol == "NIFTY50"))
        assert index is not None and index.yahoo_symbol == "^NSEI"
        assert index.instrument_type == "index"


def test_seed_us_watchlist(db: Database) -> None:
    with db.session() as s:
        syms = set(s.scalars(select(Instrument.symbol).where(Instrument.market_code == "US")))
    assert syms == {"SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM"}


def test_seed_costs(db: Database) -> None:
    with db.session() as s:
        defaults = s.scalars(select(BrokerageProfile).where(BrokerageProfile.is_default == 1))
        assert {p.market_code for p in defaults} == {"IN", "US"}
        rows = list(s.scalars(select(ChargeSchedule)))
    assert all(r.source_url for r in rows), "every charge row needs its source (D-09)"
    charges = {(r.market_code, r.charge) for r in rows}
    for c in ("stt", "exchange_txn", "sebi_fee", "stamp_duty", "gst", "dp_charge"):
        assert ("IN", c) in charges
    assert {("US", "sec_fee"), ("US", "finra_taf")} <= charges


def test_effective_dated_rows_do_not_overlap(db: Database) -> None:
    with db.session() as s:
        rows = list(s.scalars(select(ChargeSchedule).order_by(ChargeSchedule.effective_from)))
    groups: dict[tuple[str, str, str, str], list[ChargeSchedule]] = {}
    for r in rows:
        groups.setdefault((r.market_code, r.charge, r.product, r.side), []).append(r)
    for key, items in groups.items():
        for a, b in itertools.pairwise(items):
            assert a.effective_to is not None, f"{key}: open-ended row followed by another"
            assert a.effective_to < b.effective_from, f"{key}: overlapping dates"
            assert b.effective_from - a.effective_to == 1, f"{key}: gap between rows"


def test_seed_is_idempotent(paths: Paths, clock: FakeClock) -> None:
    first = upgrade_and_seed(clock=clock, paths=paths)
    with first.session() as s:
        before = s.scalar(select(func.count()).select_from(Instrument))
        n_charges = s.scalar(select(func.count()).select_from(ChargeSchedule))
    first.engine.dispose()
    second = upgrade_and_seed(clock=clock, paths=paths)
    with second.session() as s:
        assert s.scalar(select(func.count()).select_from(Instrument)) == before
        assert s.scalar(select(func.count()).select_from(ChargeSchedule)) == n_charges
    second.engine.dispose()


def test_no_backup_for_a_brand_new_database(paths: Paths, clock: FakeClock) -> None:
    upgrade_and_seed(clock=clock, paths=paths).engine.dispose()
    assert list(paths.backups_dir.glob("*.db")) == []


def test_backup_copies_existing_database(db: Database, paths: Paths) -> None:
    from backend.db.migrate import backup

    backup(paths)
    copies = list(paths.backups_dir.glob("agora-*.db"))
    assert len(copies) == 1
    con = sqlite3.connect(copies[0])
    assert con.execute("SELECT count(*) FROM instruments").fetchone()[0] == 61
    con.close()


def test_upgrade_backs_up_when_schema_is_behind(
    paths: Paths, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.db import migrate

    upgrade_and_seed(clock=clock, paths=paths).engine.dispose()
    monkeypatch.setattr(migrate, "revisions", lambda db, cfg: ("0000_older", "0001"))
    monkeypatch.setattr(migrate.command, "upgrade", lambda cfg, rev: None)
    upgrade_and_seed(clock=clock, paths=paths).engine.dispose()
    assert len(list(paths.backups_dir.glob("agora-*.db"))) == 1


def test_kairos_strategies_are_allowed(db: Database, paths: Paths) -> None:
    con = sqlite3.connect(paths.db_file)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='strategies'").fetchone()[0]
    ver = con.execute("SELECT sql FROM sqlite_master WHERE name='strategy_versions'").fetchone()[0]
    con.close()
    assert "'kairos'" in sql and "'kairos'" in ver and "'visual'" in sql


def test_upgrade_keeps_saved_strategies_and_runs(tmp_path: Path, clock: FakeClock) -> None:
    """A laptop database at 0003 with strategies, versions and a paper session upgrades
    to head (the 0004 rebuild must not trip over the rows pointing at it)."""
    from alembic import command

    from backend.db.migrate import _alembic_config

    p = Paths(tmp_path / "old")
    p.ensure()
    url = f"sqlite:///{p.db_file}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, "0003")
    old = Database(url)
    rows = [
        "INSERT INTO markets VALUES ('IN', 'India', 'INR', 'Asia/Kolkata', 'XNSE')",
        "INSERT INTO strategies (id, name, description, kind, market_code, created_at,"
        " updated_at) VALUES (1, 'Mine', '', 'visual', 'IN', 0, 0)",
        "INSERT INTO strategy_versions (id, strategy_id, version, definition, schema_version,"
        " content_hash, created_at, note, created_by)"
        " VALUES (1, 1, 1, '{}', 1, 'h', 0, '', 'user')",
    ]
    with old.engine.begin() as conn:
        for sql in rows:
            conn.execute(text(sql))
    old.engine.dispose()
    db = upgrade_and_seed(url, clock=clock, paths=p)
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM strategies")).scalar() == "Mine"
        assert conn.execute(text("SELECT strategy_id FROM strategy_versions")).scalar() == 1
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    with db.session() as s:
        s.execute(text("UPDATE strategies SET kind = 'kairos' WHERE id = 1"))
    db.engine.dispose()
