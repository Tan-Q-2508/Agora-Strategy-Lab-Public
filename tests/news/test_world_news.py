"""World news (Phase 10.5): reading headlines for topic, severity and impact; GDELT; the
news risk gauge (hand-calculated); stock alerts; the service and the live API."""

from __future__ import annotations

import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.context import AppContext
from backend.core.types import Market
from backend.db.models import NewsItem
from backend.news import risk, topics
from backend.news.feeds import GDELT_HOST, WORLD_FEEDS, Feed, gdelt_url, parse_gdelt
from backend.news.fetch import HttpFetcher, NewsUnavailable

NOW = 1_792_600_000_000
H = 3_600_000


# ---------------------------------------------------------------- reading headlines


@pytest.mark.parametrize(
    ("title", "topic", "sev", "sign", "scope"),
    [
        ("Russia launches full-scale invasion of Ukraine", "conflict", 5, -1, "WORLD"),
        ("Israel and Hamas agree to a ceasefire after talks", "conflict", 2, 1, "WORLD"),
        ("RBI hikes repo rate by 50 basis points to fight inflation", "central_bank", 2, -1, "IN"),
        ("Fed cuts interest rates by a quarter point", "central_bank", 1, 1, "US"),
        ("US imposes 50% tariffs on Indian goods", "trade", 3, -1, "WORLD"),
        (
            "Sensex crashes 4,000 points as circuit breaker halts trading",
            "market_stress",
            5,
            -1,
            "IN",
        ),
        (
            "Oil prices surge as tensions escalate in the Strait of Hormuz",
            "conflict",
            4,
            -1,
            "WORLD",
        ),
        (
            "Silicon Valley Bank collapses in biggest bank failure since 2008",
            "banking",
            5,
            -1,
            "US",
        ),
        ("WHO declares a pandemic as the virus spreads", "health", 5, -1, "WORLD"),
        ("Infosys quarterly profit rises 8%, beats estimates", "corporate", 1, 1, "IN"),
    ],
)
def test_headlines_are_read_like_a_desk_would(
    title: str, topic: str, sev: int, sign: int, scope: str
) -> None:
    r = topics.classify(title, market="IN" if scope == "IN" else None)
    assert r.topics[0] == topic, r
    assert r.severity == sev, r
    assert (r.impact > 0) == (sign > 0) and r.impact != 0, r
    assert r.scope == scope, r


def test_not_market_news_is_ignored() -> None:
    r = topics.classify("Local club wins the football championship")
    assert r.topics == () and r.severity == 0


def test_calming_news_flips_the_sectors() -> None:
    war = topics.classify("Missile strikes hit oil facilities; troops mass at the border")
    assert war.sectors["Defence"] == 1 and war.sectors["Airlines"] == -1
    peace = topics.classify("Ceasefire agreed; peace talks to start")
    assert peace.calming and peace.sectors["Airlines"] == 1


def test_company_news_ranks_below_bigger_topics() -> None:
    r = topics.classify("Tata Motors profit falls as new US tariffs hit car exports")
    assert r.topics[0] == "trade" and "corporate" in r.topics


# ---------------------------------------------------------------- GDELT

GDELT_DOC = {
    "articles": [
        {
            "url": "https://news.example/a",
            "title": "Missiles strike near the border as tensions rise",
            "seendate": "20261022T101500Z",
            "domain": "news.example",
            "language": "English",
            "sourcecountry": "United States",
        },
        {"url": "https://x.example/b", "title": "Titre en français", "language": "French"},
        {"url": "", "title": "no link"},
    ]
}


def test_gdelt_answers_are_parsed() -> None:
    items = parse_gdelt(json.dumps(GDELT_DOC).encode(), now_ms=NOW)
    assert len(items) == 1
    it = items[0]
    assert it.publisher == "news.example" and it.link == "https://news.example/a"
    assert it.published_at == 1_792_664_100_000  # 2026-10-22 10:15:00 UTC
    assert parse_gdelt(b"{}", now_ms=NOW) == []


def test_gdelt_urls_and_rate_limit() -> None:
    url = gdelt_url('(war OR "trade war") sourcelang:english')
    assert GDELT_HOST in url and "mode=artlist" in url and "format=json" in url
    assert "%22trade%20war%22" in url
    keys = {f.key for f in WORLD_FEEDS}
    assert {"bbc_world", "aljazeera", "fed_press", "rbi_press", "gdelt_geopolitics"} <= keys

    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "busy" in str(req.url):
            return httpx.Response(429, text="Please limit requests to one every 5 seconds")
        return httpx.Response(200, content=json.dumps(GDELT_DOC).encode())

    class Clock:
        def now_ms(self) -> int:
            return NOW

    f = HttpFetcher(Clock(), transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    f.pace_s[GDELT_HOST] = 0.0  # tests don't wait; Agora waits 6 s between GDELT calls
    feed = Feed("g", "GDELT · test", url, None, "world", format="gdelt")
    assert len(f.fetch(feed)) == 1
    with pytest.raises(NewsUnavailable, match="429"):
        f.fetch(Feed("g", "GDELT · test", url + "&busy=1", None, "world", format="gdelt"))


# ---------------------------------------------------------------- the gauge


def item(
    title: str,
    sev: int,
    impact: float,
    *,
    publisher: str = "A",
    age_h: float = 0.0,
    scope: str = "WORLD",
    topic: str = "conflict",
) -> dict[str, object]:
    return {
        "title": title,
        "severity": sev,
        "impact": impact,
        "publisher": publisher,
        "published_at": NOW - int(age_h * H),
        "scope": scope,
        "topics": [topic],
        "link": "",
    }


def test_gauge_hand_calculated() -> None:
    # one fresh severity-3 story, impact −0.8, one source: 1 × 0.8 = 0.8 (world news counts
    # 0.8 for a market: 0.64) → 100 × (1 − e^(−0.64/4))
    one = [item("Missiles fired at the border; oil prices jump", 3, -0.8)]
    g = risk.gauge(one, "IN", NOW)
    assert g["level"] == pytest.approx(100 * (1 - math.exp(-0.64 / 4)), abs=0.1)
    assert g["name"] == "calm"
    # the same story from five publishers: × 3 → 1.92 → 38.1, watchful
    five = [
        item("Missiles fired at the border; oil prices jump", 3, -0.8, publisher=p) for p in "ABCDE"
    ]
    g5 = risk.gauge(five, "IN", NOW)
    assert g5["level"] == pytest.approx(100 * (1 - math.exp(-1.92 / 4)), abs=0.1)
    assert g5["name"] == "watchful" and g5["drivers"][0]["sources"] == 5
    # an invasion (3.5 × 0.9) reported by five: 9.45 × 0.8 = 7.56 → 84.9, severe
    inv = [item("Full-scale invasion begins", 5, -0.9, publisher=p) for p in "ABCDE"]
    assert risk.gauge(inv, "IN", NOW)["name"] == "severe"


def test_gauge_weighs_age_place_and_calm() -> None:
    old = [item("Missiles fired at the border; oil prices jump", 3, -0.8, age_h=6)]  # one half-life
    assert risk.gauge(old, None, NOW)["score"] == pytest.approx(0.4)
    us_only = [item("US jobs report shocks", 3, -0.8, scope="US", topic="growth")]
    assert risk.gauge(us_only, "IN", NOW)["score"] == pytest.approx(0.8 * 0.4)
    assert risk.gauge(us_only, "US", NOW)["score"] == pytest.approx(0.8)
    calm = [
        item("Missiles fired at the border; oil prices jump", 3, -0.8),
        item("Ceasefire agreed; oil prices fall", 2, 0.6, publisher="B"),
    ]
    # 0.8 − ½ × (0.5 × 0.6) = 0.65
    assert risk.gauge(calm, None, NOW)["score"] == pytest.approx(0.65)
    assert risk.gauge([item("old news", 5, -1, age_h=40)], None, NOW)["level"] == 0
    # a war story that never mentions markets or prices counts half
    quiet = [item("Troops shell a village near the front", 3, -0.8)]
    assert risk.gauge(quiet, None, NOW)["score"] == pytest.approx(0.4)


def test_more_coverage_is_not_more_risk() -> None:
    # two different stories: the heavier counts fully, the next 0.6× → 0.8 + 0.48
    two = [
        item("Missiles fired at the border; oil prices jump", 3, -0.8),
        item("Shipping halted in the strait as tankers are attacked", 3, -0.8, publisher="B"),
    ]
    assert risk.gauge(two, None, NOW)["score"] == pytest.approx(1.28)
    # forty different war stories can't push a quiet day past "elevated"
    many = [
        item(
            f"Story number {k} about clashes and oil supply worries {k}", 3, -0.8, publisher=str(k)
        )
        for k in range(40)
    ]
    assert risk.gauge(many, None, NOW)["level"] < 75


def test_stock_alerts() -> None:
    def news(title: str, s: float, age_h: float = 1) -> dict[str, object]:
        return {"title": title, "sentiment": s, "published_at": NOW - int(age_h * H)}

    crit = risk.stock_alert([news("Company faces fraud probe; shares plunge", -0.7)], NOW)
    assert crit["state"] == "critical" and crit["flag"] in ("fraud", "probe", "plunges")
    neg = risk.stock_alert(
        [news("Weak demand hurts sales", -0.5), news("Margins shrink", -0.6)], NOW
    )
    assert neg["state"] == "negative"
    pos = risk.stock_alert([news("Wins a big order", 0.6), news("Upgrade to buy", 0.7)], NOW)
    assert pos["state"] == "positive"
    assert risk.stock_alert([news("Annual meeting next week", 0.0)], NOW)["state"] == "quiet"
    assert risk.stock_alert([news("Fraud probe", -0.9, age_h=60)], NOW)["state"] == "quiet"


# ---------------------------------------------------------------- service and API


def test_world_feeds_are_stored_classified_and_filtered(ctx: AppContext) -> None:
    svc = ctx.news
    r = svc.refresh(svc.world_feeds(None))
    assert r.feeds == len(WORLD_FEEDS) and r.new > 0 and not r.errors
    items = svc.latest(None, world=None, limit=100)
    assert all(i["severity"] is not None and i["scope"] for i in items)
    oil = next(i for i in items if "OPEC" in i["title"])
    assert oil["topics"][0] == "energy" and oil["group"] == "Economy"
    geo = svc.latest(None, world=None, group="Geopolitics", limit=100)
    assert geo and all(i["group"] == "Geopolitics" for i in geo)
    assert all("Ceasefire" in i["title"] for i in svc.latest(None, world=None, q="ceasefire"))
    g = svc.risk(Market.IN)
    assert g["market"] == "IN" and 0 <= g["level"] < 50  # practice news is calm-to-watchful
    assert g["drivers"]


def test_rows_from_before_the_upgrade_are_classified_on_read(ctx: AppContext) -> None:
    with ctx.db.session() as s:
        s.add(
            NewsItem(
                uid="old",
                source="et_markets",
                market="IN",
                title="RBI hikes repo rate unexpectedly",
                summary="",
                link="https://example.invalid/x",
                publisher="ET",
                published_at=ctx.clock.now_ms() - H,
                fetched_at=ctx.clock.now_ms() - H,
                sentiment=-0.2,
            )
        )
    items = ctx.news.latest(Market.IN, world=None)
    old = next(i for i in items if i["title"].startswith("RBI hikes"))
    assert old["topics"][0] == "central_bank" and old["scope"] == "IN"
    with ctx.db.session() as s:
        row = s.scalar(select(NewsItem).where(NewsItem.uid == "old"))
        assert row is not None and row.severity is not None


def test_live_news_api(client: TestClient, ctx: AppContext) -> None:
    ctx.news.refresh([*ctx.news.feeds(None), *ctx.news.world_feeds(None)])
    body = client.get("/api/news/live").json()
    assert body["items"] and set(body["risk"]) == {"IN", "US", "WORLD"}
    assert body["guard"] == "protective" and "Geopolitics" in body["groups"]
    assert any(t["key"] == "conflict" for t in body["topics"])
    assert "BBC News · World" in body["sources"] and "GDELT · World geopolitics" in body["sources"]
    world = client.get("/api/news/live", params={"region": "WORLD"}).json()["items"]
    assert world and all(i["scope"] == "WORLD" for i in world)
    g = client.get("/api/news/risk", params={"market": "US"}).json()
    assert g["market"] == "US" and g["name"] in ("calm", "watchful", "elevated", "severe")
    market = client.get("/api/news", params={"market": "IN"}).json()
    assert market["risk"]["market"] == "IN"
