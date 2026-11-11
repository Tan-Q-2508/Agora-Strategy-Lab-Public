"""Claude's idea batch, weekend 2026-11-07 (D-160): the heavy-fall bounce and its relatives.

Why these and not 10,000 variants: the scanner test (D-224) over two years found one causal edge in
either market, the US bounce after a heavy fall on high volume. Agora's earlier dip batch failed
the luck check on small universes. Each idea below has a reason, not a tuned threshold: panic
selling on high volume is forced selling, which reverses over days; it should work in liquid stocks
in a healthy market and fail in a stock falling for a reason. Thresholds are round numbers, written
once.

Writes the batch as JSON for ``python -m backend.metis.claude run FILE``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.lab.families import all_of, cmp, ind, num, price, stop, visual


def definition(market: str, rules: dict[str, Any], size: float = 12.0) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "market": market,
        "universe": {"kind": "symbols", "symbols": []},
        "timeframe": "1d",
        "product": "cash" if market == "US" else "delivery",
        "sizing": {"kind": "percent_equity", "value": size},
        "limits": {"max_open_positions": 8, "max_per_symbol": 1},
        "parameters": [],
        **rules,
    }


def fell(pct: float) -> dict[str, Any]:
    return cmp(ind("roc", period=1), "below", num(-pct))


def loud(times: float) -> dict[str, Any]:
    return cmp(ind("rvol", period=20), "above", num(times))


ABOVE_200 = cmp(price("close"), "above", ind("sma", period=200))
ABOVE_50 = cmp(price("close"), "above", ind("sma", period=50))
CALMER = cmp(ind("natr", period=14), "below", num(4))


def idea(
    market: str, title: str, why: str, long: dict[str, Any], hold: int, sl: float | None
) -> dict[str, Any]:
    rules = visual(long, None, stop_loss=stop("atr", sl) if sl else None, max_bars=hold)
    return {
        "kind": "new_strategy",
        "title": title,
        "why": why,
        "market": market,
        "timeframe": "1d",
        "definition": definition(market, rules),
    }


WHY = "Forced selling on high volume reverses over days (D-224: the one causal edge found)."
IDEAS = [
    idea("US", "US heavy fall on loud volume, held 5 days", WHY, all_of(fell(5), loud(2)), 5, None),
    idea(
        "US",
        "US heavy fall on loud volume, in an uptrend",
        WHY + " A stock above its 200-day average fell on an event, not a slide.",
        all_of(fell(5), loud(2), ABOVE_200),
        5,
        None,
    ),
    idea(
        "US",
        "US heavy fall on loud volume, stop 3 ATR",
        WHY + " With a stop, for the fall that keeps falling.",
        all_of(fell(5), loud(2), ABOVE_200),
        5,
        3.0,
    ),
    idea(
        "US",
        "US heavy fall on loud volume, held 10 days",
        WHY + " Longer, in case the bounce is slow.",
        all_of(fell(5), loud(2), ABOVE_200),
        10,
        None,
    ),
    idea(
        "US",
        "US deep fall on very loud volume",
        "The harder the panic, the cleaner the reversal.",
        all_of(fell(8), loud(3)),
        5,
        None,
    ),
    idea(
        "US",
        "US heavy fall in a calm stock",
        "A calm stock falling 5% is news-driven panic, not its normal noise.",
        all_of(fell(5), loud(2), CALMER),
        5,
        None,
    ),
    idea(
        "IN",
        "India heavy fall on loud volume, in an uptrend",
        "The same reason in India, where "
        "the scanner found no edge: tested to see if the US result is general.",
        all_of(fell(5), loud(2), ABOVE_200),
        5,
        None,
    ),
    idea(
        "IN",
        "India heavy fall in a calm stock",
        "Same reason; calm large stocks only.",
        all_of(fell(5), loud(2), CALMER, ABOVE_50),
        5,
        None,
    ),
]

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(json.dumps(IDEAS, indent=1), encoding="utf8")
    print(len(IDEAS), "ideas written")
