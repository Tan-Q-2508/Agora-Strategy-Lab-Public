"""The news risk gauge, and news alerts for one stock (Phase 10.5, D-68).

**Market gauge (0–100).** Over the last 36 hours, headlines that matter to a market
(same market: full weight; world news: 0.8; the other market's news: 0.4) are grouped
into stories (same main topic, overlapping words). A story's weight is

    severity weight (0, 0.15, 0.5, 1, 2, 3.5 for severity 0…5)
    × how risk-off it reads (0 … 1)
    × recency (half-life 6 hours)
    × corroboration (1 + 0.5 per extra publisher, up to 3×)
    × ½ for a geopolitical story that never mentions markets, prices or the economy
      (unless it is severity 5: an invasion needn't mention markets)

The heaviest story counts fully, the next 0.6×, the next 0.36× … (the ten heaviest only):
an ongoing war produces dozens of stories a day, and coverage volume is not new risk.
Calming stories (a ceasefire, a rate cut, a deal) subtract half their weight. The total
``S`` becomes ``100 × (1 − e^(−S/4))``. One fresh war headline from one source that talks
about oil reads about 15; the same story from five publishers about 38 (watchful); an
invasion or a market-wide circuit breaker confirmed by five sources 85 (severe). Levels:
calm < 25 ≤ watchful < 50 ≤ elevated < 75 ≤ severe. Checked on a real day of world news
(2026-10-22, an ongoing Middle East war): the gauge read watchful, not severe.

**Stock alert.** A stock's own headlines from the last 48 hours: a clearly negative one
that names a red-flag event (fraud, raid, default, a profit warning, the CEO quitting…)
is **critical**; a recency-weighted mood of −0.4 or worse over two or more headlines is
**negative**; +0.4 or better is **positive** (a catalyst).

Pure functions over the stored items, so the same headlines always give the same gauge.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

from backend.news import topics as tp

WINDOW_MS = 36 * 3_600_000
STOCK_WINDOW_MS = 48 * 3_600_000
HALF_LIFE_MS = 6 * 3_600_000
SEV_WEIGHT = (0.0, 0.15, 0.5, 1.0, 2.0, 3.5)
SCALE = 4.0
DECAY = 0.6  # each next-heaviest story counts this much less
TOP_STORIES = 10
UNLINKED = 0.5  # a geopolitical story that never mentions markets or the economy
LEVELS = ((75, "severe"), (50, "elevated"), (25, "watchful"), (0, "calm"))
WORDS = {
    "calm": "Calm: nothing in the news is likely to move the whole market.",
    "watchful": "Watchful: some market-moving news; worth keeping an eye on.",
    "elevated": "Elevated: serious news is in play. Kairos's desk keeps trading at half size "
    "where the news hurts, looks for chances where it helps, and in protective mode cuts losing "
    "trades once prices confirm.",
    "severe": "Severe: major market-moving news, reported by several sources. Kairos's desk "
    "trades at half size and, in protective mode, sells longs once the market falls with it.",
}
# fmt: off
RED_FLAGS = (
    "fraud", "raid", "raids", "probe", "investigation", "default", "defaults", "defaulted",
    "bankruptcy", "insolvency", "insolvent", "banned", "ban", "resigns", "quits", "steps down",
    "profit warning", "cuts guidance", "lowers guidance", "accounting", "auditor", "scam",
    "arrest", "arrested", "fire at", "explosion", "recall", "delisting", "delist",
    "short seller", "hindenburg", "nclt", "enforcement directorate", "sebi order", "penalty",
    "plunges", "crashes", "downgrade", "downgrades", "downgraded", "suspended", "halted",
    "lawsuit",
)
# fmt: on
_RED = re.compile(
    r"(?<![\w])("
    + "|".join(sorted(map(re.escape, RED_FLAGS), key=len, reverse=True))
    + r")(?![\w])"
)
_WORD = re.compile(r"[a-z][a-z'\-]{2,}")
# fmt: off
_STOP = {
    "the", "and", "for", "with", "after", "over", "from", "that", "this", "its", "into",
    "says", "said", "will", "amid", "as", "are", "was", "has", "have", "new", "more", "than",
}
# fmt: on


FEAR_DAYS = 90
FEAR_RATIO = 1.25  # this far above its usual level, the market is still frightened
FEAR_FLOOR = 30.0  # watchful, never more: fear keeps the gauge awake, it doesn't halve trades


def with_fear(g: dict[str, Any], fear: tuple[str, float, float] | None) -> dict[str, Any]:
    """Headlines fade in hours and frightened markets don't (D-233): two days after the worst US
    day in 19 months, with the VIX at 25, the gauge read "Calm: nothing in the news is likely to
    move the whole market", and Kairos was readier to buy on it. A fear gauge well above its
    usual level holds the gauge at watchful, and says why."""
    if fear is None:
        return g
    name, now, usual = fear
    if usual <= 0 or now < FEAR_RATIO * usual or float(g.get("level") or 0.0) >= FEAR_FLOOR:
        return g
    return {
        **g,
        "level": FEAR_FLOOR,
        "name": level_name(FEAR_FLOOR),
        "text": f"Watchful: the headlines have gone quiet, but the market is still frightened "
        f"({name} {now:.1f}, usually about {usual:.1f}).",
    }


def level_name(level: float) -> str:
    return next(name for lo, name in LEVELS if level >= lo)


def scope_weight(scope: str | None, market: str | None) -> float:
    scope = scope or "WORLD"
    if market is None:
        return 1.0 if scope == "WORLD" else 0.6
    if scope == market:
        return 1.0
    if scope == "WORLD":
        return 0.8
    return 0.4


def _terms(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if w not in _STOP}


def _recency(age_ms: float) -> float:
    return math.exp(-max(0.0, age_ms) * math.log(2) / HALF_LIFE_MS)


_FIGURE = re.compile(r"(\d+(?:\s?[.,]\s?\d+)?)\s?(%|points|pts)")


def _anchors(title: str) -> tuple[set[str], set[str]]:
    """The places and markets a headline names, and its figures ("8%", "1,800 points")."""
    low = title.lower()
    places = {m.lower() for rx in tp.ANCHOR_RX for m in rx.findall(low)}
    places = {"korea" if "korea" in p else p for p in places}
    figures = {re.sub(r"[\s,]", "", m.group(1)) + m.group(2)[0] for m in _FIGURE.finditer(low)}
    return places, figures


def stories(items: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group headlines about the same story: same main topic and ≥ 35% shared words, or the
    same place or market and the same figure (D-189: "South Korea stocks plunge 8%", "Kospi
    crashes 8%" and "Asian markets crash… Kospi plunges 8%" are one event; counted as three,
    the gauge added it three times instead of once with three sources)."""
    groups: list[tuple[str, set[str], set[str], set[str], list[dict[str, Any]]]] = []
    for it in sorted(items, key=lambda x: -int(x["published_at"])):
        topic = (it.get("topics") or ["none"])[0]
        words = _terms(it["title"])
        places, figures = _anchors(it["title"])
        for t, ws, ps, fs, members in groups:
            if t != topic:
                continue
            similar = bool(words) and len(words & ws) / len(words | ws) >= 0.35
            same_event = bool(places & ps) and bool(figures & fs)
            if similar or same_event:
                members.append(it)
                ws |= words
                ps |= places
                fs |= figures
                break
        else:
            groups.append((topic, set(words), places, figures, [it]))
    # join groups a later headline tied together (order of arrival mustn't split one event)
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = groups[i], groups[j]
                if a[0] == b[0] and a[2] & b[2] and a[3] & b[3]:
                    groups[i] = (a[0], a[1] | b[1], a[2] | b[2], a[3] | b[3], a[4] + b[4])
                    del groups[j]
                    merged = True
                    break
            if merged:
                break
    return [m for *_, m in groups]


def gauge(items: Sequence[dict[str, Any]], market: str | None, now: int) -> dict[str, Any]:
    """The news risk level for ``market`` (``None`` = the world) from stored items."""
    recent = [
        it
        for it in items
        if now - int(it["published_at"]) <= WINDOW_MS and int(it.get("severity") or 0) >= 2
    ]
    risk_off: list[float] = []
    home_off = 0.0  # the part of the risk that is this market's own news (D-198)
    calming = 0.0
    # which sectors the stories on now help (+) or hurt (−), weighted like the stories (D-211)
    pushes: dict[str, list[float]] = {}
    lead_story: dict[str, tuple[float, str]] = {}  # each sector's heaviest story, for the notes
    drivers: list[dict[str, Any]] = []
    for group in stories(recent):
        neg = pos = 0.0
        for it in group:
            w = (
                SEV_WEIGHT[int(it["severity"])]
                * _recency(now - int(it["published_at"]))
                * scope_weight(it.get("scope"), market)
            )
            topic = tp.BY_KEY.get((it.get("topics") or ["none"])[0])
            text = f"{it['title']} {it.get('summary') or ''}"
            unlinked = topic is not None and topic.group == tp.GEO and not tp.market_linked(text)
            if unlinked and int(it["severity"]) < 5:  # an invasion needn't mention markets
                w *= UNLINKED
            impact = float(it.get("impact") or 0.0)
            neg = max(neg, w * max(0.0, -impact))
            pos = max(pos, w * max(0.0, impact))
        publishers = {it.get("publisher") or it.get("source") or "" for it in group}
        boost = 1.0 + 0.5 * min(4, max(0, len(publishers) - 1))
        score = neg * boost - 0.5 * pos * boost
        lead = max(group, key=lambda x: (int(x["severity"]), -float(x.get("impact") or 0.0)))
        # a story only moves sectors when its headline is about the topic (its severity is at
        # least the topic's own; a topic named only in the summary reads one lower): a summary
        # that mentions a war in passing doesn't (D-211: such stories had added up to Airlines
        # −7.7)
        lead_topic = tp.BY_KEY.get((lead.get("topics") or ["none"])[0])
        lead_text = f"{lead['title']} {lead.get('summary') or ''}"
        # … and when it isn't a local story from a far smaller economy (D-213: Western Sahara)
        if int(lead["severity"]) >= (lead_topic.severity if lead_topic else 3) and not tp.far_only(
            lead_text
        ):
            for sector, effect in (lead.get("sectors") or {}).items():
                push = abs(score) * float(effect)
                pushes.setdefault(sector, []).append(push)
                if abs(push) > lead_story.get(sector, (0.0, ""))[0]:
                    lead_story[sector] = (abs(push), str(lead["title"]))
        if score >= 0:
            risk_off.append(score)
            if market is not None and lead.get("scope") == market:
                home_off += score
        else:
            calming += -score
        drivers.append(
            {
                "title": lead["title"],
                "link": lead.get("link"),
                "publisher": lead.get("publisher"),
                "published_at": lead["published_at"],
                "topic": (lead.get("topics") or [None])[0],
                "topic_label": tp.label((lead.get("topics") or ["none"])[0]),
                "severity": int(lead["severity"]),
                "impact": float(lead.get("impact") or 0.0),
                "sources": len(publishers),
                "scope": lead.get("scope"),
                "sectors": dict(lead.get("sectors") or {}),
                "weight": round(score, 3),
            }
        )
    risk_off.sort(reverse=True)
    total = sum(x * DECAY**k for k, x in enumerate(risk_off[:TOP_STORIES])) - calming
    total = max(0.0, total)
    level = round(100.0 * (1.0 - math.exp(-total / SCALE)), 1)
    name = level_name(level)
    drivers.sort(key=lambda d: -abs(d["weight"]))
    all_off = sum(risk_off)
    # each sector's pushes add up like the gauge's stories: the heaviest in full, each next one
    # DECAY less, the top TOP_STORIES only, so many small stories can't outweigh the big ones
    tilt = {
        k: sum(x * DECAY**i for i, x in enumerate(sorted(v, key=abs, reverse=True)[:TOP_STORIES]))
        for k, v in pushes.items()
    }
    return {
        "market": market or "WORLD",
        "level": level,
        "name": name,
        "home_share": round(home_off / all_off, 3) if all_off > 0 else 0.0,
        "text": WORDS[name],
        "score": round(total, 3),
        "calming": round(calming, 3),
        "sector_tilt": {k: round(v, 3) for k, v in sorted(tilt.items()) if abs(v) >= 0.01},
        "sector_story": {k: lead_story[k][1] for k in sorted(lead_story)},
        "drivers": [d for d in drivers if abs(d["weight"]) > 0.01][:6],
        "headlines": len(recent),
        "as_of": now,
    }


ROUNDUP_STOCKS = 3  # a headline naming more stocks than this is a roundup or a live blog (D-185)
# A market live blog ("Sensex Today | Stock Market Live Updates: Nifty surges 230 points") is about
# the market even when its summary names only Titan: its tone isn't Titan's news (D-200).
_LIVE_BLOG = re.compile(r"\blive\b|live updates|as it happened|stocks to watch", re.IGNORECASE)


def stock_alert(items: Sequence[dict[str, Any]], now: int) -> dict[str, Any]:
    """critical / negative / positive / quiet for one stock's own headlines. Roundups and live
    blogs ("Q2 results live: NCC PAT up 19%; …" names thirty companies) don't count: their tone
    is about the others (D-185: Laurus Labs got a "positive catalyst" from a PVR Inox roundup,
    and Airtel and Titan sat on 40 live-blog updates a day)."""
    recent = [
        it
        for it in items
        if now - int(it["published_at"]) <= STOCK_WINDOW_MS
        and len(it.get("symbols") or []) <= ROUNDUP_STOCKS
        and not _LIVE_BLOG.search(it["title"])
    ]
    if not recent:
        return {"state": "quiet", "score": 0.0, "count": 0, "headline": None}
    for it in sorted(recent, key=lambda x: float(x.get("sentiment") or 0.0)):
        text = f"{it['title']} {it.get('summary') or ''}".lower()
        if float(it.get("sentiment") or 0.0) <= -0.3 and _RED.search(text):
            return {
                "state": "critical",
                "score": float(it["sentiment"]),
                "count": len(recent),
                "headline": it["title"],
                "flag": _RED.search(text).group(1),  # type: ignore[union-attr]
            }
    w = [_recency(now - int(it["published_at"])) for it in recent]
    mood = sum(wi * float(it.get("sentiment") or 0.0) for wi, it in zip(w, recent, strict=True))
    mood /= sum(w)
    state = "quiet"
    if len(recent) >= 2 and mood <= -0.4:
        state = "negative"
    elif len(recent) >= 2 and mood >= 0.4:
        state = "positive"
    top = min(recent, key=lambda x: float(x.get("sentiment") or 0.0))
    if state == "positive":
        top = max(recent, key=lambda x: float(x.get("sentiment") or 0.0))
    return {"state": state, "score": round(mood, 3), "count": len(recent), "headline": top["title"]}
