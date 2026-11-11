"""Portfolios and opportunities as the app uses them (PORTFOLIO §2–§7, D-84 to D-86).

Creating a portfolio plans it at once (finding opportunities first when the market has none),
as a job; backtesting and paper trading build on the latest plan. Every step is written in the
portfolio's diary (``portfolio_moves``).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from backend.core.types import Market
from backend.db.models import (
    Opportunity,
    Portfolio,
    PortfolioMove,
    PortfolioSleeve,
    Strategy,
)
from backend.errors import AgoraError
from backend.logging_setup import get_logger
from backend.metrics.summary import money
from backend.portfolio import allocate, scan, sleeves
from backend.portfolio.backtest import run_portfolio
from backend.settings_store import read_all
from backend.strategy import service as strategies_svc

log = get_logger("portfolio")
DEFAULT_BUDGET = {"IN": 100_000.0, "US": 10_000.0}


def _err(code: str, message: str, action: str = "", status: int = 422) -> AgoraError:
    return AgoraError(code, message, action, status=status)


# ---------------------------------------------------------------- the diary


def note(ctx: Any, pid: int, kind: str, text: str, **detail: Any) -> None:
    with ctx.db.session() as s:
        s.add(
            PortfolioMove(
                portfolio_id=pid,
                ts=ctx.clock.now_ms(),
                kind=kind,
                text=text[:2000],
                detail=json.dumps(detail, default=str),
            )
        )


def moves(ctx: Any, pid: int, limit: int = 50) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        rows = s.scalars(
            select(PortfolioMove)
            .where(PortfolioMove.portfolio_id == pid)
            .order_by(PortfolioMove.id.desc())
            .limit(limit)
        ).all()
        return [
            {"id": r.id, "ts": r.ts, "kind": r.kind, "text": r.text, "detail": json.loads(r.detail)}
            for r in rows
        ]


# ---------------------------------------------------------------- opportunities


def opportunity_public(r: Opportunity, name: str = "") -> dict[str, Any]:
    return {
        "id": r.id,
        "market": r.market_code,
        "strategy_id": r.strategy_id,
        "version_id": r.version_id,
        "name": name,
        "symbols": json.loads(r.symbols),
        "overrides": json.loads(r.overrides),
        "source": r.source,
        "status": r.status,
        "score": r.score,
        "study": json.loads(r.study),
        "exam": json.loads(r.exam),
        "luck": json.loads(r.luck),
        "evidence": r.evidence,
        "found_at": r.found_at,
        "checked_at": r.checked_at,
    }


def opportunities(
    ctx: Any, market: str | None = None, *, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        q = select(Opportunity, Strategy.name).join(
            Strategy, Strategy.id == Opportunity.strategy_id
        )
        if market:
            q = q.where(Opportunity.market_code == market)
        if status:
            q = q.where(Opportunity.status == status)
        else:
            q = q.where(Opportunity.status.in_(("open", "in_portfolio")))
        rows = s.execute(q.order_by(Opportunity.score.desc()).limit(limit)).all()
        return [opportunity_public(r, name) for r, name in rows]


def dismiss(ctx: Any, oid: int) -> dict[str, Any]:
    with ctx.db.session() as s:
        row = s.get(Opportunity, oid)
        if row is None:
            raise _err("NOT_FOUND", "That opportunity doesn't exist.", status=404)
        row.status = "dismissed"
        name = s.scalar(select(Strategy.name).where(Strategy.id == row.strategy_id)) or ""
        return opportunity_public(row, name)


def start_scan(ctx: Any, markets: list[str]) -> str:
    def work(jc: Any) -> dict[str, Any]:
        out = []
        for k, m in enumerate(markets):

            def say(pct: float, msg: str, k: int = k) -> None:
                jc.progress((k * 100 + pct) / len(markets), msg)

            out.append(scan.scan(ctx, m, progress=say))
        return {"markets": out, "note": " ".join(o["note"] for o in out)}

    job = ctx.jobs.submit("opportunity_scan", "Finding new opportunities", work, single=True)
    return str(job.id)


def record_research(
    ctx: Any, version_id: int, symbols: list[str], overrides: dict[str, float]
) -> int | None:
    """Kairos's research found a strategy the user already has (D-80): keep it as an
    opportunity (that strategy on those stocks with its tuned settings)."""
    spec = sleeves.spec_of(ctx, version_id, symbols, overrides)
    if spec is None:
        return None
    r = sleeves.run_sleeve(ctx, spec, scan.REFERENCE_CAPITAL[spec.market])
    return scan.record(ctx, spec, sleeves.evidence(r, 1), "kairos_research")


# ---------------------------------------------------------------- candidates and plans


def candidates(ctx: Any, market: str, pid: int | None = None) -> list[allocate.Candidate]:
    """The open opportunities of the market plus the portfolio's own active sleeves, each run
    as a sleeve over the default period (study and exam years)."""
    specs: dict[str, sleeves.SleeveSpec] = {}
    with ctx.db.session() as s:
        opps = s.scalars(
            select(Opportunity).where(
                Opportunity.market_code == market, Opportunity.status.in_(("open", "in_portfolio"))
            )
        ).all()
        rows = [(o.id, o.version_id, json.loads(o.symbols), json.loads(o.overrides)) for o in opps]
        sl_rows = (
            s.scalars(
                select(PortfolioSleeve).where(
                    PortfolioSleeve.portfolio_id == pid, PortfolioSleeve.status == "active"
                )
            ).all()
            if pid is not None
            else []
        )
        own = [
            (r.id, r.version_id, json.loads(r.symbols), json.loads(r.overrides), r.opportunity_id)
            for r in sl_rows
        ]
        archived = {
            sid
            for (sid,) in s.execute(select(Strategy.id).where(Strategy.archived_at.is_not(None)))
        }
    for sleeve_id, vid, syms, ov, oid in own:
        sp = sleeves.spec_of(ctx, vid, syms, ov, opportunity_id=oid, sleeve_id=sleeve_id)
        if sp is not None:
            specs[sp.key] = sp
    for oid, vid, syms, ov in rows:
        sp = sleeves.spec_of(ctx, vid, syms, ov, opportunity_id=oid)
        if sp is not None and sp.strategy_id not in archived and sp.key not in specs:
            specs[sp.key] = sp
    tries = max(1, len(specs))
    out = []
    for sp in specs.values():
        try:
            r = sleeves.run_sleeve(ctx, sp, scan.REFERENCE_CAPITAL[market])
        except Exception:
            log.exception("Couldn't run %s as a sleeve", sp.name)
            continue
        ev = sleeves.evidence(r, tries)
        out.append(
            allocate.Candidate(
                key=sp.key,
                name=sp.name,
                strategy_id=sp.strategy_id,
                version_id=sp.version_id,
                symbols=sp.symbols,
                size_pct=sp.size_pct,
                max_open=sp.max_open,
                dearest=r.dearest,
                days=r.days,
                returns=r.returns,
                split_index=r.split_index,
                exam=ev["exam"],
                sharpe=ev["sharpe"],
                dsr=ev["luck"]["dsr"],
                worst_drop_pct=r.worst_drop_pct(),
                overrides=sp.overrides,
                opportunity_id=sp.opportunity_id,
                sleeve_id=sp.sleeve_id,
            )
        )
    return out


def _row(ctx: Any, pid: int) -> Portfolio:
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        if row is None or row.status == "archived":
            raise _err("NOT_FOUND", "That portfolio doesn't exist.", "Pick one from the list.", 404)
        s.expunge(row)
        out: Portfolio = row
        return out


METHOD_TEMPLATE = {"momentum": "momentum_top", "low_volatility": "low_volatility"}
METHOD_WORD = {"momentum": "momentum ranking", "low_volatility": "low-volatility ranking"}


def ranking_strategy(ctx: Any, market: str, method: str) -> int:
    """The ranking strategy behind a ranking portfolio (D-91): the user's own if they have one
    with the same logic, else made from the starter (reused, never copied: D-79)."""
    from backend.strategy import ranking, revisions

    key = METHOD_TEMPLATE[method]
    d = ranking.ranking_definition(key, market)
    with ctx.db.session() as s:
        found = revisions.match(s, d, template_key=key)
        if found is not None:
            v = strategies_svc.latest_version(s, found.strategy_id)
            if v is not None:
                return int(v.id)
        saved = revisions.save(
            s,
            definition=d,
            author="kairos",
            name=ranking.RANKING_TEMPLATES[key].name,
            description=ranking.RANKING_TEMPLATES[key].description,
            now=ctx.clock.now_ms(),
            note="Made for a ranking portfolio",
            template_key=key,
        )
        return int(saved.version_id)


def _ranking_plan(ctx: Any, p: Portfolio, say: Any) -> dict[str, Any]:
    say(10, "Testing the ranking on the whole index…")
    vid = ranking_strategy(ctx, p.market_code, p.method)
    spec = sleeves.spec_of(ctx, vid, [])
    assert spec is not None
    r = sleeves.run_sleeve(ctx, spec, scan.REFERENCE_CAPITAL[p.market_code])
    ev = sleeves.evidence(r, 1)
    cand = allocate.Candidate(
        key=spec.key,
        name=spec.name,
        strategy_id=spec.strategy_id,
        version_id=spec.version_id,
        symbols=[],
        size_pct=spec.size_pct,
        max_open=spec.max_open,
        dearest=r.dearest,
        days=r.days,
        returns=r.returns,
        split_index=r.split_index,
        exam=ev["exam"],
        sharpe=ev["sharpe"],
        dsr=ev["luck"]["dsr"],
        worst_drop_pct=r.worst_drop_pct(),
    )
    say(90, "Sizing it to the budget…")
    plan = allocate.ranking_plan(cand, p.budget, p.risk, p.market_code, METHOD_WORD[p.method])
    return plan.public()


def make_plan(ctx: Any, pid: int, progress: Any = None) -> dict[str, Any]:
    say = progress or (lambda _p, _m: None)
    p = _row(ctx, pid)
    market = p.market_code
    if p.method in METHOD_TEMPLATE:
        plan = _ranking_plan(ctx, p, say)
        return _store_plan(ctx, p, plan, say)
    if not opportunities(ctx, market, status="open"):
        say(5, "Finding opportunities first…")
        scan.scan(ctx, market, progress=lambda q, m: say(5 + q * 0.5, m))
    say(55, "Testing each candidate as a sleeve…")
    cands = candidates(ctx, market, pid)
    say(90, "Allocating the budget…")
    plan = allocate.plan(cands, p.budget, p.risk, market).public()
    return _store_plan(ctx, p, plan, say)


def _store_plan(ctx: Any, p: Portfolio, plan: dict[str, Any], say: Any) -> dict[str, Any]:
    pid, market = p.id, p.market_code
    plan["made_at"] = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        row.plan = json.dumps(plan)
        row.updated_at = ctx.clock.now_ms()
    m = Market(market)
    if plan["sleeves"]:
        text = (
            f"Planned {len(plan['sleeves'])} sleeve{'s' if len(plan['sleeves']) != 1 else ''} "
            f"for {money(p.budget, m)}: "
            + "; ".join(f"{x['name']} {money(x['capital'], m)}" for x in plan["sleeves"])
            + f"; {money(plan['cash'], m)} kept in cash."
        )
    else:
        text = "Nothing passed the tests, so the plan keeps the money in cash."
    note(ctx, pid, "plan", text, sleeves=len(plan["sleeves"]), left_out=len(plan["left_out"]))
    say(100, "Done.")
    return plan


def submit_plan(ctx: Any, pid: int) -> str:
    _row(ctx, pid)
    job = ctx.jobs.submit(
        "portfolio_plan",
        "Planning the portfolio",
        lambda jc: make_plan(ctx, pid, jc.progress),
        key=f"portfolio:{pid}",
        single=True,
    )
    return str(job.id)


def backtest(ctx: Any, pid: int, progress: Any = None, check: Any = None) -> dict[str, Any]:
    p = _row(ctx, pid)
    plan = json.loads(p.plan or "{}")
    if not plan.get("sleeves"):
        raise _err(
            "NO_PLAN",
            "The portfolio has no sleeves to backtest yet.",
            "Plan it first (it needs strategies that held up on unseen years).",
        )
    result = run_portfolio(ctx, plan, progress=progress, check_cancel=check)
    result["made_at"] = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        row.backtest = json.dumps(result)
        row.updated_at = ctx.clock.now_ms()
    mt = result.get("metrics") or {}
    m = Market(p.market_code)
    note(
        ctx,
        pid,
        "note",
        f"Backtest: {money(p.budget, m)} became {money(result.get('final', p.budget), m)} "
        f"({(mt.get('total_return') or 0) * 100:.1f}%), worst drop "
        f"{abs(mt.get('max_drawdown') or 0) * 100:.1f}%, {result.get('rebalances', 0)} rebalances.",
    )
    return result


def submit_backtest(ctx: Any, pid: int) -> str:
    _row(ctx, pid)
    job = ctx.jobs.submit(
        "portfolio_backtest",
        "Backtesting the portfolio",
        lambda jc: backtest(ctx, pid, jc.progress, jc.check),
        key=f"portfolio:{pid}",
        single=True,
    )
    return str(job.id)


# ---------------------------------------------------------------- portfolios


def create(
    ctx: Any,
    *,
    market: str,
    budget: float | None,
    risk: str = "balanced",
    name: str = "",
    method: str = "mix",
) -> dict[str, Any]:
    if market not in ("IN", "US"):
        raise _err("BAD_MARKET", "A portfolio is for India (IN) or the US (US).")
    if risk not in allocate.RISK:
        raise _err("BAD_RISK", "Risk must be careful, balanced or bold.")
    if method != "mix" and method not in METHOD_TEMPLATE:
        raise _err("BAD_METHOD", "The method must be mix, momentum or low_volatility.")
    amount = float(budget or DEFAULT_BUDGET[market])
    if amount <= 0:
        raise _err("BAD_BUDGET", "The budget must be more than zero.")
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        manage = bool(read_all(s)["portfolio.manage"])
        row = Portfolio(
            name=(name.strip() or f"{'India' if market == 'IN' else 'US'} portfolio")[:80],
            market_code=market,
            budget=amount,
            risk=risk,
            status="draft",
            manage=1 if manage else 0,
            created_at=now,
            updated_at=now,
            plan="{}",
            backtest="{}",
            cash=amount,
            method=method,
        )
        s.add(row)
        s.flush()
        pid = int(row.id)
    how = f", {METHOD_WORD[method]}" if method in METHOD_WORD else ""
    note(ctx, pid, "note", f"Portfolio created: {money(amount, Market(market))}, {risk} risk{how}.")
    return detail(ctx, pid)


def update(ctx: Any, pid: int, **changes: Any) -> dict[str, Any]:
    _row(ctx, pid)
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        if changes.get("name"):
            row.name = str(changes["name"])[:80]
        if changes.get("risk") in allocate.RISK:
            row.risk = str(changes["risk"])
        if changes.get("budget") is not None:
            if row.status == "paper":
                raise _err(
                    "PAPER_RUNNING",
                    "The budget can't change while the portfolio is paper trading.",
                    "Stop paper trading first.",
                )
            row.budget = float(changes["budget"])
            row.cash = row.budget
        if changes.get("manage") is not None:
            row.manage = 1 if changes["manage"] else 0
        row.updated_at = ctx.clock.now_ms()
    return detail(ctx, pid)


def archive(ctx: Any, pid: int) -> None:
    p = _row(ctx, pid)
    if p.status == "paper":
        stop_paper(ctx, pid)
    with ctx.db.session() as s:
        row = s.get(Portfolio, pid)
        assert row is not None
        row.status = "archived"


def summary(ctx: Any, row: Portfolio) -> dict[str, Any]:
    plan = json.loads(row.plan or "{}")
    bt = json.loads(row.backtest or "{}")
    out = {
        "id": row.id,
        "name": row.name,
        "market": row.market_code,
        "budget": row.budget,
        "risk": row.risk,
        "method": row.method,
        "status": row.status,
        "manage": bool(row.manage),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "sleeves_planned": len(plan.get("sleeves") or []),
        "backtest_return": (bt.get("metrics") or {}).get("total_return"),
        "paper_started_at": row.paper_started_at,
    }
    if row.status == "paper":
        from backend.portfolio import live

        out["live"] = live.value(ctx, row.id)
    return out


def portfolios(ctx: Any) -> list[dict[str, Any]]:
    with ctx.db.session() as s:
        rows = s.scalars(
            select(Portfolio).where(Portfolio.status != "archived").order_by(Portfolio.id.desc())
        ).all()
        for r in rows:
            s.expunge(r)
    return [summary(ctx, r) for r in rows]


def detail(ctx: Any, pid: int) -> dict[str, Any]:
    row = _row(ctx, pid)
    from backend.portfolio import live

    out = summary(ctx, row)
    out["plan"] = json.loads(row.plan or "{}")
    out["backtest"] = json.loads(row.backtest or "{}")
    out["sleeves"] = live.sleeves_public(ctx, pid)
    out["moves"] = moves(ctx, pid, 30)
    out["cash"] = row.cash
    out["opportunities"] = opportunities(ctx, row.market_code)[:20]
    return out


def start_paper(ctx: Any, pid: int) -> dict[str, Any]:
    from backend.portfolio import live

    return live.start(ctx, pid)


def stop_paper(ctx: Any, pid: int) -> dict[str, Any]:
    from backend.portfolio import live

    return live.stop(ctx, pid)
