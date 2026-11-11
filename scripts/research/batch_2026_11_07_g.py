"""Batch G: entries of a different kind from batches C to F, on wide lists.

A slow pullback (not a two-day dip) inside an uptrend, and a short for falling stocks, which is the
one thing that could make money in the kind of year India just had. US only for the short: Indian
delivery trades can't be short. Judged on the list as it stood before the exam (D-231).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_2026_11_07_a import ABOVE_200
from batch_2026_11_07_c import cmp, idea, ind, num, price, visual

from backend.lab.families import all_of

RSI_LOW = cmp(ind("rsi", period=14), "below", num(40))
RSI_BACK = cmp(ind("rsi", period=14), "above", num(60))
BELOW_200 = cmp(price("close"), "below", ind("sma", period=200))
BREAK_LOW = cmp(price("close"), "crosses_below", ind("donchian", "lower", 1, period=50))
ABOVE_50 = cmp(price("close"), "above", ind("sma", period=50))

IDEAS = [
    idea(
        m,
        f"{where}: pullback to RSI 40 in an uptrend, out at RSI 60",
        "A two-week pullback in a healthy stock, slower than the RSI(2) dip, so fewer trades and "
        "lower costs.",
        visual(all_of(RSI_LOW, ABOVE_200), RSI_BACK, max_bars=30),
    )
    for m, where in (("US", "US 250"), ("IN", "India 250"))
]
IDEAS.append(
    idea(
        "US",
        "US 250: short a 50-day low below the 200-day average",
        "Falling stocks keep falling, and a short earns when the kept long rules can't.",
        visual(None, None, short=all_of(BREAK_LOW, BELOW_200), exit_short=ABOVE_50),
    )
)

if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(IDEAS), encoding="utf8")
    print(len(IDEAS), "ideas")
