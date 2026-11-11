"""Kairos's trade check, its reviews and strategy improvement (KAIROS §16, D-71, D-72)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.types import Market
from backend.kairos import improve, quality, review
from backend.kairos.quality import Sample, fit, judge
from tests.data.helpers import wait_job
from tests.golden.test_indicators import DAILY
from tests.strategy.test_backtest_api import Y2018, Y2026, make_strategy, start, wait_run

FIVE = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"]

# ---------------------------------------------------------------- the model, by hand


def _three_groups() -> list[Sample]:
    """30 trades: choppiness 30 (9 of 10 won), 50 (5 of 10), 70 (1 of 10).
    Wins return +2%, losses −1%."""
    out = []
    for value, wins in ((30.0, 9), (50.0, 5), (70.0, 1)):
        for k in range(10):
            win = k < wins
            out.append(Sample({"chop": value}, win, 2.0 if win else -1.0, ts=len(out)))
    return out


def test_fit_by_hand() -> None:
    m = fit(_three_groups())
    assert m is not None
    # base = (15 + 1) / (30 + 2) = 0.5; weighted thirds of [30×10, 50×10, 70×10] → 40 and 60
    assert m.base == pytest.approx(0.5)
    assert m.stats["chop"].edges == pytest.approx((40.0, 60.0))
    parts = {p.third: p for p in m.parts({"chop": 30.0})} | {
        p.third: p for p in m.parts({"chop": 70.0})
    }
    # shrunk rates: (9 + 10×0.5)/(10 + 10) = 0.7 and (1 + 5)/20 = 0.3
    assert parts["low"].win_rate == pytest.approx(0.7)
    assert parts["high"].win_rate == pytest.approx(0.3)
    assert parts["low"].effect == pytest.approx(math.log(0.7 / 0.3))
    assert m.chance({"chop": 70.0}) == pytest.approx(
        1 / (1 + math.exp(m.damp * math.log(0.7 / 0.3)))
    )
    assert m.damp in (0.15, 0.25, 0.35, 0.5, 0.7, 1.0)
    assert m.avg_win == pytest.approx(2.0) and m.avg_loss == pytest.approx(1.0)


def test_judging_skips_the_losing_condition_and_explains_why() -> None:
    m = fit(_three_groups())
    calm = judge(m, {"chop": 30.0}, "balanced")
    choppy = judge(m, {"chop": 70.0}, "balanced")
    assert calm.take and not choppy.take
    assert "choppy" in choppy.reason and "won 30% of 10" in choppy.reason
    assert judge(m, {"chop": 70.0}, "learn").take  # learn mode never skips
    assert judge(m, {"chop": 70.0}, "off").take
    strict = judge(m, {"chop": 50.0}, "strict")
    assert not strict.take  # the middle third is no better than a coin flip


def test_nothing_is_skipped_before_thirty_results() -> None:
    few = _three_groups()[20:]  # ten choppy trades
    assert judge(fit(few), {"chop": 70.0}, "strict").take


def test_readings_are_causal_and_turn_round_for_shorts() -> None:
    full = quality.FeatureBook(DAILY)
    part = quality.FeatureBook(DAILY.upto(900))
    for i in (300, 600, 899):
        assert full.at(i, 1) == part.at(i, 1)
    long_, short = full.at(800, 1), full.at(800, -1)
    assert short["adx"] == long_["adx"] and short["natr"] == long_["natr"]
    assert short["rsi"] == pytest.approx(100 - long_["rsi"])
    assert short["long_trend"] == pytest.approx(-long_["long_trend"])
    assert set(long_) == {r.key for r in quality.READINGS}


# ---------------------------------------------------------------- the review, by hand


def _t(net: float, gross: float, charges: float, k: int, reason: str = "signal") -> review.TradeIn:
    day = 86_400_000
    return review.TradeIn(
        "TCS", 1, k * 10 * day, (k * 10 + 5) * day, gross, charges, net, net / 1000, 5, reason
    )


def test_costs_that_turn_profit_into_loss_are_called_out() -> None:
    trades = [_t(-20.0, 100.0, 120.0, k) for k in range(4)]
    r = review.review(trades, {}, Market.IN)
    m = r["money"]
    assert m["gross"] == 400 and m["charges"] == 480 and m["net"] == -80
    assert m["level"] == "bad" and "turned that into a loss" in m["verdict"]
    assert m["avg_gross"] == 100 and m["avg_charges"] == 120


def test_win_rate_payoff_and_break_even() -> None:
    nets = [300.0, -100.0, -100.0, 300.0, -100.0]
    trades = [_t(n, n + 10, 10, k) for k, n in enumerate(nets)]
    w = review.review(trades, {}, Market.US)["wins"]
    # 2 wins of 5; average win 300, loss 100 → payoff 3, break-even 1/(1+3) = 25%
    assert (w["wins"], w["losses"], w["win_rate"]) == (2, 3, 0.4)
    assert w["payoff"] == 3.0 and w["breakeven_win_rate"] == 0.25
    assert w["expectancy"] == 60.0 and w["longest_losing_streak"] == 2


def test_filters_must_hold_up_on_trades_they_never_saw() -> None:
    rows = []
    for k in range(40):
        chop = 35.0 + (k * 7) % 35  # 35…69, mixed through time
        win = chop < 58
        t = _t(100.0 if win else -100.0, 110.0 if win else -90.0, 10.0, k)
        rows.append(review._Row(t, {"chop": chop, "adx": 20.0 + (k * 3) % 7}, None, None))
    f = review._filters_part(rows, Market.IN)
    held = [r for r in f["rules"] if r["held_up"]]
    assert held and held[0]["key"] == "chop" and held[0]["keep"] == "at_most"
    assert held[0]["test"]["after"]["win_rate"] > held[0]["test"]["before"]["win_rate"]
    assert held[0]["condition"]["indicator"] == "chop"
    assert f["train_trades"] == 24 and f["test_trades"] == 16


def test_filters_turn_round_for_short_trades() -> None:
    rsi = review.condition_for("rsi", "at_least", 45.0)
    trend = review.condition_for("long_trend", "at_least", -3.0)
    chop = review.condition_for("chop", "at_most", 58.0)
    assert improve.to_condition(rsi, -1).op == "at_most"
    assert improve.to_condition(rsi, -1).right.value == 55.0  # type: ignore[union-attr]
    assert improve.to_condition(trend, -1).right.value == 3.0  # type: ignore[union-attr]
    assert improve.to_condition(chop, -1).op == "at_most"
    assert improve.to_condition(chop, 1).right.value == 58.0  # type: ignore[union-attr]


# ---------------------------------------------------------------- end to end


def test_trade_check_in_a_backtest(client: TestClient) -> None:
    created = make_strategy(client, "bollinger_reversion", "IN")
    vid = created["version"]["id"]
    common = {"strategy_version_id": vid, "symbols": FIVE, "end": Y2026}
    off = wait_run(client, start(client, **common, start=Y2018))
    learn = wait_run(client, start(client, **common, start=Y2018, trade_check="learn"))
    assert off["status"] == learn["status"] == "done"
    assert learn["metrics"]["trades"] == off["metrics"]["trades"]  # learning never skips
    assert learn["metrics"]["trade_check"]["skipped"] == 0
    strict = wait_run(client, start(client, **common, start=Y2018, trade_check="strict"))
    tc = strict["metrics"]["trade_check"]
    assert tc["mode"] == "strict" and tc["checked"] > 0
    assert strict["metrics"]["trades"] <= off["metrics"]["trades"]
    # deterministic: the same request gives the same result
    again = wait_run(client, start(client, **common, start=Y2018, trade_check="strict"))
    assert again["metrics"]["trades"] == strict["metrics"]["trades"]
    assert again["metrics"]["trade_check"] == tc


def test_review_improve_and_learn_on_their_own(client: TestClient) -> None:
    created = make_strategy(client, "bollinger_reversion", "IN")
    sid, vid = created["strategy"]["id"], created["version"]["id"]
    run_id = start(client, strategy_version_id=vid, symbols=FIVE, start=Y2018, end=Y2026)
    assert wait_run(client, run_id)["status"] == "done"
    assert client.get(f"/api/kairos/review/backtest/{run_id}").json()["review"] is None
    job = client.post(f"/api/kairos/review/backtest/{run_id}").json()["job_id"]
    done = wait_job(client, job, timeout=120)
    assert done["status"] == "done", done
    r = client.get(f"/api/kairos/review/backtest/{run_id}").json()["review"]
    assert r["trades"] > 0 and r["money"]["charges"] > 0 and r["wins"]["trades"] == r["trades"]
    assert r["conditions"] and "features" not in r
    assert {x["reason"] for x in r["exits"]["by_reason"]}
    pic = client.get(f"/api/kairos/trade-check/{sid}").json()
    assert pic["trades"] == r["trades"] and pic["model"]["readings"]
    # improving: a verdict either way, logged, and a new version only when it did better
    job = client.post(f"/api/kairos/improve/{sid}").json()["job_id"]
    res = wait_job(client, job, timeout=300)
    assert res["status"] == "done", res
    out = res["result"]
    assert isinstance(out["changed"], bool) and out["headline"]
    versions = client.get(f"/api/strategies/{sid}/versions").json()["versions"]
    assert len(versions) == (2 if out["changed"] else 1)
    hist = client.get("/api/kairos/improvements", params={"strategy_id": sid}).json()
    assert hist["improvements"][0]["headline"] == out["headline"]
    # the always-on learner: one round studies what's new and remembers it
    job = client.post("/api/kairos/learner/round").json()["job_id"]
    rnd = wait_job(client, job, timeout=300)
    assert rnd["status"] == "done", rnd
    st = client.get("/api/kairos/learner").json()
    assert st["last_round_at"] is not None and st["strategies"]
    assert st["thread"] is False  # practice data: no background thread in tests


def test_the_check_must_earn_the_right_to_skip() -> None:
    day = 86_400_000
    rng = np.random.default_rng(7)
    # real structure: choppy markets lose, repeated over 240 trades in time order
    real = []
    for k in range(240):
        chop = float(rng.choice([30.0, 50.0, 70.0]))
        win = bool(rng.random() < {30.0: 0.8, 50.0: 0.5, 70.0: 0.2}[chop])
        real.append(Sample({"chop": chop}, win, 2.0 if win else -1.0, 1.0, k * day, k * day + day))
    # noise: the same readings, but the result is a coin flip
    noise = [Sample(x.features, bool(rng.random() < 0.5), 1.0, 1.0, x.ts, x.known_ts) for x in real]
    smart, dumb = quality.TradeCheck("strict", real), quality.TradeCheck("strict", noise)
    assert smart.proven() and smart.skill()[0] > quality.PROOF_SKILL
    assert not dumb.proven()
    s = DAILY.upto(300)
    feats = {"chop": 70.0}
    smart.book = lambda key, series: type("B", (), {"at": lambda self, i, side: feats})()  # type: ignore[method-assign]
    dumb.book = smart.book  # type: ignore[method-assign]
    assert smart.check(1, "X", s, 299, 1) is not None  # skipped, with a reason
    assert dumb.check(1, "X", s, 299, 1) is None  # still proving itself: takes the trade
    assert quality.brier_skill([(0.8, 0.5, True), (0.2, 0.5, False)]) == pytest.approx(
        1 - (0.04 + 0.04) / (0.25 + 0.25)
    )


def test_shadow_trades_settle_after_the_usual_holding_time() -> None:
    check = quality.TradeCheck("strict", _three_groups())
    s = DAILY.upto(400)
    # judge a signal, then pretend it was skipped and settle it 10 candles later
    check._shadows.append(quality._Shadow(1, 1, {"chop": 70.0}, int(s.ts[300])))
    check.observe(1, s, 305)
    assert len(check._shadows) == 1  # not yet
    check.observe(1, s, 320)
    assert not check._shadows and check.stats.shadow_wins + check.stats.shadow_losses == 1
    last = check.samples[-1]
    entry, exit_ = float(s.open[301]), float(s.close[311])
    assert last.source == "shadow" and last.weight == quality.SHADOW_WEIGHT
    assert last.ret_pct == pytest.approx((exit_ / entry - 1) * 100 - 0.3)
    assert np.isfinite(last.ret_pct)
