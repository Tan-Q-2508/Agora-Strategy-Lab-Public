"""News: feed parsing, sentiment, matching headlines to stocks, the service and the API."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.context import AppContext
from backend.core.types import Market
from backend.db.models import NewsItem
from backend.news import relevance, sentiment
from backend.news.feeds import MARKET_FEEDS, Feed, parse_rss, stock_feeds
from backend.news.fetch import HttpFetcher, NewsUnavailable
from backend.news.service import uid_for

SAMPLES = Path(__file__).parent.parent / "fixtures" / "news"
NOW = 1_792_600_000_000


def test_google_news_titles_lose_their_publisher_suffix() -> None:
    items = parse_rss(
        (SAMPLES / "google.xml").read_bytes(), default_publisher="Google News", now_ms=NOW
    )
    assert [i.title for i in items] == [
        "Reliance Industries shares surge after strong quarterly profit",
        "Brokerage downgrades Reliance on weak refining margins",
    ]
    assert items[0].publisher == "Example Wire"
    assert items[0].summary == ""  # Google repeats the title as a link
    assert items[0].published_at == int(
        datetime(2026, 10, 20, 12, 41, 12, tzinfo=UTC).timestamp() * 1000
    )


def test_items_without_a_title_are_skipped_and_dates_fall_back() -> None:
    et = parse_rss((SAMPLES / "et.xml").read_bytes(), default_publisher="ET", now_ms=NOW)
    assert len(et) == 2 and et[0].publisher == "ET"
    mw = parse_rss((SAMPLES / "marketwatch.xml").read_bytes(), default_publisher="MW", now_ms=NOW)
    assert mw[1].published_at == NOW  # no pubDate → when it was read


def test_garbage_and_huge_feeds_are_refused() -> None:
    with pytest.raises(ET.ParseError):
        parse_rss(b"<html>not a feed", default_publisher="x", now_ms=NOW)
    with pytest.raises(ValueError, match="too large"):
        parse_rss(b"x" * 2_000_001, default_publisher="x", now_ms=NOW)


@pytest.mark.parametrize(
    ("text", "sign"),
    [
        ("Infosys beats estimates, raises guidance", 1),
        ("Reliance shares surge to record high", 1),
        ("Brokerage downgrades Titan on weak demand", -1),
        ("JPMorgan profit falls as loan losses widen", -1),
        ("Company faces fraud probe", -1),
        ("Shares did not plunge despite the warning", 0),
        ("Company to hold annual meeting", 0),
    ],
)
def test_sentiment_direction(text: str, sign: int) -> None:
    s = sentiment.score(text)
    if sign > 0:
        assert s > 0.25, s
    elif sign < 0:
        assert s < -0.25, s
    else:
        assert abs(s) < 0.5, s


def test_sentiment_hand_calculated() -> None:
    # "beats" +1.0, "upgrade" +1.2 → 2.2 → tanh(1.1)
    assert sentiment.score("Beats and upgrade") == pytest.approx(0.800499, abs=1e-6)
    # a negator flips the next three words: "not" + "weak" (−0.7 → +0.7) → tanh(0.35)
    assert sentiment.score("not weak") == pytest.approx(0.336376, abs=1e-6)
    # headline counts twice the summary
    h = sentiment.headline_score("Beats and upgrade", "")
    assert h == pytest.approx(0.8005, abs=1e-3)


def _matcher() -> relevance.Matcher:
    return relevance.Matcher(
        [
            relevance.target(1, "RELIANCE", "Reliance Industries Ltd."),
            relevance.target(2, "TCS", "Tata Consultancy Services Ltd."),
            relevance.target(3, "INFY", "Infosys Ltd."),
            relevance.target(4, "BHARTIARTL", "Bharti Airtel Ltd."),
            relevance.target(5, "TITAN", "Titan Company Ltd."),
            relevance.target(6, "TMPV", "Tata Motors Passenger Vehicles Ltd."),
            relevance.target(7, "GOOGL", "Alphabet Inc. (Class A)"),
            relevance.target(8, "BSE", "BSE Ltd."),
        ]
    )


def test_headlines_are_matched_to_the_right_stocks() -> None:
    m = _matcher()
    assert m.find("Sensex, Nifty end higher; Infosys and TCS lead, Airtel slips") == {2, 3, 4}
    assert m.find("Reliance shares surge") == {1}
    assert m.find("Titan of industry") == {5}  # the company name, written as a name
    assert m.find("a titan of industry") == set()
    assert m.find("Tata Steel and Tata Power rise") == set()  # 'Tata' alone is ambiguous
    assert m.find("Tata Motors launches a new car") == {6}
    assert m.find("Google parent climbs") == {7}
    assert m.find("BSE Sensex closes flat") == set()  # BSE the index, not BSE Ltd.
    assert relevance.short_name("Amazon.com, Inc.") == "Amazon"


def test_same_story_from_two_feeds_has_one_id() -> None:
    assert uid_for("Infosys beats estimates!") == uid_for("infosys  beats estimates")


def test_feed_lists() -> None:
    assert {f.key for f in MARKET_FEEDS[Market.IN]} >= {"et_markets", "mint_markets", "bs_markets"}
    us = stock_feeds(Market.US, 9, "AAPL", "AAPL", "Apple")
    assert [f.key for f in us] == ["yahoo:AAPL", "google:AAPL"]
    india = stock_feeds(Market.IN, 1, "RELIANCE", "RELIANCE.NS", "Reliance Industries")
    assert [f.key for f in india] == ["google:RELIANCE"]  # Yahoo has no NSE headlines
    assert "%22Reliance+Industries%22" in india[0].url


def test_http_fetcher_reads_and_reports_failures() -> None:
    body = (SAMPLES / "marketwatch.xml").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        if "broken" in str(req.url):
            return httpx.Response(503)
        return httpx.Response(200, content=body)

    class Clock:
        def now_ms(self) -> int:
            return NOW

    f = HttpFetcher(Clock(), transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    ok = Feed("mw", "MarketWatch · Top", "https://feeds.example/ok", Market.US, "market")
    assert len(f.fetch(ok)) == 2
    with pytest.raises(NewsUnavailable, match="answered 503"):
        f.fetch(
            Feed("mw", "MarketWatch · Top", "https://feeds.example/broken", Market.US, "market")
        )


def test_service_stores_links_and_scores(ctx: AppContext) -> None:
    svc = ctx.news
    r = svc.refresh(svc.feeds(Market.IN))
    assert r.feeds == len(MARKET_FEEDS[Market.IN]) and r.new > 0 and not r.errors
    # the same practice headlines in every market feed are stored once
    with ctx.db.session() as s:
        stored = s.scalar(select(func.count()).select_from(NewsItem))
    assert stored == 6
    items = svc.latest(Market.IN)
    tagged = next(i for i in items if "Reliance Industries and Infosys" in i["title"])
    assert {"RELIANCE", "INFY"} <= set(tagged["symbols"])
    # a second refresh within 10 minutes reads nothing
    assert svc.refresh(svc.feeds(Market.IN)).feeds == 0


def test_stock_news_and_mood(ctx: AppContext) -> None:
    svc = ctx.news
    with ctx.db.session() as s:
        from backend.data.store import find_instrument

        rel = find_instrument(s, Market.IN, "RELIANCE")
    assert rel is not None
    svc.refresh(svc.feeds(instrument=rel))
    items = svc.latest(instrument_id=rel.id)
    assert len(items) == 5 and all("Reliance Industries" in i["title"] for i in items)
    mood = svc.mood(rel.id)
    assert mood["count"] == 5 and -1 <= mood["score"] <= 1


def test_failing_feed_cools_down(ctx: AppContext) -> None:
    class Broken:
        name = "broken"
        calls = 0

        def fetch(self, feed: Feed) -> list[object]:
            Broken.calls += 1
            raise NewsUnavailable("Couldn't reach it.")

    ctx.news_fetcher = Broken()
    r = ctx.news.refresh(ctx.news.feeds(Market.US))
    assert r.feeds == 0 and r.errors
    calls = Broken.calls
    ctx.news.refresh(ctx.news.feeds(Market.US))
    assert Broken.calls == calls  # left alone for 15 minutes


def test_news_api(client: TestClient, ctx: AppContext) -> None:
    ctx.news.refresh(ctx.news.feeds(Market.US))
    body = client.get("/api/news", params={"market": "US"}).json()
    assert body["enabled"] and body["items"] and "MarketWatch · Top stories" in body["sources"]
    aapl = next(
        i for i in client.get("/api/instruments", params={"q": "AAPL"}).json()["instruments"]
    )
    r = client.post("/api/news/refresh", json={"instrument_id": aapl["id"]}).json()
    assert r["feeds"] == 2 and r["new"] >= 1
    one = client.get("/api/news", params={"instrument_id": aapl["id"]}).json()
    assert one["items"] and one["mood"]["count"] >= 1
    client.put("/api/settings", json={"news.enabled": False})
    off = client.get("/api/news", params={"market": "US"}).json()
    assert off["enabled"] is False and off["refreshing"] is False


def test_stocks_in_no_index_dont_grab_everyday_headline_words(ctx: AppContext) -> None:
    """D-102: ~6,000 listed-only stocks; "Seven Hills" must not tag "Seven missing…"."""
    from backend.db.models import Instrument, InstrumentProfile

    with ctx.db.session() as s:
        row = Instrument(
            market_code="US",
            symbol="SEVN",
            yahoo_symbol="SEVN",
            name="Seven Hills Realty Trust",
            instrument_type="equity",
            is_active=1,
            added_at=0,
        )
        s.add(row)
        s.flush()
        s.add(
            InstrumentProfile(
                instrument_id=row.id, sector="", industry="", size="", tags="", lists="listed"
            )
        )
        iid = row.id
    found = ctx.news._matcher_for().find("Seven missing after building collapses")
    assert iid not in found


def test_two_refreshes_at_once_store_each_headline_once(ctx: AppContext) -> None:
    """D-121: the chat's news tool and the background refresh saved the same headline together."""
    import threading

    svc = ctx.news
    feeds = svc.feeds(Market.IN)
    errors: list[BaseException] = []

    def go() -> None:
        try:
            svc._last.clear()  # both read the feeds, as two callers would
            svc.refresh(feeds)
        except BaseException as exc:  # the test reports any failure
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with ctx.db.session() as s:
        assert s.scalar(select(func.count()).select_from(NewsItem)) == 6


def test_a_refresh_asked_for_while_agora_stops_is_ignored(ctx: AppContext) -> None:
    """The autopilot asked for fresh news just after the news workers shut down, and the
    round failed with "cannot schedule new futures after shutdown" (2026-11-05)."""
    news = ctx.services["news"]
    news._pool.shutdown(wait=False)
    assert news.ensure_fresh(news.feeds()) is False


def test_a_crisis_in_a_small_far_economy_isnt_systemic_here() -> None:
    """D-173: "Paraguay's president resigns after bank collapse" came through a US feed, was
    read as US news at severity 5, and pushed the US gauge to "Elevated"."""
    from backend.news import topics as t

    far = t.classify("Paraguay President Santiago Peña resigns after bank collapse", market="US")
    assert far.scope == "WORLD" and far.severity <= t.FAR_SEVERITY
    congress = t.classify(
        "Paraguay President Santiago Peña resigns after bank collapse",
        "The move follows a bank collapse and after the lower house of congress voted.",
        market="US",
    )
    assert congress.scope == "WORLD" and congress.severity <= t.FAR_SEVERITY
    ally = t.classify(
        "Paraguay President Pena resigns in wake of bank collapse",
        "President Pena, a Trump ally, had faced an impeachment motion and protests.",
        market="US",
    )
    assert ally.scope == "WORLD" and ally.severity <= t.FAR_SEVERITY
    fed = t.classify("Fed warns Wall Street over Argentina bank collapse", market="US")
    assert fed.severity >= 4  # US markets named: not only far away
    home = t.classify("US banks face contagion as regional lender collapses", market="US")
    assert home.scope == "US" and home.severity == 5  # unchanged at home
    spread = t.classify("Bank run in Argentina spreads to global markets", market="US")
    assert spread.severity >= 4  # names the world: not only far away
    # 5 Nov: the same story named only a region, and "american" in "Latin American" made it US news
    region = t.classify("Latin American president resigns after bank collapse", market="US")
    assert region.scope == "WORLD" and region.severity <= t.FAR_SEVERITY
    africa = t.classify("African central bank collapse sparks protests", market="IN")
    assert africa.scope == "WORLD" and africa.severity <= t.FAR_SEVERITY


def test_saved_headlines_are_read_again_when_the_reading_changes(ctx: AppContext) -> None:
    """A fix to the news reading must reach the stories already saved: the far-away bank
    collapse kept the US gauge at "Severe" until it was re-read by hand (5 Nov)."""
    from backend.db.models import NewsItem, SettingRow
    from backend.news import service as news_service
    from backend.news import topics as t

    now = ctx.clock.now_ms()
    title = "Latin American president resigns after bank collapse"
    with ctx.db.session() as s:
        s.add(SettingRow(key=news_service.TOPICS_VERSION_KEY, value="old", updated_at=now))
        s.add(
            NewsItem(
                uid="x1",
                source="test",
                market="US",
                title=title,
                link="http://x",
                publisher="",
                published_at=now - 3_600_000,
                fetched_at=now,
                topics="banking",
                severity=5,
                impact=-0.8,
                scope="US",
            )
        )
    svc = ctx.news
    with ctx.db.session() as s:
        svc._backfilled = False
        svc._backfill(s)
    with ctx.db.session() as s:
        row = s.scalar(select(NewsItem).where(NewsItem.uid == "x1"))
        assert row is not None and row.scope == "WORLD" and row.severity <= t.FAR_SEVERITY
        assert s.get(SettingRow, news_service.TOPICS_VERSION_KEY).value == t.VERSION  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("Share pledge, personal guarantee and 17% coupon debt: How Ola Electric is funded", ""),
        ("US sanctions India-based couple, companies over alleged support for Iran's oil", ""),
        ("Toronto home invasion suspect wounded during break-in walks free from hospital", ""),
        ("Trump DOJ invasion hype backfires as judge threatens to punish officials", ""),
        ("China resettling Tibetans near LAC to push demographic invasion: report", ""),
        (
            "Ice hockey federation reiterates opposition to reinstatement of Russia",
            "Russia has been banned since its invasion of Ukraine in 2022.",
        ),
        (
            "Amy Acton wins Ohio race for governor, ending 16 years of Republican control",
            "Acton led the state's health department during the covid pandemic.",
        ),
        ("The U.S. military and NASA have power problems. Nuclear microreactors might help", ""),
        ("Democrats eye historic upset in Mississippi Senate race", ""),
    ],
)
def test_misread_headlines_are_not_crises(title: str, summary: str) -> None:
    """D-179: the audit of every headline rated 4–5 in the two weeks to 5 Nov found these read
    as crises: whole words only ("coup" was found in "coupon" and "couple"), escalating words
    count only in the headline, a topic named only in the summary counts one level lower, and
    phrases like "home invasion" or "nuclear microreactors" mean something else."""
    from backend.news import topics as t

    assert t.classify(title, summary, market="US").severity <= 3


@pytest.mark.parametrize(
    "title",
    [
        "Russia invades Ukraine",
        "Full-scale invasion begins; oil prices soar",
        "Military coup in Pakistan",
        "WHO declares pandemic as cases spread",
        "Nifty hits circuit breaker as markets crash",
        "Silicon Valley Bank collapse sends shockwaves through US banks",
    ],
)
def test_real_crises_still_read_as_crises(title: str) -> None:
    from backend.news import topics as t

    assert t.classify(title, market="US").severity == 5


def test_everyday_words_dont_link_headlines_to_companies() -> None:
    """D-179: the audit found "United" linking every United States story to 20 companies (a
    Dollar General lawsuit blocked trades in an oil fund), "Share India" on 355 headlines,
    "Nasdaq"/"Dow" on the companies Nasdaq Inc. and Dow Inc., "Trump" on Trump Media, and an
    Indian story about Reliance on the US company Reliance, Inc."""
    rows = [
        (1, "RELIANCE", "Reliance Industries Ltd.", "IN"),
        (2, "RPOWER", "Reliance Power Ltd.", "IN"),
        (3, "RS", "Reliance, Inc.", "US"),
        (4, "BNO", "United States Brent Oil Fund", "US"),
        (5, "UAL", "United Airlines Holdings", "US"),
        (6, "SHAREINDIA", "Share India Securities Ltd.", "IN"),
        (7, "NDAQ", "Nasdaq, Inc.", "US"),
        (8, "DOW", "Dow Inc.", "US"),
        (9, "DJT", "Trump Media & Technology Group", "US"),
        (10, "INFY", "Infosys Ltd.", "IN"),
    ]
    shared = relevance.shared_first_words([n for _, _, n, _ in rows])
    m = relevance.Matcher([relevance.target(i, s, n, shared, mk) for i, s, n, mk in rows])
    assert m.find("FTC and 20 states sue Dollar General; United States courts weigh in") == set()
    assert m.find("United Nations envoy visits Sudan") == set()
    assert m.find("Tata Steel Share Price Live Updates: Share India view") == set()
    assert m.find("Stock market today: Dow, S&P 500 and Nasdaq rise") == set()
    assert m.find("Trump invokes Cold War-era act to bolster gasoline output") == set()
    assert m.find("Reliance shares surge after Jio listing", "IN") == {1}
    assert m.find("Infosys and Reliance lead the Sensex", "US") == set()  # a US feed
    # the real names still work
    assert m.find("United Airlines raises its outlook") == {5}
    assert m.find("Share India Securities posts record profit") == {6}
    assert m.find("Nasdaq, Inc. beats estimates") == {7}
    assert m.find("Trump Media & Technology Group shares jump") == {9}
    assert m.find("Infosys wins a $1 billion deal", "IN") == {10}


@pytest.mark.parametrize(
    ("title", "severity"),
    [
        ("AI stock sell-off sends the S&P 500 down 4.4% in worst day since April 2025", 5),
        ("Nasdaq 100 plunges 6.36% as AI selloff spreads", 5),
        ("AI stock sell - off sends the S & P 500 down 4 . 4 % in worst day", 5),
        ("Sensex falls 1,200 points, Nifty down 3.2% as FIIs sell", 4),
    ],
)
def test_an_index_falling_hard_reads_as_market_stress(title: str, severity: int) -> None:
    """D-183: on 5 Nov the S&P 500 fell 4.4% and the Nasdaq 100 6.4%, Wall Street's worst day in
    19 months, and the US gauge read calm: an index's fall now counts by its size."""
    from backend.news import topics as t

    r = t.classify(title, market="US")
    assert r.severity == severity and r.topics[0] == "market_stress" and r.impact < 0


@pytest.mark.parametrize(
    "title",
    [
        "Dow edges down 0.3% as investors await Fed",
        "Nifty jumps 2% on US election results",
        "Zomato shares down 8% after results, Nifty flat",
    ],
)
def test_small_or_single_stock_moves_are_not_a_market_fall(title: str) -> None:
    from backend.news import topics as t

    assert t.classify(title, market="IN").severity <= 3


def test_roundups_dont_drive_a_stocks_alert() -> None:
    """D-185: a live blog naming thirty companies said Laurus Labs had a positive catalyst
    (it was PVR Inox's). Headlines naming more than three stocks don't count for one stock."""
    from backend.news import risk as rk

    now = 1_800_000_000_000
    roundup = {
        "title": "Q2 results live: Paytm raided, NCC PAT up 19%, Titan, Airtel react",
        "published_at": now - 3_600_000,
        "sentiment": -0.8,
        "symbols": ["PAYTM", "NCC", "TITAN", "BHARTIARTL"],
    }
    assert rk.stock_alert([roundup], now)["state"] == "quiet"
    own = {**roundup, "title": "Paytm offices raided in fraud probe", "symbols": ["PAYTM"]}
    assert rk.stock_alert([own], now)["state"] == "critical"


def test_privilege_escalation_is_not_war() -> None:
    from backend.news import topics as t

    title = "OpenAI Cyber Model Uncovers 948 Linux Kernel Privilege Escalation Vulnerabilities"
    assert t.classify(title, market="IN").severity <= 2
    assert t.classify("Iran war escalation fears grow", market="US").severity >= 4


@pytest.mark.parametrize(
    ("title", "most", "least"),
    [
        ("OpenAI AI Pipeline Generates 948 Linux Root Escalation Exploits in 30-Hour Run", 1, 0),
        ("The U.S. military and NASA have power problems", 1, 0),
        ("Iran war escalation fears grow", 5, 4),
        ("Israel launches offensive in Gaza", 5, 3),
        ("Military clashes on India-China border", 5, 3),
    ],
)
def test_a_weak_war_word_alone_isnt_a_war(title: str, most: int, least: int) -> None:
    """D-187: words like "escalation" or "military" also mean other things; alone, with no war
    word or warring place beside them, they don't make a story a war."""
    from backend.news import topics as t

    assert least <= t.classify(title, market="US").severity <= most


def test_other_markets_are_world_news_and_de_escalation_calms() -> None:
    """D-188: "South Korea stocks plunge 8%" from a US feed read as US news at full weight, and
    "Iran war de-escalation" escalated because "escalation" sits inside "de-escalation"."""
    from backend.news import topics as t

    korea = t.classify("South Korea stocks plunge 8%, circuit breaker triggered", market="US")
    assert korea.scope == "WORLD" and korea.severity == 5
    calm = t.classify("Fuel oil slumps as market prices in potential Iran war de-escalation")
    assert calm.calming and calm.severity <= 3 and calm.impact > 0


def test_one_event_from_three_outlets_is_one_story() -> None:
    """D-189: the Kospi crash counted as three stories in the gauge, not one from three sources."""
    from backend.news import risk as rk

    def item(title: str, k: int) -> dict[str, Any]:
        return {"title": title, "topics": ["market_stress"], "published_at": 1_000 + k}

    kospi = [
        item("Asian markets today: South Korea's Kospi crashes 8%, plunges below 5,000", 1),
        item("South Korea stocks plunge 8%, circuit breaker triggered as chip shares tumble", 2),
        item("Asian markets crash as AI rout rocks US markets, Kospi plunges 8%", 3),
    ]
    assert len(rk.stories(kospi)) == 1
    other = [
        item("US stocks plunge 3% as Nasdaq falls on chip worries", 1),
        item("India stocks plunge 3% as Nifty falls on FII selling", 2),
    ]
    assert len(rk.stories(other)) == 2


def test_a_stocks_fall_in_the_next_clause_isnt_the_indexs() -> None:
    """D-193: "Nifty below 24,500; Power Grid drops 3%" read as the Nifty falling 3%."""
    from backend.news import topics as t

    title = "Opening Bell: Sensex starts on choppy note, Nifty below 24,500; Power Grid drops 3%"
    assert t.classify(title, market="IN").severity <= 2
    assert t.index_drop("sensex falls 1,200 points, nifty down 3.2% as fiis sell") == 3.2


def test_a_sector_index_slipping_isnt_the_market_falling() -> None:
    """D-194: "Sensex jumps 400 pts, Nifty near 24,600; Nifty Realty down 2%" rated 4."""
    from backend.news import topics as t

    up = "Stock Market LIVE: Sensex jumps 400 pts, Nifty near 24,600; Nifty Realty down 2%"
    assert t.classify(up, market="IN").severity <= 2
    assert t.classify("Nifty 50 down 2.5% in early trade", market="IN").severity >= 4


def test_historic_isnt_escalation_and_plurals_still_count() -> None:
    """D-199: "historic midterm win" raised severity; and whole-word matching (D-179) had made
    "circuit breakers" miss the top-severity list."""
    from backend.news import topics as t

    pol = "Trump blames Democrats for Wall Street selloff after historic midterm election win"
    assert t.classify(pol, market="US").severity <= 3
    crash = "Stocks suffer historic crash as circuit breakers trip"
    assert t.classify(crash, market="US").severity == 5


def test_a_market_live_blog_isnt_a_stocks_own_news() -> None:
    """D-200: ET's "Stock Market Live Updates: Nifty surges 230 points" posts named Titan in their
    summaries and set Titan's own news tone."""
    from backend.news import risk as rk

    now = 1_800_000_000_000
    blog = {
        "title": "Sensex Today | Stock Market Live Updates: Nifty surges 230 points",
        "published_at": now - 3_600_000,
        "sentiment": 0.8,
        "symbols": ["TITAN"],
    }
    assert rk.stock_alert([blog, {**blog, "published_at": now - 1_000}], now)["state"] == "quiet"
    own = {**blog, "title": "Titan shines 3% on Dhanteras after 2x profit"}
    assert rk.stock_alert([own, {**own, "published_at": now - 1_000}], now)["state"] == "positive"


def test_direction_words_are_read_next_to_what_they_describe() -> None:
    from backend.news import topics as t

    # D-229, the user's lead: the rupee's high made a falling oil price read as oil rising
    r = t.classify("Rupee hits six-month high on oil price decline")
    assert r.sectors["Airlines"] == 1 and r.sectors["Oil producers"] == -1
    up = t.classify("Rupee weakens as crude oil jumps")
    assert up.sectors["Airlines"] == -1


def test_a_central_bank_standing_still_is_neither_a_hike_nor_a_cut() -> None:
    from backend.news import topics as t

    for head in ("RBI holds repo rate", "Fed keeps rates unchanged", "ECB leaves rates on hold"):
        r = t.classify(head)
        assert "Banks" not in r.sectors and abs(r.impact) < 0.1, head
    assert t.classify("RBI raises repo rate by 25 bps").sectors["Banks"] == 1


def test_a_trade_war_is_not_a_war() -> None:
    from backend.news import topics as t

    r = t.classify("Trade war fears ease after talks")
    assert "conflict" not in r.topics and "trade" in r.topics


def test_a_frightened_market_is_never_called_calm() -> None:
    # D-233: the headlines faded, the VIX didn't
    from backend.news import risk as r

    calm = {"level": 13.7, "name": "calm", "text": "Calm."}
    held = r.with_fear(calm, ("VIX", 25.5, 18.0))
    assert (
        held["name"] == "watchful" and held["level"] == r.FEAR_FLOOR and "VIX 25.5" in held["text"]
    )
    assert r.with_fear(calm, ("VIX", 18.5, 18.0)) == calm  # its usual level: no change
    assert r.with_fear(calm, None) == calm
    hot = {"level": 80.0, "name": "severe", "text": "Severe."}
    assert r.with_fear(hot, ("VIX", 40.0, 18.0)) == hot  # never lowers the gauge
