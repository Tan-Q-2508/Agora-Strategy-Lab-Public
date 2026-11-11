"""Why Kairos misses opportunities: measured, not guessed (WEEKEND_BRIEF §4, task 27.5).

Take every big up day of the last weeks in stocks a desk could really have traded, and ask: was
the stock on a desk's list, did a desk want it, and what stopped it? Read-only, so it can be run
against the live database at any time.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

DAY_MS = 86_400_000
BIG_MOVE_PCT = 5.0
MIN_TRADED = {"IN": 2e8, "US": 2e7}  # the picker's thin-stock floor
TOP_N = 250


@dataclass
class Event:
    market: str
    symbol: str
    iid: int
    ts: int
    move_pct: float
    next5_pct: float | None
    traded: float
    rank: int
    verdict: str = ""
    detail: str = ""


@dataclass
class Report:
    days: int
    events: list[Event] = field(default_factory=list)
    refusals: Counter[str] = field(default_factory=Counter)

    def table(self, market: str) -> list[tuple[str, int, float]]:
        rows = [e for e in self.events if e.market == market]
        out: dict[str, list[float]] = {}
        for e in rows:
            out.setdefault(e.verdict, []).append(e.move_pct)
        return sorted(
            ((k, len(v), statistics.mean(v)) for k, v in out.items()), key=lambda r: -r[1]
        )


def _daily(c: sqlite3.Connection, market: str, since: int) -> dict[int, list[tuple[Any, ...]]]:
    rows = c.execute(
        """select c.instrument_id, i.symbol, c.ts, c.close, c.volume
           from candles c join instruments i on i.id = c.instrument_id
           where i.market_code = ? and c.timeframe = '1d' and c.ts >= ?
             and i.instrument_type = 'equity' and i.is_active = 1 and c.close > 0
           order by c.instrument_id, c.ts""",
        (market, since - 45 * DAY_MS),
    ).fetchall()
    out: dict[int, list[tuple[Any, ...]]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(r)
    return out


def _desk_history(c: sqlite3.Connection, market: str) -> list[dict[str, Any]]:
    """Each Kairos desk session with the stocks it followed and when."""
    out = []
    for sid, started, stopped, notes, definition in c.execute(
        """select s.id, s.started_at, s.stopped_at, s.notes, v.definition
           from paper_sessions s join strategy_versions v on v.id = s.strategy_version_id
           join strategies st on st.id = v.strategy_id
           where st.kind = 'kairos' and json_extract(v.definition, '$.market') = ?""",
        (market,),
    ):
        d = json.loads(definition)
        n = json.loads(notes or "{}")
        out.append(
            {
                "id": sid,
                "from": started,
                "to": stopped or int(time.time() * 1000),
                "symbols": set(n.get("symbols") or d.get("universe", {}).get("symbols") or []),
                "tf": d.get("timeframe"),
            }
        )
    return out


def _orders(c: sqlite3.Connection, market: str, since: int) -> dict[int, list[tuple[Any, ...]]]:
    out: dict[int, list[tuple[Any, ...]]] = {}
    for iid, ts, status, reason, side in c.execute(
        """select o.instrument_id, o.created_ts, o.status, o.reason, o.side
           from paper_orders o join paper_sessions s on s.id = o.session_id
           join paper_accounts a on a.id = s.account_id
           join strategy_versions v on v.id = s.strategy_version_id
           join strategies st on st.id = v.strategy_id
           where a.market_code = ? and st.kind = 'kairos' and o.created_ts >= ?""",
        (market, since),
    ):
        out.setdefault(iid, []).append((ts, status, reason, side))
    return out


def measure(c: sqlite3.Connection, days: int = 28, now_ms: int | None = None) -> Report:
    now = now_ms or int(time.time() * 1000)
    since = now - days * DAY_MS
    rep = Report(days)
    for market in ("IN", "US"):
        daily = _daily(c, market, since)
        desks = _desk_history(c, market)
        orders = _orders(c, market, since - 3 * DAY_MS)
        # money traded a day (20-day median) as it stood, day by day, for the most-traded rank
        by_day: dict[int, list[tuple[float, int]]] = {}
        medians: dict[tuple[int, int], float] = {}
        for iid, rows in daily.items():
            for i, r in enumerate(rows):
                past = [x[3] * x[4] for x in rows[max(0, i - 20) : i]]
                if len(past) < 10:
                    continue
                med = statistics.median(past)
                medians[(iid, r[2])] = med
                by_day.setdefault(r[2], []).append((med, iid))
        ranks: dict[tuple[int, int], int] = {}
        for ts, items in by_day.items():
            for n, (_m, iid) in enumerate(sorted(items, reverse=True), 1):
                ranks[(iid, ts)] = n
        for iid, rows in daily.items():
            for i in range(1, len(rows)):
                _, sym, ts, close, _vol = rows[i]
                if ts < since:
                    continue
                prev = rows[i - 1][3]
                move = 100 * (close / prev - 1)
                if move < BIG_MOVE_PCT or move > 100:  # above 100%: a data fault, not a move
                    continue
                traded = medians.get((iid, ts), 0.0)
                if traded < MIN_TRADED[market]:
                    continue
                later = rows[i + 5][3] if i + 5 < len(rows) else None
                e = Event(
                    market,
                    sym,
                    iid,
                    ts,
                    move,
                    100 * (later / close - 1) if later else None,
                    traded,
                    ranks.get((iid, ts), 9999),
                )
                _judge(e, desks, orders.get(iid, []))
                rep.events.append(e)
    for reason, n in c.execute(
        "select reason, count(*) from paper_orders where status='rejected' "
        "and created_ts >= ? group by 1",
        (since,),
    ):
        rep.refusals[reason[:70]] = n
    return rep


def _judge(e: Event, desks: list[dict[str, Any]], orders: list[tuple[Any, ...]]) -> None:
    window = [o for o in orders if e.ts - 2 * DAY_MS <= o[0] <= e.ts + DAY_MS]
    buys = [o for o in window if o[3] == "buy"]
    if any(o[1] == "filled" for o in buys):
        e.verdict, e.detail = "Traded", ""
        return
    refused = [o for o in buys if o[1] == "rejected"]
    if refused:
        e.verdict = "Wanted, refused: " + str(refused[0][2])[:44]
        return
    following = [d for d in desks if d["from"] <= e.ts <= d["to"] and e.symbol in d["symbols"]]
    if following:
        e.verdict = "Followed, no signal"
        return
    if e.rank <= TOP_N:
        e.verdict = "In the 250, not on a desk's list then"
    else:
        e.verdict = "Outside the 250"
