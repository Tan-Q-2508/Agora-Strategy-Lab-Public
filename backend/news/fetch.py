"""Reading feeds: the real HTTP reader and a fake for tests and practice mode (D-05)."""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from backend.core.clock import Clock, ms_to_dt
from backend.news.feeds import GDELT_HOST, Feed, RawItem, parse_gdelt, parse_rss

TIMEOUT_S = 10.0
SLOW_HOSTS = {GDELT_HOST: 25.0}  # GDELT often takes 10–20 s to answer (D-128)
REST_FIRST_S = 15 * 60.0  # after a refusal (429) or a time-out, leave the host alone this long
REST_MAX_S = 2 * 3600.0  # doubling each time, up to this
USER_AGENT = "Mozilla/5.0 (Agora personal research; local app)"


class NewsUnavailable(Exception):
    """A feed couldn't be read (plain-English message)."""


class NewsFetcher(Protocol):
    name: str

    def fetch(self, feed: Feed) -> list[RawItem]: ...


class HttpFetcher:
    """Reads RSS feeds and GDELT searches. GDELT asks callers to wait 5 seconds between
    requests, so calls to it are spaced ``pace_s[host]`` seconds apart (this runs on the
    news worker thread, never on a screen's request)."""

    name = "rss"

    def __init__(self, clock: Clock, transport: httpx.BaseTransport | None = None) -> None:
        self.clock = clock
        self.transport = transport
        self.pace_s: dict[str, float] = {GDELT_HOST: 6.0}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        # hosts that refused or timed out rest before the next try (D-128): asking again at
        # once only extends a rate limit
        self._rest_until: dict[str, float] = {}
        self._rest_s: dict[str, float] = {}

    def _resting(self, host: str) -> float:
        with self._lock:
            return max(0.0, self._rest_until.get(host, 0.0) - time.monotonic())

    def _refused(self, host: str) -> None:
        with self._lock:
            gap = min(self._rest_s.get(host, REST_FIRST_S / 2) * 2, REST_MAX_S)
            self._rest_s[host] = gap
            self._rest_until[host] = time.monotonic() + gap

    def _answered(self, host: str) -> None:
        with self._lock:
            self._rest_s.pop(host, None)
            self._rest_until.pop(host, None)

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        gap = self.pace_s.get(host, 0.0)
        if gap <= 0:
            return
        with self._lock:
            wait = self._last.get(host, -1e9) + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def fetch(self, feed: Feed) -> list[RawItem]:
        host = urlsplit(feed.url).hostname or ""
        rest = self._resting(host) if host in SLOW_HOSTS else 0.0
        if rest > 0:
            raise NewsUnavailable(
                f"{feed.label} is resting for {rest / 60:.0f} more minutes after refusing requests."
            )
        self._wait_turn(feed.url)
        try:
            with httpx.Client(
                timeout=SLOW_HOSTS.get(host, TIMEOUT_S),
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
                transport=self.transport,
            ) as c:
                r = c.get(feed.url)
        except httpx.HTTPError as exc:
            if host in SLOW_HOSTS:
                self._refused(host)
            raise NewsUnavailable(f"Couldn't reach {feed.label}.") from exc
        if r.status_code != 200:
            if host in SLOW_HOSTS and r.status_code in (429, 503):
                self._refused(host)
            raise NewsUnavailable(f"{feed.label} answered {r.status_code}.")
        if host in SLOW_HOSTS:
            self._answered(host)
        try:
            if feed.format == "gdelt":
                return parse_gdelt(r.content, now_ms=self.clock.now_ms())
            return parse_rss(
                r.content, default_publisher=feed.label.split(" · ")[0], now_ms=self.clock.now_ms()
            )
        except Exception as exc:  # a broken feed must never break Agora
            raise NewsUnavailable(f"{feed.label} sent something that isn't a news feed.") from exc


_GOOD = (
    "{name} beats estimates as profit rises",
    "Analysts upgrade {name}, see strong growth ahead",
    "{name} shares rally after a large new order",
    "{name} announces share buyback",
)
_BAD = (
    "{name} misses estimates; shares slide",
    "{name} faces probe over accounting concerns",
    "Brokerage downgrades {name} on weak demand",
    "{name} profit falls as costs rise",
)
_NEUTRAL = (
    "{name} to hold its annual general meeting next month",
    "What to watch in {name} this week",
)
_MARKET = (
    "Markets end higher as banks and IT stocks gain",
    "Benchmark indices slip as oil prices rise",
    "Central bank keeps rates unchanged; signals caution",
    "Foreign investors turn buyers for a third straight session",
    "Global stocks mixed ahead of inflation data",
    "Reliance Industries and Infosys lead gains; Apple and Nvidia firm in US trade",
)
# World practice headlines: a calm-to-watchful mix (one practice publisher, so nothing is
# "confirmed by several sources" and the risk gauge stays below "elevated").
_WORLD = (
    "Oil prices rise as OPEC+ extends output cuts",
    "Border tensions flare between two neighbours; markets watch closely",
    "Ceasefire talks make progress, officials say",
    "Global stocks mixed ahead of US inflation data",
    "Rupee steadies as forex reserves rise",
    "Trade talks between the US and China resume next week",
    "Cyclone warning issued for the eastern coast",
    "Federal Reserve holds interest rates steady",
)


class FakeFetcher:
    """Practice headlines, the same for the same feed and day: a mix of good, bad and
    neutral news so sentiment, matching and the screens can be exercised offline."""

    name = "fake"

    def __init__(self, clock: Clock, names: dict[str, str] | None = None) -> None:
        self.clock = clock
        self.names = names or {}

    def fetch(self, feed: Feed) -> list[RawItem]:
        now = self.clock.now_ms()
        day = ms_to_dt(now, UTC).date().isoformat()
        out: list[RawItem] = []
        if feed.kind == "market":
            for k, text in enumerate(_MARKET):
                out.append(self._item(feed, text, now - k * 3_600_000, k))
            return out
        if feed.kind == "world":
            for k, text in enumerate(_WORLD):
                out.append(self._item(feed, text, now - (k * 2 + 1) * 3_600_000, k))
            return out
        sym = feed.key.split(":", 1)[-1]
        name = self.names.get(sym, sym)
        seed = int(hashlib.sha256(f"{sym}:{day}".encode()).hexdigest(), 16)
        every = [*_GOOD, *_BAD, *_NEUTRAL]
        start = seed % len(every)
        step = 3 if len(every) % 3 else 5  # coprime with the list length: five different ones
        for k in range(5):
            text = every[(start + k * step) % len(every)].format(name=name)
            out.append(self._item(feed, text, now - (k * 7 + 1) * 3_600_000, k))
        return out

    def _item(self, feed: Feed, title: str, ts: int, k: int) -> RawItem:
        slug = hashlib.sha1(f"{feed.key}{title}".encode()).hexdigest()[:12]
        return RawItem(
            title, f"https://example.invalid/practice-news/{slug}", "", "Practice news", ts
        )
