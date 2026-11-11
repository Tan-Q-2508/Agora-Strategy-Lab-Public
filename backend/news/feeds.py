"""Which public news feeds Kairos reads, and how to read one (D-59, D-68).

No keys, no accounts. Market feeds give the day's business news; stock feeds (Yahoo's
per-ticker headlines for US stocks, Google News searches by company name for both markets)
give news about one company; world feeds give geopolitics, central banks and the global
economy: plain public RSS plus GDELT's free DOC 2.0 API, which watches news sites in
dozens of countries and answers keyword searches as JSON (no key; at most one request every
5 seconds). Market feeds were checked on 2026-10-21, world feeds on 2026-10-22.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import quote, quote_plus
from xml.etree import ElementTree as ET

from backend.core.clock import ms_to_dt
from backend.core.types import Market

MAX_BYTES = 2_000_000  # a feed bigger than this is not a news feed


@dataclass(frozen=True)
class Feed:
    key: str  # e.g. "et_markets", "google:RELIANCE"
    label: str
    url: str
    market: Market | None
    kind: Literal["market", "stock", "world"]
    instrument_id: int | None = None  # for stock feeds: the stock it is about
    format: Literal["rss", "gdelt"] = "rss"


@dataclass(frozen=True)
class RawItem:
    title: str
    link: str
    summary: str
    publisher: str
    published_at: int  # UTC ms


MARKET_FEEDS: dict[Market, tuple[Feed, ...]] = {
    Market.IN: (
        Feed(
            "et_markets",
            "Economic Times · Markets",
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            Market.IN,
            "market",
        ),
        Feed(
            "mint_markets",
            "Mint · Markets",
            "https://www.livemint.com/rss/markets",
            Market.IN,
            "market",
        ),
        Feed(
            "bs_markets",
            "Business Standard · Markets",
            "https://www.business-standard.com/rss/markets-106.rss",
            Market.IN,
            "market",
        ),
        Feed(
            "google_business_in",
            "Google News · Business (India)",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
            Market.IN,
            "market",
        ),
    ),
    Market.US: (
        Feed(
            "marketwatch",
            "MarketWatch · Top stories",
            "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            Market.US,
            "market",
        ),
        Feed(
            "yahoo_spy",
            "Yahoo Finance · S&P 500",
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US",
            Market.US,
            "market",
        ),
        Feed(
            "google_business_us",
            "Google News · Business (US)",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
            Market.US,
            "market",
        ),
    ),
}


GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_HOST = "api.gdeltproject.org"


def gdelt_url(query: str, timespan: str = "12h", records: int = 75) -> str:
    return (
        f"{GDELT}?query={quote(query)}&mode=artlist&format=json&sort=datedesc"
        f"&maxrecords={records}&timespan={timespan}"
    )


def gdelt_window_url(query: str, start_ms: int, end_ms: int, records: int = 75) -> str:
    """A GDELT search over a time window (GDELT keeps the last three months), used to find
    the news around a sudden market move (D-96)."""
    from datetime import UTC

    def stamp(ms: int) -> str:
        return ms_to_dt(ms, UTC).strftime("%Y%m%d%H%M%S")

    return (
        f"{GDELT}?query={quote(query)}&mode=artlist&format=json&sort=hybridrel"
        f"&maxrecords={records}&startdatetime={stamp(start_ms)}&enddatetime={stamp(end_ms)}"
    )


def _world(key: str, label: str, url: str, market: Market | None = None) -> Feed:
    return Feed(key, label, url, market, "world")


WORLD_FEEDS: tuple[Feed, ...] = (
    _world("bbc_world", "BBC News · World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    _world("bbc_business", "BBC News · Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    _world("aljazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    _world("guardian_world", "The Guardian · World", "https://www.theguardian.com/world/rss"),
    _world(
        "guardian_business", "The Guardian · Business", "https://www.theguardian.com/business/rss"
    ),
    _world(
        "nyt_world",
        "New York Times · World",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    ),
    _world(
        "nyt_business",
        "New York Times · Business",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    ),
    _world(
        "wsj_world", "Wall Street Journal · World", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"
    ),
    _world(
        "google_world",
        "Google News · World",
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    ),
    _world("oilprice", "OilPrice.com", "https://oilprice.com/rss/main"),
    _world(
        "fed_press",
        "Federal Reserve · Press releases",
        "https://www.federalreserve.gov/feeds/press_all.xml",
        Market.US,
    ),
    _world(
        "rbi_press", "RBI · Press releases", "https://rbi.org.in/pressreleases_rss.xml", Market.IN
    ),
    _world(
        "bbc_india",
        "BBC News · India",
        "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
        Market.IN,
    ),
    _world("mint_economy", "Mint · Economy", "https://www.livemint.com/rss/economy", Market.IN),
    _world(
        "et_economy",
        "Economic Times · Economy",
        "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        Market.IN,
    ),
    _world(
        "cnbctv18_markets",
        "CNBC-TV18 · Markets",
        "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
        Market.IN,
    ),
    Feed(
        "gdelt_geopolitics",
        "GDELT · World geopolitics",
        gdelt_url(
            "(war OR missile OR airstrike OR invasion OR sanctions OR tariffs OR ceasefire OR "
            'coup OR "trade war" OR terrorist) sourcelang:english'
        ),
        None,
        "world",
        format="gdelt",
    ),
    Feed(
        "gdelt_economy",
        "GDELT · World economy",
        gdelt_url(
            '("stock market" OR "central bank" OR "interest rates" OR inflation OR recession '
            'OR "oil prices" OR "bond yields") sourcelang:english'
        ),
        None,
        "world",
        format="gdelt",
    ),
    Feed(
        "gdelt_india",
        "GDELT · India",
        gdelt_url(
            "(India OR Indian OR RBI OR Sensex OR Nifty) (economy OR markets OR tariffs OR "
            "sanctions OR border OR rupee) sourcelang:english"
        ),
        Market.IN,
        "world",
        format="gdelt",
    ),
)


def stock_feeds(
    market: Market, instrument_id: int, symbol: str, yahoo_symbol: str, name: str
) -> list[Feed]:
    """News about one company. Yahoo's per-ticker feed is empty for NSE stocks, so India
    uses Google News searches by company name only."""
    query = quote_plus(f'"{name}" stock when:7d')
    region = "hl=en-IN&gl=IN&ceid=IN:en" if market is Market.IN else "hl=en-US&gl=US&ceid=US:en"
    feeds = [
        Feed(
            f"google:{symbol}",
            "Google News",
            f"https://news.google.com/rss/search?q={query}&{region}",
            market,
            "stock",
            instrument_id,
        ),
    ]
    if market is Market.US:
        feeds.insert(
            0,
            Feed(
                f"yahoo:{symbol}",
                "Yahoo Finance",
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(yahoo_symbol)}&region=US&lang=en-US",
                market,
                "stock",
                instrument_id,
            ),
        )
    return feeds


_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean(text: str) -> str:
    """Plain text from an RSS field: HTML tags and entities removed, spaces collapsed."""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def _ms(date_text: str | None, fallback: int) -> int:
    if not date_text:
        return fallback
    try:
        return int(parsedate_to_datetime(date_text).timestamp() * 1000)
    except (TypeError, ValueError, IndexError):
        return fallback


def parse_rss(data: bytes, *, default_publisher: str, now_ms: int) -> list[RawItem]:
    """Items of an RSS 2.0 document. Undated items get ``now_ms``. Google News titles end
    with " - Publisher", which is split off into the publisher."""
    if len(data) > MAX_BYTES:
        raise ValueError("That feed is too large to be a news feed.")
    root = ET.fromstring(data)  # expat refuses entity-expansion attacks; no DTDs are loaded
    out: list[RawItem] = []
    for it in root.iter("item"):
        title = clean(it.findtext("title") or "")
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        if not title or not link:
            continue
        publisher = clean(it.findtext("source") or "") or default_publisher
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].rstrip()
        summary = clean(it.findtext("description") or "")
        if summary.startswith(title):  # Google repeats the title as a link
            summary = ""
        out.append(
            RawItem(
                title[:400],
                link[:2000],
                summary[:1000],
                publisher[:120],
                _ms(it.findtext("pubDate"), now_ms),
            )
        )
    return out


def _gdelt_ms(seen: str, fallback: int) -> int:
    """GDELT's ``seendate`` is ``YYYYMMDDTHHMMSSZ`` (UTC)."""
    from datetime import UTC, datetime

    try:
        return int(datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp() * 1000)
    except (TypeError, ValueError):
        return fallback


def parse_gdelt(data: bytes, *, now_ms: int) -> list[RawItem]:
    """Articles from a GDELT DOC 2.0 ``artlist`` JSON answer (an empty search gives ``{}``)."""
    if len(data) > MAX_BYTES:
        raise ValueError("That answer is too large to be a news list.")
    doc = json.loads(data.decode("utf-8", errors="replace") or "{}")
    out: list[RawItem] = []
    for a in doc.get("articles") or []:
        title = clean(str(a.get("title") or ""))
        link = str(a.get("url") or "").strip()
        if not title or not link:
            continue
        lang = str(a.get("language") or "English")
        if lang and lang.lower() != "english":
            continue
        out.append(
            RawItem(
                title[:400],
                link[:2000],
                "",
                clean(str(a.get("domain") or "GDELT"))[:120],
                _gdelt_ms(str(a.get("seendate") or ""), now_ms),
            )
        )
    return out
