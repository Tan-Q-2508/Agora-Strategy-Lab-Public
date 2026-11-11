"""Is the saved market data believable? Read-only checks on recent candles (WEEKEND_BRIEF §3)."""

from __future__ import annotations

import sqlite3
import time
from collections import Counter

from backend.diagnosis.reconcile import Check

WEEK_MS = 7 * 86_400_000
BIG_MOVE = 0.45  # a close-to-close move this big needs a second look


def _since(days: int = 7) -> int:
    return int(time.time() * 1000) - days * 86_400_000


def impossible_candles(c: sqlite3.Connection) -> Check:
    chk = Check("impossible_candles", "Does any candle break high ≥ open, close ≥ low?")
    since = _since()
    chk.checked = int(c.execute("select count(*) from candles where ts>=?", (since,)).fetchone()[0])
    for iid, tf, ts, o, h, lo, cl in c.execute(
        """select instrument_id, timeframe, ts, open, high, low, close from candles
           where ts >= ? and (high < low or high < open or high < close or low > open
                              or low > close or low <= 0)
           limit 200""",
        (since,),
    ):
        chk.faults.append(f"instrument {iid} {tf} {ts}: O{o} H{h} L{lo} C{cl}")
    return chk


def flat_candles(c: sqlite3.Connection) -> Check:
    """A candle with open = high = low = close and real volume is a half-saved candle (ABB, the
    user's lead): a tick stored as a candle looks right and isn't."""
    chk = Check(
        "flat_candles",
        "Are there candles with one price but real volume (half-saved candles)?",
        severity="warning",
    )
    since = _since()
    rows = c.execute(
        """select i.symbol, c.timeframe, count(*) n, min(c.ts), max(c.ts), sum(c.volume)
           from candles c join instruments i on i.id = c.instrument_id
           where c.ts >= ? and c.timeframe in ('1d', '1h') and c.open = c.high and c.high = c.low
                 and c.low = c.close and c.volume > 0
           group by 1, 2 order by n desc""",
        (since,),
    ).fetchall()
    chk.checked = len(rows)
    by_source: Counter[str] = Counter()
    for row in c.execute(
        """select source, count(*) from candles where ts >= ? and timeframe in ('1d', '1h')
           and open = high and high = low and low = close and volume > 0 group by 1""",
        (since,),
    ):
        by_source[row[0]] = row[1]
    if by_source:
        chk.note = f"by source: {dict(by_source)}"
    for sym, tf, n, _a, _b, vol in rows[:40]:
        chk.faults.append(f"{sym} {tf}: {n} candles, volume {vol:,.0f}")
    return chk


def desk_stocks_have_candles(c: sqlite3.Connection) -> Check:
    """Every stock a live desk follows should have a recent candle on the desk's chart."""
    chk = Check(
        "desk_stocks_have_candles",
        "Does every stock on a live desk have recent candles on that desk's chart?",
    )
    import json

    for sid, notes, definition, market in c.execute(
        """select s.id, s.notes, v.definition, json_extract(v.definition, '$.market')
           from paper_sessions s join strategy_versions v on v.id = s.strategy_version_id
           join strategies st on st.id = v.strategy_id
           where s.state != 'stopped' and st.kind = 'kairos'"""
    ):
        n = json.loads(notes or "{}")
        d = json.loads(definition)
        tf = d.get("timeframe", "1d")
        syms = n.get("symbols") or d.get("universe", {}).get("symbols") or []
        if not syms:
            continue
        chk.checked += len(syms)
        recent = _since(6)
        have = {
            r[0]
            for r in c.execute(
                f"""select i.symbol from candles c join instruments i on i.id = c.instrument_id
                    where i.market_code = ? and c.timeframe = ? and c.ts >= ?
                    and i.symbol in ({",".join("?" * len(syms))}) group by 1""",
                (market, tf, recent, *syms),
            )
        }
        gone = sorted(set(syms) - have)
        if gone:
            chk.faults.append(
                f"session {sid} ({market} {tf}): {len(gone)} of {len(syms)} stocks have no "
                f"candle in 6 days: {', '.join(gone[:8])}"
            )
    return chk


def wild_moves(c: sqlite3.Connection) -> Check:
    """A huge daily move is either news or a bad price; list them to look at."""
    chk = Check(
        "wild_moves", "Any daily move over 45%? (real news or a bad price)", severity="warning"
    )
    since = _since(14)
    for sym, market, ts, prev, close in c.execute(
        """with d as (select instrument_id iid, ts, close * split_factor adj,
                             lag(close * split_factor) over
                               (partition by instrument_id order by ts) pc
                      from candles where timeframe = '1d' and ts >= ?)
           select i.symbol, i.market_code, d.ts, d.pc, d.adj
           from d join instruments i on i.id = d.iid
           where i.instrument_type = 'equity' and i.is_active = 1 and d.pc > 0
             and d.ts >= ? and abs(d.adj / d.pc - 1) > ? limit 60""",
        (since - 10 * 86_400_000, since, BIG_MOVE),
    ):
        chk.checked += 1
        chk.faults.append(f"{market} {sym} {ts}: {prev:g} → {close:g}")
    return chk


CHECKS = (impossible_candles, flat_candles, desk_stocks_have_candles, wild_moves)
