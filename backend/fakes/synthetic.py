"""Deterministic synthetic market data for tests, replays and cloud development.

The cloud sessions that build Agora usually can't reach Yahoo, so every test runs on this
data instead (CLAUDE.md §3). It is generated from a fixed seed with plain Python (no
numpy), written as gzip CSV with a zeroed timestamp, so re-running the generator produces
byte-identical files and a test can prove nothing drifted.

The data deliberately contains the awkward cases real data has (docs/DATA_SOURCES.md §9):
splits, dividends, a missing-data gap, an overnight price gap, a circuit-locked bar,
holidays and early closes. ``manifest.json`` lists exactly where each one is so tests can
look them up instead of hard-coding dates.

The holiday calendar here is a simplified, fixture-only calendar. Real calendars come
from ``pandas_market_calendars`` in Phase 2.3.
"""

from __future__ import annotations

import gzip
import io
import json
import math
import random
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market

SEED = 20261020
START = date(2016, 1, 1)
END = date(2025, 12, 31)
INTRADAY_SESSIONS = 60  # 5m and 1h cover the last 60 sessions (like Yahoo's 60-day window)
ONE_MINUTE_SESSIONS = 5  # 1m covers the last 5 sessions
MS_PER_MIN = 60_000

SESSION_HOURS: dict[Market, tuple[time, time]] = {
    Market.IN: (time(9, 15), time(15, 30)),
    Market.US: (time(9, 30), time(16, 0)),
}
TICK: dict[Market, float] = {Market.IN: 0.05, Market.US: 0.01}


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    market: Market
    yahoo_symbol: str
    kind: str  # equity | etf | index
    start_price: float
    drift: float  # mean daily return
    vol: float  # daily return standard deviation
    base_volume: float


def _in(sym: str, price: float, drift: float, vol: float, volume: float) -> SymbolSpec:
    return SymbolSpec(sym, Market.IN, f"{sym}.NS", "equity", price, drift, vol, volume)


def _us(
    sym: str, price: float, drift: float, vol: float, volume: float, kind: str = "equity"
) -> SymbolSpec:
    return SymbolSpec(sym, Market.US, sym, kind, price, drift, vol, volume)


SYMBOLS: tuple[SymbolSpec, ...] = (
    _in("RELIANCE", 1000.0, 0.0005, 0.017, 8e6),
    _in("TCS", 2400.0, 0.0004, 0.014, 2.5e6),
    _in("HDFCBANK", 1050.0, 0.0004, 0.013, 7e6),
    _in("INFY", 1100.0, 0.0004, 0.016, 6e6),
    _in("ICICIBANK", 250.0, 0.0006, 0.018, 1.5e7),
    _in("SBIN", 220.0, 0.0005, 0.020, 2e7),
    _in("ITC", 220.0, 0.0003, 0.013, 1.5e7),
    _in("LT", 1300.0, 0.0004, 0.016, 2e6),
    _in("BHARTIARTL", 300.0, 0.0006, 0.017, 7e6),
    _in("MARUTI", 4500.0, 0.0003, 0.015, 8e5),
    SymbolSpec("NIFTY50", Market.IN, "^NSEI", "index", 7900.0, 0.0004, 0.010, 0.0),
    _us("SPY", 200.0, 0.0004, 0.011, 8e7, "etf"),
    _us("QQQ", 105.0, 0.0006, 0.014, 4e7, "etf"),
    _us("AAPL", 105.0, 0.0008, 0.018, 1e8),
    _us("MSFT", 55.0, 0.0009, 0.016, 3e7),
    _us("NVDA", 33.0, 0.0018, 0.030, 4e7),
    _us("AMZN", 650.0, 0.0006, 0.020, 4e6),
    _us("GOOGL", 750.0, 0.0006, 0.017, 2e6),
    _us("META", 105.0, 0.0006, 0.022, 2e7),
    _us("TSLA", 45.0, 0.0012, 0.035, 2.5e7),
    _us("JPM", 63.0, 0.0005, 0.016, 1.2e7),
)
INTRADAY_SYMBOLS = ("RELIANCE", "INFY", "AAPL", "SPY")

# Special cases baked into the daily data. Dates snap forward to the next session.
SPLITS = {"RELIANCE": (date(2020, 6, 1), 2.0), "NVDA": (date(2021, 7, 20), 4.0)}
DIVIDENDS = {
    "ITC": [(date(2023, 5, 30), 6.0), (date(2024, 6, 4), 6.25)],
    "AAPL": [(date(2022, 8, 5), 0.23), (date(2023, 8, 11), 0.24)],
}
DATA_GAP = ("TCS", date(2022, 3, 14), 3)  # three sessions missing from the file
PRICE_GAP = ("INFY", date(2023, 4, 17), -0.08)  # opens 8% below the previous close
CIRCUIT = ("SBIN", date(2021, 5, 4), 0.05)  # locked 5% up: open == high == low == close


# ---------------------------------------------------------------- fixture calendar


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def fixture_holidays(market: Market, start: date = START, end: date = END) -> list[date]:
    out: list[date] = []
    for year in range(start.year, end.year + 1):
        if market is Market.IN:
            days = [date(year, 1, 26), date(year, 8, 15), date(year, 10, 2), date(year, 12, 25)]
        else:
            days = [
                date(year, 1, 1),
                date(year, 7, 4),
                date(year, 12, 25),
                _nth_weekday(year, 11, 3, 4),
            ]  # Thanksgiving: 4th Thursday of November
        out.extend(d for d in days if d.weekday() < 5 and start <= d <= end)
    return sorted(out)


def fixture_early_closes(market: Market, start: date = START, end: date = END) -> dict[date, time]:
    if market is Market.IN:
        return {}
    out: dict[date, time] = {}
    for year in range(start.year, end.year + 1):
        for d in (_nth_weekday(year, 11, 3, 4) + timedelta(days=1), date(year, 12, 24)):
            if d.weekday() < 5 and start <= d <= end:
                out[d] = time(13, 0)
    return out


def fixture_sessions(market: Market, start: date = START, end: date = END) -> list[date]:
    closed = set(fixture_holidays(market, start, end))
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in closed:
            days.append(d)
        d += timedelta(days=1)
    return days


def session_bounds_ms(market: Market, day: date, early: dict[date, time]) -> tuple[int, int]:
    tz = ZoneInfo(MARKET_TZ[market])
    open_t, close_t = SESSION_HOURS[market]
    close_t = early.get(day, close_t)
    o = datetime.combine(day, open_t, tz)
    c = datetime.combine(day, close_t, tz)
    return int(o.timestamp() * 1000), int(c.timestamp() * 1000)


def _snap(day: date, sessions: list[date]) -> date:
    for s in sessions:
        if s >= day:
            return s
    raise ValueError(f"No session on or after {day}")


# ---------------------------------------------------------------- generation


Row = tuple[int, float, float, float, float, float, float]  # ts,o,h,l,c,v,split_factor


def _round(x: float, tick: float) -> float:
    return round(round(x / tick) * tick, 2)


def _rng(symbol: str, salt: str = "") -> random.Random:
    return random.Random(SEED ^ zlib.crc32(f"{symbol}{salt}".encode()))


def _daily(
    spec: SymbolSpec, sessions: list[date], early: dict[date, time]
) -> tuple[list[Row], list[dict[str, Any]]]:
    """Daily bars in RAW (as-traded) prices plus the corporate actions applied."""
    rng = _rng(spec.symbol)
    tick = TICK[spec.market]
    split = SPLITS.get(spec.symbol)
    split_day = _snap(split[0], sessions) if split else None
    split_factor_pre = 1.0 / split[1] if split else 1.0
    divs = {_snap(d, sessions): amt for d, amt in DIVIDENDS.get(spec.symbol, [])}
    gap_day = _snap(PRICE_GAP[1], sessions) if spec.symbol == PRICE_GAP[0] else None
    circuit_day = _snap(CIRCUIT[1], sessions) if spec.symbol == CIRCUIT[0] else None

    rows: list[Row] = []
    actions: list[dict[str, Any]] = []
    adj_close = spec.start_price  # path in today's split-adjusted terms
    for day in sessions:
        ts, _ = session_bounds_ms(spec.market, day, early)
        pre_split = split_day is not None and day < split_day
        factor = split_factor_pre if pre_split else 1.0
        gap = rng.gauss(0.0, spec.vol * 0.3)
        ret = rng.gauss(spec.drift, spec.vol)
        wick_hi = abs(rng.gauss(0.0, spec.vol * 0.4))
        wick_lo = abs(rng.gauss(0.0, spec.vol * 0.4))
        vol_noise = rng.lognormvariate(0.0, 0.35)
        if day == gap_day:
            gap = PRICE_GAP[2]
        if day in divs:
            gap = -divs[day] / adj_close
            actions.append({"ex_date": ts, "kind": "dividend", "ratio": None, "amount": divs[day]})
        if day == split_day and split:
            actions.append({"ex_date": ts, "kind": "split", "ratio": split[1], "amount": None})
        o = adj_close * (1 + gap)
        c = o * (1 + ret)
        h = max(o, c) * (1 + wick_hi)
        lo = min(o, c) * (1 - wick_lo)
        volume = round(spec.base_volume * vol_noise)
        if day == circuit_day:
            o = h = lo = c = adj_close * (1 + CIRCUIT[2])
            volume = round(spec.base_volume * 0.05)
        # Convert to raw prices: before a 2:1 split, shares traded at twice today's terms.
        raw = [_round(p / factor, tick) for p in (o, h, lo, c)]
        raw[1] = max(raw)
        raw[2] = min(raw)
        raw_volume = float(round(volume * factor))
        rows.append((ts, raw[0], raw[1], raw[2], raw[3], raw_volume, factor))
        adj_close = raw[3] * factor
    return rows, actions


def _intraday_1m(
    spec: SymbolSpec, sessions: list[date], early: dict[date, time], prev_close: float
) -> list[Row]:
    rng = _rng(spec.symbol, "intraday")
    tick = TICK[spec.market]
    rows: list[Row] = []
    last = prev_close
    for day in sessions:
        start_ms, end_ms = session_bounds_ms(spec.market, day, early)
        n = (end_ms - start_ms) // MS_PER_MIN
        sigma = spec.vol / math.sqrt(n)
        price = last * (1 + rng.gauss(0.0, spec.vol * 0.3))
        for i in range(n):
            o = price
            c = o * (1 + rng.gauss(spec.drift / n, sigma))
            h = max(o, c) * (1 + abs(rng.gauss(0.0, sigma * 0.5)))
            lo = min(o, c) * (1 - abs(rng.gauss(0.0, sigma * 0.5)))
            u_shape = 1.0 + 2.0 * ((i - n / 2) / (n / 2)) ** 2  # busier at open and close
            v = float(round(spec.base_volume / n * u_shape * rng.lognormvariate(0.0, 0.4)))
            raw = [_round(p, tick) for p in (o, h, lo, c)]
            raw[1] = max(raw)
            raw[2] = min(raw)
            rows.append((start_ms + i * MS_PER_MIN, raw[0], raw[1], raw[2], raw[3], v, 1.0))
            price = raw[3]
        last = price
    return rows


def _aggregate(rows: list[Row], bucket_ms: int, sessions_ms: list[tuple[int, int]]) -> list[Row]:
    """Group 1m rows into buckets anchored at each session's open (like Yahoo does)."""
    out: list[Row] = []
    idx = 0
    for start, end in sessions_ms:
        groups: dict[int, list[Row]] = {}
        while idx < len(rows) and rows[idx][0] < end:
            r = rows[idx]
            if r[0] >= start:
                groups.setdefault(start + (r[0] - start) // bucket_ms * bucket_ms, []).append(r)
            idx += 1
        for ts in sorted(groups):
            g = groups[ts]
            out.append(
                (
                    ts,
                    g[0][1],
                    max(r[2] for r in g),
                    min(r[3] for r in g),
                    g[-1][4],
                    sum(r[5] for r in g),
                    1.0,
                )
            )
    return out


def generate() -> dict[str, Any]:
    """Build every fixture in memory: ``{"files": {relpath: rows}, "manifest": {...}}``."""
    files: dict[str, list[Row]] = {}
    actions: dict[str, list[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []
    cal: dict[Market, tuple[list[date], dict[date, time]]] = {
        m: (fixture_sessions(m), fixture_early_closes(m)) for m in Market
    }
    for spec in SYMBOLS:
        sessions, early = cal[spec.market]
        rows, acts = _daily(spec, sessions, early)
        if acts:
            actions[spec.symbol] = acts
        if spec.symbol in INTRADAY_SYMBOLS:
            window = sessions[-INTRADAY_SESSIONS:]
            window_ms = [session_bounds_ms(spec.market, d, early) for d in window]
            keep = len(rows) - INTRADAY_SESSIONS
            prev_close = rows[keep - 1][4]
            m1 = _intraday_1m(spec, window, early, prev_close)
            m5 = _aggregate(m1, 5 * MS_PER_MIN, window_ms)
            h1 = _aggregate(m1, 60 * MS_PER_MIN, window_ms)
            day_rows = _aggregate(m1, 24 * 60 * MS_PER_MIN, window_ms)
            rows = rows[:keep] + day_rows  # daily bars agree exactly with the intraday data
            first_1m = window_ms[-ONE_MINUTE_SESSIONS][0]
            files[f"{spec.market}/{spec.symbol}_1m.csv.gz"] = [r for r in m1 if r[0] >= first_1m]
            files[f"{spec.market}/{spec.symbol}_5m.csv.gz"] = m5
            files[f"{spec.market}/{spec.symbol}_1h.csv.gz"] = h1
        if spec.symbol == DATA_GAP[0]:
            first = _snap(DATA_GAP[1], sessions)
            i = sessions.index(first)
            missing = {
                session_bounds_ms(spec.market, d, early)[0] for d in sessions[i : i + DATA_GAP[2]]
            }
            rows = [r for r in rows if r[0] not in missing]
            events.append(
                {
                    "kind": "data_gap",
                    "symbol": spec.symbol,
                    "timeframe": "1d",
                    "dates": [d.isoformat() for d in sessions[i : i + DATA_GAP[2]]],
                    "ts": sorted(missing),
                    "note": "These sessions are missing from the file on purpose.",
                }
            )
        files[f"{spec.market}/{spec.symbol}_1d.csv.gz"] = rows

    for sym, (_day, ratio) in SPLITS.items():
        a = next(x for x in actions[sym] if x["kind"] == "split")
        events.append(
            {
                "kind": "split",
                "symbol": sym,
                "date": _iso(a["ex_date"], sym),
                "ts": a["ex_date"],
                "ratio": ratio,
            }
        )
    for sym in DIVIDENDS:
        for a in (x for x in actions[sym] if x["kind"] == "dividend"):
            events.append(
                {
                    "kind": "dividend",
                    "symbol": sym,
                    "date": _iso(a["ex_date"], sym),
                    "ts": a["ex_date"],
                    "amount": a["amount"],
                }
            )
    for kind, (sym, d, size) in (("price_gap", PRICE_GAP), ("circuit_locked", CIRCUIT)):
        spec = _spec(sym)
        day = _snap(d, cal[spec.market][0])
        events.append(
            {
                "kind": kind,
                "symbol": sym,
                "date": day.isoformat(),
                "size": size,
                "ts": session_bounds_ms(spec.market, day, cal[spec.market][1])[0],
            }
        )

    manifest = {
        "generator": "backend/fakes/synthetic.py",
        "seed": SEED,
        "range": [START.isoformat(), END.isoformat()],
        "note": "Synthetic data for tests only. Not real prices.",
        "columns": ["ts", "open", "high", "low", "close", "volume", "split_factor"],
        "symbols": {
            s.symbol: {
                "market": s.market.value,
                "yahoo_symbol": s.yahoo_symbol,
                "type": s.kind,
                "timeframes": ["1d", "1h", "5m", "1m"] if s.symbol in INTRADAY_SYMBOLS else ["1d"],
            }
            for s in SYMBOLS
        },
        "sessions": {
            m.value: {
                "open": SESSION_HOURS[m][0].strftime("%H:%M"),
                "close": SESSION_HOURS[m][1].strftime("%H:%M"),
                "timezone": MARKET_TZ[m],
            }
            for m in Market
        },
        "holidays": {m.value: [d.isoformat() for d in fixture_holidays(m)] for m in Market},
        "early_closes": {
            m.value: {
                d.isoformat(): t.strftime("%H:%M") for d, t in fixture_early_closes(m).items()
            }
            for m in Market
        },
        "corporate_actions": actions,
        "events": events,
    }
    return {"files": files, "manifest": manifest}


def _spec(symbol: str) -> SymbolSpec:
    return next(s for s in SYMBOLS if s.symbol == symbol)


def _iso(ts: int, symbol: str) -> str:
    tz = ZoneInfo(MARKET_TZ[_spec(symbol).market])
    return ms_to_dt(ts, tz).date().isoformat()


def encode_csv_gz(rows: list[Row]) -> bytes:
    text = io.StringIO()
    text.write("ts,open,high,low,close,volume,split_factor\n")
    for ts, o, h, lo, c, v, f in rows:
        text.write(f"{ts},{o:.2f},{h:.2f},{lo:.2f},{c:.2f},{v:.0f},{f:g}\n")
    buf = io.BytesIO()
    # mtime=0 and no filename keep the bytes identical on every run.
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(text.getvalue().encode())
    return buf.getvalue()


def write_fixtures(out_dir: Path) -> list[Path]:
    data = generate()
    written: list[Path] = []
    for rel, rows in sorted(data["files"].items()):
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode_csv_gz(rows))
        written.append(path)
    manifest = out_dir / "manifest.json"
    manifest.write_text(json.dumps(data["manifest"], indent=1, sort_keys=True) + "\n")
    written.append(manifest)
    return written
