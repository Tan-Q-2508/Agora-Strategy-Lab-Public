"""Write the list of US listings Agora stops following (the user's request 2026-11-06, D-223).

Keeps stocks on the NYSE and Nasdaq. Leaves out other exchanges (NYSE American, NYSE Arca, Cboe,
IEX), warrants, units, rights, preferred shares, notes and blank-check shells, and anything no
exchange lists any more and nobody trades. Nothing is deleted: a stock left out keeps its saved
prices, just stops being updated, and Agora follows it again if its line leaves the file.

Reads Nasdaq Trader's two official lists, already downloaded:

    python scripts/exclude_universe.py nasdaqlisted.txt otherlisted.txt
"""

from __future__ import annotations

import csv
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "seed_data" / "excluded_us.csv"
EXCHANGE = {"A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
# ordered: the first that matches is the reason. "Depositary shares" alone is not here: ADRs such
# as Alibaba's are common stock.
KINDS = (
    ("warrant", r"\bwarrants?\b"),
    ("unit", r"\bunits?\b.*\b(each|consist)"),
    ("right", r"\brights?\b"),
    ("preferred", r"\bpreferred\b|\bpreference shares\b|\bnotes? due\b|\bdebentures?\b"),
    ("blank-check shell", r"acquisition (corp|company|inc|ltd|limited)|blank check|merger corp"),
)
MONEY_DAYS = 30
THIN = 1e6  # no exchange lists it and under $1 million a day: it's gone


def read_lists(nasdaq: Path, other: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for line in other.read_text(encoding="utf8").splitlines():
        p = line.split("|")
        if len(p) >= 7 and p[0] != "ACT Symbol" and not p[0].startswith("File"):
            out[p[0].replace(".", "-").replace("$", "-P")] = (p[2], p[1])
    for line in nasdaq.read_text(encoding="utf8").splitlines():
        p = line.split("|")
        if len(p) >= 7 and p[0] != "Symbol" and not p[0].startswith("File"):
            out[p[0]] = ("Q", p[1])
    return out


def reason(sym: str, name: str, listed: tuple[str, str] | None, money: float) -> str | None:
    if listed is None:
        return None if money >= THIN else "no longer listed"
    if listed[0] in EXCHANGE:
        return EXCHANGE[listed[0]]
    text = f"{listed[1]} {name}".lower()
    return next((word for word, rule in KINDS if re.search(rule, text)), None)


def main() -> None:
    listed = read_lists(Path(sys.argv[1]), Path(sys.argv[2]))
    c = sqlite3.connect(f"file:{(ROOT / 'data' / 'agora.db').as_posix()}?mode=ro", uri=True)
    since = int((time.time() - MONEY_DAYS * 86_400) * 1000)
    money = dict(
        c.execute(
            "select instrument_id, avg(close * volume) from candles "
            "where timeframe = '1d' and ts >= ? group by 1",
            (since,),
        )
    )
    rows = []
    for iid, sym, name in c.execute(
        "select id, symbol, name from instruments "
        "where market_code = 'US' and instrument_type = 'equity' order by symbol"
    ):
        why = reason(sym, name or "", listed.get(sym), float(money.get(iid) or 0))
        if why:
            rows.append((sym, why, name))
    with OUT.open("w", encoding="utf8", newline="") as f:
        w = csv.writer(f)
        w.writerow(("symbol", "reason", "name"))
        w.writerows(rows)
    print(f"{len(rows)} listings left out of {OUT.name}")


if __name__ == "__main__":
    main()
