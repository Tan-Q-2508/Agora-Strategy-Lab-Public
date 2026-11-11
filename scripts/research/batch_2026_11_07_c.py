"""Batch C (D-230): the families with the strongest evidence, on a wide list for the first time.

The cap in D-230 kept nearly every new strategy on 8 stocks or fewer, so these well-known families
were never really tested on the stocks desks trade. One plain version of each, thresholds from the
textbook, written once, so few tries are spent. Caveat for every result: the list is today's most
traded stocks, so past results are flattered by survivorship.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_2026_11_07_a import ABOVE_200, definition

from backend.lab.families import all_of, cmp, ind, num, price, stop, visual

with urllib.request.urlopen("http://127.0.0.1:8765/api/kairos/desk") as r:
    body = json.load(r)
desks = body if isinstance(body, list) else body["desks"]


def stocks(market: str) -> list[str]:
    return next(d for d in desks if d["market"] == market and d["timeframe"] == "1d")["symbols"][
        :250
    ]


def idea(market: str, title: str, why: str, rules: dict[str, Any]) -> dict[str, Any]:
    syms = stocks(market)
    d = definition(market, rules, size=10.0)
    d["limits"]["max_open_positions"] = 10
    d["universe"]["symbols"] = syms
    return {
        "kind": "new_strategy",
        "title": title,
        "why": why,
        "market": market,
        "timeframe": "1d",
        "symbols": syms,
        "definition": d,
    }


HIGH_52 = cmp(price("close"), "crosses_above", ind("high_52w"))
DONCHIAN = cmp(price("close"), "crosses_above", ind("donchian", "upper", 1, period=50))
RSI2 = cmp(ind("rsi", period=2), "below", num(10))
ROC = cmp(ind("roc", period=126), "above", num(20))
OUT_50 = cmp(price("close"), "below", ind("sma", period=50))
OUT_5 = cmp(price("close"), "above", ind("sma", period=5))
TRAIL = stop("atr", 4.0)

IDEAS = []
for m, where in (("US", "US 250"), ("IN", "India 250")):
    IDEAS += [
        idea(
            m,
            f"{where}: 52-week-high breakout, 4 ATR trail",
            "Stocks at new highs keep going, "
            "and a wide list holds the few big winners that pay for the rest.",
            visual(HIGH_52, None, trailing=TRAIL),
        ),
        idea(
            m,
            f"{where}: 50-day breakout in an uptrend, exit below 50-day average",
            "Classic trend following, needing many stocks to catch the few that trend.",
            visual(all_of(DONCHIAN, ABOVE_200), OUT_50),
        ),
        idea(
            m,
            f"{where}: RSI(2) dip in an uptrend, exit above 5-day average",
            "Short dips in "
            "uptrends paid in both markets (agora_evidence); it needs breadth to trade often.",
            visual(all_of(RSI2, ABOVE_200), OUT_5, max_bars=10),
        ),
        idea(
            m,
            f"{where}: strong six-month momentum, exit below 50-day average",
            "Relative strength persists for months; a plain rule, not a monthly ranking.",
            visual(
                all_of(ROC, ABOVE_200, cmp(ind("rsi", period=14), "crosses_above", num(50))), OUT_50
            ),
        ),
    ]

if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(IDEAS), encoding="utf8")
    print(len(IDEAS), "ideas")
