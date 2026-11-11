"""Backtest vs live (SPEC §7.5): run a backtest of the same strategy, account and days as
a paper session, and explain any difference in plain English.

Both use the same engine and the same stored candles (the live feed saves every candle it
uses), so differences have concrete causes: times Agora was closed (gaps), late prices
that blocked new trades, pauses, or prices that were revised after the live session
saw them. With none of those, the two match exactly (pinned by tests/paper).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from backend.backtest.run import NoData, RunSpec, run
from backend.core.types import Market, Timeframe
from backend.db.models import (
    BrokerageProfile,
    PaperAccount,
    PaperEquity,
    PaperEvent,
    PaperSession,
    PaperTrade,
)
from backend.errors import AgoraError
from backend.markets.calendar import sessions_between_ms
from backend.paper.runner import with_session_settings
from backend.paper.timing import bar_end_ms, bar_open_for_close, next_bar_close
from backend.settings_store import read_all
from backend.strategy import service as strategies

MIN_SESSIONS = 5  # fewer trading days than this say too little to compare


def vs_backtest(ctx: Any, sid: int) -> dict[str, Any]:
    with ctx.db.session() as s:
        row = s.get(PaperSession, sid)
        if row is None:
            raise AgoraError(
                "NOT_FOUND", "That paper session doesn't exist.", "Go back.", status=404
            )
        acct = s.get(PaperAccount, row.account_id)
        version = strategies.get_version(s, row.strategy_version_id)
        assert acct is not None and version is not None
        profile = s.get(BrokerageProfile, acct.brokerage_profile_id)
        assert profile is not None
        notes = json.loads(row.notes or "{}")
        d = with_session_settings(version.definition, notes)  # the session's own (D-80)
        market, tf = Market(d.market), Timeframe(d.timeframe)
        insts, _, _ = ctx.backtests._instruments(s, d, notes.get("symbols") or None, market)
        settings = read_all(s)
        points = s.execute(
            select(PaperEquity.ts, PaperEquity.equity)
            .where(PaperEquity.session_id == sid)
            .order_by(PaperEquity.ts)
        ).all()
        live_trades = s.scalars(select(PaperTrade).where(PaperTrade.session_id == sid)).all()
        live_rows = [
            (t.instrument_id, t.entry_ts, t.exit_ts, t.net_pnl, t.side) for t in live_trades
        ]
        n_late = len(
            s.scalars(
                select(PaperEvent.id).where(
                    PaperEvent.session_id == sid, PaperEvent.kind.in_(("outage", "delayed"))
                )
            ).all()
        )
        n_paused = len(
            s.scalars(
                select(PaperEvent.id).where(
                    PaperEvent.session_id == sid, PaperEvent.kind == "paused"
                )
            ).all()
        )
        capital = acct.starting_capital
        started_at = row.started_at
        rules = json.loads(profile.rules)
        slippage = acct.slippage_bps
    if not points:
        return {
            "ready": False,
            "message": "The comparison appears once the session has traded a few days.",
        }
    first_close = next_bar_close(ctx.calendar, market, tf, started_at)
    start = (
        bar_open_for_close(ctx.calendar, market, tf, first_close)
        if first_close is not None
        else points[0].ts
    )
    start = min(start, points[0].ts)
    end = bar_end_ms(ctx.calendar, market, tf, points[-1].ts)
    days = len(sessions_between_ms(ctx.calendar, market, start, end))
    if days < MIN_SESSIONS:
        return {
            "ready": False,
            "message": f"The comparison appears after {MIN_SESSIONS} trading days ({days} so far).",
            "days": days,
        }
    spec = RunSpec(
        definition=d,
        instruments=insts,
        timeframe=tf,
        start_ms=start,
        end_ms=points[-1].ts + 1,
        capital=capital,
        brokerage_rules=rules,
        slippage_bps=slippage,
        volume_cap_pct=float(settings["volume_cap_pct"]),
        square_off=str(settings["intraday_square_off_time"]),
        overrides={k: float(v) for k, v in notes.get("overrides", {}).items()},
        history_from_ms=notes.get("history_from"),
    )
    try:
        out = run(ctx.cache, spec)
    except NoData:
        return {"ready": False, "message": "No saved prices for these days yet."}
    names = {i.id: i.symbol for i in insts}
    bt_rows = [
        (t.instrument_id, t.entry_ts, t.exit_ts, t.net_pnl, t.side) for t in out.trades if t.closed
    ]
    live_keys = {(r[0], r[1], r[4]) for r in live_rows}
    bt_keys = {(r[0], r[1], r[4]) for r in bt_rows}
    only_bt = sorted(bt_keys - live_keys, key=lambda k: k[1])
    only_live = sorted(live_keys - bt_keys, key=lambda k: k[1])
    live_final = points[-1][1]
    bt_final = out.equity[-1].equity if out.equity else capital
    live_ret = 100.0 * (live_final / capital - 1.0)
    bt_ret = 100.0 * (bt_final / capital - 1.0)
    gaps = notes.get("gaps", [])
    reasons = _reasons(
        len(live_rows), len(bt_rows), live_ret, bt_ret, gaps, n_late, n_paused, only_bt, only_live
    )
    first_list = d.universe.symbols if d.universe.kind == "symbols" else []
    if notes.get("symbols") and first_list and set(notes["symbols"]) != set(first_list):
        # the backtest runs today's list over the whole session (D-217): US hourly's 251 stocks
        # against the 20 it really followed read as "no trades in common"
        reasons.insert(
            0,
            f"This desk's stocks changed during the session ({len(first_list)} to "
            f"{len(notes['symbols'])}). The backtest used today's list for every day, so the two "
            "can't be compared trade by trade.",
        )
    return {
        "ready": True,
        "days": days,
        "start": start,
        "end": end,
        "live": _side(live_ret, live_rows, live_final),
        "backtest": _side(bt_ret, bt_rows, bt_final),
        "matched_trades": len(live_keys & bt_keys),
        "only_backtest": [_trade_key(k, names) for k in only_bt[:20]],
        "only_live": [_trade_key(k, names) for k in only_live[:20]],
        "series": [
            {
                "label": "Paper trading",
                "points": [{"ts": t, "value": 100.0 * v / capital} for t, v in points],
            },
            {
                "label": "Backtest",
                "points": [{"ts": p.ts, "value": 100.0 * p.equity / capital} for p in out.equity],
            },
        ],
        "reasons": reasons,
        "gaps": gaps,
    }


def _side(ret: float, rows: list[Any], final: float) -> dict[str, Any]:
    wins = [r for r in rows if r[3] > 0]
    return {
        "total_return": ret,
        "final_equity": final,
        "trades": len(rows),
        "win_rate": len(wins) / len(rows) if rows else None,
        "net_pnl": sum(r[3] for r in rows),
    }


def _trade_key(k: tuple[int, int, str], names: dict[int, str]) -> dict[str, Any]:
    return {"symbol": names.get(k[0], "?"), "entry_ts": k[1], "side": k[2]}


def _reasons(
    n_live: int,
    n_bt: int,
    live_ret: float,
    bt_ret: float,
    gaps: list[Any],
    n_late: int,
    n_paused: int,
    only_bt: list[Any],
    only_live: list[Any],
) -> list[str]:
    out: list[str] = []
    diff = live_ret - bt_ret
    if abs(diff) < 0.005 and not only_bt and not only_live:
        out.append("Paper trading and the backtest made exactly the same trades.")
        return out
    out.append(
        f"Paper trading returned {live_ret:+.2f}%, the backtest {bt_ret:+.2f}% "
        f"({abs(diff):.2f} percentage points {'better' if diff > 0 else 'worse'} live)."
    )
    if n_live != n_bt:
        out.append(f"The backtest made {n_bt} trade(s); paper trading made {n_live}.")
    if gaps:
        out.append(
            f"Agora was closed {len(gaps)} time(s) during this session. The backtest traded "
            "through those times; paper trading couldn't."
        )
    if n_late:
        out.append(
            "Live prices were late or missing at times, and no new trades open on late prices."
        )
    if n_paused:
        out.append("You paused the session at times; no new trades opened while paused.")
    if (only_bt or only_live) and not (gaps or n_late or n_paused):
        out.append(
            "Some prices were revised after paper trading saw them, so the backtest saw "
            "slightly different candles."
        )
    return out
