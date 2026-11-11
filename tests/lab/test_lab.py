"""The lab (D-143): a whole research sprint on the practice data, offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.context import AppContext
from backend.core.types import Market
from backend.db.models import LabTest
from backend.lab import families, ledger, playbook, runner, vault
from backend.lab.__main__ import main
from backend.strategy.validator import validate

DAY = 86_400_000


def test_every_family_is_valid_rules_on_every_market_and_timeframe() -> None:
    syms = [f"S{i}" for i in range(30)]
    keys = set()
    for f in families.FAMILIES:
        assert f.key not in keys and len(f.why) > 60
        keys.add(f.key)
        for m in f.markets:
            for tf in f.timeframes:
                res = validate(f.definition(m, tf, syms))
                assert res.ok, (f.key, m, tf, [e.sentence() for e in res.errors])
        assert len(f.variants()) <= 18, f"{f.key}: keep grids small (the luck check counts them)"


def test_the_vault_is_recent_history() -> None:
    now = 1_767_225_600_000
    assert vault.start("1d", now) == now - 365 * DAY
    assert vault.start("5m", now) > vault.start("1h", now) > vault.start("1d", now)


def test_universe_is_most_traded_first(stocked: AppContext) -> None:
    syms = runner.universe(stocked, "IN", "1d", 5)
    assert len(syms) == 5
    values = []
    with stocked.db.session() as s:
        from backend.data import store

        for sym in syms:
            values.append(runner.traded_value(stocked, store.find_instrument(s, Market.IN, sym)))
    assert values == sorted(values, reverse=True)


def test_a_whole_sprint(
    stocked: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = ["sma_cross", "trend_dip_rsi", "ranking_momentum"]
    out = runner.run_sprint(stocked, "t1", family_keys=keys, markets=["IN"], stocks=9)
    n = out["tested"]
    assert n == sum(len(families.BY_KEY[k].variants()) or 1 for k in keys)
    rows = ledger.rows(stocked, "t1")
    r = rows[0]
    # research never reaches into the vault
    assert r["split_ms"] < r["vault_ms"] < r["end_ms"] and r["vault"] is None
    assert r["vault_ms"] == vault.start("1d", stocked.clock.now_ms())
    assert {"trades", "net", "sharpe", "win_rate"} <= set(r["study"])
    assert "returns" in r["exam"] and "returns" not in r["study"]
    assert r["regimes"] and set(r["regimes"]) <= {*runner.measure.regime_map.REGIMES, "unknown"}
    # running again tests nothing twice
    assert (
        runner.run_sprint(stocked, "t1", family_keys=keys, markets=["IN"], stocks=9)["tested"] == 0
    )
    assert ledger.tries(stocked, "t1") == n
    # nor when the most-traded list shifts a place between runs (new prices arrived)
    real = runner.universe
    monkeypatch.setattr(runner, "universe", lambda *a, **k: list(reversed(real(*a, **k))))
    assert (
        runner.run_sprint(stocked, "t1", family_keys=keys, markets=["IN"], stocks=9)["tested"] == 0
    )
    monkeypatch.setattr(runner, "universe", real)
    text = runner.report(stocked, "t1")
    assert "sma_cross · IN · 1d" in text and "study" in text

    # force one finalist so the vault and the playbook are exercised whatever the practice
    # data says (the finalist rules themselves are tested below)
    monkeypatch.setattr(runner, "checks", lambda row, tries: [("ok", True)])
    finalists = runner.pick_finalists(stocked, "t1")
    assert len(finalists) == len(keys)  # one per family, market and timeframe
    opened = runner.open_vault(stocked, "t1")
    assert len(opened) == len(keys)
    assert all(o["status"] in ("promoted", "failed_vault") and o["vault"] for o in opened)
    assert runner.open_vault(stocked, "t1") == []  # never twice
    with stocked.db.session() as s:
        assert all(
            row.vault_opened_at for row in s.query(LabTest).filter(LabTest.status != "tested")
        )

    path = tmp_path / "playbook.json"
    monkeypatch.setattr(playbook, "PATH", path)
    for row in ledger.rows(stocked, "t1", status=["failed_vault"]):
        ledger.update(stocked, row["id"], status="promoted")  # make sure one entry is written
    assert main(["promote", "--sprint", "t1"], ctx=stocked) == 0
    entries = playbook.load(path)
    assert len(entries) == len(keys)
    e = entries[0]
    assert {"key", "why", "definition", "works_in", "avoid_in", "vault"} <= set(e)
    assert "returns" not in json.dumps(e["exam"])  # summary numbers only
    assert validate(e["definition"]).ok


def test_finalist_rules() -> None:
    good = {
        "study": {"trades": 80, "net": 5000.0, "profit_factor": 1.4, "stocks": 10, "stocks_up": 7},
        "exam": {
            "trades": 30,
            "net": 2000.0,
            "profit_factor": 1.3,
            "returns": [0.001, -0.0005] * 200,
            "sharpe": 1.4,
            "index_sharpe": 0.9,
        },
    }
    found = runner.checks(good, 9)
    assert all(ok for _s, ok in found), found
    thin = {**good, "exam": {**good["exam"], "trades": 5}}
    assert not all(ok for _s, ok in runner.checks(thin, 9))
    narrow = {**good, "study": {**good["study"], "stocks_up": 2}}
    assert not all(ok for _s, ok in runner.checks(narrow, 9))
    beaten = {**good, "exam": {**good["exam"], "sharpe": 0.6}}
    assert not all(ok for _s, ok in runner.checks(beaten, 9))  # holding the index did better
    luckless = {**good, "exam": {**good["exam"], "returns": [0.0001, -0.0001] * 200}}
    assert not all(ok for _s, ok in runner.checks(luckless, 9))


def test_a_lone_winner_among_losing_neighbours_is_luck() -> None:
    f = families.BY_KEY["trend_dip_rsi"]
    rows = []
    for i, v in enumerate(f.variants()):
        rows.append({"id": i, "variant": v, "study": {"net": -100.0}})
    lone = next(r for r in rows if r["variant"] == {"rsi_len": 3, "dip": 10})
    lone["study"]["net"] = 900.0
    assert not runner.neighbours_hold(lone, f, rows)
    for r in rows:
        r["study"]["net"] = 50.0
    assert runner.neighbours_hold(lone, f, rows)


def test_playbook_matches_regimes() -> None:
    a = {
        "key": "a",
        "market": "IN",
        "timeframe": "1d",
        "works_in": ["up-calm"],
        "avoid_in": [],
        "regimes": {"up-calm": {"avg_return_pct": 0.8}},
    }
    b = {
        "key": "b",
        "market": "IN",
        "timeframe": "1d",
        "works_in": [],
        "avoid_in": ["up-calm"],
        "regimes": {},
    }
    c = {
        "key": "c",
        "market": "IN",
        "timeframe": "1d",
        "works_in": ["down-volatile"],
        "avoid_in": [],
        "regimes": {},
    }
    assert [e["key"] for e in playbook.for_regime([a, b, c], "IN", "1d", "up-calm")] == ["a", "c"]
    good, bad = playbook.homes(
        {
            "up-calm": {"trades": 20, "avg_return_pct": 0.5},
            "down-calm": {"trades": 30, "avg_return_pct": -0.2},
            "sideways-calm": {"trades": 3, "avg_return_pct": 2.0},
        }
    )
    assert good == ["up-calm"] and bad == ["down-calm"]


def test_the_committed_playbook_is_valid() -> None:
    for e in playbook.load():
        assert validate(e["definition"]).ok, e["key"]
