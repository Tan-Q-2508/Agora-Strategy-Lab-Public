"""The news guard (D-69): the rule table, the brain following it, the diary, and the rule
that it never touches backtests or replays."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from backend.backtest.run import run
from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.db.models import KairosJournal, NewsItem
from backend.kairos import brain
from backend.kairos import news_guard as ng
from tests.kairos.test_brain import spec

H = 3_600_000


def gauge(level: float, title: str = "Full-scale invasion begins") -> dict[str, Any]:
    from backend.news.risk import level_name

    return {"level": level, "name": level_name(level), "drivers": [{"title": title}]}


QUIET = {"state": "quiet"}


def no_move() -> float | None:
    return None


@pytest.mark.parametrize(
    ("mode", "level", "pnl", "expect"),
    [
        # calm: nothing
        ("protective", 10, 2.0, dict(block_long=False, exit_long=False, size_factor=1.0)),
        # D-211: severity alone never stops trading; watchful changes nothing …
        ("protective", 30, None, dict(block_long=False, size_factor=1.0)),
        # … elevated and severe halve new trades, longs and shorts alike, and block nothing
        ("protective", 60, -1.0, dict(block_long=False, block_short=False, size_factor=0.5)),
        ("protective", 80, 3.0, dict(block_long=False, block_short=False, exit_long=False)),
        # without the market's own fall, even 92 keeps a long (no panic exit)
        ("protective", 92, 3.0, dict(exit_long=False, size_factor=0.5)),
        ("cautious", 92, 3.0, dict(block_long=False, exit_long=False, size_factor=0.5)),
        # off: the news is ignored
        ("off", 99, -5.0, dict(block_long=False, exit_long=False, size_factor=1.0)),
    ],
)
def test_rule_table(mode: str, level: float, pnl: float | None, expect: dict[str, Any]) -> None:
    a = ng.advise(mode, gauge(level), QUIET, long_pnl_pct=pnl, move_pct=no_move)
    for k, v in expect.items():
        assert getattr(a, k) == v, (k, a)


def test_market_wide_news_needs_the_market_to_agree() -> None:
    """D-179: the gauge is read from headline words and has misread far-away and off-topic
    stories as crises; before market news closes a trade the market's own move must agree."""
    falling = ng.advise("protective", gauge(60), QUIET, long_pnl_pct=-1.0, move_pct=lambda: -0.8)
    assert falling.exit_long and "-0.8%" in falling.reason
    rising = ng.advise("protective", gauge(60), QUIET, long_pnl_pct=-1.0, move_pct=lambda: 0.3)
    assert not rising.block_long and not rising.exit_long and rising.size_factor == 0.5
    severe = ng.advise("protective", gauge(80), QUIET, long_pnl_pct=2.0, move_pct=lambda: -1.8)
    assert severe.exit_long and "-1.8%" in severe.reason
    held = ng.advise("protective", gauge(95), QUIET, long_pnl_pct=2.0, move_pct=lambda: -0.3)
    assert not held.exit_long  # a winning long stays while the market holds
    # a company's own red flag needs no confirmation
    crit = {"state": "critical", "flag": "fraud", "headline": "Fraud probe at the company"}
    assert ng.advise("protective", gauge(5), crit, long_pnl_pct=4.0, move_pct=lambda: 1.0).exit_long


def sector_gauge(level: float) -> dict[str, Any]:
    """Crude oil spikes: oil marketers and paint makers hurt, oil producers helped."""
    return {
        **gauge(level, "Crude jumps 8% as supply fears grow"),
        "drivers": [
            {
                "title": "Crude jumps 8% as supply fears grow",
                "weight": 1.2,
                "sectors": {"Oil producers": 1, "Oil marketing": -1, "Paints": -1},
            }
        ],
        "sector_tilt": {"Oil producers": 1.2, "Oil marketing": -1.2, "Paints": -1.2},
    }


def _sector(mode: str, level: float, pnl: float | None, sector: str) -> ng.Advice:
    return ng.advise(
        mode,
        sector_gauge(level),
        QUIET,
        long_pnl_pct=pnl,
        move_pct=no_move,
        exposure=frozenset({sector}),
    )


def test_news_that_helps_a_sector_is_an_opportunity_and_news_that_hurts_is_caution() -> None:
    """D-211, the user: some news hurts one part of the market and helps another; Kairos must
    be opportune on the positive side and cautious on the negative side."""
    helped = _sector("protective", 80, None, "Oil producers")
    assert helped.nudge == ng.NUDGE and helped.size_factor == 1.0 and not helped.block_long
    assert "helps Oil producers" in helped.reason and "Crude" in helped.reason
    hurt = _sector("protective", 80, -1.5, "Oil marketing")
    assert hurt.size_factor == 0.5 and hurt.exit_long and not hurt.block_long
    assert "hurts Oil marketing" in hurt.reason and "cut the loss" in hurt.reason
    winning = _sector("protective", 80, 2.0, "Paints")
    assert not winning.exit_long and winning.size_factor == 0.5
    cautious = _sector("cautious", 10, -3.0, "Paints")
    assert not cautious.exit_long and cautious.size_factor == 0.5


def test_calming_news_makes_kairos_readier_to_buy() -> None:
    calm = {**gauge(10, "Ceasefire agreed"), "calming": 0.9}
    calm["drivers"] = [{"title": "Ceasefire agreed", "weight": -0.9}]
    a = ng.advise("protective", calm, QUIET, long_pnl_pct=None, move_pct=no_move)
    assert a.nudge == ng.NUDGE / 2 and "Ceasefire" in a.reason


def test_company_news() -> None:
    crit = {"state": "critical", "flag": "fraud", "headline": "Fraud probe at the company"}
    a = ng.advise("protective", gauge(5), crit, long_pnl_pct=4.0, move_pct=no_move)
    assert a.block_long and a.exit_long and "fraud" in a.reason
    assert not ng.advise("cautious", gauge(5), crit, long_pnl_pct=4.0, move_pct=no_move).exit_long
    neg = {"state": "negative", "headline": "Weak demand"}
    b = ng.advise("protective", gauge(5), neg, long_pnl_pct=None, move_pct=no_move)
    assert not b.block_long and b.size_factor == 0.5 and b.nudge == -ng.NUDGE
    assert ng.advise("protective", gauge(5), neg, long_pnl_pct=-1.2, move_pct=no_move).exit_long
    pos = {"state": "positive", "headline": "Wins a record order"}
    c = ng.advise("protective", gauge(5), pos, long_pnl_pct=None, move_pct=no_move)
    assert c.nudge == ng.NUDGE and not c.block_long


def test_stock_profiles_map_onto_news_sectors() -> None:
    from backend.news.exposure import names_for

    assert names_for("Energy", "Refineries", ["refiner"]) >= {"Energy", "Oil marketing"}
    assert "Paints" in names_for("Materials", "Paints & Varnishes", [])
    assert "Airlines" in names_for("Industrials", "Airlines", ["travel", "oil_user"])
    assert names_for("", "", []) == frozenset()


def test_gauge_adds_up_what_stories_do_to_sectors() -> None:
    from backend.news.risk import gauge as read_gauge

    now = 10 * H
    item = {
        "title": "Crude oil surges as OPEC cuts output",
        "summary": "",
        "published_at": now - H,
        "severity": 3,
        "impact": -0.6,
        "scope": "IN",
        "topics": ["oil"],
        "publisher": "A",
        "sectors": {"Oil producers": 1, "Oil marketing": -1},
    }
    g = read_gauge([item], "IN", now)
    assert g["sector_tilt"]["Oil producers"] > 0 > g["sector_tilt"]["Oil marketing"]
    assert g["drivers"][0]["sectors"] == {"Oil producers": 1, "Oil marketing": -1}
    # D-213: the guard's note quotes the story that moved the sector, never "()"
    assert g["sector_story"]["Oil marketing"] == item["title"]
    a = ng.advise(
        "protective",
        {**g, "drivers": []},
        QUIET,
        long_pnl_pct=None,
        move_pct=no_move,
        exposure=frozenset({"Oil marketing"}),
    )
    assert "Crude oil surges" in a.reason and "()" not in a.reason


class ScriptedGuard:
    """Stands in for the live guard inside a backtest, to watch the brain obey it."""

    def __init__(self, advice: ng.Advice) -> None:
        self.advice = advice
        self.acts: list[str] = []

    def advise(self, symbol: str, ts: int, pnl: float | None) -> ng.Advice:
        return self.advice

    def acted(self, symbol: str, action: str, advice: ng.Advice, day: str) -> None:
        self.acts.append(action)


def _with_guard(monkeypatch: pytest.MonkeyPatch, advice: ng.Advice) -> ScriptedGuard:
    guard = ScriptedGuard(advice)
    real = brain.compile_brain

    def compile_with_guard(d: Any, params: dict[str, float]) -> tuple[brain.Brain, int]:
        b, warm = real(d, params)
        b.news = guard
        return b, warm

    monkeypatch.setattr(brain, "compile_brain", compile_with_guard)
    return guard


def test_the_brain_obeys_the_guard(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = run(ctx.cache, spec(ctx, "IN", ["RELIANCE", "INFY"]))
    assert len(plain.trades) >= 5
    # blocked: no trade opens at all, and each skip is recorded
    guard = _with_guard(monkeypatch, ng.Advice(level=80, block_long=True, reason="test"))
    blocked = run(ctx.cache, spec(ctx, "IN", ["RELIANCE", "INFY"]))
    assert blocked.trades == [] and "skip" in guard.acts
    # pull out: every long is closed on the candle after it opens
    guard = _with_guard(monkeypatch, ng.Advice(level=95, exit_long=True, reason="test"))
    out = run(ctx.cache, spec(ctx, "IN", ["RELIANCE", "INFY"]))
    assert out.trades and all(t.bars_held <= 2 for t in out.trades if t.closed)
    assert "exit" in guard.acts


def test_a_desk_whose_entries_lost_trades_at_full_size(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-215, the user: "keep it at full size and never bench it"."""
    from types import SimpleNamespace

    plain = run(ctx.cache, spec(ctx, "IN", ["RELIANCE", "INFY"]))
    real = brain.compile_brain

    def compile_warned(d: Any, params: dict[str, float]) -> tuple[brain.Brain, int]:
        b, warm = real(d, params)
        b.judge_model = SimpleNamespace(active=False, stand_aside=True)
        return b, warm

    monkeypatch.setattr(brain, "compile_brain", compile_warned)
    warned = run(ctx.cache, spec(ctx, "IN", ["RELIANCE", "INFY"]))
    assert [(t.symbol, t.entry_ts, t.qty) for t in warned.trades] == [
        (t.symbol, t.entry_ts, t.qty) for t in plain.trades
    ]


def test_backtests_have_no_guard() -> None:
    from backend.strategy.compiler import compile_definition

    p = compile_definition(brain.definition("IN", ["TCS"]))
    assert p.brain is not None and p.brain.news is None


def _severe_news(ctx: AppContext) -> None:
    now = ctx.clock.now_ms()
    from backend.db.models import SettingRow
    from backend.news import service as news_service
    from backend.news import topics

    with ctx.db.session() as s:
        # these rows are read as stored, not again by today's classifier (D-178)
        s.add(SettingRow(key=news_service.TOPICS_VERSION_KEY, value=topics.VERSION, updated_at=now))
        for k, pub in enumerate("ABCDE"):
            s.add(
                NewsItem(
                    uid=f"inv{k}",
                    source="bbc_world",
                    market=None,
                    title="Full-scale invasion begins; oil prices soar",
                    summary="",
                    link=f"https://example.invalid/{k}",
                    publisher=pub,
                    published_at=now - H // 2,
                    fetched_at=now,
                    sentiment=-0.6,
                    topics="conflict",
                    severity=5,
                    impact=-0.9,
                    scope="WORLD",
                )
            )


def test_live_guard_reads_the_news_and_writes_the_diary(ctx: AppContext) -> None:
    _severe_news(ctx)
    now = ctx.clock.now_ms()
    guard = ng.NewsGuard(
        ctx,
        session_id=None,  # type: ignore[arg-type]
        market=Market.IN,
        instruments={"RELIANCE": 1},
        live_from=now - 86_400_000,
        bar_ms=Timeframe.D1.minutes * 60_000,
        move_pct=lambda: -2.0,
    )
    a = guard.advise("RELIANCE", now - 3_600_000, 1.5)
    assert a.name == "severe" and a.exit_long and not a.block_long and a.size_factor == 0.5
    guard.acted("RELIANCE", "exit", a, "2026-10-22")
    guard.acted("RELIANCE", "exit", a, "2026-10-22")  # once per stock, action and day
    with ctx.db.session() as s:
        notes = s.scalars(select(KairosJournal).where(KairosJournal.kind == "note")).all()
    expected = "News guard: selling RELIANCE at the next candle's open because"
    assert len(notes) == 1 and notes[0].text.startswith(expected)
    # a candle from before the desk went live, or long ago, is never judged on today's news
    assert guard.advise("RELIANCE", now - 30 * 86_400_000, 1.5) == ng.NEUTRAL


def test_guard_switch_and_news_off(ctx: AppContext, client: Any) -> None:
    _severe_news(ctx)
    now = ctx.clock.now_ms()
    guard = ng.NewsGuard(
        ctx, 1, Market.IN, {}, live_from=now, bar_ms=86_400_000, move_pct=lambda: None
    )
    assert client.put("/api/settings", json={"kairos.news_guard": "off"}).status_code == 200
    assert guard.advise("X", now - H, None) == ng.NEUTRAL
    client.put("/api/settings", json={"kairos.news_guard": "cautious"})
    a = guard.advise("X", now - H, 2.0)
    assert a.size_factor == 0.5 and not a.block_long and not a.exit_long
    bad = client.put("/api/settings", json={"kairos.news_guard": "panic"})
    assert bad.status_code == 422  # a plain-English "must be one of" error


def test_other_markets_news_doesnt_slow_a_market_thats_up() -> None:
    """D-198: on 6 Nov India's gauge read 84 on the US and Asian sell-off while the Nifty was up
    0.3%. Mostly foreign news + this market not falling: trade as usual (D-211); this market's
    own news, or a falling market, halves new trades and says why."""
    foreign = {**gauge(84), "home_share": 0.1}
    up = ng.advise(
        "protective", foreign, QUIET, long_pnl_pct=None, move_pct=no_move, home_move=lambda: 0.3
    )
    assert not up.block_long and up.size_factor == 1.0
    down = ng.advise(
        "protective", foreign, QUIET, long_pnl_pct=None, move_pct=no_move, home_move=lambda: -1.2
    )
    assert not down.block_long and down.size_factor == 0.5 and "-1.2% today" in down.reason
    home = {**gauge(84), "home_share": 0.8}
    mine = ng.advise(
        "protective", home, QUIET, long_pnl_pct=None, move_pct=no_move, home_move=lambda: 0.3
    )
    assert mine.size_factor == 0.5 and not mine.block_long


def test_falling_oil_helps_oil_users_and_many_small_stories_dont_add_up() -> None:
    """D-211, checked on the real 6 Nov news: "Oil Slides Below $100" read as oil going up, and
    122 small war mentions added up to Airlines −7.7 against a top story of 0.6."""
    from backend.news import topics
    from backend.news.risk import gauge as read_gauge

    down = topics.classify("Oil Slides Below $100 a Barrel", "", "IN")
    assert down.calming and down.sectors["Airlines"] == 1 and down.sectors["Oil producers"] == -1
    up = topics.classify("Oil prices surge as OPEC cuts output", "", "IN")
    assert not up.calming and up.sectors["Airlines"] == -1

    now = 10 * H
    story = {
        "summary": "",
        "published_at": now - H,
        "severity": 3,
        "impact": -0.6,
        "scope": "IN",
        "topics": ["conflict"],
        "sectors": {"Airlines": -1},
    }
    many = [
        {**story, "title": f"Story {k} about a far war", "publisher": f"P{k}"} for k in range(40)
    ]
    g = read_gauge(many, "IN", now)
    top = max(abs(d["weight"]) for d in g["drivers"])
    assert -top / (1 - 0.6) - 1e-6 <= g["sector_tilt"]["Airlines"] < 0  # at most 2.5× the top
    # a war named only in the summary (one severity lower) moves no sector
    faint = read_gauge([{**story, "severity": 2, "title": "Energy policy"}], "IN", now)
    assert "Airlines" not in faint["sector_tilt"]


def test_a_far_local_conflict_moves_no_sector() -> None:
    """D-213: the heaviest "war" story behind Airlines and Defence on 6 Nov was the Polisario
    warning about Western Sahara, a local conflict far from both markets (D-173)."""
    from backend.news import topics

    r = topics.classify(
        "The alternative to diplomacy is war: Polisario warns of risks after collapse of Western "
        "Sahara UN mission",
        "",
        "US",
    )
    assert r.severity <= topics.FAR_SEVERITY
    from backend.news.risk import gauge as read_gauge

    now = 10 * H
    item = {
        "title": "Polisario warns of war after collapse of Western Sahara UN mission",
        "summary": "",
        "published_at": now - H,
        "severity": 3,
        "impact": -0.7,
        "scope": "WORLD",
        "topics": ["conflict"],
        "publisher": "A",
        "sectors": {"Airlines": -1, "Defence": 1},
    }
    assert "Airlines" not in read_gauge([item], "US", now)["sector_tilt"]


def test_a_smaller_trade_is_smaller_even_when_the_cap_sets_the_size() -> None:
    """D-214: risk sizing with a close stop asks for more than the per-trade cap, so halving the
    risk changed nothing and "half size" trades were full size. The share comes after the cap."""
    from backend.engine.core import _size
    from backend.strategy.runtime import SizeSpec, StopRule

    stop = StopRule("percent", 2.0)
    full, _ = _size(SizeSpec("risk_percent", 1.0), 100.0, 1_000_000.0, stop, None, 10.0)
    half, _ = _size(SizeSpec("risk_percent", 1.0, 0.5), 100.0, 1_000_000.0, stop, None, 10.0)
    assert full == 1_000 and half == 500
