"""One-off repair (D-221): hourly candles Yahoo re-served with volume 0 get it back from the
15-minute candles of the same hour, where those exist. Touches only candles with a price range and
no volume; prices are left alone. Safe to run twice.

    python scripts/repair_zero_volume.py          count what it would change
    python scripts/repair_zero_volume.py --apply  change it
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "data" / "agora.db"
HOUR = 3_600_000
FIND = """select c.instrument_id, c.ts from candles c
          where c.timeframe = '1h' and c.volume = 0 and c.high > c.low"""
SUM = """select sum(volume), count(*) from candles
         where instrument_id = ? and timeframe = '15m' and ts >= ? and ts < ?"""


def main() -> None:
    apply = "--apply" in sys.argv
    c = sqlite3.connect(FILE, timeout=60)
    rows = c.execute(FIND).fetchall()
    fixed = left = 0
    pending: list[tuple[float, int, int]] = []
    for iid, ts in rows:
        total, n = c.execute(SUM, (iid, ts, ts + HOUR)).fetchone()
        if n and total:
            fixed += 1
            pending.append((float(total), iid, ts))
        else:
            left += 1
    print(f"{len(rows)} hourly candles with no volume: {fixed} can be repaired, {left} can't")
    if apply:
        for i in range(0, len(pending), 2000):
            c.executemany(
                "update candles set volume = ? where instrument_id = ? and timeframe = '1h' "
                "and ts = ?",
                pending[i : i + 2000],
            )
            c.commit()
        print("repaired")


if __name__ == "__main__":
    main()
