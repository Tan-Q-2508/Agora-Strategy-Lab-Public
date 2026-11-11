"""GDELT rests after refusing (D-128) instead of being asked again at once."""

from __future__ import annotations

import httpx
import pytest

from backend.fakes.clock import FakeClock
from backend.news.feeds import Feed, gdelt_url
from backend.news.fetch import HttpFetcher, NewsUnavailable


def test_gdelt_rests_after_a_429() -> None:
    calls: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(429)

    f = HttpFetcher(FakeClock(0), transport=httpx.MockTransport(answer))
    f.pace_s = {}
    feed = Feed("gdelt_test", "GDELT · test", gdelt_url("india"), None, "world", format="gdelt")
    with pytest.raises(NewsUnavailable, match="429"):
        f.fetch(feed)
    with pytest.raises(NewsUnavailable, match="resting"):
        f.fetch(feed)
    assert len(calls) == 1
