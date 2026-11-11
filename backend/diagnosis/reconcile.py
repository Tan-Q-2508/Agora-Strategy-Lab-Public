"""Do the paper books add up? Read-only checks on the saved fills, trades and money (§3).

Each check takes a read-only sqlite3 connection and returns a :class:`Check`, so the whole set can
be run against the live database while Agora trades, and in tests against a small one.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

# A fill can sit outside its candle by the account's slippage; anything past this is a real fault.
TOLERANCE = 0.0025
MONEY_TOLERANCE = 0.01  # share of a percent of the account: rounding, not a fault


@dataclass
class Check:
    name: str
    question: str  # what is being asked, in plain words
    checked: int = 0
    faults: list[str] = field(default_factory=list)
    note: str = ""
    severity: str = "error"  # error | warning

    @property
    def ok(self) -> bool:
        return not self.faults


def _sessions(c: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for sid, acct, cap, slip, market, state, notes, definition, stopped in c.execute(
        """select s.id, a.name, a.starting_capital, a.slippage_bps, a.market_code, s.state, s.notes,
                  v.definition, s.stopped_at
           from paper_sessions s join paper_accounts a on a.id = s.account_id
           join strategy_versions v on v.id = s.strategy_version_id"""
    ):
        d = json.loads(definition or "{}")
        out.append(
            {
                "id": sid,
                "account": acct,
                "capital": cap,
                "slippage_bps": slip,
                "market": market,
                "state": state,
                "notes": json.loads(notes or "{}"),
                "timeframe": d.get("timeframe", "1d"),
                "product": d.get("product", "delivery"),
                "stopped_at": stopped,
            }
        )
    return out


def fills_inside_candles(c: sqlite3.Connection) -> Check:
    """Every fill's price must be a price that traded in its candle."""
    chk = Check(
        "fills_inside_candles", "Is every paper fill inside the high and low of its candle?"
    )
    tf = {s["id"]: s for s in _sessions(c)}
    rows = c.execute(
        """select f.id, f.ts, f.price, o.session_id, o.instrument_id, i.symbol, o.side
           from paper_fills f join paper_orders o on o.id = f.order_id
           join instruments i on i.id = o.instrument_id"""
    ).fetchall()
    missing = 0
    for fid, ts, price, sid, iid, sym, side in rows:
        s = tf.get(sid)
        if s is None:
            continue
        chk.checked += 1
        bar = c.execute(
            "select low, high, split_factor from candles "
            "where instrument_id=? and timeframe=? and ts=?",
            (iid, s["timeframe"], ts),
        ).fetchone()
        if bar is None:
            missing += 1
            continue
        low, high, _ = bar
        slip = float(s["slippage_bps"] or 0) / 10_000 + TOLERANCE
        if not low * (1 - slip) <= price <= high * (1 + slip):
            chk.faults.append(
                f"session {sid} {sym} {side} at {price:g} outside {low:g} to {high:g} (fill {fid})"
            )
    if missing:
        chk.note = f"{missing} fills have no saved candle at their time to check against"
    return chk


def trade_arithmetic(c: sqlite3.Connection) -> Check:
    """Gross, charges and net must agree on each closed trade."""
    chk = Check("trade_arithmetic", "Does each trade's gross minus charges equal its net?")
    for tid, sid, sym, side, qty, ep, xp, gross, charges, net, ets, xts in c.execute(
        """select t.id, t.session_id, i.symbol, t.side, t.qty, t.entry_price, t.exit_price,
                  t.gross_pnl, t.charges, t.net_pnl, t.entry_ts, t.exit_ts
           from paper_trades t join instruments i on i.id = t.instrument_id"""
    ):
        chk.checked += 1
        where = f"session {sid} {sym} trade {tid}"
        if xts is not None and xts < ets:
            chk.faults.append(f"{where}: exits before it enters")
        if qty <= 0:
            chk.faults.append(f"{where}: quantity {qty}")
        if abs(gross - charges - net) > max(0.02, abs(net) * 1e-6):
            chk.faults.append(f"{where}: {gross:.2f} − {charges:.2f} ≠ {net:.2f}")
        if xp is not None:
            sign = 1 if side == "long" else -1
            expect = sign * (xp - ep) * qty
            if abs(expect - gross) > max(1.0, abs(expect) * 0.01):
                chk.faults.append(f"{where}: gross {gross:.2f} but prices give {expect:.2f}")
        if charges < 0:
            chk.faults.append(f"{where}: negative charges {charges}")
    return chk


def duplicate_trades(c: sqlite3.Connection) -> Check:
    chk = Check("duplicate_trades", "Was any trade recorded twice?")
    chk.checked = int(c.execute("select count(*) from paper_trades").fetchone()[0])
    for sid, iid, ets, n in c.execute(
        """select session_id, instrument_id, entry_ts, count(*) from paper_trades
           group by 1, 2, 3 having count(*) > 1"""
    ):
        chk.faults.append(f"session {sid} instrument {iid} entry {ets}: {n} copies")
    return chk


def money_adds_up(c: sqlite3.Connection) -> Check:
    """Starting money + closed trades + what open trades have cost = cash; cash + open trades'
    value = equity. Open trades are read from the engine's saved state: they carry their entry
    charges and any part already sold, which no closed-trade total includes."""
    chk = Check("money_adds_up", "Does starting money plus every trade equal the money shown?")
    for s in _sessions(c):
        snap = s["notes"].get("engine")
        last = c.execute(
            "select ts, equity, cash, unrealized_pnl from paper_equity "
            "where session_id=? order by ts desc limit 1",
            (s["id"],),
        ).fetchone()
        if snap is None or last is None:
            continue
        chk.checked += 1
        moved = float(s["notes"].get("moved") or 0.0)
        net = c.execute(
            "select coalesce(sum(net_pnl), 0) from paper_trades where session_id=?", (s["id"],)
        ).fetchone()[0]
        spent = 0.0
        for p in (snap.get("positions") or {}).values():
            start = float(p.get("start_qty") or p["qty"])
            sign = 1.0 if p["side"] == "long" else -1.0
            entry_charges = sum(float(v) for v in p["entry_charges"].values())
            sold_charges = sum(float(v) for v in (p.get("sold_charges") or {}).values())
            spent += sign * start * float(p["entry_price"]) + entry_charges + sold_charges
            spent -= sign * float(p.get("sold_value") or 0.0) + float(p.get("dividends") or 0.0)
        cash = float(snap["cash"])
        expect = float(s["capital"]) + moved + net - spent
        gap = cash - expect
        if abs(gap) > max(1.0, float(s["capital"]) * MONEY_TOLERANCE / 100):
            chk.faults.append(
                f"session {s['id']} ({s['account']}, {s['state']}): cash {cash:,.2f}, "
                f"trades give {expect:,.2f}, gap {gap:,.2f}"
            )
    return chk


def equity_series_steps(c: sqlite3.Connection) -> Check:
    """Money must not jump far between two points unless trades explain it."""
    chk = Check(
        "equity_series_steps", "Does the money chart ever jump with no reason?", severity="warning"
    )
    for s in _sessions(c):
        rows = c.execute(
            "select ts, equity from paper_equity where session_id=? order by ts", (s["id"],)
        ).fetchall()
        chk.checked += len(rows)
        for (t0, e0), (t1, e1) in itertools.pairwise(rows):
            if e0 > 0 and abs(e1 / e0 - 1) > 0.10:
                chk.faults.append(
                    f"session {s['id']} ({s['account']}) moved {100 * (e1 / e0 - 1):+.1f}% "
                    f"between {t0} and {t1}"
                )
    return chk


def intraday_closed_same_day(c: sqlite3.Connection) -> Check:
    """An intraday trade may not stay open past its day: no overnight risk on an intraday desk."""
    chk = Check("intraday_closed_same_day", "Did every intraday trade close the day it opened?")
    from datetime import UTC, datetime, timedelta

    offset = {"IN": timedelta(hours=5, minutes=30), "US": timedelta(hours=-5)}
    for s in _sessions(c):
        if s["product"] != "intraday":
            continue
        for sym, ets, xts in c.execute(
            """select i.symbol, t.entry_ts, t.exit_ts from paper_trades t
               join instruments i on i.id = t.instrument_id
               where t.session_id=? and t.exit_ts is not null""",
            (s["id"],),
        ):
            chk.checked += 1
            off = offset.get(s["market"], timedelta())
            a = (datetime.fromtimestamp(ets / 1000, UTC) + off).date()
            b = (datetime.fromtimestamp(xts / 1000, UTC) + off).date()
            if a != b:
                chk.faults.append(f"session {s['id']} {sym} opened {a}, closed {b}")
    return chk


def one_desk_per_slot(c: sqlite3.Connection) -> Check:
    """Two live sessions on one Kairos desk would trade the same money twice."""
    chk = Check("one_desk_per_slot", "Is only one session running for each Kairos desk?")
    seen: dict[tuple[str, str], list[int]] = {}
    for sid, tf, market in c.execute(
        """select s.id, json_extract(v.definition, '$.timeframe'),
                  json_extract(v.definition, '$.market')
           from paper_sessions s join strategy_versions v on v.id = s.strategy_version_id
           join strategies st on st.id = v.strategy_id
           where st.kind = 'kairos' and s.state != 'stopped'"""
    ):
        chk.checked += 1
        seen.setdefault((str(market), str(tf)), []).append(sid)
    for slot, ids in seen.items():
        if len(ids) > 1:
            chk.faults.append(f"{slot}: sessions {ids} are all live")
    return chk


CHECKS = (
    fills_inside_candles,
    trade_arithmetic,
    duplicate_trades,
    money_adds_up,
    equity_series_steps,
    intraday_closed_same_day,
    one_desk_per_slot,
)
