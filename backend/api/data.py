"""Instruments, universes, coverage, refresh and candles (API_CONTRACT → Instruments and data)."""

from __future__ import annotations

import re
import threading
from datetime import UTC
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.context import AppContext, get_ctx
from backend.core.clock import ms_to_dt
from backend.core.types import Market, Timeframe
from backend.data import service, store
from backend.data.adjust import adjusted
from backend.data.errors import RateLimited
from backend.data.store import InstrumentRef
from backend.db.models import DataFetchLog, Instrument, Universe, UniverseMember
from backend.errors import AgoraError
from backend.jobs import JobContext

router = APIRouter()
Ctx = Annotated[AppContext, Depends(get_ctx)]
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def inst_json(i: InstrumentRef) -> dict[str, Any]:
    return {
        "id": i.id,
        "market": i.market.value,
        "symbol": i.symbol,
        "yahoo_symbol": i.yahoo_symbol,
        "name": i.name,
        "type": i.instrument_type,
    }


def _instrument(ctx: AppContext, instrument_id: int) -> InstrumentRef:
    with ctx.db.session() as s:
        inst = store.get_instrument(s, instrument_id)
    if inst is None:
        raise AgoraError(
            "INSTRUMENT_NOT_FOUND",
            "Agora doesn't know that stock.",
            "Pick a stock from the list.",
            detail=f"instrument_id={instrument_id}",
            status=404,
        )
    return inst


def _timeframe(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError:
        raise AgoraError(
            "INVALID_TIMEFRAME",
            "That timeframe isn't supported.",
            "Choose 1 day, 1 hour, 15 minutes, 5 minutes or 1 minute.",
            detail=value,
            status=422,
        ) from None


# ---------------------------------------------------------------- instruments


@router.get("/instruments")
def list_instruments(
    ctx: Ctx, market: Market | None = None, q: str | None = None
) -> dict[str, Any]:
    with ctx.db.session() as s:
        items = service.instruments(s, market, q)
    return {"instruments": [inst_json(i) for i in items]}


class AddInstrument(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    market: Literal["US"] = "US"


@router.post("/instruments", status_code=201)
def add_instrument(ctx: Ctx, body: AddInstrument) -> dict[str, Any]:
    symbol = body.symbol.strip().upper()
    if not TICKER.match(symbol):
        raise AgoraError(
            "INVALID_TICKER",
            f"“{body.symbol}” doesn't look like a US ticker.",
            "Type a ticker such as AAPL or BRK-B.",
            status=422,
        )
    market = Market.US
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.scalar(
            select(Instrument).where(
                Instrument.market_code == market.value, Instrument.symbol == symbol
            )
        )
        existing = store.ref(row) if row else None
    probe_ref = existing or InstrumentRef(-1, market, symbol, symbol, symbol, "equity")
    try:
        found, detail = ctx.cache.probe(probe_ref)
    except RateLimited as exc:
        raise AgoraError(
            "DATA_SOURCE_RATE_LIMITED",
            "Yahoo Finance is limiting requests right now, so Agora couldn't check that ticker.",
            "Wait a few minutes and try again.",
            detail=exc.detail,
            status=503,
        ) from exc
    if not found:
        raise AgoraError(
            "TICKER_NOT_FOUND",
            f"Agora couldn't find prices for {symbol}.",
            "Check the spelling. US tickers only, for example MSFT or SPY.",
            detail=detail,
            status=404,
        )
    with ctx.db.session() as s:
        if row is None:
            row = Instrument(
                market_code=market.value,
                symbol=symbol,
                yahoo_symbol=symbol,
                name=symbol,
                instrument_type="equity",
                is_active=1,
                added_at=now,
            )
            s.add(row)
            s.flush()
        else:
            row = s.get(Instrument, row.id)
            assert row is not None
            row.is_active = 1
        uid = service.universe_id(s, "US_WATCHLIST")
        current = s.scalar(
            select(UniverseMember.id).where(
                UniverseMember.universe_id == uid,
                UniverseMember.instrument_id == row.id,
                UniverseMember.valid_to.is_(None),
            )
        )
        if current is None:
            s.add(
                UniverseMember(
                    universe_id=uid, instrument_id=row.id, valid_from=now, source="added by you"
                )
            )
        inst = store.ref(row)
    job = _start_refresh(ctx, [inst], [Timeframe.D1], f"Downloading {symbol} history")
    return {"instrument": inst_json(inst), "job_id": job}


@router.delete("/instruments/{instrument_id}")
def remove_instrument(ctx: Ctx, instrument_id: int) -> dict[str, Any]:
    inst = _instrument(ctx, instrument_id)
    if inst.market is not Market.US or inst.symbol == service.BENCHMARK[Market.US]:
        raise AgoraError(
            "CANNOT_REMOVE",
            f"{inst.symbol} can't be removed.",
            "Only your own US tickers can be removed; SPY stays as the US benchmark.",
            status=409,
        )
    with ctx.db.session() as s:
        service.deactivate(s, inst.id, ctx.clock.now_ms())
    return {"removed": inst.symbol}


# ---------------------------------------------------------------- universes


@router.get("/universes")
def list_universes(ctx: Ctx) -> dict[str, Any]:
    with ctx.db.session() as s:
        out = []
        for u in s.scalars(select(Universe).order_by(Universe.id)):
            count = len(service.members(s, u.id))
            out.append(
                {
                    "id": u.id,
                    "market": u.market_code,
                    "name": u.name,
                    "description": u.description,
                    "members": count,
                    "has_history": service.has_membership_history(s, u.id),
                }
            )
    return {"universes": out}


@router.get("/universes/{universe_id}/members")
def universe_members(ctx: Ctx, universe_id: int, as_of: int | None = None) -> dict[str, Any]:
    with ctx.db.session() as s:
        items = service.members(s, universe_id, as_of)
    return {"members": [inst_json(i) for i in items], "as_of": as_of}


class ImportHistory(BaseModel):
    csv: str = Field(min_length=1, max_length=2_000_000)


@router.post("/universes/{universe_id}/import-history")
def import_history(ctx: Ctx, universe_id: int, body: ImportHistory) -> dict[str, Any]:
    with ctx.db.session() as s:
        u = s.get(Universe, universe_id)
        if u is None:
            raise AgoraError(
                "NOT_FOUND", "That list doesn't exist.", "Go back and try again.", status=404
            )
        try:
            report = service.import_membership_history(
                s, universe_id, Market(u.market_code), body.csv, ctx.clock.now_ms()
            )
        except ValueError as exc:
            raise AgoraError(
                "INVALID_MEMBERSHIP_FILE",
                str(exc),
                "Use a CSV with the columns symbol, start_date, end_date (dates like 2019-03-29).",
                status=422,
            ) from exc
    return {
        "rows": report.rows,
        "instruments_added": report.instruments_added,
        "problems": report.problems,
    }


# ---------------------------------------------------------------- coverage & refresh


COVERAGE_TTL_MS = 300_000  # the whole market's stock-by-stock count takes seconds; keep it a while
_coverage_cache: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
_coverage_busy: set[tuple[str, str]] = set()
SHOW_ROWS = 1000


def _coverage_targets(
    s: Any, ctx: AppContext, market: Market | None, tf: Timeframe
) -> list[InstrumentRef]:
    """Daily prices are kept for every active stock, so that's the whole set (the user,
    2026-11-06: the tab showed the Nifty 50 and 10 US stocks). Shorter candles are kept only
    for stocks that desks and research use, so those are the set there."""
    markets = [market] if market else list(Market)
    if not tf.is_intraday:
        return [i for m in markets for i in service.instruments(s, m) if not i.is_index]
    follow: list[InstrumentRef] = []
    for m in markets:
        follow += service.default_symbols(s, m)
    seen = {i.id for i in follow}
    for desk in ctx.desk.desks():
        if desk.get("timeframe") == tf.value and (market is None or desk["market"] == market.value):
            for sym in desk.get("symbols") or []:
                inst = store.find_instrument(s, Market(desk["market"]), sym)
                if inst is not None and inst.id not in seen:
                    seen.add(inst.id)
                    follow.append(inst)
    return follow


@router.get("/data/coverage")
def data_coverage(ctx: Ctx, market: Market | None = None, timeframe: str = "1d") -> dict[str, Any]:
    """The whole data set in totals; stock by stock, only those with something wrong."""
    tf = _timeframe(timeframe)
    now = ctx.clock.now_ms()
    key = (market.value if market else "", tf.value)
    hit = _coverage_cache.get(key)
    if hit is not None and ctx.data_mode == "real":
        # answer at once and count again behind the scenes, so no one waits for the whole market
        if now - hit[0] >= COVERAGE_TTL_MS and key not in _coverage_busy:
            _coverage_busy.add(key)
            threading.Thread(
                target=_count_coverage,
                args=(ctx, market, tf, key),
                name="agora-coverage",
                daemon=True,
            ).start()
        return hit[1]
    return _count_coverage(ctx, market, tf, key)


def _count_coverage(
    ctx: AppContext, market: Market | None, tf: Timeframe, key: tuple[str, str]
) -> dict[str, Any]:
    now = ctx.clock.now_ms()
    try:
        return _coverage_body(ctx, market, tf, key, now)
    finally:
        _coverage_busy.discard(key)


def _coverage_body(
    ctx: AppContext, market: Market | None, tf: Timeframe, key: tuple[str, str], now: int
) -> dict[str, Any]:
    with ctx.db.session() as s:
        targets = _coverage_targets(s, ctx, market, tf)
        rows = service.coverage(s, ctx.calendar, targets, tf, now)
        out = [c.public(now) for c in rows]
        if tf.is_intraday:
            for item, c in zip(out, rows, strict=True):
                item["days"] = service.intraday_days(s, c.instrument, tf) if c.bars else 0
        last_update = s.scalar(
            select(DataFetchLog.started_at)
            .where(DataFetchLog.status.in_(("ok", "fallback")))
            .order_by(DataFetchLog.started_at.desc())
            .limit(1)
        )
    totals = {
        "symbols": len(out),
        "ok": sum(1 for r in out if r["status"] == "ok"),
        "empty": sum(1 for r in out if r["status"] == "empty"),
        "stale": sum(1 for r in out if r["status"] == "stale"),
        "gaps": sum(1 for r in out if r["status"] == "gaps"),
    }
    order = {"stale": 0, "gaps": 1, "empty": 2}
    wrong = sorted(
        (r for r in out if r["status"] != "ok"),
        key=lambda r: (order.get(r["status"], 3), -int(r.get("gaps") or 0)),
    )
    body = {
        "timeframe": tf.value,
        "rows": wrong[:SHOW_ROWS],
        "totals": totals,
        "last_update": last_update,
        "data_mode": ctx.data_mode,
    }
    _coverage_cache[key] = (now, body)
    return body


class RefreshBody(BaseModel):
    symbols: list[str] | None = None
    instrument_ids: list[int] | None = None
    market: Market | None = None
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])
    start: int | None = None
    end: int | None = None
    # "lists": the starter list (onboarding); "saved": every stock with saved prices (Data screen)
    scope: Literal["lists", "saved"] = "lists"


def _start_refresh(
    ctx: AppContext,
    targets: list[InstrumentRef],
    tfs: list[Timeframe],
    title: str,
    start: int | None = None,
    end: int | None = None,
    key: str | None = None,
) -> str:
    def run(job: JobContext) -> dict[str, Any]:
        summary = service.refresh(
            ctx.cache,
            targets,
            tfs,
            start_ms=start,
            end_ms=end,
            progress=job.progress,
            check_cancel=job.check,
            workers=4 if len(targets) > 20 else 1,
        )
        if summary.failed:
            job.progress(100.0, f"Finished. {len(summary.failed)} download(s) need a retry.")
        else:
            job.progress(100.0, "All prices are up to date.")
        return summary.public()

    return ctx.jobs.submit("data_refresh", title, run, key=key, single=key is not None).id


@router.post("/data/refresh", status_code=202)
def data_refresh(ctx: Ctx, body: RefreshBody) -> dict[str, Any]:
    tfs = [_timeframe(t) for t in body.timeframes] or [Timeframe.D1]
    with ctx.db.session() as s:
        targets: list[InstrumentRef] = []
        if body.instrument_ids:
            for iid in body.instrument_ids:
                inst = store.get_instrument(s, iid)
                if inst:
                    targets.append(inst)
        elif body.symbols:
            for sym in body.symbols:
                for m in [body.market] if body.market else list(Market):
                    inst = store.find_instrument(s, m, sym)
                    if inst:
                        targets.append(inst)
        else:
            for m in [body.market] if body.market else list(Market):
                if body.scope == "saved":
                    targets += service.saved_symbols(s, m, tfs[0])
                else:
                    targets += service.default_symbols(s, m)
    if not targets:
        raise AgoraError(
            "NOTHING_TO_REFRESH",
            "There are no stocks to download.",
            "Pick at least one stock.",
            status=422,
        )
    title = (
        f"Downloading {targets[0].symbol}"
        if len(targets) == 1
        else f"Downloading prices for {len(targets)} stocks"
    )
    whole = not (body.instrument_ids or body.symbols) and body.start is None and body.end is None
    key = f"{body.market or 'all'}:{','.join(t.value for t in tfs)}:{body.scope}" if whole else None
    job_id = _start_refresh(ctx, targets, tfs, title, body.start, body.end, key=key)
    return {"job_id": job_id}


# ---------------------------------------------------------------- candles & sources


@router.get("/candles")
def candles(
    ctx: Ctx,
    instrument_id: int,
    timeframe: str = "1d",
    start: int | None = None,
    end: int | None = None,
    adjusted_prices: Annotated[bool, Query(alias="adjusted")] = True,
    fetch: bool = False,
    full: bool = False,
    limit: int = Query(5000, ge=1, le=50_000),
) -> dict[str, Any]:
    """With ``full`` (and no ``start``) the chart gets all the history there is: whatever
    the sources still serve, plus every older candle Agora saved before they dropped it."""
    inst = _instrument(ctx, instrument_id)
    tf = _timeframe(timeframe)
    now = ctx.clock.now_ms()
    hi = end if end is not None else now + 1
    if start is not None:
        lo = start
    elif full:
        lo = service.full_start_ms(tf, now)
    else:
        lo = service.default_start_ms(tf, now)
    read_lo = lo
    if full and start is None:
        with ctx.db.session() as s:
            first = store.first_ts(s, inst.id, tf)
        if first is not None:
            read_lo = min(lo, first)
    note = None
    if fetch:
        result = ctx.cache.ensure(inst, tf, lo, hi)
        if result.problems:
            note = result.problems[0] + " Showing saved prices."
    bars = ctx.cache.bars(inst, tf, read_lo, hi)
    if len(bars) > limit:
        bars = bars[-limit:]
    shown = [adjusted(b) for b in bars] if adjusted_prices else bars
    return {
        "instrument": inst_json(inst),
        "timeframe": tf.value,
        "adjusted": adjusted_prices,
        "bars": [
            {
                "ts": b.ts,
                "open": round(b.open, 4),
                "high": round(b.high, 4),
                "low": round(b.low, 4),
                "close": round(b.close, 4),
                "volume": b.volume,
                "source": b.source,
            }
            for b in shown
        ],
        "note": note,
    }


SOURCE_LABEL = {
    "yahoo": "Yahoo Finance",
    "nse": "NSE end-of-day files",
    "stooq": "Stooq",
    "fake": "Practice data (synthetic)",
}


@router.get("/data/sources")
def data_sources(ctx: Ctx, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        states = store.source_states(s)
        sources = []
        for src in ctx.sources:
            st = states.get(src.name)
            state = st.state if st else "ok"
            if st and state == "cooling_down" and st.until and st.until <= now:
                state = "ok"
            sources.append(
                {
                    "source": src.name,
                    "label": SOURCE_LABEL.get(src.name, src.name),
                    "state": state,
                    "until": st.until if st else None,
                    "last_error": st.last_error if st else None,
                }
            )
        log_rows = s.scalars(
            select(DataFetchLog)
            .order_by(DataFetchLog.started_at.desc(), DataFetchLog.id.desc())
            .limit(limit)
        ).all()
        # only the stocks in these rows: loading all ~8,500 took seconds under load (D-113)
        ids = {r.instrument_id for r in log_rows if r.instrument_id is not None}
        names = dict(
            s.execute(select(Instrument.id, Instrument.symbol).where(Instrument.id.in_(ids))).all()
        )
        recent = [
            {
                "source": r.source,
                "symbol": names.get(r.instrument_id or -1),
                "timeframe": r.timeframe,
                "status": r.status,
                "rows": r.rows,
                "message": r.message,
                "at": r.started_at,
                "duration_ms": r.duration_ms,
            }
            for r in log_rows
        ]
    return {"sources": sources, "recent": recent, "server_time": now}


def _iso(ms: int) -> str:
    return ms_to_dt(ms, UTC).isoformat()
