"""Reading and writing candles, corporate actions and the fetch log.

Uses SQLAlchemy Core (not ORM objects) because backtests read tens of thousands of bars
at a time; plain row tuples keep that fast.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import case, and_, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend import actions
from backend.core.types import Bar, CorporateAction, Market, Timeframe
from backend.data.adjust import factor_at, split_events
from backend.db.models import (
    Candle,
    CorporateActionRow,
    DataFetchLog,
    Instrument,
    SourceStatus,
)

CHUNK = 500  # rows per INSERT (SQLite allows ~32k variables; 11 columns each)


@dataclass(frozen=True)
class InstrumentRef:
    id: int
    market: Market
    symbol: str
    yahoo_symbol: str
    name: str
    instrument_type: str

    @property
    def is_index(self) -> bool:
        return self.instrument_type == "index"


def ref(row: Instrument) -> InstrumentRef:
    return InstrumentRef(
        row.id, Market(row.market_code), row.symbol, row.yahoo_symbol, row.name, row.instrument_type
    )


def get_instrument(s: Session, instrument_id: int) -> InstrumentRef | None:
    row = s.get(Instrument, instrument_id)
    return ref(row) if row else None


def find_instrument(s: Session, market: Market, symbol: str) -> InstrumentRef | None:
    row = s.scalar(
        select(Instrument).where(
            Instrument.market_code == market.value, Instrument.symbol == symbol.upper()
        )
    )
    return ref(row) if row else None


def upsert_bars(
    s: Session, instrument_id: int, timeframe: Timeframe, bars: Sequence[Bar], fetched_at: int
) -> int:
    """Insert or replace bars (a re-fetched bar overwrites the old one). Non-final bars
    are never stored: strategies must only ever see closed candles."""
    rows = [
        {
            "instrument_id": instrument_id,
            "timeframe": timeframe.value,
            "ts": b.ts,
            "open": b.open,
            # a candle's high and low always include its open and close (D-182: Yahoo's daily
            # rows for 5 Nov had the opening auction above the day's high for ZS, CSX, CRWD)
            "high": max(b.high, b.open, b.close),
            "low": min(b.low, b.open, b.close),
            "close": b.close,
            "volume": b.volume,
            "split_factor": b.split_factor,
            "source": b.source,
            "fetched_at": fetched_at,
        }
        for b in bars
        if b.is_final
    ]
    for i in range(0, len(rows), CHUNK):
        stmt = insert(Candle).values(rows[i : i + CHUNK])
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "timeframe", "ts"],
            set_={
                **{
                    c: stmt.excluded[c]
                    for c in ("open", "high", "low", "close", "split_factor", "source", "fetched_at")
                },
                # a re-served candle with no volume never wipes the volume already saved (D-221)
                "volume": case(
                    (stmt.excluded.volume > 0, stmt.excluded.volume), else_=Candle.volume
                ),
            },
        )
        s.execute(stmt)
    return len(rows)


def load_bars(
    s: Session, instrument_id: int, timeframe: Timeframe, start_ms: int, end_ms: int
) -> list[Bar]:
    """Raw bars (with their split factors) with ``start_ms <= ts < end_ms``, oldest first."""
    c = Candle.__table__.c
    rows = s.execute(
        select(c.ts, c.open, c.high, c.low, c.close, c.volume, c.source, c.split_factor)
        .where(
            c.instrument_id == instrument_id,
            c.timeframe == timeframe.value,
            c.ts >= start_ms,
            c.ts < end_ms,
        )
        .order_by(c.ts)
    ).all()
    return [Bar(r[0], r[1], r[2], r[3], r[4], r[5], r[6], True, r[7]) for r in rows]


def stored_ts(
    s: Session, instrument_id: int, timeframe: Timeframe, start_ms: int, end_ms: int
) -> dict[int, int]:
    """ts → fetched_at for stored bars in the range."""
    c = Candle.__table__.c
    rows = s.execute(
        select(c.ts, c.fetched_at).where(
            c.instrument_id == instrument_id,
            c.timeframe == timeframe.value,
            c.ts >= start_ms,
            c.ts < end_ms,
        )
    ).all()
    return {r[0]: r[1] for r in rows}


def first_ts(s: Session, instrument_id: int, timeframe: Timeframe) -> int | None:
    """The oldest stored bar's ts, or None when nothing is stored yet."""
    c = Candle.__table__.c
    first: int | None = s.scalar(
        select(func.min(c.ts)).where(
            c.instrument_id == instrument_id, c.timeframe == timeframe.value
        )
    )
    return first


def coverage_stats(
    s: Session, timeframe: Timeframe, instrument_ids: Iterable[int] | None = None
) -> dict[int, tuple[int, int, int, str]]:
    """instrument_id → (first ts, last ts, count, most recent source).

    Pass ``instrument_ids`` whenever only some stocks are wanted: with the whole market saved
    (D-102) the unfiltered scan reads millions of candles (12–33 s under load, D-113)."""
    c = Candle.__table__.c
    q = select(
        c.instrument_id, func.min(c.ts), func.max(c.ts), func.count(), func.max(c.source)
    ).where(c.timeframe == timeframe.value)
    if instrument_ids is not None:
        q = q.where(c.instrument_id.in_(list(instrument_ids)))
    rows = s.execute(q.group_by(c.instrument_id)).all()
    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}


def sources_used(
    s: Session, instrument_id: int, timeframe: Timeframe, start_ms: int, end_ms: int
) -> dict[str, int]:
    c = Candle.__table__.c
    rows = s.execute(
        select(c.source, func.count())
        .where(
            c.instrument_id == instrument_id,
            c.timeframe == timeframe.value,
            c.ts >= start_ms,
            c.ts < end_ms,
        )
        .group_by(c.source)
    ).all()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------- corporate actions


def save_actions(
    s: Session, instrument_id: int, actions: Iterable[CorporateAction], source: str
) -> bool:
    """Store new actions. Returns True if the split list changed (factors need redoing)."""
    changed = False
    for a in actions:
        exists = s.scalar(
            select(CorporateActionRow).where(
                CorporateActionRow.instrument_id == instrument_id,
                CorporateActionRow.ex_date == a.ex_date,
                CorporateActionRow.kind == a.kind,
            )
        )
        if exists is None:
            s.add(
                CorporateActionRow(
                    instrument_id=instrument_id,
                    ex_date=a.ex_date,
                    kind=a.kind,
                    ratio=a.ratio,
                    amount=a.amount,
                    source=source,
                )
            )
            changed = changed or a.kind == "split"
        elif a.kind == "split" and exists.ratio != a.ratio:
            exists.ratio = a.ratio
            changed = True
        elif a.kind == "dividend" and exists.amount != a.amount:
            exists.amount = a.amount
    s.flush()
    return changed


def load_actions(s: Session, instrument_id: int) -> list[CorporateAction]:
    rows = s.scalars(
        select(CorporateActionRow)
        .where(CorporateActionRow.instrument_id == instrument_id)
        .order_by(CorporateActionRow.ex_date)
    )
    return [CorporateAction(r.ex_date, r.kind, r.ratio, r.amount) for r in rows]


def reapply_split_factors(s: Session, instrument_id: int) -> None:
    """Recompute every stored candle's split factor from the split list. Raw prices are
    never touched, so this is safe to run any time."""
    splits = split_events(load_actions(s, instrument_id))
    bounds = [-(2**62)] + [ex for ex, _ in splits] + [2**62]
    for lo, hi in zip(bounds, bounds[1:], strict=False):
        s.execute(
            update(Candle)
            .where(and_(Candle.instrument_id == instrument_id, Candle.ts >= lo, Candle.ts < hi))
            .values(split_factor=factor_at(lo, splits))
        )


# ---------------------------------------------------------------- log + source status


def log_fetch(
    s: Session,
    *,
    source: str,
    instrument_id: int | None,
    timeframe: Timeframe | None,
    range_start: int | None,
    range_end: int | None,
    status: str,
    rows: int,
    message: str,
    started_at: int,
    duration_ms: int,
) -> None:
    actions.note(
        "data_fetch",
        f"{source} {timeframe.value if timeframe else ''}".strip(),
        message[:300] or f"{rows} rows",
        status="failed" if status in ("error", "failed", "rate_limited") else "ok",
        instrument_id=instrument_id,
        rows=rows,
        ms=duration_ms,
    )
    s.add(
        DataFetchLog(
            source=source,
            instrument_id=instrument_id,
            timeframe=timeframe.value if timeframe else None,
            range_start=range_start,
            range_end=range_end,
            status=status,
            rows=rows,
            message=message[:2000],
            started_at=started_at,
            duration_ms=duration_ms,
        )
    )


def attempted_ranges(
    s: Session, instrument_id: int, timeframe: Timeframe, since_ms: int = 0
) -> list[tuple[int, int, int, str]]:
    """(range_start, range_end, started_at, status) of past fetches that got an answer
    (ok, fallback or empty), so the cache manager can avoid asking the same question."""
    t = DataFetchLog
    rows = s.execute(
        select(t.range_start, t.range_end, t.started_at, t.status).where(
            t.instrument_id == instrument_id,
            t.timeframe == timeframe.value,
            t.status.in_(("ok", "empty", "fallback")),
            t.started_at >= since_ms,
        )
    ).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows if r[0] is not None and r[1] is not None]


def set_source_state(
    s: Session,
    source: str,
    state: str,
    now: int,
    until: int | None = None,
    error: str | None = None,
) -> bool:
    """Returns True when the state actually changed (worth telling the UI)."""
    row = s.get(SourceStatus, source)
    if row is None:
        s.add(
            SourceStatus(source=source, state=state, until=until, last_error=error, updated_at=now)
        )
        return True
    changed = row.state != state
    row.state, row.until, row.updated_at = state, until, now
    if error is not None:
        row.last_error = error
    return changed


def source_states(s: Session) -> dict[str, SourceStatus]:
    return {r.source: r for r in s.scalars(select(SourceStatus))}


def prune_logs(s: Session, older_than_ms: int) -> None:
    s.execute(delete(DataFetchLog).where(DataFetchLog.started_at < older_than_ms))


def groups(s: Session, instrument_ids: Sequence[int]) -> dict[int, str]:
    """Each stock's sector, or its industry when it has no sector (an oil fund), for the
    per-sector trade limit (D-168); stocks with neither are left out (they count alone)."""
    from backend.db.models import InstrumentProfile

    out: dict[int, str] = {}
    for row in s.scalars(
        select(InstrumentProfile).where(InstrumentProfile.instrument_id.in_(list(instrument_ids)))
    ):
        name = (row.sector or row.industry or "").strip()
        if name:
            out[row.instrument_id] = name
    return out
