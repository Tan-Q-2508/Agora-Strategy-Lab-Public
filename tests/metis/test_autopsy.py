"""The trade autopsy (METIS §18, D-109): what separated losers from winners, checked on later
trades, turned into filter ideas; second opinions; the self-learning record."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.context import AppContext
from backend.engine.types import Trade
from backend.metis import autopsy as au


def _trade(i: int, net: float, side: str = "long") -> Trade:
    ts = 1_600_000_000_000 + i * 86_400_000
    return Trade("X", 1, side, 1, ts, 1, ts + 5, 1, net, 1.0, net, 0, 1, "", "signal")  # type: ignore[arg-type]


RVOL = next(p for p in au.OWN if p.indicator == "rvol")
RSI = next(p for p in au.OWN if p.indicator == "rsi")


def _rows(n: int = 40, *, holds_later: bool = True) -> list[au.Row]:
    """Losers came on thin volume (relative volume under 1); RSI says nothing."""
    rows = []
    for i in range(n):
        thin = i % 3 == 0
        late = i >= n * 0.6
        lose = thin if (holds_later or not late) else not thin
        r = au.Row(_trade(i, -100.0 if lose else 80.0))
        r.values = {RVOL.key: 0.6 if thin else 1.5, RSI.key: 40.0 + (i * 7) % 30}
        rows.append(r)
    return rows


def test_finds_the_reading_that_separates_losers_and_writes_it_as_a_rule() -> None:
    rule = au.search(_rows(), RVOL, "long")
    assert rule is not None and rule.keep == "at_least" and 0.6 < rule.value <= 1.5
    assert rule.bad_rate == 0.0 and rule.kept_rate == 1.0 and rule.val_gain > 0
    c = rule.condition()
    assert c["indicator"] == "rvol" and c["op"] == "at_least" and c["probe"] == RVOL.key
    assert "relative volume" in rule.text()


def test_a_rule_that_doesnt_hold_on_later_trades_is_dropped() -> None:
    assert au.search(_rows(holds_later=False), RVOL, "long") is None
    assert au.search(_rows(), RSI, "long") is None  # noise isn't a rule
    assert au.search(_rows(10), RVOL, "long") is None  # too few trades


def test_bigger_chart_readings_are_offered_for_a_daily_strategy() -> None:
    keys = {p.key for p in au.probes_for("1d")}
    assert "1w:rsi" in keys and "1mo:rsi" in keys and "rvol" in keys
    weekly = next(p for p in au.probes_for("1d") if p.key == "1w:rsi")
    assert weekly.words() == "RSI on the weekly chart"


def test_another_strategys_state_conditions_become_filters() -> None:
    rsi_above = {
        "type": "compare",
        "left": {"kind": "indicator", "name": "rsi", "params": {"period": 14}, "output": None},
        "op": "above",
        "right": {"kind": "number", "value": 50},
    }
    assert au._as_filter(rsi_above) == {
        "indicator": "rsi",
        "params": {"period": 14.0},
        "output": None,
        "op": "above",
        "value": 50.0,
    }
    close_over_sma = {
        "type": "compare",
        "left": {"kind": "price", "field": "close"},
        "op": "above",
        "right": {"kind": "indicator", "name": "sma", "params": {"period": 200}},
    }
    got = au._as_filter(close_over_sma)
    assert got is not None and got["op"] == "below" and got["price"] == "close"
    assert au._as_filter({**rsi_above, "op": "crosses_above"}) is None  # a moment, not a state


def test_thresholds_are_rounded_so_new_candles_dont_make_new_ideas() -> None:
    assert au._nice(1.23456) == 1.23 and au._nice(1234.5) == 1230 and au._nice(0.0) == 0.0


def test_the_record_learns_which_readings_hold_up(ctx: AppContext) -> None:
    from backend.metis import notebook

    rid = notebook.start_round(ctx, "user", "", "playbook")
    for status, probe in (("held_up", "rvol"), ("rejected", "rvol"), ("rejected", "1w:rsi")):
        spec: dict[str, Any] = {"conditions": [{"indicator": "x", "probe": probe}], "side": "long"}
        notebook.add_idea(
            ctx,
            rid,
            kind="filter",
            title="t",
            why="",
            market_code="IN",
            strategy_id=1,
            strategy_version_id=7,
            spec=json.dumps(spec),
            fingerprint=f"{status}{probe}",
            status=status,
            verdict="",
            result="{}",
            origin="playbook",
        )
    rec = au.record(ctx)
    assert rec["rvol"] == (2, 1) and rec["1w:rsi"] == (1, 0)
    assert au.tried_on(ctx, 7) == {"rvol", "1w:rsi"}
    assert au._family_key("1w:disparity(20)") == "1w:disparity"
    assert "rvol (1 of 2)" in au.learned_lines(rec)[0]


def test_the_autopsy_runs_on_a_real_strategy_with_second_opinions(
    client: Any, ctx: AppContext
) -> None:
    from backend.metis import brief
    from tests.metis.test_metis import FIVE, _strategy
    from tests.strategy.test_backtest_api import make_strategy

    sid, _vid = _strategy(client)
    make_strategy(client, "rsi_mean_reversion", "IN")  # a second opinion of the same kind
    make_strategy(client, "ma_crossover", "IN")  # and one of another style
    b = brief.baseline(ctx, sid)
    assert b is not None and [i.symbol for i in b.spec.instruments] == FIVE
    found = au.run_autopsy(ctx, b)
    study = [t for t in b.out.trades if t.closed and t.exit_ts < b.split_ms]
    assert len(study) >= au.MIN_TRADES  # practice data gives enough trades for the full path
    assert found is not None and found.lines[0].startswith("Trade autopsy of")
    assert any("Second opinions" in line for line in found.lines), found.lines
    for seed in found.seeds:  # every idea is an ordinary filter Metis can test
        assert seed["kind"] == "filter" and seed["conditions"]
        assert all(c.get("probe") for c in seed["conditions"])
    again = au.run_autopsy(ctx, b)  # cached: same answer, no new runs
    assert again is not None and again.rules == found.rules
    text = brief.build(ctx, "", ["IN"]).text
    assert "Trade autopsy" in text and "exam" not in text.lower()


def test_the_screen_gets_the_autopsy_lines_by_strategy() -> None:
    from backend.metis.notebook import autopsy_of

    brief = (
        "STRATEGY #3 “Golden cross” (visual, India)\nRules…\n"
        "Trade autopsy of 40 study-year trades.\n"
        "What separated its losers from its winners: thin volume.\n"
        "STRATEGY #4 “Other” (code, US)\nNothing here."
    )
    assert autopsy_of(brief) == [
        {
            "strategy": "#3 “Golden cross”",
            "lines": [
                "Trade autopsy of 40 study-year trades.",
                "What separated its losers from its winners: thin volume.",
            ],
        }
    ]


def test_a_new_strategy_without_its_description_uses_what_the_model_did_write() -> None:
    from backend.metis.think import clean_idea

    got = clean_idea(
        {
            "kind": "new_strategy",
            "title": "RSI dip in uptrend",
            "why": "Buy RSI(2) under 10 above SMA200",
        }
    )
    assert got is not None and got["idea"] == "RSI dip in uptrend. Buy RSI(2) under 10 above SMA200"
    got = clean_idea(
        {"kind": "new_strategy", "idea": "", "rules": ["buy when RSI < 30", "sell > 70"]}
    )
    assert got is not None and got["idea"] == "buy when RSI < 30; sell > 70"


def test_metis_gives_way_to_a_kairos_chat() -> None:
    """D-120: Metis stops thinking (closing the stream stops the model) when the user chats."""
    from types import SimpleNamespace

    from backend.metis import think

    closed: list[bool] = []

    def events() -> Any:
        try:
            for _ in range(100):
                yield SimpleNamespace(kind="thinking", text="hmm ")
        finally:
            closed.append(True)

    provider = SimpleNamespace(chat_tools=lambda *a, **k: events())
    chatting = iter([False, False, True])
    with pytest.raises(think.GaveWay):
        think.think(provider, "evidence", model="m", num_ctx=1, give_way=lambda: next(chatting))
    assert closed == [True]
