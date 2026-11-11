"""The Kairos brain, its signals and its training (KAIROS §8–9, D-60, D-61)."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select

from backend.analysis import signals as sig
from backend.analysis.report import Analysis
from backend.analysis.volume import VolumeArrays
from backend.backtest.run import RunSpec, run
from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import service, store
from backend.db.models import BrokerageProfile, KairosSignalStat
from backend.kairos import brain, learning
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import canonical_json
from backend.strategy.validator import validate
from tests.golden.test_indicators import DAILY, INTRA

Y2016 = 1_451_606_400_000
Y2026 = 1_767_225_600_000


# ---------------------------------------------------------------- signals


@pytest.mark.parametrize("series", [DAILY, INTRA], ids=["daily", "5m"])
def test_signals_never_change_the_past(series: object) -> None:
    from backend.indicators.series import BarSeries

    assert isinstance(series, BarSeries)
    full = sig.compute(series)
    for cut in (700, 1500):
        part = sig.compute(series.upto(cut))
        assert [e for e in full.events if e.index < cut] == part.events
        np.testing.assert_array_equal(full.trend[:cut], part.trend)
        np.testing.assert_array_equal(full.momentum[:cut], part.momentum)
        np.testing.assert_array_equal(full.volume[:cut], part.volume)


def test_signal_readings_match_the_chart_report() -> None:
    s = DAILY.upto(900)
    ss = sig.compute(s)
    an = Analysis(s, Market.IN, "RELIANCE")
    i = len(s) - 1
    assert ss.trend[i] == an.trend.state(i, an.minor.known_at(i)).score
    assert ss.momentum[i] == pytest.approx(an.mom.state(i).score, abs=1e-3)
    va = VolumeArrays(s.high, s.low, s.close, s.volume)
    for k in (300, 600, i):
        assert ss.volume[k] == pytest.approx(va.state(k).score, abs=1e-9)


def test_every_family_shows_up_on_ten_years_of_prices() -> None:
    ss = sig.compute(DAILY)
    families = {e.family for e in ss.events}
    assert families == set(sig.WINDOW)
    for e in ss.events:
        assert e.direction in (1, -1) and e.label
        assert learning.direction_of(e.key) == e.direction, e.key
        if e.family == "pattern" and not e.key.startswith("pattern:failed"):
            assert e.stop is not None and e.target is not None
            assert (e.target - ss.close[e.index]) * e.direction > 0


def test_recent_events_fade_out() -> None:
    ss = sig.compute(DAILY.upto(1200))
    e = next(e for e in ss.events if e.family == "pattern")
    ages = {age for ev, age in ss.recent(e.index + 3) if ev == e}
    assert ages == {3}
    assert all(ev != e for ev, _ in ss.recent(e.index + sig.WINDOW["pattern"]))


# ---------------------------------------------------------------- learning maths (by hand)


def test_posterior_and_weight_by_hand() -> None:
    # Prior: 20 pseudo-trades at a 50% base rate = Beta(10, 10).
    # 30 wins of 40 → (10 + 30) / (20 + 40) = 0.6667; edge 0.1667 → weight capped at 2.
    assert learning.posterior(0.5, 30, 40) == pytest.approx(40 / 60)
    assert learning.multiplier(0.1667) == 2.0
    # 11 of 20 at a 52% base: (10.4 + 11) / 40 = 0.535 → edge 0.015 → 1 + 0.015/0.05 = 1.3
    p = learning.posterior(0.52, 11, 20)
    assert p == pytest.approx(0.535)
    assert learning.multiplier(p - 0.52) == pytest.approx(1.3)
    # No evidence: exactly the base rate, weight 1. Far worse than base: switched off.
    assert learning.posterior(0.53, 0, 0) == pytest.approx(0.53)
    assert learning.multiplier(0.0) == 1.0
    assert learning.multiplier(-0.2) == 0.0


def test_paper_trades_count_three_times() -> None:
    hist = learning.Tally(n=10, wins=5)
    paper = learning.Tally(n=2, wins=2)
    r = learning.SignalRecord("candle:hammer", 1, hist, paper, 0.5, 10)
    # (10 + 5 + 3·2) / (20 + 10 + 3·2) = 21 / 36
    assert r.posterior == pytest.approx(21 / 36)
    assert r.weight == pytest.approx(1 + (21 / 36 - 0.5) / 0.05 if 21 / 36 - 0.5 < 0.05 else 2.0)


def test_tally_counts_moves_the_signals_way() -> None:
    close = np.array([100.0, 101, 102, 99, 98, 103, 104, 101, 100, 99, 98, 97])
    ev = [
        sig.Event("candle:hammer", 0, 1, "Hammer"),  # 100 → 102 two candles later: win +2%
        sig.Event("candle:hammer", 3, 1, "Hammer"),  # 99 → 103: win
        sig.Event("candle:shooting_star", 5, -1, "Shooting star"),  # 103 → 101: win (fell)
        sig.Event("candle:hammer", 11, 1, "Hammer"),  # no future: not counted
    ]
    n = len(close)
    zeros = np.zeros(n)
    ss = sig.SignalSet(n, close, np.ones(n), zeros, zeros, zeros, ev)
    t = learning.tally_series(ss, 2)
    assert (t["candle:hammer"].n, t["candle:hammer"].wins) == (2, 2)
    assert t["candle:hammer"].sum_ret == pytest.approx(0.02 + 4 / 99)
    star = t["candle:shooting_star"]
    assert (star.n, star.wins) == (1, 1) and star.sum_ret == pytest.approx(2 / 103)


# ---------------------------------------------------------------- training on the practice data


def load(ctx: AppContext, market: Market, symbols: list[str], tf: Timeframe = Timeframe.D1) -> None:
    with ctx.db.session() as s:
        insts = [store.find_instrument(s, market, sym) for sym in symbols]
    service.refresh(ctx.cache, [i for i in insts if i], [tf], start_ms=Y2016, end_ms=Y2026)


def test_training_measures_signals_and_feeds_the_chart_panel(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["RELIANCE", "TCS", "INFY"])
    out = ctx.learning.train(Market.IN, Timeframe.D1)
    assert out["stocks"] == 3 and out["signals"] > 20 and out["horizon"] == 10
    info = ctx.learning.trained(Market.IN, Timeframe.D1)
    assert info is not None and info["candles"] > 6000 and 0.3 < info["base_rate"] < 0.7
    assert not ctx.learning.needs_training(Market.IN, Timeframe.D1)
    find = ctx.learning.lookup(Market.IN, Timeframe.D1)
    rec = ctx.learning.records(Market.IN, Timeframe.D1)
    key = max(rec, key=lambda k: rec[k].history.n)
    st = find(key)
    assert st is not None and st["n"] == rec[key].history.n and 0 <= st["hit_rate"] <= 1
    assert st["horizon"] == 10 and st["base_rate"] == pytest.approx(rec[key].base, abs=1e-4)
    weights = ctx.learning.weights(Market.IN, Timeframe.D1)
    assert weights and all(0 <= w <= 2 for w in weights.values())
    learned = ctx.learning.learned(Market.IN, Timeframe.D1)
    assert learned["trained"]["candles"] == info["candles"]
    for item in learned["best"] + learned["worst"]:
        assert "Indian stocks" in item["text"] and "%" in item["text"]
    # the chart reading now quotes how its findings worked
    with ctx.db.session() as s:
        inst = store.find_instrument(s, Market.IN, "RELIANCE")
    assert inst is not None
    report = ctx.analysis.chart(inst, Timeframe.D1, with_forecast=False)["report"]
    stats = [x["stats"] for x in report["patterns"] + report["candles"] + report["divergences"]]
    assert any(s is not None and s["n"] >= 1 for s in stats) or not stats


def test_training_from_the_api_and_retraining_rule(client: object, ctx: AppContext) -> None:
    load(ctx, Market.IN, ["RELIANCE"])
    assert ctx.learning.needs_training(Market.IN, Timeframe.D1)
    jid = ctx.learning.ensure_trained(Market.IN, Timeframe.D1)
    assert jid is not None
    from tests.data.helpers import wait_job

    assert wait_job(client, jid)["status"] == "done"  # type: ignore[arg-type]
    assert ctx.learning.ensure_trained(Market.IN, Timeframe.D1) is None
    load(ctx, Market.IN, ["TCS"])  # the data doubled: time to study again
    assert ctx.learning.needs_training(Market.IN, Timeframe.D1)


def test_paper_trades_update_the_stats(ctx: AppContext) -> None:
    signals = [("pattern:bull_flag:up", 1), ("candle:bearish_engulfing", -1)]
    ctx.learning.record_trade(Market.US, Timeframe.D1, signals, side=1, return_pct=4.0)
    ctx.learning.record_trade(Market.US, Timeframe.D1, signals, side=1, return_pct=-2.0)
    with ctx.db.session() as s:
        rows = {
            r.signal: r
            for r in s.scalars(select(KairosSignalStat).where(KairosSignalStat.source == "paper"))
        }
    flag, engulf = rows["pattern:bull_flag:up"], rows["candle:bearish_engulfing"]
    assert (flag.n, flag.wins) == (2, 1.0) and flag.sum_ret == pytest.approx(0.02)
    # the bearish candle disagreed with the long trade: it "won" when the trade lost
    assert (engulf.n, engulf.wins) == (2, 1.0) and engulf.sum_ret == pytest.approx(-0.02)
    rec = ctx.learning.records(Market.US, Timeframe.D1)["pattern:bull_flag:up"]
    assert rec.paper.n == 2 and rec.history.n == 0


# ---------------------------------------------------------------- the brain


def spec(ctx: AppContext, market: str, symbols: list[str], **kw: object) -> RunSpec:
    m = Market(market)
    d = brain.definition(market, symbols, **kw)  # type: ignore[arg-type]
    with ctx.db.session() as s:
        insts = [store.find_instrument(s, m, sym) for sym in symbols]
        rules = s.scalar(
            select(BrokerageProfile.rules).where(
                BrokerageProfile.market_code == market, BrokerageProfile.is_default == 1
            )
        )
    targets = [i for i in insts if i is not None]
    load(ctx, m, symbols)
    return RunSpec(
        definition=d,
        instruments=targets,
        timeframe=Timeframe.D1,
        start_ms=Y2016 + 400 * 86_400_000,
        end_ms=Y2026,
        capital=1_000_000 if market == "IN" else 100_000,
        brokerage_rules=json.loads(rules or "{}"),
        slippage_bps=5 if market == "IN" else 2,
    )


def test_the_brain_is_a_valid_strategy() -> None:
    d = brain.definition("US", ["AAPL", "MSFT"], weights={"candle:hammer": 1.4})
    assert validate(d).ok and d.kind == "kairos"
    p = compile_definition(d, {"entry_score": 55})
    assert p.kind == "kairos" and p.brain.entry == 55 and p.brain.weights["candle:hammer"] == 1.4
    bad = validate({**d.model_dump(), "kairos": {**d.kairos.model_dump(), "entry_score": 5}})
    assert not bad.ok and "entry score can't be below 10" in bad.errors[0].sentence().lower()
    # an equal share of the money each, so one tight stop can't take it all (D-131)
    assert d.limits.max_open_positions == 10 and d.limits.max_position_pct == 10.0
    # India delivery can't short; the brain knows
    assert not compile_definition(brain.definition("IN", ["TCS"])).brain.shorts


@pytest.mark.parametrize(
    ("market", "symbols"), [("IN", ["RELIANCE", "INFY"]), ("US", ["AAPL", "MSFT"])]
)
def test_the_brain_backtests_with_reasons_stops_and_targets(
    ctx: AppContext, market: str, symbols: list[str]
) -> None:
    out = run(ctx.cache, spec(ctx, market, symbols))
    assert len(out.trades) >= 5
    for t in out.trades:
        assert t.entry_reason.startswith("Kairos +") or t.entry_reason.startswith("Kairos −")
    if market == "IN":
        assert all(t.side == "long" for t in out.trades)
    exits = {t.exit_reason for t in out.trades if t.closed}
    assert exits & {"stop", "target", "signal", "time"}


def test_the_brain_has_no_look_ahead() -> None:
    ss_full = sig.compute(DAILY)
    for cut in (800, 1600):
        ss = sig.compute(DAILY.upto(cut))
        for i in range(cut - 30, cut):
            a, b = brain.decide(ss_full, i, {}), brain.decide(ss, i, {})
            assert a.score == b.score and a.components == b.components


def test_weights_change_the_score() -> None:
    ss = sig.compute(DAILY.upto(1500))
    i = next(e.index for e in ss.events if e.family == "pattern")
    plain = brain.decide(ss, i, {})
    # setups share the patterns bucket, so switch off everything that feeds it
    keys = {a.event.key for a in plain.active if brain.BUCKET[a.event.family] == "patterns"}
    off = brain.decide(ss, i, dict.fromkeys(keys, 0.0))
    assert off.components["patterns"] == 0.0 and plain.components["patterns"] != 0.0


def test_every_bigger_chart_is_read_together(ctx: AppContext) -> None:
    # D-132: the weekly and monthly charts read together
    def entries(**kw: object) -> set[tuple[str, int]]:
        # room for every trade (a share of 1% each), so one skipped trade can't let another in
        sp = spec(ctx, "US", ["AAPL", "MSFT"], max_positions=100, **kw)
        return {(t.symbol, t.entry_ts) for t in run(ctx.cache, sp).trades}

    none, weekly = entries(), entries(bigger_chart="1w")
    both = entries(bigger_chart="1w", bigger_charts=["1w", "1mo"])
    # the monthly chart changes the trades (a skipped trade can free the stock for a later one)
    assert both != weekly and len(both) < len(none) and len(weekly) < len(none)
    d = brain.definition("US", ["AAPL"], bigger_charts=["1w", "1mo"])
    assert compile_definition(d).brain.charts == ["1w", "1mo"]
    # a desk saved before D-132 keeps its text and hash
    old = brain.definition("US", ["AAPL"], bigger_chart="1w")
    assert "bigger_charts" not in canonical_json(old)


# ---------------------------------------------------------------- the indicators' chorus (D-138)


def _set_with(events: list[sig.Event], n: int = 10) -> sig.SignalSet:
    flat = np.zeros(n)
    return sig.SignalSet(n, np.full(n, 100.0), np.ones(n), flat, flat, flat, events)


def test_the_indicators_vote_as_a_bounded_chorus() -> None:
    from backend.analysis import indicator_signals as ind

    ups = [k for k in ind.INFO if k.startswith("momentum:") and k.endswith(":up")]
    one = brain.decide(_set_with([sig.Event(ups[0], 9, 1, "x", strength=1.0)]), 9, {})
    many = brain.decide(_set_with([sig.Event(k, 9, 1, "x", strength=1.0) for k in ups]), 9, {})
    cap = brain.CHORUS_CAP * brain.STATE_NUDGE
    # one voice is a third of the chorus at most; all of them together reach the cap, no more
    assert one.components["momentum"] == pytest.approx(cap / brain.CHORUS_MIN)
    assert many.components["momentum"] == pytest.approx(cap)
    # a learned weight of 0 silences a voice; split voices cancel out
    half = [sig.Event(k, 9, 1 if n % 2 else -1, "x", strength=1.0) for n, k in enumerate(ups[:4])]
    assert brain.decide(_set_with(half), 9, {}).components["momentum"] == pytest.approx(0.0)
    muted = brain.decide(_set_with([sig.Event(ups[0], 9, 1, "x")]), 9, {ups[0]: 0.0})
    assert muted.components["momentum"] == 0.0


def test_only_strategy_entries_count_as_something_happening() -> None:
    ev = [
        sig.Event("momentum:cci:up", 9, 1, "CCI", strength=1.0),
        sig.Event("strategy:turtle:up", 9, 1, "Turtle", strength=1.0),
    ]
    fresh = brain.decide(_set_with(ev), 9, {}).fresh(1)
    assert [a.event.key for a in fresh] == ["strategy:turtle:up"]


def test_desks_take_new_lessons_at_once(ctx: AppContext) -> None:
    b = compile_definition(brain.definition("US", ["AAPL"])).brain
    assert b is not None
    calls: list[int] = []
    b.refresh = lambda: calls.append(1) or {"x": 1.0}  # type: ignore[func-returns-value]
    b.stamp = lambda: ctx.learning.version

    class Ctx:
        date = "2026-10-28"
        bar_index = 0

    b.on_bar(Ctx())  # type: ignore[arg-type]
    b.on_bar(Ctx())  # type: ignore[arg-type]
    assert len(calls) == 1  # same day, nothing new learned
    before = ctx.learning.version
    ctx.learning.record_trade(Market.US, Timeframe.D1, [("strategy:turtle:up", 1)], 1, 2.0)
    assert ctx.learning.version > before
    b.on_bar(Ctx())  # type: ignore[arg-type]
    assert len(calls) == 2  # the closed trade's lesson is used on the next candle


def test_a_study_from_before_the_new_signals_is_redone(ctx: AppContext) -> None:
    load(ctx, Market.IN, ["RELIANCE"])
    ctx.learning.train(Market.IN, Timeframe.D1)
    assert not ctx.learning.needs_training(Market.IN, Timeframe.D1)
    rec = ctx.learning.records(Market.IN, Timeframe.D1)
    assert any(k.startswith("strategy:") for k in rec) and not any(
        k.startswith("base:") for k in rec
    )
    with ctx.db.session() as s:
        s.execute(
            KairosSignalStat.__table__.delete().where(
                KairosSignalStat.signal == learning.SIGNALS_KEY
            )
        )
        s.commit()
    assert ctx.learning.needs_training(Market.IN, Timeframe.D1)  # an old study: redo it


def test_kairos_studies_the_stocks_it_trades(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    picked = SimpleNamespace(id=-7, symbol="PICKED")
    monkeypatch.setattr(ctx.watchlists, "find", lambda name, market: {"id": 1, "name": name})
    monkeypatch.setattr(ctx.watchlists, "instruments", lambda wid: [picked])
    got = ctx.learning._instruments(Market.IN)
    assert picked in got and len(got) > 1  # the study list and Kairos's picks


def test_the_learner_restudies_every_desk_timeframe_one_at_a_time(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.kairos import autolearn

    due = {(Market.US, Timeframe.M5), (Market.US, Timeframe.H1)}
    started: list[tuple[Market, Timeframe]] = []
    monkeypatch.setattr(ctx.learning, "needs_training", lambda m, tf: (m, tf) in due)
    monkeypatch.setattr(
        ctx.learning, "ensure_trained", lambda m, tf: started.append((m, tf)) or "job"
    )
    learner = autolearn.AutoLearner(ctx)
    notes = learner._restudy()
    assert started == [(Market.US, Timeframe.H1)] and "1h" in notes[0]["text"]


def test_a_smaller_chart_against_the_trade_stops_the_entry(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-177: when the closer look says no, the desk doesn't enter (live desks only; a
    backtest has no closer look, so it trades as before)."""
    assert len(run(ctx.cache, spec(ctx, "US", ["AAPL", "MSFT"])).trades) >= 5
    asked: list[tuple[str, int]] = []
    orig = brain.Brain.__init__

    def init(self: brain.Brain, *a: Any, **k: Any) -> None:
        orig(self, *a, **k)
        self.closer = lambda sym, _ts, side: asked.append((sym, side)) is None

    monkeypatch.setattr(brain.Brain, "__init__", init)
    assert run(ctx.cache, spec(ctx, "US", ["AAPL", "MSFT"])).trades == []
    assert asked  # asked only for the entries the desk was about to make


def test_a_study_reads_only_the_strongest_picks(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-177: the desks trade 250 stocks; a study reads its study list and the first 60."""
    from types import SimpleNamespace

    from backend.kairos import learning

    many = [SimpleNamespace(id=-k, symbol=f"P{k}") for k in range(1, 251)]
    monkeypatch.setattr(ctx.watchlists, "find", lambda name, market: {"id": 1, "name": name})
    monkeypatch.setattr(ctx.watchlists, "instruments", lambda wid: many)
    got = {i.id for i in ctx.learning._instruments(Market.IN)}
    assert {i.id for i in many[: learning.STUDY_PICKS]} <= got
    assert not ({i.id for i in many[learning.STUDY_PICKS :]} & got)
