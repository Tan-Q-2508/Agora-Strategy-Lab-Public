"""Batch E: monthly rankings on wide lists, a different kind of idea from batches C and D.

Trend rules are spent: more of them would only raise the luck bar. A ranking compares stocks
with each other instead of reading one chart, and it has only been tested on 30 stocks. Each is
judged on the list as it stood before the exam (D-231).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_2026_11_07_c import stocks


def ranking(
    market: str, title: str, why: str, rank_by: str, months: int, skip: int, hold: int
) -> dict[str, Any]:
    syms = stocks(market)
    return {
        "kind": "new_strategy",
        "title": title,
        "why": why,
        "market": market,
        "timeframe": "1d",
        "symbols": syms,
        "definition": {
            "schema_version": 1,
            "market": market,
            "universe": {"kind": "symbols", "symbols": syms},
            "timeframe": "1d",
            "product": "cash" if market == "US" else "delivery",
            "sizing": {"kind": "percent_equity", "value": round(95 / hold, 1)},
            "limits": {"max_open_positions": hold + 5, "max_per_symbol": 1},
            "parameters": [],
            "kind": "ranking",
            "ranking": {
                "rank_by": rank_by,
                "lookback_months": months,
                "skip_months": skip,
                "hold": hold,
                "trend_filter": True,
            },
        },
    }


IDEAS = [
    ranking(
        "IN",
        "India 250: monthly calmest 20",
        "Calm stocks earn more than their risk suggests, "
        "and India's falling year is where that should show.",
        "low_volatility",
        6,
        0,
        20,
    ),
    ranking(
        "IN",
        "India 250: monthly 12-month momentum, top 20",
        "Momentum ranked across stocks, unlike the single-chart rule that failed the fair list.",
        "momentum",
        12,
        1,
        20,
    ),
    ranking(
        "US",
        "US 250: monthly calmest 20",
        "Wider than the kept 30-stock version.",
        "low_volatility",
        6,
        0,
        20,
    ),
    ranking(
        "US",
        "US 250: monthly 12-month momentum, top 20",
        "The classic factor, wide.",
        "momentum",
        12,
        1,
        20,
    ),
]

if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(IDEAS), encoding="utf8")
    print(len(IDEAS), "ideas")
