"""Kairos tries Metis's strategies on paper (D-139).

The user (2026-10-28): "If Kairos thinks strategies made by Metis work then it can test those
strategies too… not sure how you will regulate the usage though." The rules, all code (D-56):

- **No compulsion.** Then: "There should be no compulsion on Kairos to use those strategies."
  Kairos tries one only when it thinks it works, by its own bar, stricter than Metis's: the exam
  years won at least ``EXAM_PF``× what they lost over at least ``EXAM_TRADES`` trades, and
  Kairos's own re-test on the candles formed since the strategy was saved (which no test has
  seen) didn't lose money (judged once it has ``MIN_TRADES`` trades; one saved under
  ``NEW_MS`` ago and too new to re-test is judged on its exam alone). Each view is kept for a
  day with its reason; with none passing, Kairos tries none.
- **Which.** Strategies Metis made and saved, not archived, best exam result first (how much
  more it won than it lost in the unseen years, then how many trades that rests on).
- **How many.** At most ``kairos.trials`` (default 3) on trial per market at once (a ceiling,
  not a quota), and none while ``MAX_PROVEN`` already proved themselves live. 0 switches trials
  off.
- **Whose money.** Each trial has its own paper account (₹2 lakh / $20,000), never the desks'
  money, on the stocks Metis tested it on.
- **Verdict.** After ``JUDGE_TRADES`` closed trades or ``JUDGE_MS``, whichever comes first, it
  **works live** when it made at least ``MIN_TRADES`` trades, made money after costs and won at
  least ``KEEP_PF``× what it lost: it keeps running. Otherwise it is **retired** once it holds no
  trades, and not tried again for ``RETRY_MS`` unless a newer version is saved.
- **Safety stop.** A trial (or a proven one) whose money falls ``STOP_LOSS_PCT`` below where it
  started is stopped at once and retired.
- **New version.** When a newer version is saved, the trial starts again on it once flat.

Kairos's learner reviews their trades like any paper session's, so it learns from them too.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from backend.core.types import Market
from backend.logging_setup import get_logger
from backend.settings_store import read_all

log = get_logger("kairos.trials")

DAY_MS = 86_400_000
TRIAL_CAPITAL = {"IN": 200_000.0, "US": 20_000.0}
JUDGE_TRADES = 20
JUDGE_MS = 30 * DAY_MS
MIN_TRADES = 5
KEEP_PF = 1.1
STOP_LOSS_PCT = 10.0
RETRY_MS = 60 * DAY_MS
MAX_PROVEN = 5
NAME = "Kairos trial"
EXAM_PF = 1.2
EXAM_TRADES = 20
# A monthly ranking holds each stock for a month: few trades by design, so its bar is Metis's own
# exam minimum (D-171: six-month momentum, best in the sealed year, had 15 and was refused)
EXAM_TRADES_RANKING = 12
VIEW_MS = DAY_MS  # how long Kairos's view of a strategy stands before it looks again
NEW_MS = 30 * DAY_MS  # younger than this, a failed re-test means "too new", not "against"
RULES = 2  # views formed under older rules are formed again


def candidates(ctx: Any, market: str) -> list[dict[str, Any]]:
    """Metis's saved strategies for the market, best exam result first."""
    from backend.db.models import MetisIdea, Strategy
    from backend.strategy import service as strategies

    out: dict[int, dict[str, Any]] = {}
    with ctx.db.session() as s:
        ideas = s.scalars(
            select(MetisIdea)
            .where(
                MetisIdea.status == "saved",
                MetisIdea.kind == "new_strategy",
                MetisIdea.market_code == market,
                MetisIdea.saved_strategy_id.is_not(None),
            )
            .order_by(MetisIdea.id.desc())
        ).all()
        for idea in ideas:
            sid = int(idea.saved_strategy_id or 0)
            if sid in out:
                continue  # the newest idea behind a strategy speaks for it
            strat = s.get(Strategy, sid)
            if strat is None or strat.archived_at is not None or strat.kind == "kairos":
                continue
            newest = strategies.latest_version(s, sid)
            if newest is None or newest.definition.market != market:
                continue
            exam = (json.loads(idea.result or "{}").get("candidate") or {}).get("exam") or {}
            out[sid] = {
                "strategy_id": sid,
                "version_id": newest.id,
                "name": strat.name,
                "exam_pf": float(exam.get("profit_factor") or 0.0),
                "exam_trades": int(exam.get("trades") or 0),
                "kind": newest.definition.kind,
            }
    return sorted(out.values(), key=lambda c: (-c["exam_pf"], -c["exam_trades"], c["name"]))


def kairos_view(ctx: Any, c: dict[str, Any]) -> tuple[bool, str]:
    """Does Kairos think this strategy works? (its own bar; see the module notes)"""
    from backend.checks.forward import _forward_run
    from backend.strategy import service as strategies

    need = EXAM_TRADES_RANKING if c.get("kind") == "ranking" else EXAM_TRADES
    if c["exam_pf"] < EXAM_PF or c["exam_trades"] < need:
        return False, (
            f"its exam years ({c['exam_trades']} trades, won {c['exam_pf']:.2f}× what it lost) "
            f"are below Kairos's bar ({need}+ trades, {EXAM_PF}×)"
        )
    with ctx.db.session() as s:
        v = strategies.get_version(s, c["version_id"])
    if v is None:
        return False, "that version no longer exists"
    try:
        out, _capital = _forward_run(ctx, c["version_id"], int(v.created_at))
    except Exception as exc:
        if ctx.clock.now_ms() - int(v.created_at) < NEW_MS:
            # saved too recently for a re-test (a daily strategy needs weeks of candles): no
            # evidence against it yet, like a re-test with too few trades
            return True, "strong exam years; saved too recently to re-test since"
        return False, f"Kairos couldn't re-test it yet ({exc})"
    nets = [float(t.net_pnl) for t in out.trades if t.closed]
    if len(nets) < MIN_TRADES:
        return True, f"strong exam years; {len(nets)} trades since it was saved, none against it"
    if sum(nets) <= 0:
        return False, f"it lost money in its {len(nets)} trades since it was saved"
    return True, f"strong exam years and it made money in {len(nets)} trades since it was saved"


def record(ctx: Any, session_id: int) -> dict[str, Any] | None:
    """How a trial is doing: its state, closed trades, profit after costs, money now."""
    from backend.db.models import PaperAccount, PaperEquity, PaperSession, PaperTrade

    with ctx.db.session() as s:
        row = s.get(PaperSession, session_id)
        if row is None:
            return None
        acct = s.get(PaperAccount, row.account_id)
        nets = [
            float(t)
            for t in s.scalars(
                select(PaperTrade.net_pnl).where(PaperTrade.session_id == session_id)
            )
        ]
        eq = s.scalar(
            select(PaperEquity.equity)
            .where(PaperEquity.session_id == session_id)
            .order_by(PaperEquity.ts.desc())
            .limit(1)
        )
    capital = float(acct.starting_capital) if acct is not None else 0.0
    won = sum(n for n in nets if n > 0)
    lost = -sum(n for n in nets if n < 0)
    runner = ctx.paper.runner(session_id)
    engine = getattr(runner, "engine", None)
    open_now = sum(1 for st in engine.symbols if st.position is not None) if engine else 0
    return {
        "state": row.state,
        "trades": len(nets),
        "net": round(sum(nets), 2),
        "pf": round(won / lost, 3) if lost > 0 else (99.0 if won > 0 else 0.0),
        "equity": float(eq) if eq is not None else capital,
        "capital": capital,
        "open": open_now,
    }


def verdict(rec: dict[str, Any], age_ms: int) -> str | None:
    """ "works", "retire", "stop" (at once) or None (keep watching), by the rules above."""
    if rec["capital"] and rec["equity"] <= rec["capital"] * (1 - STOP_LOSS_PCT / 100):
        return "stop"
    if rec["trades"] < JUDGE_TRADES and age_ms < JUDGE_MS:
        return None
    good = rec["trades"] >= MIN_TRADES and rec["net"] > 0 and rec["pf"] >= KEEP_PF
    return "works" if good else "retire"


def run(ctx: Any, market: str, state: dict[str, Any]) -> dict[str, Any]:
    """One autopilot round for a market's trials: judge the running ones, start new ones."""
    from backend.paper.service import AccountIn, SessionIn

    with ctx.db.session() as s:
        slots = int(read_all(s)["kairos.trials"])
    book: dict[str, Any] = state.setdefault("trials", {})
    now = ctx.clock.now_ms()
    cands = {c["strategy_id"]: c for c in candidates(ctx, market)}
    done: list[str] = []
    for key, t in list(book.items()):
        if t.get("market") != market or t.get("status") not in ("trial", "proven"):
            continue
        rec = record(ctx, int(t["session_id"]))
        if rec is None or rec["state"] == "stopped":
            t.update(status="retired", until=now + RETRY_MS, why="stopped")
            continue
        newer = cands.get(int(key), {}).get("version_id", t["version_id"]) != t["version_id"]
        call = verdict(rec, now - int(t["started_at"]))
        if call == "stop":
            _stop(ctx, t, "Kairos stopped this trial: it lost 10% of its paper money.")
            t.update(status="retired", until=now + RETRY_MS, why="lost 10%", record=rec)
            done.append(f"{t['name']}: stopped (lost 10%)")
            _note(
                ctx,
                key,
                market,
                f"Metis's strategy {t['name']} lost 10% live: {_words(rec, market)}.",
            )
            continue
        if call == "works" and t["status"] == "trial":
            t.update(status="proven", judged_at=now, record=rec)
            done.append(f"{t['name']}: works live")
            _note(
                ctx, key, market, f"Metis's strategy {t['name']} works live: {_words(rec, market)}."
            )
            continue
        failed = call == "retire" and t["status"] == "trial"
        if (failed or newer or slots == 0) and not rec["open"]:
            why = "a newer version" if newer else "trials off" if slots == 0 else "didn't work"
            _stop(ctx, t, f"Kairos ended this trial ({why}).")
            t.update(status="retired", until=0 if newer else now + RETRY_MS, why=why, record=rec)
            done.append(f"{t['name']}: ended ({why})")
            if failed:
                _note(
                    ctx,
                    key,
                    market,
                    f"Metis's strategy {t['name']} didn't work live: {_words(rec, market)}.",
                )
    live = [t for t in book.values() if t.get("market") == market]
    trials = sum(1 for t in live if t.get("status") == "trial")
    proven = sum(1 for t in live if t.get("status") == "proven")
    started: list[str] = []
    for sid, c in cands.items():
        if trials >= slots or proven >= MAX_PROVEN:
            break
        t = book.get(str(sid))
        if t is not None and t.get("status") in ("trial", "proven"):
            continue
        if (
            t is not None
            and int(t.get("until") or 0) > now
            and t.get("version_id") == c["version_id"]
        ):
            continue  # retired recently and nothing new since
        views: dict[str, Any] = state.setdefault("trial_views", {})
        view = views.get(str(sid))
        stale = view is None or view.get("rules") != RULES or now - view["at"] >= VIEW_MS
        if stale or view is None or view["version_id"] != c["version_id"]:
            ok, why = kairos_view(ctx, c)
            view = {"version_id": c["version_id"], "at": now, "ok": ok, "why": why, "rules": RULES}
            views[str(sid)] = view
            log.info("Kairos on %s: %s (%s)", c["name"], "tries it" if ok else "passes", why)
        if not view["ok"]:
            continue  # no compulsion: Kairos passes on what it doesn't believe in
        try:
            session_id = ctx.paper.start_session(
                SessionIn(
                    strategy_version_id=c["version_id"],
                    account=AccountIn(
                        name=f"{NAME} · {c['name']}"[:80],
                        market=Market(market),
                        starting_capital=TRIAL_CAPITAL[market],
                    ),
                )
            )
        except Exception:
            log.exception("Kairos couldn't start a trial of %s", c["name"])
            continue
        book[str(sid)] = {
            "market": market,
            "name": c["name"],
            "version_id": c["version_id"],
            "session_id": session_id,
            "started_at": now,
            "status": "trial",
        }
        trials += 1
        started.append(c["name"])
        log.info("Kairos started a trial of %s (session %d)", c["name"], session_id)
    return {"started": started, "judged": done, "trials": trials, "candidates": len(cands)}


def _stop(ctx: Any, t: dict[str, Any], message: str) -> None:
    runner = ctx.paper.runner(int(t["session_id"]))
    if runner is not None:
        runner.stop(message)


def _words(rec: dict[str, Any], market: str) -> str:
    cur = "₹" if market == "IN" else "$"
    sign = "−" if rec["net"] < 0 else ""
    return (
        f"{rec['trades']} trades, {sign}{cur}{abs(rec['net']):,.0f} after costs, "
        f"won {rec['pf']:.2f}× what it lost"
    )


def _note(ctx: Any, key: str, market: str, text: str) -> None:
    """A lesson for Kairos's memory (one per strategy, the latest verdict)."""
    try:
        from backend.kairos import memory

        memory.note(ctx, f"trial-{key}", text, market)
    except Exception:
        log.debug("Couldn't save the trial lesson", exc_info=True)
