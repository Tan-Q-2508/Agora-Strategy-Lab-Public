"""Why did it move? Finding the news behind a sudden market or sector move (D-96).

Charts say *that* something fell; this finds *why*. When the whole market or a sector moves
unusually (``unusual``: the candle's move is at least ``Z_MIN`` times its usual size and at least
a minimum percentage), every headline from the hours around the move is scored as a possible
cause (``rank``):

- **severity** of the news (0–5, ``news/topics.py``);
- **timing**: published shortly before or during the move counts fully; a market report
  published just after ("Sensex sinks as oil jumps on Iran strikes") still counts, since such
  reports name the cause; news from long before counts less;
- **relevance**: about this market (world news a little less, the other market less still);
  for a sector, news whose topic or world-map scenario touches that sector or its exposure
  groups, or company news about its members;
- **direction**: risk-off news for a fall, risk-on news for a rise;
- **corroboration**: several publishers telling the same story;
- **clues**: whether the assets that should confirm it moved the same day (oil, gold, the dollar,
  the rupee, VIX, bond yields).

Headlines are grouped into causes (a world-map scenario, else the news topic, else the company),
and **contagion** is checked: the other market's own unusual move in the hours before (US stocks
falling overnight usually explain India's gap down). The verdict: a news cause, a world event,
contagion, or "unclear" (then the move is more likely flows or technical selling, said plainly).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.world import engine
from backend.world.scenarios import BY_KEY

Z_MIN = 2.5
MIN_PCT = {"market": 1.2, "sector": 2.0}
HOUR = 3_600_000
ASSET_LABEL = {
    "oil": "oil",
    "gold": "gold",
    "usd": "the dollar",
    "rupee": "the rupee",
    "vix": "the fear gauge (VIX)",
    "yields": "US bond yields",
}
MOVE_WORDS = (
    "sensex",
    "nifty",
    "stocks",
    "shares",
    "wall street",
    "dow",
    "s&p",
    "nasdaq",
    "markets",
    "market",
    "index",
    "indices",
    "sell-off",
    "selloff",
    "rally",
    "tumble",
    "slump",
    "plunge",
    "surge",
    "jump",
    "sink",
    "crash",
)


@dataclass(frozen=True)
class Move:
    market: str
    target: str  # "market" or a sector name
    label: str  # "the Nifty 50", "Financials (India)"
    timeframe: str
    start_ts: int  # when the move began (the previous close or candle)
    end_ts: int  # when it was measured (the candle's close)
    move_pct: float
    z: float

    @property
    def sign(self) -> int:
        return 1 if self.move_pct > 0 else -1


def unusual(
    closes: np.ndarray, *, kind: str = "market", look: int = 60
) -> tuple[float, float] | None:
    """(% move of the last candle, z-score against the last ``look`` candles' moves) when it is
    unusual, else None."""
    c = closes[np.isfinite(closes)]
    if len(c) < look + 2:
        return None
    r = np.diff(c[-look - 2 :]) / c[-look - 2 : -1]
    last, hist = float(r[-1]), r[:-1]
    sd = float(np.std(hist, ddof=1))
    if sd <= 0:
        return None
    z = last / sd
    pct = last * 100
    if abs(z) >= Z_MIN and abs(pct) >= MIN_PCT["market" if kind == "market" else "sector"]:
        return round(pct, 2), round(z, 2)
    return None


@dataclass
class Cause:
    key: str
    kind: str  # "world", "news", "company", "contagion"
    title: str
    score: float
    headline: dict[str, Any] | None = None
    sources: int = 1
    chain: list[str] = field(default_factory=list)
    clues: list[str] = field(default_factory=list)
    against: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "score": round(self.score, 3),
            "headline": self.headline,
            "sources": self.sources,
            "chain": self.chain,
            "clues": self.clues,
            "against": self.against,
        }


def _timing(published: int, move: Move) -> float:
    lead = move.start_ts - published  # how long before the move began
    if published <= move.end_ts:
        if lead <= 18 * HOUR:
            return 1.0
        return max(0.2, 1.0 - (lead - 18 * HOUR) / (48 * HOUR))
    after = published - move.end_ts
    return 0.8 if after <= 6 * HOUR else 0.0


def _relevance(
    h: Mapping[str, Any],
    move: Move,
    scenario_effect: float | None,
    sector_symbols: frozenset[str],
    sector_tags: frozenset[str],
) -> float:
    scope = h.get("scope") or "WORLD"
    base = 1.0 if scope == move.market else 0.8 if scope == "WORLD" else 0.4
    if move.target == "market":
        return base
    if scenario_effect is not None and abs(scenario_effect) >= 0.5:
        return base
    names = {str(x) for x in (h.get("symbols") or [])}
    if names & sector_symbols:
        return 0.9 * base
    words = {str(k).lower() for k in (h.get("sectors") or {})}
    if words & {move.target.lower(), *(t.replace("_", " ") for t in sector_tags)}:
        return 0.9 * base
    return 0.3 * base


def _is_report(title: str) -> bool:
    low = title.lower()
    return sum(1 for w in MOVE_WORDS if w in low) >= 1


def rank(
    move: Move,
    headlines: Sequence[Mapping[str, Any]],
    *,
    sector_symbols: frozenset[str] = frozenset(),
    sector_tags: frozenset[str] = frozenset(),
    clues: Mapping[str, tuple[float, float]] | None = None,
    other_market: tuple[str, float, float] | None = None,
) -> list[Cause]:
    """Possible causes, most likely first. ``headlines`` are news dicts (title, published_at,
    severity, impact, scope, topics, sectors, symbols, publisher, calming); ``clues`` maps an
    asset to (% move, z) on the day; ``other_market`` is (label, % move, z) of the other
    market's latest move before this one."""
    groups: dict[str, Cause] = {}
    seen_titles: dict[str, set[str]] = {}
    for h in headlines:
        title = str(h.get("title") or "")
        pub = int(h.get("published_at") or 0)
        t = _timing(pub, move)
        if t <= 0:
            continue
        sev = float(h.get("severity") or 0)
        if sev <= 0:
            continue
        topics = (
            [x for x in str(h.get("topics") or "").split(",") if x]
            if isinstance(h.get("topics"), str)
            else list(h.get("topics") or [])
        )
        hits = engine.match(
            title, str(h.get("summary") or ""), topics, int(sev), bool(h.get("calming"))
        )
        impact = float(h.get("impact") or 0.0)
        effect: float | None = None
        key, kind, label = "", "news", title
        if hits:
            hit = hits[0]
            s = BY_KEY[hit.scenario]
            eff = s.effects.get(move.market, {})
            tgt = "market" if move.target == "market" else move.target
            val = eff.get(tgt)
            if val is None and move.target != "market":
                tag_vals = [v for k, v in eff.items() if k[4:] in sector_tags]
                val = max(tag_vals, key=abs) if tag_vals else eff.get("market")
            effect = (val or 0) * hit.sign
            key, kind, label = f"world:{hit.scenario}", "world", s.title
            if hit.sign < 0:
                label = f"{s.title} (calming)"
            direction = 1.0 if effect * move.sign > 0 else 0.25 if effect * move.sign < 0 else 0.6
        else:
            syms = [str(x) for x in (h.get("symbols") or [])]
            company = [x for x in syms if x in sector_symbols] if move.target != "market" else []
            if company and (not topics or topics[0] == "corporate"):
                key, kind, label = f"company:{company[0]}", "company", f"{company[0]} news"
            elif topics:
                key, label = f"topic:{topics[0]}", topics[0].replace("_", " ")
            else:
                key = f"title:{title[:40].lower()}"
            direction = (
                1.0 if impact * move.sign > 0.15 else 0.25 if impact * move.sign < -0.15 else 0.6
            )
        rel = _relevance(h, move, effect, sector_symbols, sector_tags)
        report = 1.15 if _is_report(title) and pub >= move.start_ts else 1.0
        score = (sev / 5.0) * t * rel * direction * report
        c = groups.get(key)
        pubs = seen_titles.setdefault(key, set())
        publisher = str(h.get("publisher") or h.get("source") or title)
        if c is None:
            c = groups[key] = Cause(key, kind, label, 0.0)
            if kind == "world":
                c.chain = list(BY_KEY[key.split(":", 1)[1]].chain)
        if publisher not in pubs:
            pubs.add(publisher)
            c.sources = len(pubs)
        best = c.headline["_score"] if c.headline else -1.0
        if score > best:
            c.headline = {
                "title": title,
                "publisher": h.get("publisher") or "",
                "published_at": pub,
                "link": h.get("link") or "",
                "_score": score,
            }
        # diminishing: the best story counts fully, the rest add a little each
        c.score = max(c.score, score) + 0.15 * min(score, c.score)
    causes = list(groups.values())
    for c in causes:
        c.score *= 1.0 + 0.25 * min(3, c.sources - 1)
        if c.kind == "world" and clues:
            s = BY_KEY[c.key.split(":", 1)[1]]
            fit, against = _clue_check(s.assets, clues, move.sign)
            c.clues, c.against = fit, against
            if fit:
                c.score *= 1.3
            elif against:
                c.score *= 0.8
        if c.headline:
            c.headline.pop("_score", None)
    if other_market is not None:
        label, pct, z = other_market
        if abs(z) >= 2.0 and pct * move.sign > 0:
            causes.append(
                Cause(
                    "contagion",
                    "contagion",
                    f"{label} moved {pct:+.1f}% just before",
                    score=min(1.0, 0.25 + abs(z) / 10.0),
                    chain=[
                        "Big moves in one market spill into others: global funds sell (or buy) "
                        "everywhere at once.",
                    ],
                )
            )
    causes.sort(key=lambda c: -c.score)
    return causes


def _clue_check(
    expected: Mapping[str, int], clues: Mapping[str, tuple[float, float]], move_sign: int
) -> tuple[list[str], list[str]]:
    """Which confirming assets moved the way a risk-off (or risk-on) story says they should."""
    fit: list[str] = []
    against: list[str] = []
    # For a fall, the scenario's escalating direction applies; for a rise, the calming one.
    flip = 1 if move_sign < 0 else -1
    for asset, want in expected.items():
        got = clues.get(asset)
        if got is None or want == 0:
            continue
        pct, z = got
        if abs(z) < 1.0:
            continue
        say = f"{ASSET_LABEL.get(asset, asset)} {'rose' if pct > 0 else 'fell'} {abs(pct):.1f}%"
        if pct * want * flip > 0:
            fit.append(say)
        else:
            against.append(say)
    return fit, against


def verdict(causes: Sequence[Cause]) -> str:
    if not causes or causes[0].score < 0.2:
        return "unclear"
    top = causes[0]
    return {"world": "world", "contagion": "contagion"}.get(top.kind, "news")


def explain(move: Move, causes: Sequence[Cause], when: str) -> str:
    """The plain-English answer."""
    went = "rose" if move.move_pct > 0 else "fell"
    times = f"{abs(move.z):.1f}× a normal {('day' if move.timeframe == '1d' else 'candle')}"
    head = f"{move.label} {went} {abs(move.move_pct):.1f}% {when} (unusual: {times})."
    v = verdict(causes)
    if v == "unclear":
        return (
            f"{head} No news explains it clearly: such moves are often big funds buying or "
            "selling, options expiry, or technical levels breaking. Kairos keeps watching the "
            "news for a later explanation."
        )
    top = causes[0]
    out = [head]
    if top.kind == "contagion":
        out.append(f"Most likely: contagion. {top.title}.")
    else:
        hl = top.headline or {}
        src = f" ({top.sources} sources)" if top.sources > 1 else ""
        out.append(f"Most likely cause: {top.title}: “{hl.get('title', '')}”{src}.")
        if top.chain:
            out.append(top.chain[0])
    if top.clues:
        out.append("It fits: " + ", ".join(top.clues) + " the same day.")
    if len(causes) > 1 and causes[1].score >= 0.5 * top.score:
        out.append(f"Also in play: {causes[1].title}.")
    return " ".join(out)


def confidence(causes: Sequence[Cause]) -> str:
    if not causes:
        return "low"
    top = causes[0].score
    second = causes[1].score if len(causes) > 1 else 0.0
    if top >= 0.6 and top >= 1.5 * second:
        return "high"
    if top >= 0.3:
        return "medium"
    return "low"


def zscore(x: np.ndarray, look: int = 60) -> tuple[float, float] | None:
    """(% move of the last value, z) for a confirming asset, without thresholds."""
    c = x[np.isfinite(x)]
    if len(c) < 12:
        return None
    r = np.diff(c[-min(len(c), look + 2) :]) / c[-min(len(c), look + 2) : -1]
    sd = float(np.std(r[:-1], ddof=1)) if len(r) > 2 else 0.0
    if sd <= 0 or not math.isfinite(sd):
        return None
    return round(float(r[-1]) * 100, 2), round(float(r[-1]) / sd, 2)
