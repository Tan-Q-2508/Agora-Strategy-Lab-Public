"""Real-network news checks (Phase 10). Skipped by default; Settings → Diagnostics runs them on
the laptop. They confirm the world feeds and GDELT still answer in the formats Agora reads."""

from __future__ import annotations

import time

import pytest

from backend.core.clock import SystemClock
from backend.news.feeds import WORLD_FEEDS
from backend.news.fetch import HttpFetcher, NewsUnavailable
from backend.news.topics import classify

pytestmark = pytest.mark.live


def test_world_news_feeds() -> None:
    f = HttpFetcher(SystemClock())
    rss = [x for x in WORLD_FEEDS if x.format == "rss"]
    ok = 0
    for feed in rss:
        try:
            items = f.fetch(feed)
        except NewsUnavailable:
            continue
        ok += bool(items)
    # most world feeds must answer; one or two being down is normal
    assert ok >= len(rss) - 3, f"only {ok} of {len(rss)} world news feeds answered"


def test_gdelt_news_api() -> None:
    f = HttpFetcher(SystemClock())
    gdelt = next(x for x in WORLD_FEEDS if x.format == "gdelt")
    for attempt in range(3):  # GDELT says "busy" (429) when called too often; wait and retry
        try:
            items = f.fetch(gdelt)
            break
        except NewsUnavailable:
            if attempt == 2:
                raise
            time.sleep(20)
    assert items and all(i.title and i.link for i in items)
    assert any(classify(i.title).topics for i in items)  # headlines read as market topics
