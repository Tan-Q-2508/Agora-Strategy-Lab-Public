"""The world desk (D-95, D-96): headlines → kinds of events, effects on sectors and stocks,
measured reactions by hand, learning from past and live events, and "why did it move?"."""

from __future__ import annotations

import json

import numpy as np
from sqlalchemy import select

from backend.context import AppContext
from backend.db.models import NewsItem, WorldEffect, WorldEvent
from backend.news import topics
from backend.world import engine
from backend.world import investigate as inv
from backend.world.history import EVENTS
from backend.world.scenarios import BY_KEY, SCENARIOS

HOUR = 3_600_000


def read(title: str) -> list[engine.Hit]:
    r = topics.classify(title)
    return engine.match(title, "", r.topics, r.severity, r.calming)


def test_headlines_are_recognised() -> None:
    assert read("Iran fires missiles at Israel, oil jumps")[0].scenario == "mideast_war"
    calm = read("Israel and Iran agree to a ceasefire after 12 days of war")
    assert calm and calm[0].scenario == "mideast_war" and calm[0].sign == -1
    assert read("Tanker attacked in the Strait of Hormuz")[0].scenario == "shipping_chokepoint"
    assert read("US slaps 50% tariffs on Indian goods")[0].scenario == "us_tariffs_india"
    assert read("RBI cuts repo rate by 25 basis points")[0].scenario == "rbi_cut"
    assert read("China retaliates with tariffs on US chips")[0].scenario == "us_china_trade"
    assert read("Chinese warships surround Taiwan in drills")[0].scenario == "taiwan_strait"
    assert read("Russian troops cross into Ukraine")[0].scenario == "russia_ukraine"
    assert not read("Infosys wins a large deal from a European bank")


def test_every_scenario_is_complete_and_history_points_at_real_scenarios() -> None:
    for s in SCENARIOS:
        assert s.chain and s.effects, s.key
        for market, effects in s.effects.items():
            assert market in ("IN", "US")
            assert all(-2 <= v <= 2 for v in effects.values()), s.key
    assert all(e.scenario in BY_KEY for e in EVENTS)
    assert len(EVENTS) >= 80


def test_blend_by_hand() -> None:
    assert engine.blend(-2, None) == -2.0
    # 3 measured events averaging +1.0% (1 unit) at 5 days: weight 3/6 → (−2 + 1) / 2
    assert engine.blend(-2, engine.Learned(3, 1.0)) == -0.5
    # capped at ±2 units however big the measured move
    assert engine.blend(0, engine.Learned(3, 10.0)) == 1.0


def test_effects_on_sectors_and_stocks() -> None:
    ev = engine.ActiveEvent("mideast_war", strength=20.0, sign=1.0)
    v = engine.view("IN", [ev], {})
    assert v.tilt < 0
    assert v.tags["omc"] < 0 < v.tags["oil_producer"]
    omc, why = v.stock("Energy", ["omc", "refiner"])
    producer, _ = v.stock("Energy", ["oil_producer"])
    assert omc < v.tilt < producer
    assert any("fuel retailers" in w for w in why)
    calm = engine.view("IN", [engine.ActiveEvent("mideast_war", 20.0, -1.0)], {})
    assert calm.tilt > 0 and calm.tags["omc"] > 0


def test_reactions_by_hand() -> None:
    lines = {
        "market": np.array([100.0, 98.0, 97.0, 99.0, 100.0, 101.0, 102.0]),
        "Energy": np.array([50.0, 52.0, 53.0, 54.0, 55.0, 55.0, 56.0]),
    }
    rx = engine.reactions(lines, base=0, horizons=(1, 5))
    assert rx["market"] == {1: -2.0, 5: 1.0}
    # Energy +4% on day 1 while the market fell 2%: +6% beyond the market
    assert rx["Energy"][1] == 6.0
    assert rx["Energy"][5] == round((55 / 50 - 1) * 100 - 1.0, 3)


def _move(pct: float = -2.6, target: str = "market") -> inv.Move:
    return inv.Move("IN", target, "the Nifty 50", "1d", 10 * HOUR, 20 * HOUR, pct, -3.4)


def test_a_war_headline_explains_a_fall() -> None:
    heads = [
        {
            "title": "Iran fires missiles at Israel; oil jumps",
            "published_at": 8 * HOUR,
            "severity": 4,
            "impact": -0.8,
            "scope": "WORLD",
            "topics": ["conflict", "energy"],
            "publisher": "Reuters",
        },
        {
            "title": "Iran strikes Israel in retaliation",
            "published_at": 9 * HOUR,
            "severity": 4,
            "impact": -0.8,
            "scope": "WORLD",
            "topics": ["conflict"],
            "publisher": "BBC",
        },
        {
            "title": "Titan opens 20 new stores",
            "published_at": 11 * HOUR,
            "severity": 1,
            "impact": 0.4,
            "scope": "IN",
            "topics": ["corporate"],
            "publisher": "Mint",
        },
    ]
    causes = inv.rank(_move(), heads, clues={"oil": (4.2, 3.0), "rupee": (-0.6, -2.1)})
    top = causes[0]
    assert top.key == "world:mideast_war" and top.sources == 2
    assert "oil rose 4.2%" in top.clues and "the rupee fell 0.6%" in top.clues
    assert inv.verdict(causes) == "world"
    text = inv.explain(_move(), causes, "on Mon 14 Apr")
    assert "War in the Middle East" in text and "It fits" in text


def test_contagion_and_unclear() -> None:
    causes = inv.rank(_move(), [], other_market=("The S&P 500", -2.4, -3.1))
    assert inv.verdict(causes) == "contagion"
    assert inv.verdict(inv.rank(_move(), [])) == "unclear"
    assert "No news explains it clearly" in inv.explain(_move(), [], "today")


def test_unusual_moves_by_hand() -> None:
    rng = np.random.default_rng(1)
    calm = 100 * np.cumprod(1 + rng.normal(0, 0.005, 80))
    assert inv.unusual(calm) is None
    shocked = np.r_[calm, calm[-1] * 0.97]
    got = inv.unusual(shocked)
    assert got is not None and got[0] == -3.0 and got[1] < -2.5


def _news(ctx: AppContext, title: str, at: int, publisher: str) -> None:
    r = topics.classify(title)
    with ctx.db.session() as s:
        s.add(
            NewsItem(
                uid=f"{publisher}:{title}",
                source=publisher,
                market=None,
                title=title,
                summary="",
                link=f"https://example.com/{len(title)}",
                publisher=publisher,
                published_at=at,
                fetched_at=at,
                sentiment=0.0,
                topics=",".join(r.topics),
                severity=r.severity,
                impact=r.impact,
                scope=r.scope,
            )
        )


def test_the_desk_notices_an_event_and_explains_it(ctx: AppContext) -> None:
    now = ctx.clock.now_ms()
    _news(ctx, "Iran fires missiles at Israel, oil jumps", now - 3 * HOUR, "Reuters")
    _news(ctx, "Israel vows response after Iranian missile barrage", now - 2 * HOUR, "BBC")
    _news(ctx, "Oil surges as Middle East war fears grow", now - HOUR, "CNBC")
    events = ctx.world.detect()
    assert [e.scenario for e in events] == ["mideast_war"]
    with ctx.db.session() as s:
        row = s.scalar(select(WorldEvent))
        assert row is not None and row.status == "active"
    v = ctx.world.view("IN")
    assert v["tilt"] < 0 and v["drivers"][0]["scenario"] == "mideast_war"
    assert any(x["symbol"] in ("BPCL", "IOC", "HINDPETRO", "INDIGO") for x in v["hurt"])
    assert any(x["symbol"] in ("ONGC", "OIL") for x in v["helped"]) or v["helped"]
    stock = ctx.world.stock(_id(ctx, "IN", "BPCL"))
    assert stock["tilt"] < 0 and stock["why"]


def _id(ctx: AppContext, market: str, symbol: str) -> int:
    from backend.core.types import Market
    from backend.data import store

    ctx.watchlists.ensure()
    with ctx.db.session() as s:
        ref = store.find_instrument(s, Market(market), symbol)
    assert ref is not None
    return ref.id


def _download(ctx: AppContext, *symbols: tuple[str, str]) -> None:
    from backend.core.types import Market, Timeframe
    from backend.data import store

    with ctx.db.session() as s:
        refs = [store.find_instrument(s, Market(m), sym) for m, sym in symbols]
    for ref in refs:
        assert ref is not None
        ctx.cache.ensure(ref, Timeframe.D1, 0, ctx.clock.now_ms())


def test_learning_from_past_events_on_saved_prices(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    _download(
        ctx,
        ("IN", "NIFTY50"),
        ("IN", "ONGC"),
        ("IN", "BPCL"),
        ("IN", "RELIANCE"),
        ("IN", "TCS"),
        ("IN", "INFY"),
        ("US", "SPY"),
        ("US", "AAPL"),
        ("US", "NVDA"),
    )
    counts = ctx.world.train_history(force=True)
    # practice prices run 2016–2025: every event in those years is measured
    in_years = [e for e in EVENTS if "2016-01-05" <= e.day <= "2025-12-01"]
    assert counts["IN"] >= len(in_years) - 3 and counts["US"] >= len(in_years) - 3
    with ctx.db.session() as s:
        rows = s.scalars(select(WorldEffect).where(WorldEffect.source == "history")).all()
        assert rows and all(r.n >= 1 for r in rows)
        assert {r.horizon for r in rows} == {1, 5, 20}
    learned = ctx.world.learned()
    assert ("mideast_war", "IN", "market", 5) in learned
    assert ctx.world.lessons()


def test_live_events_are_measured_later(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    _download(ctx, ("IN", "NIFTY50"), ("IN", "BPCL"), ("IN", "IOC"), ("IN", "ONGC"))
    # the event was seen 60 days ago (the practice prices end the day before "now")
    first = ctx.clock.now_ms() - 60 * 86_400_000
    with ctx.db.session() as s:
        s.add(
            WorldEvent(
                scenario="mideast_war",
                title="Practice event",
                first_seen=first,
                last_seen=first,
                strength=12.0,
                status="fading",
                headlines="[]",
                reactions=json.dumps({"sign": 1.0}),
            )
        )
    assert ctx.world.learn_live() > 0
    with ctx.db.session() as s:
        live = s.scalars(select(WorldEffect).where(WorldEffect.source == "live")).all()
        assert {r.horizon for r in live} == {1, 5, 20}
        ev = s.scalar(select(WorldEvent))
        assert ev is not None and ev.status == "measured"
    assert ctx.world.learn_live() == 0  # each horizon is learned once


def test_a_move_is_investigated_and_saved(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    now = ctx.clock.now_ms()
    _news(ctx, "Iran fires missiles at Israel, oil jumps", now - 5 * HOUR, "Reuters")
    move = inv.Move("IN", "market", "the Nifty 50", "1d", now - 4 * HOUR, now, -2.8, -3.6)
    out = ctx.world.explain_move(move)
    assert out["verdict"] == "world" and "Most likely cause" in out["text"]
    assert ctx.world.investigations("IN")[0]["id"] == out["id"]


def test_many_events_dont_pin_the_market_at_the_limit() -> None:
    """D-167: 20 active events pinned both markets (and whole groups) at exactly −2.0."""
    one = engine.view("IN", [engine.ActiveEvent("mideast_war", 20.0, 1.0)], {})
    keys = ("mideast_war", "shipping_chokepoint", "india_pakistan", "terror_major", "taiwan_strait")
    many = engine.view("IN", [engine.ActiveEvent(k, 20.0, 1.0) for k in keys] * 4, {})
    assert -2.0 < many.tilt < one.tilt < 0  # worse reads worse, and never sits at the cap
    assert all(-2.0 < v < 2.0 for v in many.tags.values())
    assert engine.soft(0.5) == 0.4 and engine.soft(-20) > -1.9  # order kept, cap never reached
