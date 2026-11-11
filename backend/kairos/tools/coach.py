"""Kairos's coaching tools: review trades, improve a strategy, say what it learned on its
own (KAIROS §16–18)."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from sqlalchemy import select

from backend.db.models import BacktestRun, StrategyVersion
from backend.errors import AgoraError
from backend.kairos import resolve
from backend.kairos.tools.base import Args, Env, Result, Tool
from backend.kairos.tools.lab import wait_job


class ReviewArgs(Args):
    strategy: str | None = Field(
        None, description="Strategy name or id (default: the one we're talking about)."
    )
    backtest_id: int | None = Field(None, description="A backtest id (default: the latest one).")
    paper_session_id: int | None = Field(
        None, description="Review a paper-trading session instead of a backtest."
    )


def _latest_run(ctx: Any, strategy_id: int) -> int | None:
    with ctx.db.session() as s:
        rid = s.scalar(
            select(BacktestRun.id)
            .join(StrategyVersion, StrategyVersion.id == BacktestRun.strategy_version_id)
            .where(
                StrategyVersion.strategy_id == strategy_id,
                BacktestRun.status == "done",
                BacktestRun.parent_run_id.is_(None),
            )
            .order_by(BacktestRun.id.desc())
            .limit(1)
        )
    return int(rid) if rid is not None else None


def review_trades(env: Env, a: ReviewArgs) -> Result:
    coach = env.ctx.services["kairos_coach"]
    if a.paper_session_id or (
        a.backtest_id is None
        and a.strategy is None
        and env.state.session_id
        and env.page.get("screen") == "paper"
    ):
        sid = int(a.paper_session_id or env.state.session_id or 0)
        env.progress(20, "Reading the paper trades…")
        r = coach.review_paper(sid)
        link = f"/paper/{sid}"
        what = f"paper session #{sid}"
    else:
        rid = a.backtest_id
        if rid is None:
            if a.strategy is not None or env.state.strategy_id is not None:
                ref = resolve.strategy(env.ctx, a.strategy, latest_id=env.state.strategy_id)
                rid = _latest_run(env.ctx, ref.strategy_id)
            else:
                rid = env.state.run_id
        if rid is None:
            raise AgoraError(
                "NO_BACKTEST",
                "There's no finished backtest to review yet.",
                "Run a backtest first, then ask me why its trades won or lost.",
            )
        env.progress(20, "Reading the trades and the market around each one…")
        r = coach.review_backtest(int(rid))
        env.state.run_id = int(rid)
        link = f"/backtests/{rid}#kairos-review"
        what = f"backtest #{rid}"
    if not r.get("trades"):
        return Result(True, str(r.get("headline")), f"Reviewed {what}", "No closed trades")
    lines = list(r.get("lines", []))[:6]
    good = [x for x in r.get("filters", {}).get("rules", []) if x.get("held_up")]
    for x in good[:2]:
        t = x["test"]
        lines.append(
            f"Filter that held up on unseen trades: {x['text']} (win rate "
            f"{(t['before']['win_rate'] or 0) * 100:.0f}% → {(t['after']['win_rate'] or 0) * 100:.0f}%)."
        )
    lines += [f"Advice: {x}" for x in r.get("advice", [])[:2]]
    card = {
        "type": "list",
        "title": f"Why the trades went the way they did ({what})",
        "items": [{"label": x, "sub": "", "link": None} for x in lines[:5]],
        "link": link,
    }
    return Result(
        True,
        "\n".join(lines),
        f"Reviewed {what}",
        f"{r['trades']} trades",
        card,
        {"navigate": link},
    )


class ImproveArgs(Args):
    strategy: str | None = Field(None, description="Strategy name or id.")


def improve_strategy(env: Env, a: ImproveArgs) -> Result:
    ref = resolve.strategy(env.ctx, a.strategy, latest_id=env.state.strategy_id)
    env.state.strategy_id = ref.strategy_id
    from backend.kairos.improve import improve

    job = env.ctx.jobs.submit(
        "kairos_improve",
        f"Improving {ref.name}",
        lambda jc: improve(env.ctx, ref.strategy_id, jc.progress),
        key=f"strategy:{ref.strategy_id}",
        priority=True,  # the user is waiting in the chat (D-115)
    )
    out = wait_job(env, job.id, "improvement test")
    lines = [str(out.get("headline", "")), *out.get("lines", [])]
    link = f"/strategies/{ref.strategy_id}"
    card = {
        "type": "list",
        "title": f"Improving {ref.name}",
        "items": [{"label": x, "sub": "", "link": None} for x in lines[:4]],
        "link": link,
    }
    return Result(
        True,
        "\n".join(lines),
        "Tested an improvement" if not out.get("changed") else "Saved an improved version",
        ref.name,
        card,
    )


class NoArgs(Args):
    pass


def learning_status(env: Env, a: NoArgs) -> Result:
    learner = env.ctx.services["kairos_learner"]
    st = learner.status()
    lines = []
    if not st["on"]:
        lines.append("My always-on learning is switched off in Settings → Kairos.")
    for item in st["activity"][:6]:
        lines.append(f"- {item['text']}")
    for h in st["history"][:3]:
        for item in h.get("items", [])[:3]:
            lines.append(f"- {item['text']}")
    if len(lines) <= 1:
        lines.append(
            "I haven't studied anything new yet in this run of Agora. I review finished "
            "backtests and paper trades, and check my price predictions against what happened, "
            "every ten minutes or so while Agora is open."
        )
    return Result(True, "\n".join(dict.fromkeys(lines)), "Checked what I studied", "")


TOOLS = [
    Tool(
        "review_trades",
        "Explain why a backtest's (or paper session's) trades won or lost: costs versus profit, "
        "win rate versus the size of wins and losses, exits, the market conditions where the "
        "strategy's trades failed although its rules were met, and filters that held up on "
        "unseen trades.",
        ReviewArgs,
        review_trades,
        lambda a: "Reviewing the trades…",
        group="coach",
    ),
    Tool(
        "improve_strategy",
        "Make a strategy take fewer bad trades: find a filter that held up on unseen trades, "
        "backtest it, and save it as a new version only if it made more after costs and won "
        "more often.",
        ImproveArgs,
        improve_strategy,
        lambda a: "Testing an improvement…",
        group="coach",
    ),
    Tool(
        "learning_status",
        "What Kairos has been studying on its own while Agora is open (reviews, predictions "
        "checked, strategies improved).",
        NoArgs,
        learning_status,
        lambda a: "Checking what I studied…",
        group="learning",
    ),
]
