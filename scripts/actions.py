"""Read Agora's action log from a terminal (for a Claude session; the user has the Logs page).

python scripts/actions.py                    what happened in the last 24 hours, by kind
python scripts/actions.py --kind metis_round --hours 72
python scripts/actions.py --status failed
python scripts/actions.py --q IOVA --limit 50
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "data" / "actions.db"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--q", default="")
    p.add_argument("--kind", default="")
    p.add_argument("--status", default="")
    p.add_argument("--hours", type=float, default=24.0)
    p.add_argument("--limit", type=int, default=40)
    a = p.parse_args()
    c = sqlite3.connect(f"file:{FILE.as_posix()}?mode=ro", uri=True, timeout=10)
    since = int((time.time() - a.hours * 3600) * 1000)
    if not (a.q or a.kind or a.status):
        for row in c.execute(
            """select kind, count(*), sum(status='ok'), sum(status='failed'), sum(status='wrong'),
                      sum(status='cut_off'), sum(status='running'), cast(avg(ms) as int)
               from actions where started_at >= ? group by 1 order by 2 desc""",
            (since,),
        ):
            print(
                "{:<24} n {:<7} ok {:<7} failed {:<5} wrong {:<4} cut {:<4} open {:<4} avg ms {}".format(  # noqa: E501
                    *row
                )
            )
        return
    where, args = ["started_at >= ?"], [since]
    if a.q:
        where.append("(what like ? or why like ? or output like ?)")
        args += [f"%{a.q}%"] * 3
    if a.kind:
        where.append("kind = ?")
        args.append(a.kind)
    if a.status:
        where.append("status = ?")
        args.append(a.status)
    sql = (
        "select started_at, kind, who, status, ms, what, output from actions "
        f"where {' and '.join(where)} order by id desc limit ?"
    )
    for at, kind, who, status, ms, what, out in c.execute(sql, [*args, a.limit]):
        when = datetime.fromtimestamp(at / 1000).strftime("%m-%d %H:%M:%S")
        print(f"{when} {kind:<18} {who:<9} {status:<8} {ms or 0:>7}ms  {what} -> {out}"[:220])


if __name__ == "__main__":
    main()
