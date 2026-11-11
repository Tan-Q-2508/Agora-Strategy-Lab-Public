"""Run a research sprint from the command line (D-143). Used by Claude in a laptop session:

    uv run python -m backend.lab run     --sprint 2026-11 [--families a,b] [--markets IN,US]
    uv run python -m backend.lab report  --sprint 2026-11
    uv run python -m backend.lab pick    --sprint 2026-11
    uv run python -m backend.lab vault   --sprint 2026-11
    uv run python -m backend.lab promote --sprint 2026-11

It reads the user's saved prices (no downloads) and writes the ledger into his database. It
is safe while Agora is open: it only adds rows to its own table.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from backend.lab import ledger, playbook, runner


def _ctx() -> Any:
    from backend.config import get_paths
    from backend.db.migrate import upgrade_and_seed
    from backend.main import build_real_context

    paths = get_paths()
    paths.ensure()
    upgrade_and_seed(paths=paths).engine.dispose()
    return build_real_context(paths)


def main(argv: list[str] | None = None, ctx: Any = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.lab")
    ap.add_argument("step", choices=["run", "report", "pick", "vault", "promote", "families"])
    ap.add_argument("--sprint", default="")
    ap.add_argument("--families", default="all")
    ap.add_argument("--markets", default="IN,US")
    ap.add_argument("--timeframes", default="")
    ap.add_argument("--stocks", type=int, default=0)
    a = ap.parse_args(argv)
    if a.step == "families":
        from backend.lab.families import FAMILIES

        for f in FAMILIES:
            n = len(f.variants()) or 1
            print(f"{f.key}: {f.name} [{f.style}; {', '.join(f.timeframes)}; {n} variants]")
        return 0
    if not a.sprint:
        print("Name the sprint with --sprint (e.g. 2026-11).", file=sys.stderr)
        return 2
    ctx = ctx or _ctx()
    say = lambda m: print(m, flush=True)  # noqa: E731
    if a.step == "run":
        out = runner.run_sprint(
            ctx,
            a.sprint,
            family_keys=a.families.split(","),
            markets=a.markets.split(","),
            timeframes=[x for x in a.timeframes.split(",") if x] or None,
            stocks=a.stocks or None,
            say=say,
        )
        print(out)
    elif a.step == "report":
        print(runner.report(ctx, a.sprint))
    elif a.step == "pick":
        for r in runner.pick_finalists(ctx, a.sprint):
            print(
                f"finalist #{r['id']} {r['family']} {r['market']} {r['timeframe']} {r['variant']}"
            )
    elif a.step == "vault":
        runner.open_vault(ctx, a.sprint, say=say)
    elif a.step == "promote":
        rows = ledger.rows(ctx, a.sprint, status=["promoted"])
        entries = [playbook.entry_of(r) for r in rows]
        playbook.save(playbook.merge(playbook.load(), entries))
        print(f"{len(entries)} entries written to {playbook.PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
