"""Forward checks (task 16.4, D-90; Trade Ideas' Holly re-tests its strategies every night,
LANDSCAPE §4): does what Kairos and Metis saved still hold up on candles formed *after* it was
saved? Those candles were never seen by any test, so they are the fairest exam there is.

Two kinds of subject:

- **Revisions Kairos or Metis saved on their own** (author ``kairos`` or ``metis``, with a
  parent), while they are still their strategy's newest version: the revision and the version
  before it are both backtested from the day the revision was saved to now, on their own stocks,
  with the same money and costs.
  - *Holding up*: it made at least as much as the version before.
  - *Stopped holding up*: after at least 40 trading days it made less, by more than 0.1% of the
    money, and the daily difference says it is really worse (at least 80% likely, the
    probabilistic Sharpe ratio of the difference).
  - *Slipping*: worse, but not clearly yet.
- **Portfolio sleeves** (active in a paper portfolio, or planned in a draft one): the sleeve is
  backtested from the day it was added, with its money and trade size, and compared with what
  its exam years led to expect: how likely is it that its average day since is really below the
  exam years' average (a z-test on the mean)?
  - *Stopped holding up*: after at least 40 trading days it lost money and is at least 97.5%
    likely to be doing worse than its exam years.

With fewer than 20 new trading days (or 4 trades) a subject is *waiting*. Each subject is checked
at most once a day, by Kairos's always-on learner while Agora is open (and on **Check now**).

**Undo.** A revision that stopped holding up is put back: the version before it is saved again as
the newest (nothing is deleted, so it can be restored), on its own when **Undo what stops holding
up** is on (``revisions.auto_undo``, default on), else with the **Undo** button. A sleeve that
stopped holding up in a paper portfolio is wound down (no new trades; its money returns to the
cash once flat) when the portfolio manages itself, else with the button. Kairos gets a lesson
either way. Orders still only ever come from strategies in the shared engine (D-56).
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

import numpy as np
from sqlalchemy import and_, or_, select

from backend.backtest.manager import BacktestRequest
from backend.backtest.run import NoData, RunOutput, run
from backend.checks import store
from backend.core.types import MARKET_TZ, Market
from backend.db.models import (
    Portfolio,
    PortfolioSleeve,
    Strategy,
    StrategyCheck,
    StrategyVersion,
)
from backend.errors import AgoraError
from backend.logging_setup import get_logger
from backend.metrics.summary import money
from backend.quant import stats
from backend.settings_store import read_all
from backend.strategy import service as strategies

log = get_logger("checks.forward")
DAY_MS = 86_400_000
AUTO_AUTHORS = ("metis", "kairos")
MIN_SESSIONS = 20
FAIL_SESSIONS = 40
MIN_TRADES = 4
MIN_GAIN = 0.001  # of the money, as Metis's own keep rule (METIS §4)
REVISION_FAIL_P = 0.8
SLEEVE_FAIL_P = 0.975
EVERY_MS = DAY_MS
LOOKBACK_MS = 400 * DAY_MS
UNDO_SOURCE = "forward-undo:"
_lock = threading.Lock()
NORMAL = NormalDist()


@dataclass
class Subject:
    kind: str  # revision | sleeve
    strategy_id: int
    version_id: int
    since: int
    name: str
    market: str
    baseline_version_id: int | None = None
    sleeve_id: int | None = None
    portfolio_id: int | None = None
    author: str = "metis"


# ---------------------------------------------------------------- what to check


def subjects(ctx: Any) -> list[Subject]:
    now = ctx.clock.now_ms()
    out: list[Subject] = []
    with ctx.db.session() as s:
        newest: dict[int, tuple[int, int]] = {}  # strategy → (version id, version number)
        for sid, vid, ver in s.execute(
            select(StrategyVersion.strategy_id, StrategyVersion.id, StrategyVersion.version)
        ):
            if sid not in newest or ver > newest[sid][1]:
                newest[sid] = (vid, ver)
        rows = s.execute(
            select(StrategyVersion, Strategy)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(
                StrategyVersion.created_by.in_(AUTO_AUTHORS),
                StrategyVersion.parent_version_id.is_not(None),
                StrategyVersion.created_at >= now - LOOKBACK_MS,
                Strategy.archived_at.is_(None),
            )
        ).all()
        for v, strat in rows:
            in_use = newest.get(strat.id, (0, 0))[0] == v.id
            if not in_use or v.source.startswith(UNDO_SOURCE):
                continue
            out.append(
                Subject(
                    "revision",
                    strat.id,
                    v.id,
                    v.created_at,
                    f"{strat.name}: version {v.version}",
                    strat.market_code,
                    baseline_version_id=v.parent_version_id,
                    author=v.created_by,
                )
            )
        sleeves = s.execute(
            select(PortfolioSleeve, Portfolio, Strategy)
            .join(Portfolio, Portfolio.id == PortfolioSleeve.portfolio_id)
            .join(Strategy, Strategy.id == PortfolioSleeve.strategy_id)
            .where(
                or_(
                    and_(PortfolioSleeve.status == "active", Portfolio.status == "paper"),
                    and_(PortfolioSleeve.status == "planned", Portfolio.status == "draft"),
                )
            )
        ).all()
        for sl, p, strat in sleeves:
            out.append(
                Subject(
                    "sleeve",
                    strat.id,
                    sl.version_id,
                    sl.added_at,
                    f"{p.name}: {strat.name}",
                    p.market_code,
                    sleeve_id=sl.id,
                    portfolio_id=p.id,
                )
            )
    return out


def _last(ctx: Any, subj: Subject) -> StrategyCheck | None:
    with ctx.db.session() as s:
        q = select(StrategyCheck).where(
            StrategyCheck.kind == "forward", StrategyCheck.version_id == subj.version_id
        )
        q = q.where(
            StrategyCheck.sleeve_id == subj.sleeve_id
            if subj.sleeve_id is not None
            else StrategyCheck.sleeve_id.is_(None)
        )
        row: StrategyCheck | None = s.scalars(q.order_by(StrategyCheck.id.desc()).limit(1)).first()
        if row is not None:
            s.expunge(row)
        return row


def is_due(ctx: Any, subj: Subject) -> bool:
    now = ctx.clock.now_ms()
    if now - subj.since < (MIN_SESSIONS * 7 // 5 + 2) * DAY_MS:
        return False  # not enough new candles can have formed yet
    last = _last(ctx, subj)
    return last is None or now - last.created_at >= EVERY_MS


# ---------------------------------------------------------------- running a check


def _forward_run(ctx: Any, version_id: int, since: int, **req: Any) -> tuple[RunOutput, float]:
    with ctx.db.session() as s:
        v = strategies.get_version(s, version_id)
    if v is None:
        raise ValueError("That version no longer exists.")
    spec, _x = ctx.backtests.spec_for(
        v.definition,
        BacktestRequest(strategy_version_id=version_id, start=since, end=ctx.clock.now_ms(), **req),
    )
    ctx.backtests.ensure_data_for(spec)
    return run(ctx.cache, spec), spec.capital


def _net(out: RunOutput, capital: float) -> float:
    return float(out.equity[-1].equity - capital) if out.equity else 0.0


def _daily(out: RunOutput, market: Market) -> dict[str, float]:
    return dict(stats.daily_points(out.equity, MARKET_TZ[market]))


def _waiting(subj: Subject, sessions: int, trades: int, why: str) -> dict[str, Any]:
    return {
        "verdict": "waiting",
        "title": "Waiting for more new candles.",
        "text": why,
        "subject": subj.kind,
        "name": subj.name,
        "since": subj.since,
        "sessions": sessions,
        "trades": trades,
        "numbers": [],
        "can_undo": False,
    }


def check_revision(ctx: Any, subj: Subject) -> dict[str, Any]:
    assert subj.baseline_version_id is not None
    market = Market(subj.market)
    with ctx.db.session() as s:
        new_v = strategies.get_version(s, subj.version_id)
        old_v = strategies.get_version(s, subj.baseline_version_id)
    if new_v is None or old_v is None:
        raise ValueError("A version this check needs no longer exists.")
    new_out, capital = _forward_run(ctx, subj.version_id, subj.since)
    old_out, _c = _forward_run(ctx, subj.baseline_version_id, subj.since, capital=capital)
    a, b = _daily(new_out, market), _daily(old_out, market)
    days = sorted(set(a) & set(b))
    sessions = len(days)
    trades = len(new_out.trades) + len(old_out.trades)
    nv, ov = new_v.version, old_v.version
    if sessions < MIN_SESSIONS or trades < MIN_TRADES:
        return _waiting(
            subj,
            sessions,
            trades,
            f"{sessions} trading days and {trades} trades since version {nv} was saved; the "
            f"check needs {MIN_SESSIONS} days and {MIN_TRADES} trades.",
        )
    new_net, old_net = _net(new_out, capital), _net(old_out, capital)
    diff = new_net - old_net
    ra = stats.returns_of([a[d] for d in days])
    rb = stats.returns_of([b[d] for d in days])
    p_worse = 1.0 - stats.psr(ra - rb)
    need = MIN_GAIN * capital
    if diff >= 0:
        verdict = "holding"
        title = f"Version {nv} is holding up."
        text = (
            f"On the {sessions} trading days since it was saved it made {money(diff, market)} "
            f"more than version {ov} after costs ({money(new_net, market)} against "
            f"{money(old_net, market)})."
        )
    elif sessions >= FAIL_SESSIONS and -diff > need and p_worse >= REVISION_FAIL_P:
        verdict = "failed"
        title = f"Version {nv} stopped holding up."
        text = (
            f"On the {sessions} trading days since it was saved it made {money(-diff, market)} "
            f"less than version {ov} after costs ({money(new_net, market)} against "
            f"{money(old_net, market)}), and the day-by-day difference says it is really worse "
            f"({p_worse * 100:.0f}% likely)."
        )
    else:
        verdict = "slipping"
        title = f"Version {nv} is slipping."
        text = (
            f"On the {sessions} trading days since it was saved it made {money(-diff, market)} "
            f"less than version {ov}, but not clearly enough to undo it yet "
            f"({p_worse * 100:.0f}% likely to be really worse; undone at "
            f"{REVISION_FAIL_P * 100:.0f}% after {FAIL_SESSIONS} days)."
        )
    return {
        "verdict": verdict,
        "title": title,
        "text": text,
        "subject": "revision",
        "name": subj.name,
        "since": subj.since,
        "sessions": sessions,
        "trades": trades,
        "numbers": [
            {"label": f"Version {nv} made", "value": money(new_net, market)},
            {"label": f"Version {ov} made", "value": money(old_net, market)},
            {
                "label": f"Trades (version {nv} · {ov})",
                "value": f"{len(new_out.trades)} · {len(old_out.trades)}",
            },
            {"label": f"Chance version {nv} is really worse", "value": f"{p_worse * 100:.0f}%"},
        ],
        "raw": {
            "new_net": round(new_net, 2),
            "old_net": round(old_net, 2),
            "p_worse": round(p_worse, 4),
            "capital": capital,
            "version": nv,
            "baseline_version": ov,
        },
        "can_undo": verdict == "failed",
        "undo_label": f"Put version {ov} back",
    }


def check_sleeve(ctx: Any, subj: Subject) -> dict[str, Any]:
    from backend.portfolio import sleeves as sleeve_mod

    assert subj.sleeve_id is not None
    market = Market(subj.market)
    with ctx.db.session() as s:
        row = s.get(PortfolioSleeve, subj.sleeve_id)
        assert row is not None
        symbols, overrides = json.loads(row.symbols), json.loads(row.overrides)
        capital = float(row.capital)
    spec = sleeve_mod.spec_of(ctx, subj.version_id, symbols, overrides, sleeve_id=subj.sleeve_id)
    if spec is None:
        raise ValueError("The sleeve's strategy version no longer exists.")
    fwd, _c = _forward_run(
        ctx,
        subj.version_id,
        subj.since,
        symbols=symbols,
        overrides=overrides,
        size_pct=spec.size_pct,
        capital=capital,
    )
    pts = stats.daily_points(fwd.equity, MARKET_TZ[market])
    r = stats.returns_of([capital] + [v for _d, v in pts])
    sessions, trades = len(pts), len(fwd.trades)
    if sessions < MIN_SESSIONS or trades < MIN_TRADES:
        return _waiting(
            subj,
            sessions,
            trades,
            f"{sessions} trading days and {trades} trades since the sleeve was added; the check "
            f"needs {MIN_SESSIONS} days and {MIN_TRADES} trades.",
        )
    exam = sleeve_mod.run_sleeve(ctx, spec, capital, end=subj.since).exam_returns
    net = _net(fwd, capital)
    if len(exam) < 20:
        z, p_worse, exam_mean = 0.0, 0.5, 0.0
    else:
        exam_mean = float(np.mean(exam))
        sd = float(np.std(exam, ddof=1))
        se = sd / math.sqrt(len(r)) if sd > 0 else 0.0
        z = (float(np.mean(r)) - exam_mean) / se if se > 0 else 0.0
        p_worse = NORMAL.cdf(-z)
    if net >= 0 or p_worse < 0.5:
        verdict, title = "holding", "This sleeve is holding up."
        text = (
            f"Since it was added ({sessions} trading days) it made {money(net, market)} after "
            "costs, in line with or better than its exam years."
        )
    elif sessions >= FAIL_SESSIONS and p_worse >= SLEEVE_FAIL_P:
        verdict, title = "failed", "This sleeve stopped holding up."
        text = (
            f"Since it was added ({sessions} trading days) it lost {money(-net, market)} after "
            f"costs, and its average day is well below its exam years' ({p_worse * 100:.1f}% "
            "likely to be really worse)."
        )
    else:
        verdict, title = "slipping", "This sleeve is slipping."
        text = (
            f"Since it was added ({sessions} trading days) it lost {money(-net, market)} after "
            f"costs; {p_worse * 100:.0f}% likely to be doing worse than its exam years (wound "
            f"down at {SLEEVE_FAIL_P * 100:.1f}% after {FAIL_SESSIONS} days)."
        )
    return {
        "verdict": verdict,
        "title": title,
        "text": text,
        "subject": "sleeve",
        "name": subj.name,
        "since": subj.since,
        "sessions": sessions,
        "trades": trades,
        "numbers": [
            {"label": "Made since it was added", "value": money(net, market)},
            {"label": "Trades", "value": str(trades)},
            {"label": "Average day since", "value": f"{float(np.mean(r)) * 100:.3f}%"},
            {"label": "Average exam-year day", "value": f"{exam_mean * 100:.3f}%"},
            {"label": "Chance it is really doing worse", "value": f"{p_worse * 100:.0f}%"},
        ],
        "raw": {"net": round(net, 2), "z": round(z, 3), "p_worse": round(p_worse, 4)},
        "can_undo": verdict == "failed",
        "undo_label": "Wind this sleeve down",
    }


def run_one(ctx: Any, subj: Subject) -> dict[str, Any]:
    """Check one subject, save the result, and act on it when set to."""
    result = check_revision(ctx, subj) if subj.kind == "revision" else check_sleeve(ctx, subj)
    with ctx.db.session() as s:
        if result["verdict"] == "waiting":  # keep only the latest waiting row of a subject
            q = s.query(StrategyCheck).filter(
                StrategyCheck.kind == "forward",
                StrategyCheck.version_id == subj.version_id,
                StrategyCheck.verdict == "waiting",
                StrategyCheck.sleeve_id == subj.sleeve_id
                if subj.sleeve_id is not None
                else StrategyCheck.sleeve_id.is_(None),
            )
            q.delete(synchronize_session=False)
        row = store.save(
            s,
            kind="forward",
            now=ctx.clock.now_ms(),
            strategy_id=subj.strategy_id,
            version_id=subj.version_id,
            baseline_version_id=subj.baseline_version_id,
            sleeve_id=subj.sleeve_id,
            portfolio_id=subj.portfolio_id,
            result=result,
        )
        check_id = row.id
    if result["verdict"] == "failed" and _auto(ctx, subj):
        undo(ctx, check_id, by="auto")
    return _public(ctx, check_id)


def _auto(ctx: Any, subj: Subject) -> bool:
    with ctx.db.session() as s:
        settings = read_all(s)
        if subj.kind == "revision":
            return bool(settings["revisions.auto_undo"])
        p = s.get(Portfolio, subj.portfolio_id)
        return p is not None and p.status == "paper" and bool(p.manage)


def run_due(ctx: Any, *, limit: int = 3, force: bool = False) -> list[dict[str, Any]]:
    """Check the subjects that are due (``force``: every subject with enough new candles)."""
    if not _lock.acquire(blocking=False):
        return []
    try:
        done: list[dict[str, Any]] = []
        now = ctx.clock.now_ms()
        for subj in subjects(ctx):
            if len(done) >= limit:
                break
            ready = now - subj.since >= (MIN_SESSIONS * 7 // 5 + 2) * DAY_MS
            if not (is_due(ctx, subj) or (force and ready)):
                continue
            try:
                done.append(run_one(ctx, subj))
            except (NoData, ValueError, AgoraError) as exc:
                log.info("Forward check of %s skipped: %s", subj.name, exc)
        return done
    finally:
        _lock.release()


# ---------------------------------------------------------------- undo


def undo(ctx: Any, check_id: int, *, by: str = "user") -> dict[str, Any]:
    """Act on a check that stopped holding up: put the earlier version back, or wind the sleeve
    down. ``by``: "user" (the button) or "auto" (the setting)."""
    with ctx.db.session() as s:
        row = s.get(StrategyCheck, check_id)
        if row is None or row.kind != "forward":
            raise AgoraError(
                "CHECK_NOT_FOUND", "That check doesn't exist.", "Refresh the page.", status=404
            )
        result = json.loads(row.result)
        if row.action:
            return _public(ctx, check_id)
        if not result.get("can_undo"):
            raise AgoraError(
                "NOTHING_TO_UNDO",
                "This one is still holding up, so there is nothing to undo.",
                "Check it again later.",
            )
        sleeve_id, pid = row.sleeve_id, row.portfolio_id
        sid, vid, base = row.strategy_id, row.version_id, row.baseline_version_id
    who = "on its own" if by == "auto" else "by you"
    if sleeve_id is None:
        assert base is not None
        with ctx.db.session() as s:
            strat = s.get(Strategy, sid)
            latest = strategies.latest_version(s, sid)
            old = strategies.get_version(s, base)
            new = strategies.get_version(s, vid)
            assert strat is not None and old is not None and new is not None
            if latest is None or latest.id != vid:
                action = (
                    f"Not undone: a newer version (version {latest.version if latest else '?'}) "
                    "was saved since."
                )
            else:
                v = strategies.add_version(
                    s,
                    strat,
                    old.definition,
                    ctx.clock.now_ms(),
                    note=f"Undid version {new.version}: it stopped holding up on new candles",
                    created_by=new.created_by if by == "auto" else "user",
                    evidence={"forward_check": check_id, **result.get("raw", {})},
                    source=f"{UNDO_SOURCE}{check_id}",
                )
                action = (
                    f"Version {old.version}'s rules were put back {who} as version {v.version}."
                )
            name = strat.name
            market = strat.market_code
        from backend.kairos import memory

        memory.note(
            ctx,
            f"forward:{sid}",
            f"Forward check: {name} version {new.version} stopped holding up on candles formed "
            f"after it was saved ({result.get('text', '')}) {action}",
            market=market,
        )
    else:
        assert pid is not None
        from backend.portfolio import live

        with ctx.db.session() as s:
            p = s.get(Portfolio, pid)
            paper = p is not None and p.status == "paper"
            sl = s.get(PortfolioSleeve, sleeve_id)
            if not paper and sl is not None and sl.status == "planned":
                sl.status = "retired"
                sl.retired_at = ctx.clock.now_ms()
        if paper:
            live.wind_down(
                ctx, pid, sleeve_id, "it stopped holding up on new candles (forward check)."
            )
            action = f"Wound down {who}: no new trades; its money returns to the cash once flat."
        else:
            action = f"Taken out of the plan {who}; re-plan to share out its money."
    with ctx.db.session() as s:
        row = s.get(StrategyCheck, check_id)
        assert row is not None
        row.action = action
    return _public(ctx, check_id)


# ---------------------------------------------------------------- reading


def _public(ctx: Any, check_id: int) -> dict[str, Any]:
    with ctx.db.session() as s:
        row = s.get(StrategyCheck, check_id)
        assert row is not None
        v = s.get(StrategyVersion, row.version_id)
        strat = s.get(Strategy, row.strategy_id)
        out = store.public(row, v.version if v else None)
        out["strategy_name"] = strat.name if strat else ""
    return out


def overview(ctx: Any) -> list[dict[str, Any]]:
    """Every subject with its latest check, or how long until it can be checked."""
    now = ctx.clock.now_ms()
    items: list[dict[str, Any]] = []
    for subj in subjects(ctx):
        last = _last(ctx, subj)
        item: dict[str, Any] = {
            "subject": subj.kind,
            "name": subj.name,
            "strategy_id": subj.strategy_id,
            "version_id": subj.version_id,
            "sleeve_id": subj.sleeve_id,
            "portfolio_id": subj.portfolio_id,
            "since": subj.since,
            "days_since": int((now - subj.since) // DAY_MS),
            "check": _public(ctx, last.id) if last is not None else None,
        }
        items.append(item)
    with ctx.db.session() as s:  # acted-on checks stay listed (their subject is gone)
        acted = s.scalars(
            select(StrategyCheck)
            .where(StrategyCheck.kind == "forward", StrategyCheck.action != "")
            .order_by(StrategyCheck.id.desc())
            .limit(10)
        ).all()
        acted_ids = [r.id for r in acted]
    seen = {i["check"]["id"] for i in items if i["check"]}
    for cid in acted_ids:
        if cid not in seen:
            c = _public(ctx, cid)
            items.append(
                {
                    "subject": c["result"].get("subject", "revision"),
                    "name": c["result"].get("name", c["strategy_name"]),
                    "strategy_id": c["strategy_id"],
                    "version_id": c["version_id"],
                    "sleeve_id": c["sleeve_id"],
                    "portfolio_id": c["portfolio_id"],
                    "since": c["result"].get("since"),
                    "days_since": None,
                    "check": c,
                }
            )
    return items
