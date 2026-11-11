"""News for Kairos: read feeds on demand, store and de-duplicate headlines, link them to
stocks, score their sentiment (D-59), and read world news for its topic, severity and
market impact, summed up in the news risk gauge (D-68).

Nothing runs in the background on a timer. When a screen or Kairos asks for news and the
saved headlines are more than 10 minutes old, a refresh starts on a small worker thread
and the saved headlines are returned straight away (``refreshing`` tells the screen to ask
again in a few seconds). So news is fresh while Kairos is in use and nothing happens when
it isn't. A feed that fails is left alone for 15 minutes.
"""

from __future__ import annotations

import hashlib
import math
import re
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, delete, or_, select

from backend import actions
from backend.core.types import Market
from backend.data import service as data_service
from backend.data.store import InstrumentRef, find_instrument, get_instrument
from backend.db.models import (
    Candle,
    Instrument,
    NewsItem,
    NewsLink,
    SettingRow,
)
from backend.logging_setup import get_logger
from backend.news import relevance, risk, sentiment, topics
from backend.news.feeds import MARKET_FEEDS, WORLD_FEEDS, Feed, RawItem, stock_feeds
from backend.news.fetch import FakeFetcher, HttpFetcher, NewsFetcher, NewsUnavailable
from backend.settings_store import read_setting
from backend.watchlists import seed

log = get_logger("news")

STALE_MS = 10 * 60_000
WORLD_STALE_MS = 4 * 60_000  # the News screen reads world feeds every few minutes
GDELT_STALE_MS = 15 * 60_000  # GDELT asks for few, well-spaced requests
COOL_DOWN_MS = 15 * 60_000
KEEP_MS = 30 * 86_400_000
REREAD_DAYS = 14  # saved headlines read again when the news reading changes
TOPICS_VERSION_KEY = "_news.topics_version"
LINKS_VERSION_KEY = "_news.links_version"
STOCK_FEED_SOURCES = ("google", "yahoo")  # per-company feeds (``feeds.stock_feeds``)
KEEP_WORLD_MS = 7 * 86_400_000  # world headlines are many and age fast
HALF_LIFE_MS = 24 * 3_600_000
_NORM = re.compile(r"[^a-z0-9]+")


def uid_for(title: str) -> str:
    """The same story from two feeds has the same words: hash the normalised title."""
    return hashlib.sha1(_NORM.sub(" ", title.lower()).strip().encode()).hexdigest()


@dataclass
class RefreshResult:
    feeds: int = 0
    new: int = 0
    errors: list[str] = field(default_factory=list)


class NewsService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._last: dict[str, int] = {}
        self._failed_until: dict[str, int] = {}
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        # one save of headlines at a time: the chat's news tool and the background refresh
        # saved the same headline at once ("UNIQUE constraint failed: news_items.uid", D-121)
        self._write = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="news")
        self._matcher: tuple[int, relevance.Matcher] | None = None
        self._risk_cache: dict[str, tuple[int, dict[str, Any]]] = {}

    @property
    def fetcher(self) -> NewsFetcher:
        f: NewsFetcher | None = getattr(self.ctx, "news_fetcher", None)
        if f is None:
            f = (
                FakeFetcher(self.ctx.clock, self._names())
                if self.ctx.data_mode == "fake"
                else HttpFetcher(self.ctx.clock)
            )
            self.ctx.news_fetcher = f
        return f

    def enabled(self) -> bool:
        return bool(read_setting(self.ctx.db, "news.enabled"))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------ which feeds

    def _names(self) -> dict[str, str]:
        with self.ctx.db.session() as s:
            return {i.symbol: relevance.short_name(i.name) for i in s.scalars(select(Instrument))}

    def world_feeds(self, market: Market | None = None) -> list[Feed]:
        """World feeds: the global ones, plus the given market's (RBI, Fed, …)."""
        return [f for f in WORLD_FEEDS if f.market is None or market is None or f.market == market]

    def feeds(
        self, market: Market | None = None, instrument: InstrumentRef | None = None
    ) -> list[Feed]:
        if instrument is not None:
            return stock_feeds(
                instrument.market,
                instrument.id,
                instrument.symbol,
                instrument.yahoo_symbol,
                relevance.short_name(instrument.name),
            )
        markets = [market] if market else list(Market)
        return [f for m in markets for f in MARKET_FEEDS[m]]

    def _matcher_for(self) -> relevance.Matcher:
        with self.ctx.db.session() as s:
            rows = s.scalars(select(Instrument).where(Instrument.is_active == 1)).all()
            rare = seed.rarely_named(s)  # names like "Seven Hills" match everyday words
            shared = relevance.shared_first_words([r.name for r in rows])
            targets = [
                relevance.target(r.id, r.symbol, r.name, shared, r.market_code)
                for r in rows
                if r.instrument_type != "index" and r.id not in rare
            ]
        key = len(targets)
        if self._matcher is None or self._matcher[0] != key:
            self._matcher = (key, relevance.Matcher(targets))
        return self._matcher[1]

    # ------------------------------------------------------------ reading feeds

    @staticmethod
    def stale_ms(feed: Feed) -> int:
        if feed.format == "gdelt":
            return GDELT_STALE_MS
        return WORLD_STALE_MS if feed.kind == "world" else STALE_MS

    def refresh(self, feeds: list[Feed], *, force: bool = False) -> RefreshResult:
        """Read ``feeds`` now (skipping fresh or cooling-down ones unless ``force``)."""
        result = RefreshResult()
        now = self.ctx.clock.now_ms()
        matcher = self._matcher_for()
        act = actions.track("news_read", "Read the news feeds", feeds=len(feeds))
        todo = [
            f
            for f in feeds
            if force
            or (
                now - self._last.get(f.key, 0) >= self.stale_ms(f)
                and self._failed_until.get(f.key, 0) <= now
            )
        ]

        def read(feed: Feed) -> tuple[Feed, list[RawItem] | NewsUnavailable]:
            try:
                return feed, self.fetcher.fetch(feed)
            except NewsUnavailable as exc:
                return feed, exc

        # RSS feeds are read six at a time; GDELT ones one after another (it asks callers
        # to space their requests, and the fetcher does the waiting).
        rss = [f for f in todo if f.format != "gdelt"]
        slow = [f for f in todo if f.format == "gdelt"]
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="news-read") as pool:
            answers = list(pool.map(read, rss))
        answers += [read(f) for f in slow]
        for feed, got in answers:
            if isinstance(got, NewsUnavailable):
                self._failed_until[feed.key] = now + COOL_DOWN_MS
                result.errors.append(str(got))
                log.info("News feed %s failed: %s", feed.key, got)
                continue
            self._last[feed.key] = now
            result.feeds += 1
            result.new += self._store(feed, got, matcher, now)
        with self.ctx.db.session() as s:
            s.execute(delete(NewsItem).where(NewsItem.published_at < now - KEEP_MS))
            s.execute(
                delete(NewsItem).where(
                    NewsItem.market.is_(None), NewsItem.published_at < now - KEEP_WORLD_MS
                )
            )
        text = f"{result.feeds} feeds read, {result.new} new, {len(result.errors)} failed"
        if result.errors and not result.feeds:
            act.failed(text, errors=result.errors[:5])
        else:
            act.done(text, errors=result.errors[:5])
        return result

    def _store(self, feed: Feed, items: list[RawItem], matcher: relevance.Matcher, now: int) -> int:
        # Read and match every headline first: the database is written in one short step, so
        # other parts of Agora never wait on it (D-102).
        market = feed.market.value if feed.market else None
        prepared = []
        for it in items:
            # a market's own feed links only that market's stocks (D-179)
            ids = matcher.find(f"{it.title} {it.summary}", market)
            if feed.instrument_id is not None:
                ids.add(feed.instrument_id)
            prepared.append((it, uid_for(it.title), ids))
        known: set[str] = set()
        with self.ctx.db.session() as s:
            known = set(
                s.scalars(select(NewsItem.uid).where(NewsItem.uid.in_([u for _, u, _ in prepared])))
            )
        fresh = {
            uid: (
                topics.classify(it.title, it.summary, market),
                sentiment.headline_score(it.title, it.summary),
            )
            for it, uid, _ in prepared
            if uid not in known
        }
        new = 0
        with self._write, self.ctx.db.session() as s:
            for it, uid, ids in prepared:
                row = s.scalar(select(NewsItem).where(NewsItem.uid == uid))
                if row is None:
                    read, mood = fresh.get(uid) or (
                        topics.classify(it.title, it.summary, market),
                        sentiment.headline_score(it.title, it.summary),
                    )
                    row = NewsItem(
                        uid=uid,
                        source=feed.key.split(":")[0],
                        market=market,
                        title=it.title,
                        summary=it.summary,
                        link=it.link,
                        publisher=it.publisher,
                        published_at=min(it.published_at, now),
                        fetched_at=now,
                        sentiment=mood,
                        topics=",".join(read.topics),
                        severity=read.severity,
                        impact=read.impact,
                        scope=read.scope,
                    )
                    s.add(row)
                    s.flush()
                    new += 1
                have = set(
                    s.scalars(select(NewsLink.instrument_id).where(NewsLink.news_id == row.id))
                )
                for iid in ids - have:
                    s.add(NewsLink(news_id=row.id, instrument_id=iid))
        return new

    def ensure_fresh(self, feeds: list[Feed]) -> bool:
        """Start a background refresh if any feed is stale; True while one is running."""
        if not self.enabled():
            return False
        now = self.ctx.clock.now_ms()
        stale = [
            f
            for f in feeds
            if now - self._last.get(f.key, 0) >= self.stale_ms(f)
            and self._failed_until.get(f.key, 0) <= now
        ]
        key = "|".join(sorted(f.key for f in stale))
        with self._lock:
            if not stale:
                return bool(self._inflight)
            if key in self._inflight:
                return True
            self._inflight.add(key)

        def run() -> None:
            try:
                self.refresh(stale)
            except Exception:  # the news must never break anything else
                log.exception("News refresh failed")
            finally:
                with self._lock:
                    self._inflight.discard(key)

        try:
            self._pool.submit(run)
        except RuntimeError:  # Agora is stopping: its workers are gone, nothing to refresh
            with self._lock:
                self._inflight.discard(key)
            return False
        return True

    # ------------------------------------------------------------ reading saved news

    def _backfill(self, s: Any) -> None:
        """Classify rows saved before migration 0005 (once; new rows are classified when
        they are saved), and read the last ``REREAD_DAYS`` of headlines again whenever the
        classifier's word lists changed (``topics.VERSION``): each fix to the reading of far-away
        news (D-173) had to be pushed into the saved stories by hand, and until then the gauge
        kept the old, wrong reading."""
        if getattr(self, "_backfilled", False):
            return
        row = s.get(SettingRow, TOPICS_VERSION_KEY)
        stale = row is None or row.value != topics.VERSION
        since = self.ctx.clock.now_ms() - REREAD_DAYS * 86_400_000
        q = select(NewsItem).where(
            or_(NewsItem.severity.is_(None), NewsItem.published_at >= since)
            if stale
            else NewsItem.severity.is_(None)
        )
        rows = s.scalars(q).all()
        for r in rows:
            read = topics.classify(r.title, r.summary or "", r.market)
            r.topics, r.severity, r.impact = ",".join(read.topics), read.severity, read.impact
            r.scope = read.scope
        if stale:
            now = self.ctx.clock.now_ms()
            if row is None:
                s.add(SettingRow(key=TOPICS_VERSION_KEY, value=topics.VERSION, updated_at=now))
            else:
                row.value, row.updated_at = topics.VERSION, now
            log.info("Read %d saved headlines again with the new news reading", len(rows))
        s.flush()
        self._relink(s)
        self._backfilled = True

    def _relink(self, s: Any) -> None:
        """Link the last ``REREAD_DAYS`` of saved headlines to their stocks again when the
        matching rules changed (``relevance.version()``, D-179): wrong links were what put a
        Dollar General lawsuit on an oil fund and blocked its trades. A per-stock feed's link
        (Google News or Yahoo for that company) is kept."""
        row = s.get(SettingRow, LINKS_VERSION_KEY)
        want = relevance.version()
        if row is not None and row.value == want:
            return
        matcher = self._matcher_for()
        since = self.ctx.clock.now_ms() - REREAD_DAYS * 86_400_000
        items = s.scalars(select(NewsItem).where(NewsItem.published_at >= since)).all()
        dropped = added = 0
        for it in items:
            ids = matcher.find(f"{it.title} {it.summary}", it.market)
            have = set(s.scalars(select(NewsLink.instrument_id).where(NewsLink.news_id == it.id)))
            own_feed = it.source in STOCK_FEED_SOURCES
            for iid in have - ids:
                if own_feed:
                    continue
                s.execute(
                    delete(NewsLink).where(NewsLink.news_id == it.id, NewsLink.instrument_id == iid)
                )
                dropped += 1
            for iid in ids - have:
                s.add(NewsLink(news_id=it.id, instrument_id=iid))
                added += 1
        now = self.ctx.clock.now_ms()
        if row is None:
            s.add(SettingRow(key=LINKS_VERSION_KEY, value=want, updated_at=now))
        else:
            row.value, row.updated_at = want, now
        s.flush()
        log.info(
            "Linked saved headlines to stocks again: %d links dropped, %d added", dropped, added
        )

    def latest(
        self,
        market: Market | None = None,
        instrument_id: int | None = None,
        hours: int = 72,
        limit: int = 30,
        *,
        world: int | None = 3,
        scope: str | None = None,
        group: str | None = None,
        topic: str | None = None,
        q: str | None = None,
        min_severity: int = 0,
        since: int | None = None,
    ) -> list[dict[str, Any]]:
        """Saved headlines, newest first. For a market: its own news plus world news of
        at least ``world`` severity (``None`` = no world news). ``scope``, ``group``,
        ``topic``, ``q`` (words in the title) and ``min_severity`` narrow it down."""
        since = since if since is not None else self.ctx.clock.now_ms() - hours * 3_600_000
        with self.ctx.db.session() as s:
            self._backfill(s)
            qry = select(NewsItem).where(NewsItem.published_at >= since)
            if instrument_id is not None:
                qry = qry.join(NewsLink, NewsLink.news_id == NewsItem.id).where(
                    NewsLink.instrument_id == instrument_id
                )
            elif market is not None:
                own = (NewsItem.market == market.value) | (NewsItem.scope == market.value)
                if world is not None:
                    own = own | ((NewsItem.scope == "WORLD") & (NewsItem.severity >= world))
                qry = qry.where(own)
            if scope:
                qry = qry.where(NewsItem.scope == scope)
            if min_severity:
                qry = qry.where(NewsItem.severity >= min_severity)
            if topic:
                qry = qry.where(NewsItem.topics.like(f"%{topic}%"))
            if group:
                keys = [t.key for t in topics.TOPICS if t.group == group]
                qry = qry.where(_first_topic_in(keys))
            if q:
                for word in q.split()[:5]:
                    qry = qry.where(NewsItem.title.ilike(f"%{word}%"))
            rows = s.scalars(qry.order_by(NewsItem.published_at.desc()).limit(limit)).all()
            ids = [r.id for r in rows]
            links: dict[int, list[str]] = {}
            if ids:
                for nid, sym in s.execute(
                    select(NewsLink.news_id, Instrument.symbol)
                    .join(Instrument, Instrument.id == NewsLink.instrument_id)
                    .where(NewsLink.news_id.in_(ids))
                ):
                    links.setdefault(nid, []).append(sym)
            return [_public(r, sorted(links.get(r.id, []))) for r in rows]

    def risk(self, market: Market | None) -> dict[str, Any]:
        """The news risk gauge for a market (``None`` = the world), from saved headlines."""
        now = self.ctx.clock.now_ms()
        key = (market.value if market else "WORLD", now // 60_000)
        hit = self._risk_cache.get(key[0])
        if hit is not None and hit[0] == key[1]:
            return hit[1]
        items = self.latest(None, hours=36, limit=1000, world=None, min_severity=2)
        g = risk.gauge(items, market.value if market else None, now)
        g = risk.with_fear(g, self._fear(market, now))
        self._risk_cache[key[0]] = (key[1], g)
        return g

    def _fear(self, market: Market | None, now: int) -> tuple[str, float, float] | None:
        """The market's fear gauge: its name, latest close, and its usual level (D-233)."""
        code, symbol = ("IN", "INDIAVIX") if market is Market.IN else ("US", "VIX")
        with self.ctx.db.session() as s:
            inst = find_instrument(s, Market(code), symbol)
            if inst is None:
                return None
            closes = list(
                s.scalars(
                    select(Candle.close)
                    .where(
                        Candle.instrument_id == inst.id,
                        Candle.timeframe == "1d",
                        Candle.ts >= now - risk.FEAR_DAYS * 86_400_000,
                    )
                    .order_by(Candle.ts)
                )
            )
        if len(closes) < 10:
            return None
        return symbol, float(closes[-1]), float(statistics.median(closes))

    def alert(self, instrument_id: int) -> dict[str, Any]:
        """critical / negative / positive / quiet, from the stock's own recent headlines."""
        items = self.latest(instrument_id=instrument_id, hours=48, limit=50)
        return risk.stock_alert(items, self.ctx.clock.now_ms())

    def mood(self, instrument_id: int, hours: int = 72) -> dict[str, Any]:
        """Recency-weighted average sentiment of a stock's headlines (half-life 24 h)."""
        now = self.ctx.clock.now_ms()
        items = self.latest(instrument_id=instrument_id, hours=hours, limit=100)
        if not items:
            return {"score": 0.0, "count": 0, "tone": "quiet"}
        w = [math.exp(-(now - i["published_at"]) * math.log(2) / HALF_LIFE_MS) for i in items]
        score = sum(wi * i["sentiment"] for wi, i in zip(w, items, strict=True)) / sum(w)
        return {"score": round(score, 3), "count": len(items), "tone": tone(score)}

    def instrument(self, instrument_id: int) -> InstrumentRef | None:
        with self.ctx.db.session() as s:
            return get_instrument(s, instrument_id)

    def market_instruments(self, market: Market) -> list[InstrumentRef]:
        with self.ctx.db.session() as s:
            return data_service.default_symbols(s, market)


def tone(score: float) -> str:
    if score >= 0.2:
        return "positive"
    if score <= -0.2:
        return "negative"
    return "neutral"


def _first_topic_in(keys: list[str]) -> ColumnElement[bool]:
    """The item's main topic (the first in its list) is one of ``keys``."""
    return or_(*[or_(NewsItem.topics == k, NewsItem.topics.like(f"{k},%")) for k in keys])


def _public(r: NewsItem, symbols: list[str]) -> dict[str, Any]:
    keys = [k for k in (r.topics or "").split(",") if k]
    main = topics.BY_KEY.get(keys[0]) if keys else None
    read = topics.classify(r.title, r.summary or "", r.market) if keys else None
    return {
        "id": r.id,
        "title": r.title,
        "summary": r.summary,
        "link": r.link,
        "publisher": r.publisher,
        "source": r.source,
        "published_at": r.published_at,
        "sentiment": r.sentiment,
        "tone": tone(r.sentiment),
        "symbols": symbols,
        "topics": keys,
        "topic_labels": [topics.label(k) for k in keys],
        "group": main.group if main else None,
        "severity": int(r.severity or 0),
        "impact": float(r.impact or 0.0),
        "scope": r.scope or (r.market or "WORLD"),
        "sectors": read.sectors if read else {},
        "calming": bool(read.calming) if read else False,
    }
