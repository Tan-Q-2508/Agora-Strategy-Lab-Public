"""Batch D (D-230, D-231): trend rules of different kinds on wide lists, in both markets.

Batch C's one keeper was trend following with breadth. These are different in kind, not rewordings:
a new-high rule, a volatility channel, a longer breakout, and a breakout with buying pressure behind
it. Each is judged on the list as it stood before the exam (D-231).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_2026_11_07_a import ABOVE_200
from batch_2026_11_07_c import OUT_50, TRAIL, cmp, idea, ind, num, price, visual

from backend.lab.families import all_of

HIGH_52 = cmp(price("close"), "crosses_above", ind("high_52w", offset=1))
SUPER_UP = cmp(price("close"), "crosses_above", ind("supertrend", "value", period=10, mult=3))
SUPER_DOWN = cmp(price("close"), "below", ind("supertrend", "value", period=10, mult=3))
LONG_BREAK = cmp(price("close"), "crosses_above", ind("donchian", "upper", 1, period=100))
LONG_OUT = cmp(price("close"), "below", ind("sma", period=100))
BUYERS = cmp(ind("cmf", period=20), "above", num(0.1))
BREAK_50 = cmp(price("close"), "crosses_above", ind("donchian", "upper", 1, period=50))

IDEAS = []
for m, where in (("US", "US 250"), ("IN", "India 250")):
    IDEAS += [
        idea(
            m,
            f"{where}: new 52-week high, 4 ATR trail",
            "A new yearly high needs no chart reading, and the trail lets winners run.",
            visual(HIGH_52, None, trailing=TRAIL),
        ),
        idea(
            m,
            f"{where}: Supertrend turns up above the 200-day average",
            "A volatility channel, so the exit widens with the stock's own noise.",
            visual(all_of(SUPER_UP, ABOVE_200), SUPER_DOWN),
        ),
        idea(
            m,
            f"{where}: 100-day breakout, exit below 100-day average",
            "Slower than the kept 50-day rule: fewer trades, lower costs, larger moves.",
            visual(all_of(LONG_BREAK, ABOVE_200), LONG_OUT),
        ),
        idea(
            m,
            f"{where}: 50-day breakout with buying pressure",
            "A breakout with money flowing in should fail less often.",
            visual(all_of(BREAK_50, ABOVE_200, BUYERS), OUT_50),
        ),
    ]

if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(IDEAS), encoding="utf8")
    print(len(IDEAS), "ideas")
