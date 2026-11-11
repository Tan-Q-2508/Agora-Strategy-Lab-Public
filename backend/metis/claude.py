"""Claude's ideas through Metis's tests (D-160): ``python -m backend.metis.claude``.

The user asked (2026-11-04) to replace Ollama for 48 hours and boost discovering, testing and
improving strategies "by 100x or more". The 4B model gave about one usable idea every three
minutes, many broken or repeats. In a laptop session Claude writes ideas instead: finished
rules for new strategies, and filters, settings and exits for the user's strategies. They go
through exactly the tests Metis's own ideas do (the study and exam years, the luck check that
counts every idea already tried, the overfitting check, the index bar; ``trial.try_new`` and
``trial.try_change``), are recorded in Metis's notebook as rounds by "claude", and what holds up
is saved as Metis saves its own (when ``metis.apply`` is on). Nothing here can keep an idea that
Metis's verdict wouldn't.

    strategies             the user's strategies: id, market, timeframe, rules, record
    run FILE [--note T]    test the ideas in FILE (a JSON list) as one round
    rejudge [--dry]        new strategies rejected on the luck check alone, judged again
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

KINDS = ("filter", "tweak", "simplify", "universe", "new_strategy")


def _ctx() -> Any:
    from backend.config import get_paths
    from backend.main import build_real_context

    paths = get_paths()
    paths.ensure()
    return build_real_context(paths)


def normal(raw: dict[str, Any]) -> dict[str, Any]:
    """An idea in the shape Metis's tests expect, with every key present."""
    kind = str(raw.get("kind", "")).strip().lower()
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r}")
    return {
        "kind": kind,
        "strategy_id": raw.get("strategy_id"),
        "title": str(raw.get("title") or kind)[:120],
        "why": str(raw.get("why") or "")[:600],
        "conditions": list(raw.get("conditions") or []),
        "side": raw.get("side") or "long",
        "changes": dict(raw.get("changes") or {}),
        "remove": raw.get("remove"),
        "add": list(raw.get("add") or []),
        "drop": list(raw.get("drop") or []),
        "idea": str(raw.get("idea") or ""),
        "market": raw.get("market"),
        "timeframe": raw.get("timeframe"),
        "symbols": list(raw.get("symbols") or []),
        "definition": raw.get("definition"),
        "origin": "ai",
    }


def strategies(ctx: Any) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from backend.db.models import Strategy
    from backend.metis import agenda, brief

    live = set(agenda.in_use(ctx))
    with ctx.db.session() as s:
        ids = list(
            s.scalars(
                select(Strategy.id).where(Strategy.archived_at.is_(None), Strategy.kind != "kairos")
            )
        )
    out = []
    for sid in ids:
        try:
            b = brief.baseline(ctx, sid)
        except Exception as exc:  # one strategy that can't run doesn't stop the list
            out.append({"id": sid, "error": str(exc)[:200]})
            continue
        if b is None:
            continue
        out.append(
            {
                "id": sid,
                "name": b.name,
                "version_id": b.version_id,
                "market": b.market.value,
                "timeframe": b.definition.timeframe,
                "kind": b.definition.kind,
                "in_use": sid in live,
                "rules": brief.short_rules(b.definition),
                "study": brief.part_line(b.study, b.market),
                "exam": brief.part_line(b.exam, b.market),
            }
        )
    return out


RANKING_STOCKS = 30  # the research sprint's daily universe size (D-143)


def fill_ranking_stocks(ctx: Any, idea: dict[str, Any]) -> None:
    """A ranking strategy ranks many stocks: one written without any gets the market's most
    traded stocks with enough history, as the research sprint used (all ~1,600 saved stocks
    would be far too heavy for a laptop). Every ranking idea in Claude's first batches came
    back "no stocks are chosen" without this."""
    d = idea.get("definition")
    if not d or d.get("kind") != "ranking" or (d.get("universe") or {}).get("symbols"):
        return
    from backend.lab import runner

    syms = runner.universe(ctx, str(idea["market"]), "1d", RANKING_STOCKS)
    d["universe"] = {"kind": "symbols", "symbols": syms}
    # a ranking must choose from several times the stocks it holds (as the lab does)
    r = d.setdefault("ranking", {})
    r["hold"] = max(1, min(int(r.get("hold", 10)), len(syms) // 3))
    idea["symbols"] = syms


def run(ctx: Any, ideas: list[dict[str, Any]], note: str = "") -> dict[str, Any]:
    """Test ``ideas`` as one Metis round by Claude; returns the round's counts."""
    from backend.metis import apply, brief, notebook, trial
    from backend.settings_store import read_all

    with ctx.db.session() as s:
        settings = read_all(s)
    kinds = {i["kind"] for i in ideas}
    direction = "discover" if kinds == {"new_strategy"} else "improve"
    # trigger "user" (the user asked for it) and model "claude" mark these rounds
    rid = notebook.start_round(ctx, "user", note[:200], "claude", direction)
    baselines: dict[int, Any] = {}
    tried = kept = skipped = 0
    lines: list[str] = []
    try:
        for idea in ideas:
            sid = idea.get("strategy_id")
            if idea["kind"] != "new_strategy":
                if sid is None:
                    lines.append(f"untestable  {idea['title']}: no strategy_id")
                    continue
                if sid not in baselines:
                    b = brief.baseline(ctx, int(sid))
                    if b is None:
                        lines.append(f"untestable  {idea['title']}: no strategy #{sid}")
                        continue
                    baselines[int(sid)] = b
            fill_ranking_stocks(ctx, idea)
            fp = trial.fingerprint_of(idea, baselines)
            if notebook.seen(ctx, fp):
                skipped += 1
                continue
            if idea["kind"] == "new_strategy":
                out = trial.try_new(
                    ctx,
                    idea,
                    fp,
                    provider=None,
                    model="",
                    num_ctx=0,
                    markets=[idea["market"] or "IN"],
                )
            else:
                out = trial.try_change(ctx, idea, baselines[int(sid)], fp)  # type: ignore[arg-type]
            tried += out.status != "untestable"
            iid = notebook.add_idea(
                ctx,
                rid,
                kind=idea["kind"],
                title=idea["title"],
                why=idea["why"],
                market_code=out.market,
                strategy_id=out.strategy_id,
                strategy_version_id=out.version_id,
                spec=json.dumps(out.rules),
                fingerprint=out.fingerprint,
                status=out.status,
                verdict=out.verdict,
                result=json.dumps(out.result),
                origin="ai",
            )
            lines.append(f"{out.status:11s} {idea['title']}: {out.verdict[:160]}")
            if out.status == "held_up":
                kept += 1
                if settings["metis.apply"]:
                    try:
                        apply.save(ctx, iid, auto=True)
                    except Exception as exc:  # a save that fails leaves the idea held up
                        lines.append(f"  (couldn't save: {exc})")
        text = f"Claude's ideas: tested {tried}, {kept} held up"
        text += f", skipped {skipped} tried before." if skipped else "."
        notebook.update_round(
            ctx,
            rid,
            status="done",
            finished_at=ctx.clock.now_ms(),
            note=text,
            ideas=tried,
            kept=kept,
        )
    except BaseException:
        notebook.update_round(
            ctx, rid, status="failed", finished_at=ctx.clock.now_ms(), note="Stopped."
        )
        raise
    return {"round_id": rid, "tried": tried, "kept": kept, "skipped": skipped, "lines": lines}


TF_WORDS = {"1d": "daily", "1h": "hourly", "15m": "15-minute", "5m": "5-minute", "1m": "1-minute"}
_TF_IN_NAME = re.compile(
    r"\b(intraday|hourly|daily|1h|1d|15m|5m|1m|\d+-?min(ute)?|1-hour|15-minute|5-minute)\b",
    re.IGNORECASE,
)


def true_name(title: str, timeframe: str) -> str:
    """The idea's name with the candle size it really uses: the small model, reading a cut
    brief, named daily strategies "Hourly", "1h" or "5m" (D-163)."""
    words = _TF_IN_NAME.findall(title)
    if not words:
        return title
    bare = " ".join(_TF_IN_NAME.sub("", title).split())
    return f"{bare} ({TF_WORDS.get(timeframe, timeframe)})"[:120]


def rejudge(ctx: Any, *, dry: bool = False) -> list[str]:
    """New strategies rejected on the luck check alone, judged again on their saved exam-year
    returns with the luck check's count of independent tries (D-162, D-163). Every other check
    passed at the time and is kept as it was; nothing is re-run. Today's count is used, which
    includes every try since, so the bar is at least as strict as then in tries."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from backend.db.models import MetisIdea
    from backend.metis import apply, notebook, overfit, trial
    from backend.settings_store import read_all

    with ctx.db.session() as s:
        settings = read_all(s)
        rows = s.execute(
            select(
                MetisIdea.id,
                MetisIdea.market_code,
                MetisIdea.title,
                MetisIdea.result,
                MetisIdea.spec,
            )
            .where(MetisIdea.status == "rejected", MetisIdea.kind == "new_strategy")
            .order_by(MetisIdea.id)
        ).all()
    lines: list[str] = []
    seen_returns: set[str] = set()
    for iid, market, title, raw, spec in rows:
        res = json.loads(raw or "{}")
        bad = [c for c in res.get("checks") or [] if not c.get("ok")]
        if len(bad) != 1 or not str(bad[0].get("text", "")).startswith("Luck check"):
            continue
        daily = res.get("daily") or {}
        split_day = datetime.fromtimestamp(int(res["split"]) / 1000, UTC).date().isoformat()
        exam = [
            float(r)
            for d, r in zip(daily.get("days", []), daily.get("r", []), strict=False)
            if d >= split_day
        ]
        # the small model rewrote one rule many times: one idea per distinct return series
        same = hashlib.sha256(json.dumps([round(x, 6) for x in exam]).encode()).hexdigest()
        if same in seen_returns:
            continue
        counted = notebook.tries(ctx, market=market, kind="new_strategy")
        n = overfit.effective_tries(ctx, market, counted) + 1
        lk = trial.luck(exam, n)
        if lk is None or lk["dsr"] < trial.MIN_LUCK:
            continue
        seen_returns.add(same)
        tf = str((json.loads(spec or "{}").get("definition") or {}).get("timeframe") or "1d")
        named = true_name(title, tf)
        lines.append(f"held_up  #{iid} {market} {named}: luck {lk['dsr']:.0%} over {n} tries")
        if dry:
            continue
        for c in res["checks"]:
            if str(c.get("text", "")).startswith("Luck check"):
                c.update(trial.luck_check(lk)[0])
        res["luck"] = lk
        res["rejudged"] = "D-163: luck check over independent tries (D-162)"
        verdict = (
            "Held up when judged again with the luck check over independent tries (D-162): "
            f"{lk['dsr'] * 100:.0f}% chance it beats the best of {n} lucky tries; every other "
            "check had passed."
        )
        notebook.set_idea(
            ctx, iid, status="held_up", verdict=verdict, result=json.dumps(res), title=named
        )
        if settings["metis.apply"]:
            try:
                apply.save(ctx, iid, auto=True)
            except Exception as exc:  # a save that fails leaves the idea held up
                lines.append(f"  (couldn't save #{iid}: {exc})")
    return lines


def utf8_output() -> None:
    """Print ₹ and other non-ASCII text even when the output goes to a file on Windows, whose
    default code page (cp1252) can't encode them: a batch's results were lost to a
    UnicodeEncodeError after every idea had been tested (2026-11-05)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None, ctx: Any = None) -> int:
    utf8_output()
    ap = argparse.ArgumentParser(prog="python -m backend.metis.claude")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("strategies")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--note", default="")
    j = sub.add_parser("rejudge")
    j.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    ctx = ctx or _ctx()
    if a.cmd == "strategies":
        print(json.dumps(strategies(ctx), indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "rejudge":
        found = rejudge(ctx, dry=a.dry)
        print("\n".join(found) or "Nothing to judge again.")
        print(f"{sum(1 for x in found if x.startswith('held_up'))} held up")
        return 0
    ideas = [normal(x) for x in json.loads(Path(a.file).read_text(encoding="utf-8"))]
    out = run(ctx, ideas, a.note)
    for line in out["lines"]:
        print(line)
    print(json.dumps({k: v for k, v in out.items() if k != "lines"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
