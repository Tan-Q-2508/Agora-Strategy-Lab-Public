"""Batch B (D-224, D-160): the heavy-fall bounce on the market it was found in.

Batch A failed on Metis's usual 30 large stocks, with too few trades. The edge was measured across
every liquid stock, so this tests it across the 250 most traded, written once. Reads the desk's
list from the running Agora.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_2026_11_07_a import ABOVE_200, definition, fell, loud

from backend.lab.families import all_of, visual

with urllib.request.urlopen("http://127.0.0.1:8765/api/kairos/desk") as r:
    body = json.load(r)
desks = body if isinstance(body, list) else body["desks"]
stocks = next(d for d in desks if d["market"] == "US" and d["timeframe"] == "1d")["symbols"]


def idea(title: str, why: str, long: dict, hold: int) -> dict:
    d = definition("US", visual(long, None, max_bars=hold), size=10.0)
    d["limits"]["max_open_positions"] = 10
    d["universe"]["symbols"] = stocks
    return {
        "kind": "new_strategy",
        "title": title,
        "why": why,
        "market": "US",
        "timeframe": "1d",
        "symbols": stocks,
        "definition": d,
    }


WHY = "The scanner's one causal edge, tested on a wide list as it was measured (D-224)."
IDEAS = [
    idea("US 250: heavy fall on loud volume, 5 days", WHY, all_of(fell(5), loud(2)), 5),
    idea("US 250: heavy fall, in an uptrend, 5 days", WHY, all_of(fell(5), loud(2), ABOVE_200), 5),
    idea(
        "US 250: heavy fall, in an uptrend, 10 days", WHY, all_of(fell(5), loud(2), ABOVE_200), 10
    ),
]
Path(sys.argv[1]).write_text(json.dumps(IDEAS), encoding="utf8")
print(len(IDEAS), "ideas,", len(stocks), "stocks")
