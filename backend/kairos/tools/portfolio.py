"""Kairos's tool for portfolios and opportunities (PORTFOLIO §7, D-84 to D-86): build a
portfolio from a budget, say how it is doing, backtest it, paper trade it, rebalance it, and
find new opportunities. The allocation itself is always the allocator's code (D-56)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from backend.core.types import Market
from backend.errors import AgoraError
from backend.kairos import resolve
from backend.kairos.tools.base import Args, Env, Result, Tool
from backend.kairos.tools.lab import wait_job
from backend.metrics.summary import money
from backend.portfolio import live
from backend.portfolio import service as svc


class PortfolioArgs(Args):
    action: Literal[
        "status", "build", "plan", "backtest", "start", "stop", "rebalance", "opportunities", "scan"
    ] = Field(
        "status",
        description="status: how a portfolio is doing; build: a new portfolio from a budget; "
        "plan: re-plan; backtest; start/stop: paper trading; rebalance; opportunities: list "
        "them; scan: find new opportunities.",
    )
    market: str | None = Field(None, description="IN or US.")
    budget: float | None = Field(None, description="Paper money to allocate, e.g. 100000.")
    risk: Literal["careful", "balanced", "bold"] | None = Field(None, description="Risk level.")
    method: Literal["mix", "momentum", "low_volatility"] | None = Field(
        None,
        description="build: mix (the best of the user's strategies, the default), momentum "
        "(hold the index's strongest risers, re-ranked monthly) or low_volatility (the calmest).",
    )
    portfolio: str | None = Field(None, description="Portfolio name or id (default: the latest).")


def _pick(env: Env, ref: str | None) -> dict[str, Any]:
    items = svc.portfolios(env.ctx)
    if not items:
        raise AgoraError(
            "NO_PORTFOLIO",
            "You don't have a portfolio yet.",
            "Ask me to build one, e.g. “build me a portfolio with ₹1 lakh”.",
        )
    if ref:
        low = ref.lower().lstrip("#")
        for p in items:
            if str(p["id"]) == low or p["name"].lower() == low or low in p["name"].lower():
                return p
    return items[0]


def _plan_lines(plan: dict[str, Any], m: Market) -> list[str]:
    lines = []
    for s in plan.get("sleeves", []):
        lines.append(
            f"- {s['name']} on {', '.join(s['symbols'][:5])}: {money(s['capital'], m)} "
            f"({s['weight'] * 100:.0f}%). {s['reasons'][0] if s['reasons'] else ''}"
        )
    lines.append(f"Kept in cash: {money(plan.get('cash', 0), m)}.")
    for x in plan.get("left_out", [])[:3]:
        lines.append(f"- {x['name']}: {x['reason']}")
    lines += plan.get("notes", [])[:2]
    return lines


def portfolio(env: Env, a: PortfolioArgs) -> Result:
    ctx = env.ctx
    if a.action in ("scan", "opportunities"):
        markets = [a.market.upper()] if a.market and a.market.upper() in ("IN", "US") else None
        if markets is None:
            mk = resolve.market_of(env.state.market)
            markets = [mk.value] if mk else ["IN", "US"]
        if a.action == "scan":
            out = wait_job(env, svc.start_scan(ctx, markets), "opportunity scan")
            lines = [out["note"]]
        else:
            lines = []
        opps = [o for m in markets for o in svc.opportunities(ctx, m)][:6]
        lines += [f"- {o['name']} on {', '.join(o['symbols'][:5])}: {o['evidence']}" for o in opps]
        if not opps:
            lines.append("No open opportunities yet: none held up on unseen years.")
        card = {
            "type": "list",
            "title": "Opportunities",
            "items": [
                {"label": f"{o['name']} · {', '.join(o['symbols'][:3])}", "sub": o["evidence"]}
                for o in opps
            ],
            "link": "/portfolio",
        }
        label = "Found new opportunities" if a.action == "scan" else "Listed opportunities"
        return Result(
            True, "\n".join(lines), label, f"{len(opps)} open", card, {"navigate": "/portfolio"}
        )
    if a.action == "build":
        mk = resolve.market_of(a.market) or resolve.market_of(env.state.market) or Market.IN
        p = svc.create(
            ctx,
            market=mk.value,
            budget=a.budget,
            risk=a.risk or "balanced",
            method=a.method or "mix",
        )
        plan = wait_job(env, svc.submit_plan(ctx, p["id"]), "portfolio plan")
        m = Market(p["market"])
        lines = [
            f"Built portfolio #{p['id']} “{p['name']}” with {money(p['budget'], m)} "
            f"({p['risk']} risk). The allocator (tested code) split it like this:",
            *_plan_lines(plan, m),
        ]
        if plan.get("sleeves"):
            lines.append("Next: backtest it, then paper trade it, from the Portfolio screen.")
        link = f"/portfolio/{p['id']}"
        card = {
            "type": "list",
            "title": f"Portfolio · {money(p['budget'], m)}",
            "items": [
                {
                    "label": s["name"],
                    "sub": f"{money(s['capital'], m)} · {', '.join(s['symbols'][:3])}",
                }
                for s in plan.get("sleeves", [])
            ],
            "link": link,
        }
        return Result(
            True,
            "\n".join(lines),
            "Built a portfolio",
            f"{len(plan.get('sleeves', []))} sleeves",
            card,
            {"navigate": link},
        )
    p = _pick(env, a.portfolio)
    pid, m = int(p["id"]), Market(p["market"])
    link = f"/portfolio/{pid}"
    if a.action == "plan":
        plan = wait_job(env, svc.submit_plan(ctx, pid), "portfolio plan")
        return Result(
            True,
            "\n".join(["New plan:", *_plan_lines(plan, m)]),
            "Re-planned the portfolio",
            "",
            None,
            {"navigate": link},
        )
    if a.action == "backtest":
        out = wait_job(env, svc.submit_backtest(ctx, pid), "portfolio backtest")
        mt = out.get("metrics") or {}
        lines = [
            f"Backtest of “{p['name']}”: {money(out['budget'], m)} became {money(out['final'], m)} "
            f"({(mt.get('total_return') or 0) * 100:.1f}%), worst drop "
            f"{abs(mt.get('max_drawdown') or 0) * 100:.1f}%, Sharpe {mt.get('sharpe') or 0:.2f}, "
            f"{out.get('rebalances', 0)} rebalances.",
            out.get("honesty", ""),
        ]
        lines += [
            f"- {s['name']}: made {money(s['made'], m)} on {money(s['capital'], m)}"
            for s in out.get("sleeves", [])
        ]
        return Result(
            True, "\n".join(lines), "Backtested the portfolio", "", None, {"navigate": link}
        )
    if a.action == "start":
        d = svc.start_paper(ctx, pid)
        lines = [
            f"Paper trading “{p['name']}” started with {len(d['sleeves'])} sleeves (paper money only)."
        ]
        return Result(
            True,
            "\n".join(lines),
            "Started paper trading the portfolio",
            "",
            None,
            {"navigate": link},
        )
    if a.action == "stop":
        svc.stop_paper(ctx, pid)
        return Result(
            True,
            f"Paper trading “{p['name']}” stopped.",
            "Stopped the portfolio",
            "",
            None,
            {"navigate": link},
        )
    if a.action == "rebalance":
        if p["status"] != "paper":
            return Result(
                True,
                "A portfolio is rebalanced while it paper trades; this one isn't trading.",
                "Nothing to rebalance",
                "",
            )
        out = live.rebalance(ctx, pid, "Rebalance you asked for")
        return Result(
            True,
            f"Rebalanced: moved {money(out['moved'], m)}; cash now {money(out['cash'], m)}.",
            "Rebalanced the portfolio",
            "",
            None,
            {"navigate": link},
        )
    d = svc.detail(ctx, pid)
    lines = [f"“{d['name']}” ({d['status']}): budget {money(d['budget'], m)}, {d['risk']} risk."]
    if d.get("live"):
        lv = d["live"]
        lines.append(
            f"Worth {money(lv['equity'], m)} now ({lv['return'] * 100:+.1f}%), {money(lv['cash'], m)} in cash."
        )
        for s in d["sleeves"]:
            if s["status"] != "retired":
                lines.append(
                    f"- {', '.join(s['symbols'][:4])}: {money(s['equity'] or 0, m)} ({s['status']})"
                )
    elif d["plan"].get("sleeves"):
        lines += _plan_lines(d["plan"], m)
    for mv in d["moves"][:3]:
        lines.append(f"Diary: {mv['text']}")
    return Result(True, "\n".join(lines), "Checked the portfolio", "", None, {"navigate": link})


TOOLS = [
    Tool(
        "portfolio",
        "Portfolios: one budget (e.g. ₹1 lakh or $1,000) split across strategies and stocks by "
        "Agora's allocator, backtested together and paper traded as one; and opportunities (the "
        "user's strategies on new stocks that held up on unseen years). Build, check, backtest, "
        "start/stop paper trading, rebalance, list or find opportunities.",
        PortfolioArgs,
        portfolio,
        lambda a: "Working on the portfolio…",
        group="portfolio",
    )
]
