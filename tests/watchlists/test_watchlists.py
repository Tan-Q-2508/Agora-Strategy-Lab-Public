"""Watchlists (D-94), sectors (D-98), Kairos's picks and the autopilot (D-99), and the new
Kairos tools: ready-made lists load, yours are editable, agents' lists are limited and
explained, factor lists by hand, sector readings by hand, a desk starts on its own."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import store
from backend.errors import AgoraError
from backend.sectors import rotation as rot
from backend.watchlists import factors, seed, taxonomy


def _download(ctx: AppContext, market: str, *symbols: str) -> None:
    with ctx.db.session() as s:
        refs = [store.find_instrument(s, Market(market), x) for x in symbols]
    for ref in refs:
        assert ref is not None
        ctx.cache.ensure(ref, Timeframe.D1, 0, ctx.clock.now_ms())


def test_ready_made_lists_load_once(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    lists = ctx.watchlists.lists()
    names = {w["name"] for w in lists}
    for want in (
        "Nifty 50",
        "Nifty IT",
        "Nifty Bank",
        "S&P 500",
        "Nasdaq-100",
        "Dow Jones 30",
        "Large caps (Nifty 100)",
        "Mid caps (Nifty Midcap 150)",
        "Small caps (S&P SmallCap 600)",
        "Momentum 30 (NSE)",
        "Magnificent 7",
        "Sector ETFs (SPDR)",
        "Energy (S&P 500)",
        "Financials (Nifty 500)",
    ):
        assert want in names, want
    by = {w["name"]: w for w in lists}
    assert by["Nifty 50"]["count"] == 50 and by["Dow Jones 30"]["count"] == 30
    assert by["Momentum leaders (12-1)"]["live"] is True
    with ctx.db.session() as s:
        assert not seed.needs_sync(s)
    assert len(ctx.watchlists.lists()) == len(lists)


def test_profiles_and_tags(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    with ctx.db.session() as s:
        bpcl = store.find_instrument(s, Market.IN, "BPCL")
        nvda = store.find_instrument(s, Market.US, "NVDA")
    assert bpcl is not None and nvda is not None
    p = ctx.watchlists.profile(bpcl.id)
    assert p is not None and p["sector"] == "Energy" and "omc" in p["tags"]
    assert p["size"] == "large"
    q = ctx.watchlists.profile(nvda.id)
    assert q is not None and q["sector"] == "Information Technology"
    assert {"semiconductors", "china_exposed"} <= set(q["tags"])
    assert taxonomy.size_of({"midcap150", "nifty500"}, "IN") == "mid"
    assert taxonomy.size_of({"sp600"}, "US") == "small"


def test_your_lists_are_editable_and_ready_ones_are_not(ctx: AppContext) -> None:
    w = ctx.watchlists.create("IN", "My banks", ["HDFCBANK", "ICICIBANK"], "Two banks")
    assert w["count"] == 2 and w["editable"]
    w = ctx.watchlists.update(w["id"], add=["SBIN"], remove=["ICICIBANK"], name="Banks")
    assert [i["symbol"] for i in w["items"]] == ["HDFCBANK", "SBIN"] and w["name"] == "Banks"
    with pytest.raises(AgoraError, match="already a list"):
        ctx.watchlists.create("IN", "Banks", ["SBIN"])
    with pytest.raises(AgoraError, match="doesn't know"):
        ctx.watchlists.create("IN", "Bad", ["NOTASTOCK"])
    ready = ctx.watchlists.find("nifty it", "IN")
    assert ready is not None and ready["name"] == "Nifty IT"
    with pytest.raises(AgoraError, match="kept up to date"):
        ctx.watchlists.update(ready["id"], add=["TCS"])
    copy = ctx.watchlists.copy(ready["id"])
    assert copy["name"] == "My Nifty IT" and copy["count"] == ready["count"]
    ctx.watchlists.delete(w["id"])
    assert all(x["id"] != w["id"] for x in ctx.watchlists.lists())


def test_agents_lists_are_limited_and_explained(ctx: AppContext) -> None:
    svc = ctx.watchlists
    first = svc.save_for_agent(
        "metis",
        "IN",
        "Booming: Metals",
        ["TATASTEEL", "HINDALCO"],
        "Metals are booming.",
        {"TATASTEEL": "+12% this month"},
    )
    assert first is not None and first["name"] == "Metis · Booming: Metals"
    assert first["kind"] == "metis" and first["reason"] == "Metals are booming."
    assert first["items"][0]["note"] in ("+12% this month", "")
    again = svc.save_for_agent("metis", "IN", "Booming: Metals", ["JSWSTEEL"], "Still.")
    assert again is not None and again["id"] == first["id"] and again["count"] == 1
    for k in range(2):
        assert svc.save_for_agent("metis", "IN", f"List {k}", ["TCS"], "x") is not None
    assert svc.save_for_agent("metis", "IN", "One too many", ["TCS"], "x") is None


def test_factor_scores_by_hand() -> None:
    up = np.linspace(100, 200, 300)
    s, note = factors.score("momentum", up) or (0.0, "")
    assert s == pytest.approx(up[-22] / up[-253] - 1) and "from 12 to 1 months ago" in note
    assert factors.score("trend", up) is not None
    assert factors.score("trend", up[::-1]) is None
    near, _ = factors.score("near_high", up) or (0.0, "")
    assert near == 1.0
    dip = np.r_[up, up[-1] * 0.95]
    rev = factors.score("reversal", dip)
    assert rev is not None and rev[0] == pytest.approx(1 - dip[-1] / dip[-6], abs=1e-12)
    picks = factors.rank("momentum", {1: up, 2: up[::-1], 3: up * 1.0}, top=2)
    assert [p.instrument_id for p in picks] == [1, 3]


def test_factor_lists_rebuild_from_prices(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    _download(ctx, "IN", "NIFTY50", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC", "SBIN")
    done = ctx.watchlists.refresh_factors("IN", force=True)
    assert done["IN:momentum"] >= 3
    w = ctx.watchlists.find("Momentum leaders (12-1)", "IN")
    assert w is not None
    d = ctx.watchlists.detail(w["id"])
    assert d["items"] and "months ago" in d["items"][0]["note"]
    assert d["items"][0]["last"] is not None


def test_sector_reading_by_hand() -> None:
    n = 300
    t = np.arange(n)
    bench = 100 + 0.01 * t
    a = rot.Member(1, "A", 100 * np.exp(0.002 * t), np.full(n, 1.0))
    b = rot.Member(2, "B", 50 * np.exp(0.002 * t), np.full(n, 1.0))
    line = rot.equal_weight([a, b])
    assert line[0] == 100 and line[-1] == pytest.approx(100 * np.exp(0.002 * (n - 1)), rel=1e-9)
    r = rot.read("Up", [a, b], bench)
    assert r is not None and r.quadrant in ("leading", "weakening") and r.breadth["above50"] == 100
    assert r.state in ("strong", "neutral")
    # A sudden broad jump on busy volume: a boom
    c = np.r_[np.full(n - 21, 100.0), 100 * np.cumprod(np.full(21, 1.012))]
    v = np.r_[np.full(n - 10, 1.0), np.full(10, 2.0)]
    noise = np.random.default_rng(3).normal(0, 0.004, n)
    ms = [rot.Member(i, f"S{i}", c * np.exp(np.cumsum(noise * (i + 1) / 3)), v) for i in range(4)]
    boom = rot.read("Boom", ms, np.full(n, 100.0) * np.exp(np.cumsum(noise / 4)))
    assert boom is not None and boom.state == "boom", boom.to_json()
    assert "booming" in boom.to_json()["sentence"]


def test_sector_overview_on_practice_data(ctx: AppContext, client: TestClient) -> None:
    ctx.watchlists.ensure()
    # practice prices cover 12 Nifty stocks
    _download(ctx, "IN", "NIFTY50", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN")
    o = client.get("/api/sectors?market=IN").json()
    names = {r["name"] for r in o["sectors"]}
    assert {"Information Technology", "Financials"} <= names
    assert o["sentence"] and o["stocks"] >= 6


def test_kairos_picks_and_the_autopilot_desk(ctx: AppContext) -> None:
    ctx.watchlists.ensure()
    _download(
        ctx,
        "IN",
        "NIFTY50",
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "ITC",
        "LT",
        "MARUTI",
        "BHARTIARTL",
    )
    from backend.kairos import picks

    ranked = picks.rank(ctx, "IN")
    assert 5 <= len(ranked) <= picks.N_PICKS
    for p in ranked:
        assert p["why"]
    # D-177: the n most traded (money a day), ordered by strength
    few = picks.rank(ctx, "IN", n=4)
    by_traded = sorted(ranked, key=lambda p: -p["traded"])
    assert {p["symbol"] for p in few} == {p["symbol"] for p in by_traded[:4]}
    assert [p["score"] for p in few] == sorted((p["score"] for p in few), reverse=True)
    ap = ctx.services["autopilot"]
    ctx.paper.threaded = False
    state: dict[str, object] = {}
    out = ap.desk("IN", state)
    assert out["status"] == "started"
    desks = ctx.desk.desks()
    assert len(desks) == 1 and desks[0]["market"] == "IN"
    assert ap.desk("IN", state)["status"] == "running"  # not started twice
    # D-169: rules out of date, but orders wait for the next candle: keep running
    ctx.desk.rules_outdated = lambda _sid: True  # type: ignore[method-assign]
    ap._waiting = lambda _sid: 10  # type: ignore[method-assign]
    assert ap.desk("IN", state)["status"] == "running"
    studied: list[tuple[str, str]] = []
    ctx.learning.start_training = lambda m, tf: studied.append((m.value, tf.value))  # type: ignore[method-assign]
    ap._waiting = lambda _sid: 0  # type: ignore[method-assign]
    assert ap.desk("IN", state)["status"] == "started"  # flat now: restarted with the new rules
    assert studied == []  # same stocks: no new study
    state["desks"]["IN"]["symbols"] = ["OLD1", "OLD2"]  # type: ignore[index]
    assert ap.desk("IN", state)["status"] == "started"
    assert studied == [("IN", "1d")]  # D-172: new stocks, a fresh study for the judge
    ctx.desk.rules_outdated = lambda _sid: False  # type: ignore[method-assign]
    # D-217: a desk on a much shorter list that always holds a trade moves where it stands, with
    # no pause (D-213's pause cost the US hourly and India daily desks their new trades)
    real_desks = ctx.desk.desks
    sid = state["desks"]["IN"]["session_id"]  # type: ignore[index]
    small = [
        {**d, "symbols": ["RELIANCE"], "open_positions": 2, "state": "running"}
        for d in real_desks()
    ]
    ctx.desk.desks = lambda: small  # type: ignore[method-assign]
    moved: list[tuple[int, int]] = []
    ctx.paper.relist = lambda i, syms, _m: moved.append((i, len(syms))) or True  # type: ignore[method-assign,func-returns-value]
    studied.clear()
    paused: list[int] = []
    ctx.paper.pause = lambda i: paused.append(i)  # type: ignore[method-assign]
    assert ap.desk("IN", state)["status"] == "moved"
    assert moved and moved[0][0] == sid and paused == []
    assert studied == [("IN", "1d")]  # a new list, a fresh study (D-172)
    # the list can't move yet (the desk is still loading): try again, nothing lost
    ctx.paper.relist = lambda *_a: False  # type: ignore[method-assign]
    assert ap.desk("IN", state)["status"] == "running"
    ctx.desk.desks = real_desks  # type: ignore[method-assign]
    state["desks"]["IN"]["symbols"] = ["RELIANCE"]  # type: ignore[index]
    w = ctx.watchlists.find("Kairos · Picks India", "IN")
    assert w is not None and w["kind"] == "kairos"
    status = ap.status()
    assert status["on"] is True and status["desks"]


def test_settings_default_to_working_on_their_own(ctx: AppContext) -> None:
    from backend.settings_store import read_all

    with ctx.db.session() as s:
        st = read_all(s)
    assert st["autopilot"] is True and st["metis.enabled"] is True
    assert st["kairos.bigger_chart"] is True


def test_kairos_tools_and_phrases(ctx: AppContext) -> None:
    from backend.kairos import router
    from backend.kairos.tools.base import ThreadState

    def plan(text: str) -> list[tuple[str, dict[str, object]]]:
        return [(c.name, dict(c.arguments)) for c in router.plan(ctx, text, ThreadState(), {})]

    assert plan("why did the market fall today?")[0][0] == "why_move"
    assert plan("why did IT stocks fall in India?")[0] == (
        "why_move",
        {"market": "IN", "sector": "it"},
    )
    assert plan("what's happening in the world?")[0][0] == "world_events"
    assert plan("which sectors are booming in the US?")[0] == ("sectors", {"market": "US"})
    assert plan("show me my watchlists")[0][0] == "watchlists"
    assert plan("why did my trades fail?")[0][0] != "why_move"
    from backend.kairos.resolve import stocks

    got = stocks(ctx, ["the Nifty IT list"], Market.IN)
    assert len(got) == 10 and all(i.market is Market.IN for i in got)


def test_exchange_test_symbols_arent_stocks(ctx: AppContext) -> None:
    """D-184: NSE's test securities (DUMMYHEG…) sent every Indian top-up to 400 NSE day files
    each, holding all four download threads for hours."""
    from backend.core.types import Market
    from backend.data import store
    from backend.db.models import Instrument
    from backend.watchlists import seed

    assert seed.is_test_symbol("DUMMYHEG") and not seed.is_test_symbol("DMART")
    with ctx.db.session() as s:
        s.add(
            Instrument(
                market_code="IN",
                symbol="DUMMYXYZ",
                yahoo_symbol="DUMMYXYZ.NS",
                name="Dummy",
                instrument_type="equity",
                is_active=1,
                added_at=0,
            )
        )
    with ctx.db.session() as s:
        seed.sync(s, 0)
    with ctx.db.session() as s:
        ref = store.find_instrument(s, Market.IN, "DUMMYXYZ")
        row = s.get(Instrument, ref.id) if ref else None
    assert row is not None and row.is_active == 0


def test_the_nse_backup_only_fills_recent_gaps() -> None:
    from backend.data import nse

    assert nse.MAX_DAYS_PER_CALL <= 10


def test_listings_left_out_stop_being_followed_but_open_trades_keep_theirs(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-223: the user wants NSE, NYSE and Nasdaq stocks only. A left-out listing stops updating
    # and is deleted from nothing; one with an open paper trade stays until the trade ends.
    from backend.db.models import Instrument, PaperPosition
    from backend.watchlists import seed

    with ctx.db.session() as s:
        now = 1_700_000_000_000
        s.add(
            Instrument(
                market_code="US",
                symbol="ZZSH",
                yahoo_symbol="ZZSH",
                name="Shell Acquisition Corp",
                instrument_type="equity",
                is_active=1,
                added_at=now,
            )
        )
        s.add(
            Instrument(
                market_code="US",
                symbol="ZZHD",
                yahoo_symbol="ZZHD",
                name="Held Acquisition Corp",
                instrument_type="equity",
                is_active=1,
                added_at=now,
            )
        )
        s.flush()
        held = s.scalar(select(Instrument.id).where(Instrument.symbol == "ZZHD"))
    monkeypatch.setattr(seed, "excluded_us", lambda: {"ZZSH", "ZZHD"})
    sid = _session(ctx)
    with ctx.db.session() as s:
        s.add(PaperPosition(session_id=sid, instrument_id=held, qty=1, avg_price=1, opened_ts=0))
    with ctx.db.session() as s:
        seed.sync(s, now)
    with ctx.db.session() as s:
        active = dict(
            s.execute(
                select(Instrument.symbol, Instrument.is_active).where(
                    Instrument.symbol.in_(("ZZSH", "ZZHD"))
                )
            ).all()
        )
    assert active == {"ZZSH": 0, "ZZHD": 1}


def _session(ctx: AppContext) -> int:
    from backend.paper.service import SessionIn
    from backend.strategy import service as strategies
    from backend.strategy.templates import template_definition

    ctx.paper.threaded = False
    d = template_definition("ma_crossover", "IN", ["RELIANCE"])
    with ctx.db.session() as s:
        _, v = strategies.create(s, name="t", description="", definition=d, now=0)
        vid = v.id
    return ctx.paper.start_session(SessionIn(strategy_version_id=vid))
