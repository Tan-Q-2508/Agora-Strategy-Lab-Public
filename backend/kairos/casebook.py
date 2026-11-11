"""The casebook: why each losing trade lost, one trade at a time (D-128).

The statistical review (``review.py``) needs a dozen or more trades before it can say which
conditions separate losers from winners. A strategy with five trades still deserves an answer, so
the casebook checks every losing trade against the textbook causes a trader would look for first:
bought against the trend, the whole market falling, a choppy market, thin volume, chasing a
stretched price, a stop inside the stock's normal noise, or a gain given back. Each cause is
counted among the winners too, so a reading the winners shared isn't blamed for the losses.

The readings are the trade check's (``quality.py``): taken on the signal candle and turned round
for shorts, so "against the trend" means the same thing for both sides.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MIN_SHARED = 2  # losers that must share a cause before it's named as a pattern
MIN_GAP = 0.25  # the cause must be this much more common among losers than among winners


@dataclass(frozen=True)
class Cause:
    key: str
    text: str  # one losing trade: "bought against the 200-candle trend (−4% below it)"
    pattern: str  # many: "were bought against the 200-candle trend"
    fix: str  # the fix a trader would test first, in words


CAUSES: dict[str, Cause] = {
    c.key: c
    for c in (
        Cause(
            "long_trend",
            "taken against the 200-candle trend",
            "were taken against the 200-candle trend",
            "trade only with the 200-candle average (a trend filter)",
        ),
        Cause(
            "mid_trend",
            "taken against the 50-candle trend",
            "were taken against the 50-candle trend",
            "trade only with the 50-candle average",
        ),
        Cause(
            "market",
            "taken while the whole market was moving the other way",
            "were taken while the whole market (the index) moved the other way",
            "trade only when the index is above its 50-candle average (below, for shorts)",
        ),
        Cause(
            "chop",
            "taken in a choppy market with no trend",
            "were taken in a choppy, trendless market",
            "require a trend (ADX at least 20) before entering",
        ),
        Cause(
            "rvol",
            "taken on thin volume (little conviction behind the move)",
            "were taken on thin volume",
            "require volume of at least the 20-candle average",
        ),
        Cause(
            "stretch",
            "chased a price already stretched far from its average",
            "chased a price already stretched far from its average",
            "skip entries more than 2 standard deviations from the 20-candle average",
        ),
        Cause(
            "noise_stop",
            "stopped out within two candles by the stock's ordinary wiggle",
            "were stopped out within two candles by ordinary noise",
            "a wider stop based on ATR (about 2 × ATR)",
        ),
        Cause(
            "gave_back",
            "was ahead by at least one ATR and gave it all back",
            "were ahead by at least one ATR and gave it all back",
            "partial exits (half at 1R, stop to the entry) or a trailing stop",
        ),
    )
}


def causes_of(row: Any) -> list[str]:
    """The textbook causes present in one trade (winner or loser), most telling first."""
    f: Mapping[str, float] = row.features
    t = row.t
    out: list[str] = []
    if f.get("market", 0.0) < 0:
        out.append("market")
    if f.get("long_trend", 0.0) < 0:
        out.append("long_trend")
    elif f.get("mid_trend", 0.0) < 0:
        out.append("mid_trend")
    if f.get("adx", 99.0) < 18 or f.get("chop", 0.0) > 61.8:
        out.append("chop")
    if 0 < f.get("rvol", 1.0) < 0.7:
        out.append("rvol")
    if f.get("stretch", 0.0) > 2.0:
        out.append("stretch")
    if t.exit_reason in ("stop", "trailing") and t.bars_held <= 2:
        out.append("noise_stop")
    if row.mfe_atr is not None and row.mfe_atr >= 1.0:
        out.append("gave_back")
    return out


def casebook(rows: Sequence[Any]) -> dict[str, Any]:
    """Every losing trade's causes, and the causes the losers share more than the winners.

    ``patterns``: ``[{key, losers, winners, of_losers, of_winners, text, fix}]``, strongest
    first; only causes shared by at least ``MIN_SHARED`` losers and ``MIN_GAP`` more common
    among them than among the winners."""
    losers = [r for r in rows if r.t.net <= 0]
    winners = [r for r in rows if r.t.net > 0]
    lose_c = [causes_of(r) for r in losers]
    win_c = [set(c) for c in (causes_of(r) for r in winners)]
    patterns: list[dict[str, Any]] = []
    for key, cause in CAUSES.items():
        lo = sum(1 for c in lose_c if key in c)
        wi = sum(1 for c in win_c if key in c)
        lo_share = lo / len(losers) if losers else 0.0
        wi_share = wi / len(winners) if winners else 0.0
        if key == "gave_back":
            wi_share = 0.0  # winners are ahead by definition; it's the giving back that hurts
        if lo >= MIN_SHARED and lo_share - wi_share >= MIN_GAP:
            shown = bool(winners) and key != "gave_back"
            win_words = f"; {wi} of {len(winners)} winners" if shown else ""
            patterns.append(
                {
                    "key": key,
                    "losers": lo,
                    "winners": wi,
                    "of_losers": len(losers),
                    "of_winners": len(winners),
                    "gap": lo_share - wi_share,
                    "text": f"{lo} of {len(losers)} losing trades {cause.pattern}{win_words}. "
                    f"First fix to test: {cause.fix}.",
                    "fix": cause.fix,
                }
            )
    patterns.sort(key=lambda p: (-float(p["gap"]), -int(p["losers"])))
    cases = [{"keys": keys, "why": [CAUSES[k].text for k in keys[:3]]} for keys in lose_c]
    return {"cases": cases, "patterns": patterns, "losers": len(losers), "winners": len(winners)}
