"""One Kairos study in its own process: ``python -m backend.kairos.study IN 1d`` (D-148).

A study walks every stock's history in plain Python, so studies run as threads inside Agora
share one processor core (Python's global lock): ten timeframes took hours on the user's
16-core laptop. Run as a child process, each study gets a core of its own and several finish
in minutes. The job inside Agora starts this command, passes on the ``PROGRESS`` lines as the
job's progress and reads the ``RESULT`` line; the study writes its numbers to the database and
the judge's file itself, exactly as it would in-process.
"""

from __future__ import annotations

import json
import sys
from typing import Any

PROGRESS = "PROGRESS"
RESULT = "RESULT"


def _ctx() -> Any:
    from backend.config import get_paths
    from backend.main import build_real_context

    paths = get_paths()
    paths.ensure()
    return build_real_context(paths)


def main(argv: list[str] | None = None, ctx: Any = None) -> int:
    from backend.core.types import Market, Timeframe

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m backend.kairos.study MARKET TIMEFRAME", file=sys.stderr)
        return 2
    market, tf = Market(args[0]), Timeframe(args[1])
    ctx = ctx or _ctx()

    def say(pct: float, text: str) -> None:
        print(f"{PROGRESS} {pct:.1f} {text}", flush=True)

    out = ctx.learning.train(market, tf, say)
    print(f"{RESULT} {json.dumps(out)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
