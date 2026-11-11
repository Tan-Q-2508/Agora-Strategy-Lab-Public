"""Kairos's knowledge pack covers everything Agora can compute or trade (Phase 10.7):
each indicator, candlestick, chart pattern, setup, template and news topic has a section
whose tags name it, and searching for it by name finds that section."""

from __future__ import annotations

import re

import pytest

from backend.analysis import candles, chart_patterns, setups
from backend.indicators.catalog import INDICATORS
from backend.kairos import knowledge
from backend.news import topics
from backend.strategy.templates import TEMPLATES

TAGS = {t.lower() for s in knowledge.sections() for t in s.tags}


def _base(key: str) -> str:
    return key.removesuffix("_bull").removesuffix("_bear")


COVERED = [
    *[("indicator", k) for k in INDICATORS],
    *[("candle", k) for k in candles.INFO],
    *[("pattern", k) for k in chart_patterns.NAMES],
    *[("setup", k) for k in setups.INFO],
    *[("template", k) for k in TEMPLATES],
]
# The first-generation sections (Phase 9) name a few things by words rather than keys.
OLD_WORDS = {
    "sma": "sma", "ema": "ema", "wma": "wma", "macd": "macd", "bollinger": "bollinger",
    "atr": "atr", "adx": "adx", "stochastic": "stochastic", "cci": "cci", "vwap": "vwap",
    "supertrend": "supertrend", "donchian": "donchian", "keltner": "keltner", "obv": "obv",
    "roc": "roc", "highest": "donchian", "lowest": "donchian", "high_52w": "52",
    "low_52w": "52", "prev_day": "levels", "opening_range": "opening", "dema": "dema",
    "tema": "tema", "hma": "hma", "vwma": "vwma", "kama": "kama", "ichimoku": "ichimoku",
    "psar": "parabolic", "mfi": "mfi", "williams_r": "williams", "aroon": "aroon",
    "cmf": "cmf", "stoch_rsi": "stoch", "pivots": "pivot", "rsi": "rsi",
}  # fmt: skip


@pytest.mark.parametrize(("kind", "key"), COVERED, ids=[f"{k}:{v}" for k, v in COVERED])
def test_every_thing_kairos_computes_has_a_playbook_section(kind: str, key: str) -> None:
    words = {key, _base(key), OLD_WORDS.get(key, key)}
    words |= {w for w in key.split("_") if len(w) > 4} if kind in ("candle", "template") else set()
    assert words & TAGS, f"no knowledge section is tagged for {kind} '{key}'"


@pytest.mark.parametrize("topic", [t.key for t in topics.TOPICS])
def test_every_news_topic_is_explained(topic: str) -> None:
    label = topics.BY_KEY[topic].label
    found = knowledge.search(label, k=3, min_score=0.5)
    assert found, f"nothing in the playbook about {label}"


@pytest.mark.parametrize(
    ("question", "title_words"),
    [
        ("what is a gartley pattern", "gartley"),
        ("explain the bat harmonic", "bat"),
        ("what is the connors rsi", "connors"),
        ("how does the turtle trading system work", "turtle"),
        ("what is wyckoff accumulation", "wyckoff"),
        ("elliott wave theory", "elliott"),
        ("what happens to markets when a war starts", "geopolitical"),
        ("how do rate hikes affect stocks", "central banks"),
        ("what does a falling rupee mean", "rupee"),
        ("when should kairos pull out of the market", "damage control"),
        ("what does Kairos do when the news is bad", "news guard"),
        ("what is a hikkake", "hikkake"),
        ("three line strike", "three-line strike"),
        ("what is the choppiness index", "choppiness"),
        ("india circuit breaker rules", "circuit breakers in india"),
        ("what is the ichimoku cloud strategy", "ichimoku"),
        ("what is smart money concepts order block", "smart money"),
    ],
)
def test_questions_find_the_right_section(question: str, title_words: str) -> None:
    found = knowledge.search(question, k=3)
    assert found, question
    assert any(title_words in s.title.lower() for s in found), [s.title for s in found]


def test_the_pack_is_big_and_well_formed() -> None:
    secs = knowledge.sections()
    assert len(secs) >= 200
    for s in secs:
        assert s.tags, f"section '{s.title}' has no tags line"
        assert 80 <= len(s.body) <= 2600, (s.title, len(s.body))
    titles = [s.title for s in secs]
    assert len(titles) == len(set(titles)), "two sections share a title"


@pytest.mark.parametrize(
    ("question", "title_words"),
    [
        ("what is an iron condor", "iron condor"),
        ("explain theta decay", "theta"),
        ("what is max pain", "max pain"),
        ("nifty lot size", "lot sizes"),
        ("how much stt on options", "stt"),
        ("what is the put call ratio", "put-call ratio"),
        ("long buildup open interest", "open interest"),
        ("how many f&o traders lose money sebi study", "sebi studies"),
        ("what is iv crush", "vega"),
        ("pattern day trader rule", "day-trading rule"),
        ("why do my trades fail", "why trades fail"),
        ("what are kairos's predicted candles", "predicted candles"),
        ("kairos trade check skip bad trades", "trade check"),
    ],
)
def test_fno_and_learning_questions_find_the_right_section(question: str, title_words: str) -> None:
    found = knowledge.search(question, k=3)
    assert any(title_words in s.title.lower() for s in found), [s.title for s in found]


def test_every_option_strategy_has_a_playbook_section() -> None:
    from backend.analysis.options import STRATEGIES

    for key in STRATEGIES:
        assert key in TAGS, f"no knowledge section is tagged for option strategy '{key}'"


@pytest.mark.parametrize(
    ("question", "title_words"),
    [
        ("how does warren buffett invest", "buffett"),
        ("what would druckenmiller do now", "druckenmiller"),
        ("rakesh jhunjhunwala titan", "jhunjhunwala"),
        ("jim simons renaissance quant", "simons"),
        ("what do the great traders have in common", "great traders"),
    ],
)
def test_great_traders_are_in_the_playbook(question: str, title_words: str) -> None:
    """PROGRESS 25.50: the great traders' and investors' methods, for Kairos to draw on."""
    found = knowledge.search(question)
    assert any(title_words in s.title.lower() for s in found), [s.title for s in found]


def test_metis_has_the_legends_as_testable_rules() -> None:
    from backend.metis import library

    found = library.search("minervini breakout tight range")
    assert any("minervini" in s.title.lower() for s in found)


def test_asking_kairos_to_search_the_web_gets_the_web_tools() -> None:
    """D-194: the router's "web" pattern held backspace characters instead of word boundaries
    (since D-127), so "check the web" never offered the web tools."""
    from backend.kairos import tools

    assert re.search(tools.GROUP_WORDS["web"], "check the web for this")
    assert not any(chr(8) in rx for rx in tools.GROUP_WORDS.values())
