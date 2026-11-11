"""Load the stock lists into the database: stocks, their profiles and the ready-made lists.

Runs when Agora opens (``WatchlistService.start``) and does nothing unless the seed files or
the catalog changed since last time (a fingerprint is kept in the ``settings`` table under a
private key). Stocks are added with bulk inserts; nothing the user made is touched: custom
lists and the lists Kairos and Metis made are never changed here, and a ready-made list only
changes its own members.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from backend.db.models import (
    Instrument,
    InstrumentProfile,
    PaperPosition,
    PaperSession,
    SettingRow,
    Watchlist,
    WatchlistItem,
)
from backend.watchlists import catalog, taxonomy

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"
FILES = {"IN": SEED_DIR / "instruments_in.csv", "US": SEED_DIR / "instruments_us.csv"}
LISTED_ONLY = "listed"  # the profile ``lists`` of a stock that is in no index (D-102)
MARKER = "_seed.watchlists"  # not a user setting: read_all ignores unknown keys


def rarely_named(s: Session) -> set[int]:
    """Stocks in no index that the user doesn't use (not in a watchlist or his starter lists).
    About 6,000 of them, many with names or tickers that are everyday words ("Seven Hills",
    BEST, NOW): free text (headlines, chat) is matched against them only by exact capital
    tickers (D-102)."""
    from backend.db.models import UniverseMember

    listed = set(
        s.scalars(
            select(InstrumentProfile.instrument_id).where(InstrumentProfile.lists == LISTED_ONLY)
        )
    )
    used = set(s.scalars(select(WatchlistItem.instrument_id))) | set(
        s.scalars(select(UniverseMember.instrument_id))
    )
    return listed - used


def read_rows(market: str) -> tuple[str, list[dict[str, str]]]:
    """(as_of, rows) of a seed file."""
    path = FILES[market]
    with path.open(newline="", encoding="utf-8") as fh:
        first = fh.readline().strip()
        as_of = first.split("=", 1)[1] if first.startswith("# as_of=") else ""
        if not first.startswith("#"):
            fh.seek(0)
        return as_of, [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


def fingerprint() -> str:
    h = hashlib.sha256()
    for path in (*FILES.values(), SEED_DIR / "excluded_us.csv"):
        if path.exists():
            h.update(path.read_bytes())
    h.update(json.dumps([r.__dict__ for r in catalog.all_ready()], sort_keys=True).encode())
    h.update(json.dumps([taxonomy.IN_TAGS, taxonomy.US_SUB_TAGS], sort_keys=True).encode())
    h.update(
        json.dumps([catalog.US_ETFS, catalog.IN_ETFS, catalog.GAUGES, catalog.INDICES]).encode()
    )
    return h.hexdigest()[:16]


def needs_sync(s: Session) -> bool:
    row = s.get(SettingRow, MARKER)
    return row is None or json.loads(row.value) != fingerprint()


def is_test_symbol(symbol: str) -> bool:
    """NSE lists test securities (DUMMYHEG, DUMMYINGL1…) beside real stocks. Yahoo doesn't
    know them, so every daily top-up fell back to NSE's day files for them (D-184)."""
    return symbol.upper().startswith("DUMMY")


def excluded_us() -> set[str]:
    """Listings left out of the US market (D-223, ``scripts/exclude_universe.py``)."""
    path = SEED_DIR / "excluded_us.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as f:
        return {row["symbol"] for row in csv.DictReader(f)}


def sync(s: Session, now: int) -> dict[str, int]:
    """Bring stocks, profiles and ready-made lists up to date. Returns counts."""
    out = {"instruments": 0, "profiles": 0, "lists": 0}
    # test securities saved before D-184 stop being stocks
    s.execute(
        update(Instrument)
        .where(Instrument.symbol.like("DUMMY%"), Instrument.is_active == 1)
        .values(is_active=0)
    )
    left_out = excluded_us()
    if left_out:
        # listings the user doesn't follow (D-223): no new prices, nothing deleted. A stock with an
        # open paper trade stays followed until the trade ends: its exit needs prices.
        held = set(
            s.scalars(
                select(Instrument.symbol)
                .join(PaperPosition, PaperPosition.instrument_id == Instrument.id)
                .join(PaperSession, PaperSession.id == PaperPosition.session_id)
                .where(Instrument.market_code == "US", PaperSession.state != "stopped")
            )
        )
        s.execute(
            update(Instrument)
            .where(
                Instrument.market_code == "US",
                Instrument.symbol.in_(left_out - held),
                Instrument.is_active == 1,
            )
            .values(is_active=0)
        )
    existing = {
        (m, sym): iid
        for iid, m, sym in s.execute(
            select(Instrument.id, Instrument.market_code, Instrument.symbol)
        ).all()
    }
    new_rows: dict[tuple[str, str], dict[str, object]] = {}
    profiles: dict[tuple[str, str], dict[str, str]] = {}

    def want(market: str, sym: str, yahoo: str, name: str, kind: str, isin: str = "") -> None:
        if (market, sym) not in existing and (market, sym) not in new_rows:
            new_rows[(market, sym)] = {
                "market_code": market,
                "symbol": sym,
                "yahoo_symbol": yahoo,
                "name": name,
                "instrument_type": kind,
                "isin": isin or None,
                "is_active": 1,
                "added_at": now,
            }

    for market in ("IN", "US"):
        as_of, rows = read_rows(market)
        for r in rows:
            sym, lists = r["symbol"], set(filter(None, r["lists"].split(";")))
            if is_test_symbol(sym):
                continue  # an exchange's test security, not a stock (D-184)
            if market == "IN":
                want("IN", sym, f"{sym}.NS", r["name"], "equity", r.get("isin", ""))
                prof = taxonomy.india_profile(sym, r["name"], r["industry"], lists)
            else:
                if sym not in left_out:
                    want("US", sym, sym, r["name"], "equity")
                prof = taxonomy.us_profile(sym, r["sector"], r["industry"], lists)
            prof["lists"] = ";".join(sorted(lists))
            prof["as_of"] = as_of
            profiles[(market, sym)] = prof
    for sym, name in catalog.US_ETFS:
        want("US", sym, sym, name, "etf")
        profiles.setdefault(
            ("US", sym),
            {"sector": "", "industry": "ETF", "size": "", "lists": "etf", "tags": "", "as_of": ""},
        )
    for sym, name in catalog.IN_ETFS:
        want("IN", sym, f"{sym}.NS", name, "etf")
        profiles.setdefault(
            ("IN", sym),
            {"sector": "", "industry": "ETF", "size": "", "lists": "etf", "tags": "", "as_of": ""},
        )
    for market, sym, yahoo, name in catalog.GAUGES:
        want(market, sym, yahoo, name, "index")
    for market, sym, yahoo, name, _group in catalog.INDICES:  # the Indices page (D-174)
        want(market, sym, yahoo, name, "etf" if sym == "XLE" else "index")
    if new_rows:
        s.execute(insert(Instrument), list(new_rows.values()))
        out["instruments"] = len(new_rows)
        existing = {
            (m, sym): iid
            for iid, m, sym in s.execute(
                select(Instrument.id, Instrument.market_code, Instrument.symbol)
            ).all()
        }
    have = {p.instrument_id: p for p in s.scalars(select(InstrumentProfile))}
    adds: list[dict[str, object]] = []
    for (market, sym), prof in profiles.items():
        iid = existing.get((market, sym))
        if iid is None:
            continue
        row = have.get(iid)
        if row is None:
            adds.append({"instrument_id": iid, **prof})
        elif any(getattr(row, k) != v for k, v in prof.items()):
            for k, v in prof.items():
                setattr(row, k, v)
            out["profiles"] += 1
    if adds:
        s.execute(insert(InstrumentProfile), adds)
        out["profiles"] += len(adds)
    s.flush()
    out["lists"] = _sync_ready(s, existing, now)
    mark = s.get(SettingRow, MARKER)
    value = json.dumps(fingerprint())
    if mark is None:
        s.add(SettingRow(key=MARKER, value=value, updated_at=now))
    else:
        mark.value = value
        mark.updated_at = now
    s.flush()
    return out


def members(s: Session, market: str, rule: dict[str, object]) -> list[int]:
    """Instrument ids a ready-made (non-factor) rule selects, in symbol order."""
    rows = s.execute(
        select(Instrument.id, Instrument.symbol, InstrumentProfile)
        .join(InstrumentProfile, InstrumentProfile.instrument_id == Instrument.id)
        .where(Instrument.market_code == market, Instrument.is_active == 1)
        .order_by(Instrument.symbol)
    ).all()
    if "symbols" in rule:
        wanted = [str(x) for x in rule["symbols"]]  # type: ignore[attr-defined]
        by_sym = {sym: iid for iid, sym, _ in rows}
        missing = [x for x in wanted if x not in by_sym]
        if missing:  # ETFs without a profile row
            for iid, sym in s.execute(
                select(Instrument.id, Instrument.symbol).where(
                    Instrument.market_code == market, Instrument.symbol.in_(missing)
                )
            ):
                by_sym[sym] = iid
        return [by_sym[x] for x in wanted if x in by_sym]
    within = {w for w in str(rule.get("within", "")).split(",") if w}
    tags = {t for t in str(rule.get("tag", "")).split(",") if t}
    out: list[int] = []
    for iid, _sym, prof in rows:
        lists = set(prof.lists.split(";")) if prof.lists else set()
        if within and not lists & within:
            continue
        if "list" in rule and str(rule["list"]) not in lists:
            continue
        if "sector" in rule and prof.sector != rule["sector"]:
            continue
        if "size" in rule and prof.size != rule["size"]:
            continue
        if tags and not tags & set(prof.tags.split(";")):
            continue
        out.append(iid)
    return out


def _sync_ready(s: Session, ids: dict[tuple[str, str], int], now: int) -> int:
    rows = {w.key: w for w in s.scalars(select(Watchlist).where(Watchlist.kind == "ready"))}
    changed = 0
    for r in catalog.all_ready():
        w = rows.get(r.key)
        if w is None:
            clash = s.scalar(
                select(Watchlist).where(Watchlist.market_code == r.market, Watchlist.name == r.name)
            )
            if clash is not None:  # the user already has a list with this name: keep theirs
                continue
            w = Watchlist(
                market_code=r.market,
                name=r.name,
                kind="ready",
                category=r.category,
                key=r.key,
                description=r.description,
                rule=json.dumps(r.rule, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            s.add(w)
            s.flush()
        else:
            w.name, w.category, w.description = r.name, r.category, r.description
            w.rule = json.dumps(r.rule, sort_keys=True)
        if "factor" in r.rule:
            continue  # rebuilt from prices (factors.py)
        set_items(s, w.id, members(s, r.market, r.rule), now)
        w.updated_at = now
        changed += 1
    return changed


def set_items(
    s: Session,
    watchlist_id: int,
    instrument_ids: Iterable[int],
    now: int,
    notes: dict[int, str] | None = None,
) -> None:
    """Replace a list's members (in the given order)."""
    s.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id))
    seen: set[int] = set()
    rows = []
    for rank, iid in enumerate(instrument_ids):
        if iid in seen:
            continue
        seen.add(iid)
        rows.append(
            {
                "watchlist_id": watchlist_id,
                "instrument_id": iid,
                "note": (notes or {}).get(iid, ""),
                "rank": rank,
                "added_at": now,
            }
        )
    if rows:
        s.execute(insert(WatchlistItem), rows)
