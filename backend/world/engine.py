"""The world engine's pure parts: recognise events in headlines, work out their effects, and
measure how markets reacted (D-95). No database here, so every step is tested by hand.

**Recognising** (``match``): a headline belongs to a scenario when it has one of the scenario's
news topics (or, for scenarios with their own words, one of those words in the title), names
one of its places and one of its words when the scenario lists them, and is severe enough.
Calming news (a ceasefire, a deal, a pause) on a two-sided scenario counts with the opposite
sign.

**Effects** (``view``): each active event's map effects, signed and scaled by how strong the
coverage is (``1 − e^(−strength/8)``: one severe story counts, ten count more, but not ten
times more), **blended with what was measured**: the map's −2…+2 for a target is pulled toward
the measured average reaction (in units of 1% excess move over 5 trading days, capped at ±2)
with weight n/(n+3) after n measured events. So after a handful of real events, what actually
happened outweighs the textbook.

**Measuring** (``reactions``): from the last close before the news to the close 1, 5 and 20
trading days later; the whole market as its plain return, sectors and exposure groups as their
return minus the market's (what they did *beyond* the market).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.world.scenarios import BY_KEY, SCENARIOS, Scenario, target_label

HORIZONS = (1, 5, 20)
PRIOR_WEIGHT = 3.0
UNIT_PCT = {1: 0.5, 5: 1.0, 20: 2.0}  # 1 map unit ≈ this much excess move at each horizon


def _rx(words: Iterable[str], *, prefix: bool = False) -> re.Pattern[str] | None:
    parts = [re.escape(w.strip().lower()) for w in words if w.strip()]
    if not parts:
        return None
    end = "" if prefix else r"(?![a-z])"
    return re.compile(r"(?<![a-z])(" + "|".join(sorted(parts, key=len, reverse=True)) + ")" + end)


@dataclass(frozen=True)
class _Compiled:
    s: Scenario
    places: re.Pattern[str] | None
    words: re.Pattern[str] | None


_COMPILED = [_Compiled(s, _rx(s.places), _rx(s.words, prefix=True)) for s in SCENARIOS]


@dataclass(frozen=True)
class Hit:
    scenario: str
    sign: int  # +1 escalating, −1 calming
    weight: float  # the headline's severity (0 … 5)
    specificity: int


def match(
    title: str,
    summary: str = "",
    topics: Sequence[str] = (),
    severity: int = 0,
    calming: bool = False,
    limit: int = 2,
) -> list[Hit]:
    """The scenarios a headline belongs to (most specific first, at most ``limit``)."""
    low_title = title.lower()
    low = f"{low_title}. {summary.lower()}"
    hits: list[Hit] = []
    for c in _COMPILED:
        s = c.s
        # calming news reads one step milder (news/topics.py), so it may be one step lower
        floor = s.min_severity - (1 if calming and s.two_sided else 0)
        if severity < floor:
            continue
        topic_ok = bool(set(topics) & set(s.topics))
        word_ok = c.words is None or bool(c.words.search(low))
        if c.words is not None and not topic_ok and not c.words.search(low_title):
            continue
        if not topic_ok and c.words is None:
            continue
        if not word_ok:
            continue
        if c.places is not None and not c.places.search(low):
            continue
        spec = int(topic_ok) + int(c.places is not None) + int(c.words is not None)
        sign = -1 if calming and s.two_sided else 1
        hits.append(Hit(s.key, sign, float(severity), spec))
    hits.sort(key=lambda h: (-h.specificity, -BY_KEY[h.scenario].min_severity, h.scenario))
    return hits[:limit]


# ---------------------------------------------------------------- effects


@dataclass(frozen=True)
class Learned:
    n: int
    mean: float  # % (in the escalating direction)
    hits: int = 0

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.n if self.n else None


LearnedMap = Mapping[tuple[str, str, str, int], Learned]  # (scenario, market, target, horizon)


def blend(prior: float, learned: Learned | None, horizon: int = 5) -> float:
    """The map's −2…+2, pulled toward what was measured (n/(n+3))."""
    if learned is None or learned.n <= 0:
        return float(prior)
    measured = float(np.clip(learned.mean / UNIT_PCT[horizon], -2.0, 2.0))
    w = learned.n / (learned.n + PRIOR_WEIGHT)
    return (1 - w) * float(prior) + w * measured


@dataclass
class ActiveEvent:
    scenario: str
    strength: float  # sum of headline severities, faded by age
    sign: float  # −1 … +1: net escalating or calming
    headlines: list[dict[str, Any]] = field(default_factory=list)
    event_id: int | None = None
    first_seen: int = 0

    @property
    def weight(self) -> float:
        return 1.0 - math.exp(-self.strength / 8.0)


@dataclass
class View:
    market: str
    tilt: float  # the whole market, −2 … +2
    sectors: dict[str, float]
    tags: dict[str, float]
    drivers: list[dict[str, Any]]

    def stock(self, sector: str, tags: Iterable[str]) -> tuple[float, list[str]]:
        """A stock's tilt (market + its sector + its strongest exposure) and why."""
        why: list[str] = []
        total = self.tilt
        if abs(self.tilt) >= 0.2:
            why.append(f"the whole market {_dir(self.tilt)}")
        sec = self.sectors.get(sector, 0.0)
        total += sec
        if abs(sec) >= 0.2:
            why.append(f"{sector} {_dir(sec)}")
        best = 0.0
        for t in tags:
            v = self.tags.get(t, 0.0)
            if abs(v) > abs(best):
                best = v
                if abs(v) >= 0.2:
                    why = [w for w in why if not w.startswith("its exposure")]
                    why.append(f"its exposure ({target_label('tag:' + t).lower()}) {_dir(v)}")
        total += best
        return round(float(3.0 * total / (3.0 + abs(total))), 2), why  # soft, as soft() (D-167)


def _dir(v: float) -> str:
    if v <= -1:
        return "is hurt"
    if v < 0:
        return "may be hurt"
    if v >= 1:
        return "gains"
    return "may gain"


def view(market: str, events: Sequence[ActiveEvent], learned: LearnedMap) -> View:
    sectors: dict[str, float] = {}
    tags: dict[str, float] = {}
    tilt = 0.0
    drivers: list[dict[str, Any]] = []
    for e in sorted(events, key=lambda x: -x.strength):
        s = BY_KEY.get(e.scenario)
        if s is None or market not in s.effects:
            continue
        scale = e.weight * e.sign
        effects: list[dict[str, Any]] = []
        for target, prior in s.effects[market].items():
            got = learned.get((s.key, market, target, 5))
            v = blend(prior, got) * scale
            if target == "market":
                tilt += v
            elif target.startswith("tag:"):
                tags[target[4:]] = tags.get(target[4:], 0.0) + v
            else:
                sectors[target] = sectors.get(target, 0.0) + v
            if abs(v) >= 0.05:
                effects.append(
                    {
                        "target": target,
                        "label": target_label(target),
                        "value": round(v, 2),
                        "map": prior,
                        "measured": (
                            {"n": got.n, "mean_pct": round(got.mean, 2), "hit_rate": got.hit_rate}
                            if got
                            else None
                        ),
                    }
                )
        drivers.append(
            {
                "scenario": s.key,
                "title": s.title,
                "calming": e.sign < 0,
                "strength": round(e.strength, 1),
                "weight": round(e.weight, 2),
                "chain": list(s.chain),
                "effects": sorted(effects, key=lambda x: -abs(float(x["value"]))),
                "headlines": e.headlines[:5],
                "event_id": e.event_id,
            }
        )
    return View(market, round(soft(tilt), 2), _clip(sectors), _clip(tags), drivers)


def soft(x: float) -> float:
    """−2 … +2 without a hard cap (D-167): with 20 events active, summed effects passed the old
    clip and both markets (and airlines, IT, metals…) sat at exactly −2.0, so a crisis read the
    same as a tense week and Kairos's picks couldn't tell badly hurt from slightly hurt. A
    rational curve (tanh rounds to the cap again past a sum of about 6): soft(0.5) = 0.4,
    soft(2) = 1.0, soft(20) = 1.82; order is always kept."""
    return float(2.0 * x / (2.0 + abs(x)))


def _clip(d: Mapping[str, float]) -> dict[str, float]:
    return {k: round(soft(v), 2) for k, v in d.items() if abs(v) >= 0.05}


# ---------------------------------------------------------------- measuring


def base_index(day_starts: np.ndarray, at_ms: int) -> int | None:
    """Index of the last session that started before ``at_ms`` minus a full day: the close
    the reaction is measured from (the session before the news)."""
    i = int(np.searchsorted(day_starts, at_ms, side="left")) - 1
    return i if i >= 0 else None


def reactions(
    lines: Mapping[str, np.ndarray], base: int, horizons: Sequence[int] = HORIZONS
) -> dict[str, dict[int, float]]:
    """{target: {h: %}}: the market's plain return, everything else in excess of it."""
    out: dict[str, dict[int, float]] = {}
    mkt = lines.get("market")
    for target, x in lines.items():
        got: dict[int, float] = {}
        for h in horizons:
            j = base + h
            if j >= len(x) or not (np.isfinite(x[base]) and np.isfinite(x[j])) or x[base] <= 0:
                continue
            r = (x[j] / x[base] - 1.0) * 100.0
            if target != "market":
                if mkt is None or not (np.isfinite(mkt[base]) and np.isfinite(mkt[j])):
                    continue
                r -= (mkt[j] / mkt[base] - 1.0) * 100.0
            got[h] = round(float(r), 3)
        if got:
            out[target] = got
    return out


def welford(n: int, mean: float, m2: float, x: float) -> tuple[int, float, float]:
    n += 1
    d = x - mean
    mean += d / n
    m2 += d * (x - mean)
    return n, mean, m2
