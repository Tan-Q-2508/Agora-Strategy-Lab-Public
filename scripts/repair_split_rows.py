"""One-off repair (D-228): candles Yahoo served half-adjusted around a big split.

    python scripts/repair_split_rows.py          count what it would change, and the worst cases
    python scripts/repair_split_rows.py --apply  change it

Rescales open, high, low and close by the split's ratio and the volume the other way. Daily,
hourly and shorter candles are each read as their own series. Safe to run twice: a repaired series
has no jumps left to find.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.data.repair import find  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    c = sqlite3.connect(ROOT / "data" / "agora.db", timeout=60)
    ids = [
        r[0]
        for r in c.execute(
            "select distinct instrument_id from candles where split_factor >= 3 "
            "or (split_factor <= 0.34 and split_factor > 0)"
        )
    ]
    total: Counter[str] = Counter()
    who: Counter[str] = Counter()
    pending: list[tuple[float, float, int, str, int]] = []
    for iid in ids:
        sym = c.execute("select symbol from instruments where id = ?", (iid,)).fetchone()[0]
        for tf in ("1d", "1h", "15m", "5m", "1m"):
            rows = c.execute(
                "select ts, close, split_factor from candles "
                "where instrument_id = ? and timeframe = ? order by ts",
                (iid, tf),
            ).fetchall()
            if len(rows) < 2:
                continue
            fixes = find([r[1] for r in rows], [r[2] for r in rows])
            total[tf] += len(fixes)
            if fixes:
                who[sym] += len(fixes)
            pending += [(f.multiply, 1 / f.multiply, iid, tf, rows[f.index][0]) for f in fixes]
    print(f"{len(ids)} stocks with a big split; rows to repair by timeframe: {dict(total)}")
    print("most affected:", who.most_common(12), "stocks:", len(who))
    if apply:
        # every change is written down first, so it can be undone
        undo = ROOT / "data" / "backups" / "split-repair-undo.csv"
        with undo.open("a", encoding="utf8") as f:
            w = csv.writer(f)
            w.writerows((iid, tf, ts, m) for m, _v, iid, tf, ts in pending)
        for i in range(0, len(pending), 2000):
            c.executemany(
                "update candles set open = open * ?1, high = high * ?1, low = low * ?1, "
                "close = close * ?1, volume = volume * ?2 "
                "where instrument_id = ?3 and timeframe = ?4 and ts = ?5",
                pending[i : i + 2000],
            )
            c.commit()
        print("repaired")


if __name__ == "__main__":
    main()
