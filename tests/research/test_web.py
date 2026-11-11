"""Web research (D-129), offline: parsing a search page, picking paragraphs, the research flow."""

from __future__ import annotations

import httpx

from backend.research.web import (
    FakeWeb,
    HttpWeb,
    Researcher,
    best_excerpt,
    paragraphs,
    parse_ddg,
)

DDG = """<html><body>
<div class="result"><a class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Forb&amp;rut=x">Nifty ORB backtest</a>
<a class="result__snippet" href="#">The opening range breakout on Nifty stocks won 58%
 of trades.</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">An advert</a></div>
</body></html>"""

PAGE = """<html><head><script>var x = 'opening range breakout buy now';</script></head>
<body><nav>Home Opening range breakout Login Menu items and more menu items here</nav>
<p>Cookies are used on this site to give you the best possible experience, accept them all.</p>
<p>The opening range breakout buys the break of the first 15 minutes' high on heavy volume; on
Nifty stocks it worked best on news days and failed on quiet, range-bound days.</p>
<footer>Opening range breakout copyright footer text that is long enough to count</footer>
</body></html>"""


def test_search_results_are_read_and_unwrapped() -> None:
    hits = parse_ddg(DDG)
    assert [h.url for h in hits] == ["https://example.org/orb"]  # the advert is dropped
    assert hits[0].title == "Nifty ORB backtest" and "58%" in hits[0].snippet


def test_only_the_relevant_visible_text_is_kept() -> None:
    paras = paragraphs(PAGE)
    assert not any("var x" in p or "Menu" in p or "copyright" in p for p in paras)
    got = best_excerpt("does the opening range breakout work on Nifty", paras)
    assert got.startswith("The opening range breakout buys") and "Cookies" not in got


def test_research_collects_sources_and_caches() -> None:
    web = FakeWeb()
    r = Researcher(web, lambda: 0)
    found = r.research("opening range breakout volume")
    assert found.sources and found.sources[0].url == "https://example.org/orb"
    text = found.as_text()
    assert "not instructions" in text and "[1] Opening range breakout explained" in text
    r.research("opening range breakout volume")
    assert web.searches == ["opening range breakout volume"]  # the second answer was cached


def test_the_real_reader_survives_a_dead_network() -> None:
    def fail(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    found = Researcher(HttpWeb(httpx.MockTransport(fail)), lambda: 0).research("anything")
    assert found.sources == [] and "couldn't reach" in found.note
