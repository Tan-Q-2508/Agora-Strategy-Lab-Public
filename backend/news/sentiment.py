"""Headline sentiment from a small finance word list (−1 … +1).

Good enough to sort "Infosys beats estimates, raises guidance" from "Infosys plunges after
profit warning", which is what matters for a trading desk; when the AI helper is ready,
Kairos can re-read the top headlines for nuance. Rules: each listed word adds its weight;
"not", "no", "fails to", "without" flip the next three words; a few two-word phrases
("profit falls", "rate cut") are read as one; the sum s becomes tanh(s / 2).
"""

from __future__ import annotations

import math
import re

POSITIVE: dict[str, float] = {
    "beat": 1.0,
    "beats": 1.0,
    "surge": 1.2,
    "surges": 1.2,
    "surged": 1.2,
    "soar": 1.2,
    "soars": 1.2,
    "soared": 1.2,
    "jump": 0.9,
    "jumps": 0.9,
    "jumped": 0.9,
    "rally": 0.9,
    "rallies": 0.9,
    "rallied": 0.9,
    "gain": 0.6,
    "gains": 0.6,
    "gained": 0.6,
    "rise": 0.5,
    "rises": 0.5,
    "rose": 0.5,
    "climbs": 0.6,
    "climb": 0.6,
    "record": 0.6,
    "high": 0.3,
    "upgrade": 1.2,
    "upgrades": 1.2,
    "upgraded": 1.2,
    "outperform": 1.0,
    "buy": 0.6,
    "bullish": 1.0,
    "strong": 0.6,
    "stronger": 0.6,
    "growth": 0.5,
    "grows": 0.5,
    "boost": 0.7,
    "boosts": 0.7,
    "expands": 0.5,
    "expansion": 0.4,
    "approval": 0.8,
    "approved": 0.8,
    "approves": 0.8,
    "wins": 0.8,
    "win": 0.6,
    "won": 0.6,
    "order": 0.3,
    "orders": 0.3,
    "contract": 0.4,
    "buyback": 0.9,
    "dividend": 0.5,
    "bonus": 0.4,
    "profit": 0.3,
    "profits": 0.3,
    "robust": 0.7,
    "optimistic": 0.7,
    "upbeat": 0.8,
    "rebound": 0.7,
    "rebounds": 0.7,
    "recovery": 0.5,
    "recovers": 0.6,
    "tops": 0.6,
    "exceeds": 0.9,
    "raises": 0.4,
    "raised": 0.4,
    "hike": 0.2,
    "partnership": 0.4,
    "launch": 0.2,
    "launches": 0.2,
    "breakout": 0.6,
}
NEGATIVE: dict[str, float] = {
    "miss": 1.0,
    "misses": 1.0,
    "missed": 1.0,
    "plunge": 1.3,
    "plunges": 1.3,
    "plunged": 1.3,
    "slump": 1.1,
    "slumps": 1.1,
    "slumped": 1.1,
    "tumble": 1.1,
    "tumbles": 1.1,
    "tumbled": 1.1,
    "crash": 1.4,
    "crashes": 1.4,
    "fall": 0.6,
    "falls": 0.6,
    "fell": 0.6,
    "drop": 0.6,
    "drops": 0.6,
    "dropped": 0.6,
    "decline": 0.6,
    "declines": 0.6,
    "declined": 0.6,
    "slide": 0.7,
    "slides": 0.7,
    "sinks": 0.9,
    "sink": 0.8,
    "loss": 0.7,
    "losses": 0.7,
    "lower": 0.3,
    "low": 0.3,
    "weak": 0.7,
    "weaker": 0.7,
    "downgrade": 1.2,
    "downgrades": 1.2,
    "downgraded": 1.2,
    "underperform": 1.0,
    "sell": 0.6,
    "bearish": 1.0,
    "warning": 0.9,
    "warns": 0.9,
    "cut": 0.5,
    "cuts": 0.5,
    "layoffs": 0.9,
    "layoff": 0.9,
    "probe": 1.0,
    "investigation": 1.0,
    "fraud": 1.5,
    "lawsuit": 0.9,
    "sued": 0.9,
    "penalty": 0.9,
    "fine": 0.4,
    "fined": 0.9,
    "ban": 0.9,
    "banned": 0.9,
    "recall": 0.9,
    "default": 1.2,
    "bankruptcy": 1.6,
    "resigns": 0.8,
    "quits": 0.7,
    "slowdown": 0.8,
    "pressure": 0.4,
    "concerns": 0.6,
    "concern": 0.5,
    "fears": 0.7,
    "worries": 0.6,
    "risk": 0.3,
    "volatile": 0.3,
    "selloff": 1.0,
    "sell-off": 1.0,
    "outflows": 0.6,
    "delay": 0.5,
    "delays": 0.5,
    "halts": 0.8,
    "strike": 0.5,
    "disappoint": 1.0,
    "disappoints": 1.0,
    "disappointing": 1.0,
    "shortfall": 0.9,
}
PHRASES: dict[str, float] = {
    "profit falls": -1.0,
    "profit drops": -1.0,
    "profit declines": -1.0,
    "loss widens": -1.2,
    "loss narrows": 0.8,
    "profit rises": 1.0,
    "profit jumps": 1.2,
    "rate cut": 0.6,
    "rate hike": -0.6,
    "price target cut": -1.0,
    "target price cut": -1.0,
    "raises guidance": 1.2,
    "cuts guidance": -1.2,
    "costs rise": -0.8,
    "costs fall": 0.5,
    "margins shrink": -0.9,
    "margins expand": 0.8,
    "all-time high": 0.8,
    "52-week high": 0.7,
    "52-week low": -0.7,
    "record low": -0.8,
}
NEGATORS = {"not", "no", "never", "without", "fails", "failed"}
_WORD = re.compile(r"[a-z][a-z\-']*")


def score(text: str) -> float:
    """Sentiment of one piece of text, −1 (very negative) … +1 (very positive)."""
    low = text.lower()
    total = 0.0
    for phrase, w in PHRASES.items():
        if phrase in low:
            total += w
            low = low.replace(phrase, " ")
    words = _WORD.findall(low)
    flip = 0
    for w in words:
        if w in NEGATORS:
            flip = 3
            continue
        v = POSITIVE.get(w, 0.0) - NEGATIVE.get(w, 0.0)
        if flip:
            v, flip = -v, flip - 1
        total += v
    return math.tanh(total / 2.0)


def headline_score(title: str, summary: str = "") -> float:
    """A headline counts twice as much as its summary."""
    s = 2.0 * score(title) + (score(summary) if summary else 0.0)
    return round(s / (3.0 if summary else 2.0), 3)
