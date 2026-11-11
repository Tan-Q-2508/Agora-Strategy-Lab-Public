"""Paper trading a portfolio (PORTFOLIO §6, D-86).

**Start** opens one paper session per planned sleeve (its revision, stocks, settings, trade size
and money; D-80) and keeps the rest of the budget as the portfolio's cash. While Agora is open
the **manager** (a thread, checked once a minute; never when Agora is closed, D-06):

- rebalances on the first market day of each month and when a sleeve drifts more than 25% from
  its target, moving only free cash (``PaperRunner.transfer``);
- with *Manage on its own* on, reviews the portfolio monthly: a sleeve whose live loss from its
  peak is more than twice its backtest's worst drop, or that the new plan no longer picks after
  a month, is **wound down** (paused: no new trades, open trades end by their own rules; once
  flat it is stopped and its money returns to the cash); sleeves the new plan picks are added,
  funded from the cash.

It only acts on portfolios the user started paper trading. Orders still come only from the
strategies in the shared engine; the AI never sets a weight or places an order (D-56).
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market
from backend.db.models import (
    Opportunity,
    PaperEquity,
    PaperSession,
    Portfolio,
    PortfolioSleeve,
)
from backend.errors import AgoraError
from backend.logging_setup import get_logger
from backend.metrics.summary import money
from backend.paper.service import AccountIn, SessionIn
from backend.portfolio import allocate
from backend.portfolio import service as svc

log = get_logger("portfolio.live")
TICK_S = 60.0
DRIFT = 0.25
KILL_MULTIPLE = 2.0
SETTLE_DAYS = 30
DAY_MS = 86_400_000


def _row(ctx: Any, pid: int) -> Portfolio:
    return svc._row(ctx, pid)


def _name(ctx: Any, strategy_id: int) -> str:
    from backend.db.models import Strategy

    with ctx.db.session() as s:
        return str(s.scalar(select(Strategy.name).where(Strategy.id == strategy_id)) or "a sleeve")


def session_state(ctx: Any, sid: int | None) -> dict[str, Any]:
    """A sleeve session's equity (live when running), money moved, open trades and state."""
    if sid is None:
        return {"equity": 0.0, "moved": 0.0, "open": 0, "state": "none", "starting": 0.0}
    runner = ctx.paper.runner(sid)
    with ctx.db.session() as s:
        row = s.get(PaperSession, sid)
        if row is None:
            return {"equity": 0.0, "moved": 0.0, "open": 0, "state": "none", "starting": 0.0}
        notes = json.loads(row.notes or "{}")
        from backend.db.models import PaperAccount, PaperPosition

        acct = s.get(PaperAccount, row.account_id)
        starting = acct.starting_capital if acct else 0.0
        last = s.scalar(
            select(PaperEquity.equity)
            .where(PaperEquity.session_id == sid)
            .order_by(PaperEquity.ts.desc())
            .limit(1)
        )
        n_open = int(
            s.scalar(
                select(func.count())
                .select_from(PaperPosition)
                .where(PaperPosition.session_id == sid)
            )
            or 0
        )
        state = row.state
    if runner is not None and runner.engine is not None:
        equity = runner.engine.equity_now()
        n_open = sum(1 for st in runner.engine.symbols if st.position is not None)
        state = runner.state
        moved = float(runner.notes.get("moved", notes.get("moved", 0.0)))
    else:
        moved = float(notes.get("moved", 0.0))
        equity = float(last) if last is not None else starting + moved
    return {"equity": equity, "moved": moved, "open": n_open, "state": state, "starting": starting}


def _sleeves(
    ctx: Any, pid: int, statuses: tuple[str, ...] = ("active", "winding_down")
) -> list[PortfolioSleeve]:
    with ctx.db.session() as s:
        rows = s.scalars(
            select(PortfolioSleeve).where(
                PortfolioSleeve.portfolio_id == pid, PortfolioSleeve.status.in_(statuses)
            )
        ).all()
        for r in rows:
            s.expunge(r)
    return list(rows)


def sleeves_public(ctx: Any, pid: int) -> list[dict[str, Any]]:
    out = []
    for r in _sleeves(ctx, pid, ("active", "winding_down", "retired")):
        st = session_state(ctx, r.session_id) if r.status != "retired" else None
        out.append(
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "version_id": r.version_id,
                "symbols": json.loads(r.symbols),
                "weight": r.weight,
                "capital": r.capital,
                "status": r.status,
                "session_id": r.session_id,
                "reasons": json.loads(r.reasons),
                "added_at": r.added_at,
                "retired_at": r.retired_at,
                "equity": st["equity"] if st else None,
                "moved": st["moved"] if st else None,
                "pnl": (st["equity"] - st["starting"] - st["moved"]) if st else None,
                "open_trades": st["open"] if st else 0,
            }
        )
    return out


def value(ctx: Any, pid: int) -> dict[str, Any]:
    p = _row(ctx, pid)
    invested = sum(session_state(ctx, r.session_id)["equity"] for r in _sleeves(ctx, pid))
    total = invested + p.cash
    return {
        "equity": round(total, 2),
        "cash": round(p.cash, 2),
        "invested": round(invested, 2),
        "pnl": round(total - p.budget, 2),
        "return": (total / p.budget - 1.0) if p.budget else 0.0,
    }


# ---------------------------------------------------------------- start and stop


def _open_sleeve(ctx: Any, p: Portfolio, item: dict[str, Any], capital: float) -> int:
    sid = ctx.paper.start_session(
        SessionIn(
            strategy_version_id=int(item["version_id"]),
            account=AccountIn(
                name=f"{p.name} · {item['name']}"[:80],
                market=Market(p.market_code),
                starting_capital=round(capital, 2),
            ),
            symbols=list(item["symbols"]),
            overrides=dict(item.get("overrides") or {}),
            size_pct=float(item["size_pct"]),
            portfolio_id=p.id,
        )
    )
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        s.add(
            PortfolioSleeve(
                portfolio_id=p.id,
                strategy_id=int(item["strategy_id"]),
                version_id=int(item["version_id"]),
                opportunity_id=item.get("opportunity_id"),
                symbols=json.dumps(item["symbols"]),
                overrides=json.dumps(item.get("overrides") or {}),
                size_pct=float(item["size_pct"]),
                weight=round(capital / p.budget, 4),
                capital=round(capital, 2),
                status="active",
                session_id=sid,
                worst_drop_pct=item.get("worst_drop_pct"),
                reasons=json.dumps(item.get("reasons") or []),
                added_at=now,
            )
        )
        if item.get("opportunity_id"):
            opp = s.get(Opportunity, int(item["opportunity_id"]))
            if opp is not None:
                opp.status = "in_portfolio"
    return int(sid)


def start(ctx: Any, pid: int) -> dict[str, Any]:
    p = _row(ctx, pid)
    if p.status == "paper":
        raise AgoraError("ALREADY", "This portfolio is already paper trading.", "", status=409)
    plan = json.loads(p.plan or "{}")
    items = plan.get("sleeves") or []
    if not items:
        raise AgoraError(
            "NO_PLAN",
            "The portfolio has no sleeves to paper trade yet.",
            "Plan it first: it needs strategies that held up on unseen years.",
        )
    spent = 0.0
    for item in items:
        _open_sleeve(ctx, p, item, float(item["capital"]))
        spent += float(item["capital"])
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        row.status = "paper"
        row.cash = round(p.budget - spent, 2)
        row.paper_started_at = now
        row.last_rebalance_at = now
        row.last_review_at = now
        row.updated_at = now
    m = Market(p.market_code)
    svc.note(
        ctx,
        pid,
        "start",
        f"Paper trading started: {len(items)} sleeve{'s' if len(items) != 1 else ''} with "
        f"{money(spent, m)}, {money(p.budget - spent, m)} kept in cash.",
    )
    return svc.detail(ctx, pid)


def stop(ctx: Any, pid: int) -> dict[str, Any]:
    p = _row(ctx, pid)
    for r in _sleeves(ctx, pid):
        if r.session_id is not None and ctx.paper.runner(r.session_id) is not None:
            with contextlib.suppress(AgoraError):
                ctx.paper.stop(r.session_id)
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        if row.status == "paper":
            row.status = "stopped"
        row.updated_at = ctx.clock.now_ms()
    if p.status == "paper":
        svc.note(ctx, pid, "stop", "Paper trading stopped by you. Every sleeve was stopped.")
    return svc.detail(ctx, pid)


# ---------------------------------------------------------------- rebalancing


def preview(ctx: Any, pid: int) -> dict[str, Any]:
    """What a rebalance would move now, before anything moves (like Composer's dry run)."""
    p = _row(ctx, pid)
    rows = [r for r in _sleeves(ctx, pid, ("active",))]
    states = {r.id: session_state(ctx, r.session_id) for r in rows}
    total = p.cash + sum(st["equity"] for st in states.values())
    total_w = sum(r.weight for r in rows)
    reserve_target = max(0.0, 1.0 - total_w) * total
    m = Market(p.market_code)
    lines, plan = [], []
    for r in rows:
        st = states[r.id]
        target = r.weight * total
        delta = target - st["equity"]
        free = None
        runner = ctx.paper.runner(r.session_id) if r.session_id else None
        if runner is not None and runner.engine is not None:
            free = runner.engine.free_cash()
        if delta < 0 and free is not None:
            delta = -min(-delta, free)
        plan.append(
            {
                "sleeve_id": r.id,
                "session_id": r.session_id,
                "move": round(delta, 2),
                "target": round(target, 2),
                "equity": round(st["equity"], 2),
            }
        )
        if abs(delta) >= 1:
            name = _name(ctx, r.strategy_id)
            lines.append(
                f"{'Add' if delta > 0 else 'Take'} {money(abs(delta), m)} "
                f"{'to' if delta > 0 else 'from'} {name} (now {money(st['equity'], m)}, "
                f"target {money(target, m)})."
            )
    return {
        "total": round(total, 2),
        "cash": round(p.cash, 2),
        "reserve_target": round(reserve_target, 2),
        "moves": plan,
        "lines": lines or ["Everything is on target; nothing would move."],
    }


def rebalance(ctx: Any, pid: int, why: str = "Monthly rebalance") -> dict[str, Any]:
    p = _row(ctx, pid)
    pv = preview(ctx, pid)
    cash = p.cash
    moved = 0.0
    outs = [x for x in pv["moves"] if x["move"] < 0]
    ins = [x for x in pv["moves"] if x["move"] > 0]
    for x in outs:
        runner = ctx.paper.runner(x["session_id"])
        if runner is None:
            continue
        got = -runner.transfer(x["move"], f"{why}: money back to the portfolio's cash")
        cash += got
        moved += got
    spare = max(0.0, cash - pv["reserve_target"])
    need = sum(x["move"] for x in ins)
    share = min(1.0, spare / need) if need > 0 else 0.0
    for x in ins:
        runner = ctx.paper.runner(x["session_id"])
        if runner is None or share <= 0:
            continue
        put = runner.transfer(x["move"] * share, f"{why}: money from the portfolio's cash")
        cash -= put
        moved += put
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        row.cash = round(cash, 2)
        row.last_rebalance_at = now
    if moved >= 1:
        svc.note(
            ctx,
            pid,
            "rebalance",
            f"{why}: moved {money(moved, Market(p.market_code))} between the sleeves and the cash.",
        )
    return {"moved": round(moved, 2), "cash": round(cash, 2)}


# ---------------------------------------------------------------- the monthly review


def _peak_drop_pct(ctx: Any, sid: int | None) -> float:
    if sid is None:
        return 0.0
    with ctx.db.session() as s:
        values = [
            float(v)
            for v in s.scalars(
                select(PaperEquity.equity)
                .where(PaperEquity.session_id == sid)
                .order_by(PaperEquity.ts)
            )
        ]
    peak, worst = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak * 100.0)
    return worst


def wind_down(ctx: Any, pid: int, sleeve_id: int, reason: str) -> None:
    with ctx.db.session() as s:
        r = s.get(PortfolioSleeve, sleeve_id)
        if r is None or r.status != "active":
            return
        r.status = "winding_down"
        sid = r.session_id
    if sid is not None and ctx.paper.runner(sid) is not None:
        with contextlib.suppress(AgoraError):
            ctx.paper.pause(sid, "The portfolio is winding this sleeve down.")
    svc.note(
        ctx,
        pid,
        "retire",
        f"Winding down a sleeve: {reason} No new trades; open trades end by their own rules.",
    )


def settle(ctx: Any, pid: int) -> None:
    """Sleeves that are winding down and flat: stop them and return their money to the cash."""
    p = _row(ctx, pid)
    for r in _sleeves(ctx, pid, ("winding_down",)):
        st = session_state(ctx, r.session_id)
        if st["open"]:
            continue
        if r.session_id is not None and ctx.paper.runner(r.session_id) is not None:
            with contextlib.suppress(AgoraError):
                ctx.paper.stop(r.session_id, "The portfolio ended this sleeve.")
        with ctx.db.session() as s:
            row = s.get(PortfolioSleeve, r.id)
            prow = s.get(Portfolio, pid)
            assert row is not None and prow is not None
            row.status = "retired"
            row.retired_at = ctx.clock.now_ms()
            prow.cash = round(prow.cash + st["equity"], 2)
        svc.note(
            ctx,
            pid,
            "retire",
            f"A sleeve was retired; {money(st['equity'], Market(p.market_code))} went back to "
            "the cash.",
        )


def review(ctx: Any, pid: int) -> dict[str, Any]:
    """The monthly review (Manage on its own): the kill switch, then a new plan."""
    p = _row(ctx, pid)
    now = ctx.clock.now_ms()
    wound = added = 0
    for r in _sleeves(ctx, pid, ("active",)):
        drop = _peak_drop_pct(ctx, r.session_id)
        worst = r.worst_drop_pct or 0.0
        if worst > 0 and drop > KILL_MULTIPLE * worst:
            wind_down(
                ctx,
                pid,
                r.id,
                f"its live drop ({drop:.1f}%) passed twice its backtest's worst ({worst:.1f}%).",
            )
            wound += 1
    plan = svc.make_plan(ctx, pid)
    keys = {f"{x['version_id']}|{','.join(sorted(x['symbols']))}" for x in plan["sleeves"]}
    current = _sleeves(ctx, pid, ("active",))
    have = {f"{r.version_id}|{','.join(sorted(json.loads(r.symbols)))}" for r in current}
    for r in current:
        key = f"{r.version_id}|{','.join(sorted(json.loads(r.symbols)))}"
        if key not in keys and now - r.added_at >= SETTLE_DAYS * DAY_MS:
            wind_down(ctx, pid, r.id, "the new plan no longer picks it.")
            wound += 1
    p = _row(ctx, pid)
    reserve = allocate.RISK[p.risk].reserve * p.budget
    for item in plan["sleeves"]:
        key = f"{item['version_id']}|{','.join(sorted(item['symbols']))}"
        if key in have:
            continue
        spare = p.cash - reserve
        capital = min(float(item["capital"]), spare)
        if capital < float(item["capital"]) * 0.5 or capital <= 0:
            continue  # not enough cash yet; it waits for money from retired sleeves
        _open_sleeve(ctx, p, item, capital)
        with ctx.db.session() as s:
            prow = s.get(Portfolio, pid)
            assert prow is not None
            prow.cash = round(prow.cash - capital, 2)
        p = _row(ctx, pid)
        svc.note(
            ctx,
            pid,
            "add",
            f"Added a sleeve: {item['name']} on {', '.join(item['symbols'][:5])} with "
            f"{money(capital, Market(p.market_code))}.",
        )
        added += 1
    with ctx.db.session() as s:
        prow = s.get(Portfolio, pid)
        assert prow is not None
        prow.last_review_at = now
    return {"wound_down": wound, "added": added}


def _month(ms: int, market: str) -> str:
    zone = ZoneInfo(MARKET_TZ[Market(market)])
    return ms_to_dt(ms, zone).strftime("%Y-%m")


def due(ctx: Any, p: Portfolio) -> tuple[str | None, bool]:
    """(why a rebalance is due, or None; whether the monthly review is due) for a paper
    portfolio now."""
    now = ctx.clock.now_ms()
    month = _month(now, p.market_code)
    last = p.last_rebalance_at
    new_month = last is not None and _month(last, p.market_code) != month
    review_due = bool(p.manage) and (
        p.last_review_at is not None and _month(p.last_review_at, p.market_code) != month
    )
    if new_month:
        return "Monthly rebalance", review_due
    pv = preview(ctx, p.id)
    drift = any(
        x["target"] > 0 and abs(x["equity"] / x["target"] - 1.0) > DRIFT for x in pv["moves"]
    )
    return (
        "Rebalance: a sleeve drifted more than 25% from its target" if drift else None
    ), review_due


def tick(ctx: Any) -> None:
    """One check of every paper portfolio (the manager thread calls this once a minute)."""
    with ctx.db.session() as s:
        rows = s.scalars(select(Portfolio).where(Portfolio.status == "paper")).all()
        for r in rows:
            s.expunge(r)
    for p in rows:
        try:
            settle(ctx, p.id)
            why, review_due = due(ctx, p)
            if review_due:
                review(ctx, p.id)
            if why:
                rebalance(ctx, p.id, why)
        except Exception:
            log.exception("The portfolio manager failed on portfolio %s", p.id)


class Manager:
    """The portfolio manager thread: lives and dies with the app (D-06)."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.ctx.data_mode != "real" and not os.environ.get("AGORA_PORTFOLIO"):
            return
        self._thread = threading.Thread(target=self._loop, name="portfolio", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_S):
            tick(self.ctx)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
