"""Revision control (docs/REVISIONS.md, D-79, D-80): what changed, "same strategy?", the one door
for Kairos and Metis, restore, and the API."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.db.models import Strategy
from backend.strategy import diff, lineage, revisions
from backend.strategy import service as svc
from backend.strategy.definition import CodeDefinition, StopSpec, Universe, VisualDefinition
from backend.strategy.templates import template_definition
from backend.strategy.validator import validate
from tests.strategy.test_backtest_api import make_strategy


def _rsi() -> VisualDefinition:
    d = template_definition("rsi_mean_reversion", "IN")
    assert isinstance(d, VisualDefinition)
    return d


def _with_long(d: VisualDefinition, extra: dict[str, Any]) -> VisualDefinition:
    data = d.model_dump(mode="json")
    data["entry"]["long"]["conditions"].append(extra)
    res = validate(data)
    assert res.ok and isinstance(res.definition, VisualDefinition), res.errors
    return res.definition


ADX = {
    "type": "compare",
    "left": {"kind": "indicator", "name": "adx", "params": {"period": 14}},
    "op": "at_least",
    "right": {"kind": "number", "value": 20},
}


# ---------------------------------------------------------------- what changed


def test_changes_in_plain_words() -> None:
    a = _rsi()
    assert diff.changes(None, a) == ["First version."]
    assert diff.changes(a, a) == []
    b = _with_long(a, ADX)
    params = [
        p.model_copy(update={"default": 10.0}) if p.name == "rsi_len" else p for p in b.parameters
    ]
    b = b.model_copy(
        update={
            "parameters": params,
            "exit": b.exit.model_copy(update={"stop_loss": StopSpec(kind="percent", value=2.5)}),
            "universe": Universe(kind="symbols", symbols=["TCS", "INFY"]),
        }
    )
    out = diff.changes(a, b)
    assert "Stocks: now TCS, INFY." in out
    assert "RSI length (rsi_len): 14 → 10." in out
    assert "Added to buys: adx(period=14) at least 20." in out
    assert any(x.startswith("Stop loss") and "2.5%" in x for x in out)
    # dropping the filter again reads as a removal
    assert "Removed from buys: adx(period=14) at least 20." in diff.changes(b, a)


def test_code_changes_count_lines() -> None:
    a = CodeDefinition(market="US", product="cash", code="def on_bar(ctx):\n    pass\n")
    b = a.model_copy(update={"code": "def on_bar(ctx):\n    x = 1\n    pass\n"})
    assert diff.changes(a, b) == ["Code changed (1 line added or removed)."]


# ---------------------------------------------------------------- same strategy?


def test_same_logic_ignores_numbers_and_a_filter_or_two() -> None:
    a = _rsi()
    tuned = a.model_copy(
        update={"parameters": [p.model_copy(update={"default": p.max}) for p in a.parameters]}
    )
    filtered = _with_long(a, ADX)
    sig = lineage.signature(a)
    for other, why in ((tuned, "different numbers"), (filtered, "a filter")):
        ok, sim, text = lineage.same(sig, lineage.signature(other))
        assert ok and sim >= lineage.SAME and why in text, (other, text)
    # another indicator is another strategy
    macd = template_definition("macd_momentum", "IN")
    assert not lineage.same(sig, lineage.signature(macd))[0]
    # the same rules in another market are another strategy
    assert not lineage.same(sig, lineage.signature(_rsi().model_copy(update={"market": "US"})))[0]


def test_a_number_on_the_left_is_turned_round() -> None:
    a = _rsi()
    data = a.model_dump(mode="json")
    first = data["entry"]["long"]["conditions"][0]  # rsi crosses below $oversold
    data["entry"]["long"]["conditions"][0] = {
        **first,
        "left": first["right"],
        "right": first["left"],
        "op": "crosses_above",
    }
    flipped = validate(data).definition
    assert flipped is not None
    assert lineage.signature(flipped).entry == lineage.signature(a).entry


def test_code_is_the_same_apart_from_numbers_and_comments() -> None:
    code = "def on_bar(ctx):\n    if ctx.ind.rsi(ctx.close, 14)[-1] < 30:\n        ctx.buy()\n"
    a = CodeDefinition(market="IN", product="delivery", code=code)
    b = a.model_copy(update={"code": "# tuned\n" + code.replace("14", "10").replace("30", "25")})
    c = a.model_copy(update={"code": code.replace("rsi", "cci")})
    assert lineage.same(lineage.signature(a), lineage.signature(b))[0]
    assert not lineage.same(lineage.signature(a), lineage.signature(c))[0]


# ---------------------------------------------------------------- the one door


def test_save_reuses_revises_or_creates(ctx: AppContext) -> None:
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        first = revisions.save(
            s, definition=_rsi(), author="kairos", name="RSI", description="", now=now, note="x"
        )
        assert first.outcome == "new_strategy"
        again = revisions.save(
            s, definition=_rsi(), author="kairos", name="RSI 2", description="", now=now, note="x"
        )
        assert again.outcome == "unchanged" and again.strategy_id == first.strategy_id
        better = revisions.save(
            s,
            definition=_with_long(_rsi(), ADX),
            author="metis",
            name="RSI filtered",
            description="",
            now=now,
            note="Metis: trend strength filter",
            evidence={"verdict": "Held up"},
            source="metis-idea:1",
        )
        assert better.outcome == "revision" and better.strategy_id == first.strategy_id
        assert better.version == 2 and "Added to buys" in better.changes[0]
        v2 = svc.get_version(s, better.version_id)
        assert v2 is not None and v2.created_by == "metis" and v2.source == "metis-idea:1"
        assert v2.parent_version_id == first.version_id and v2.evidence == {"verdict": "Held up"}
        n = s.query(Strategy).count()
        assert n == 1  # three saves, one strategy
        other = revisions.save(
            s,
            definition=template_definition("macd_momentum", "IN"),
            author="metis",
            name="MACD",
            description="",
            now=now,
            note="x",
            new_per_day=1,
        )
        assert other.outcome == "new_strategy"
        with pytest.raises(revisions.NewStrategyLimit):
            revisions.save(
                s,
                definition=template_definition("donchian_breakout", "IN"),
                author="metis",
                name="Donchian",
                description="",
                now=now,
                note="x",
                new_per_day=1,
            )


def test_restore_makes_a_new_version(ctx: AppContext) -> None:
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        row, v1 = svc.create(s, name="RSI", description="", definition=_rsi(), now=now)
        v2 = svc.add_version(s, row, _with_long(_rsi(), ADX), now + 1, note="filter")
        v3 = svc.restore(s, row, v1.id, now + 2)
        assert v3.version == 3 and v3.content_hash == v1.content_hash
        assert v3.source == f"restore:{v1.id}" and v3.parent_version_id == v2.id
        assert v3.changes == ("Removed from buys: adx(period=14) at least 20.",)
        assert [v.version for v in svc.versions(s, row.id)] == [3, 2, 1]


# ---------------------------------------------------------------- API


def test_revision_api(client: TestClient) -> None:
    created = make_strategy(client, "rsi_mean_reversion")
    sid, d = created["strategy"]["id"], created["version"]["definition"]
    d2 = _with_long(VisualDefinition.model_validate(d), ADX).model_dump(mode="json")
    v2 = client.post(f"/api/strategies/{sid}/versions", json={"definition": d2}).json()["version"]
    assert v2["author_label"] == "You" and v2["changes"][0].startswith("Added to buys")
    listed = client.get(f"/api/strategies/{sid}/versions").json()["versions"]
    assert listed[0]["parent_version_id"] == listed[1]["id"]
    got = client.get(f"/api/strategies/{sid}/diff", params={"to": v2["id"]}).json()
    assert got["changes"] == v2["changes"] and got["from"]["version"] == 1
    back = client.post(f"/api/strategies/{sid}/versions/{listed[1]['id']}/restore").json()
    assert back["version"]["version"] == 3 and back["version"]["note"] == "Restored version 1"
    r = client.post(f"/api/strategies/{sid}/versions/999999/restore")
    assert r.status_code == 404
    # an old-style copy shows up as the same logic
    copy = client.post(f"/api/strategies/{sid}/duplicate").json()["strategy"]["id"]
    fam = client.get(f"/api/strategies/{sid}/family").json()["same_logic"]
    assert [f["strategy_id"] for f in fam] == [copy]
    cards = client.get("/api/strategies").json()["strategies"]
    assert {c["version_author"] for c in cards if c["id"] == sid} == {"user"}
