"""Divergences between price and momentum (KAIROS §3).

Compared at consecutive swing points (minor degree, no more than 60 candles apart):

| Kind | Price | RSI | Reads as |
|---|---|---|---|
| Regular bullish | lower low | higher low | selling is losing force: a bounce may follow |
| Regular bearish | higher high | lower high | buying is losing force: a drop may follow |
| Hidden bullish | higher low | lower low | the uptrend is resting, not ending |
| Hidden bearish | lower high | higher high | the downtrend is resting, not ending |

RSI must differ by at least 2 points. The divergence is known on the candle that
confirmed the second swing; MACD's histogram agreeing makes it "strong".
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

import numpy as np

from backend.analysis.swings import Swing
from backend.indicators.series import F64

Kind = Literal["regular_bullish", "regular_bearish", "hidden_bullish", "hidden_bearish"]
LABELS: dict[str, str] = {
    "regular_bullish": "Bullish divergence",
    "regular_bearish": "Bearish divergence",
    "hidden_bullish": "Hidden bullish divergence",
    "hidden_bearish": "Hidden bearish divergence",
}


@dataclass(frozen=True)
class Divergence:
    kind: Kind
    a: Swing
    b: Swing
    rsi_a: float
    rsi_b: float
    strong: bool

    @property
    def bullish(self) -> bool:
        return self.kind.endswith("bullish")

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    @property
    def known_at(self) -> int:
        return self.b.confirmed


def find(swings: list[Swing], rsi: F64, macd_hist: F64, max_gap: int = 60) -> list[Divergence]:
    out: list[Divergence] = []
    for kind_char in ("L", "H"):
        pts = [s for s in swings if s.kind == kind_char]
        for a, b in pairwise(pts):
            if b.index - a.index > max_gap:
                continue
            ra, rb = rsi[a.index], rsi[b.index]
            if not (np.isfinite(ra) and np.isfinite(rb)) or abs(rb - ra) < 2:
                continue
            ma, mb = macd_hist[a.index], macd_hist[b.index]
            kind: Kind | None = None
            if kind_char == "L":
                if b.price < a.price and rb > ra:
                    kind = "regular_bullish"
                elif b.price > a.price and rb < ra:
                    kind = "hidden_bullish"
            else:
                if b.price > a.price and rb < ra:
                    kind = "regular_bearish"
                elif b.price < a.price and rb > ra:
                    kind = "hidden_bearish"
            if kind is None:
                continue
            strong = bool(np.isfinite(ma) and np.isfinite(mb) and (mb > ma) == (rb > ra))
            out.append(Divergence(kind, a, b, round(float(ra), 1), round(float(rb), 1), strong))
    return sorted(out, key=lambda d: d.known_at)
