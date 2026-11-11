from __future__ import annotations

from typing import Any

import pytest

from backend.strategy.definition import VisualDefinition, content_hash, json_schema
from backend.strategy.templates import TEMPLATES, template_definition
from backend.strategy.validator import describe, validate


def base(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": "visual",
        "market": "IN",
        "product": "delivery",
        "universe": {"kind": "symbols", "symbols": ["RELIANCE"]},
        "timeframe": "1d",
        "entry": {
            "long": {
                "type": "compare",
                "left": {"kind": "indicator", "name": "rsi", "params": {"period": 14}},
                "op": "crosses_below",
                "right": {"kind": "number", "value": 30},
            }
        },
        "exit": {"stop_loss": {"kind": "percent", "value": 5}},
    }
    d.update(over)
    return d


def messages(raw: dict[str, Any]) -> list[str]:
    return [f"{i.where}: {i.message}" for i in validate(raw).issues]


@pytest.mark.parametrize("key", sorted(TEMPLATES))
@pytest.mark.parametrize("market", ["IN", "US"])
def test_every_template_is_valid(key: str, market: str) -> None:
    r = validate(template_definition(key, market))
    assert r.ok, [i.sentence() for i in r.issues]
    assert not r.issues, [i.sentence() for i in r.issues]


def test_a_simple_rule_is_valid() -> None:
    r = validate(base())
    assert r.ok and r.issues == []


def test_missing_and_unknown_fields_are_plain_english() -> None:
    raw = base()
    del raw["entry"]["long"]["op"]
    raw["entry"]["long"]["colour"] = "red"
    msgs = messages(raw)
    assert "Buy rule › op: is missing." in msgs
    assert "Buy rule › colour: isn't something Agora understands." in msgs


def test_wrong_option_lists_the_choices() -> None:
    raw = base()
    raw["entry"]["long"]["op"] = "explodes"
    (issue,) = validate(raw).issues
    assert issue.where == "Buy rule › op"
    assert issue.message.startswith("must be one of: 'above', 'below'")
    assert issue.hint == "Pick one of the listed options."


def test_semantic_checks() -> None:
    raw = base(product="delivery")
    raw["entry"]["short"] = raw["entry"]["long"]
    assert any("short-selling isn't allowed" in m for m in messages(raw))

    raw = base()
    raw["entry"]["long"]["left"] = {"kind": "indicator", "name": "magic"}
    assert messages(raw) == ["Buy rule › left side › name: “magic” isn't an indicator Agora has."]

    raw = base()
    raw["entry"]["long"]["left"]["params"] = {"period": 0}
    assert messages(raw) == [
        "Buy rule › left side › settings › period: Length (candles) can't be below 1 (it allows 0)."
    ]

    raw = base()
    raw["entry"]["long"]["left"] = {"kind": "indicator", "name": "vwap"}
    assert any("only works on intraday candles" in m for m in messages(raw))

    raw = base()
    raw["entry"]["long"]["left"] = {"kind": "number", "value": 3}
    assert any("compares two fixed numbers" in m for m in messages(raw))

    raw = base()  # D-161: "%B at least %B" is always true
    raw["entry"]["long"]["right"] = dict(raw["entry"]["long"]["left"])
    assert any("compares a value with itself" in m for m in messages(raw))

    raw = base(sizing={"kind": "risk_percent", "value": 1}, exit={})
    assert any("risk-based sizing needs a stop-loss" in m for m in messages(raw))

    raw = base(market="US", product="delivery")
    assert any("US stocks use the “cash” trade type" in m for m in messages(raw))

    raw = base()
    raw["entry"]["long"]["right"]["value"] = "$level"
    assert any("parameter 'level', which doesn't exist" in m for m in messages(raw))


def test_exit_time_needs_intraday_and_market_hours() -> None:
    raw = base(exit={"exit_time": "15:15"})
    assert any("needs intraday candles" in m for m in messages(raw))
    raw = base(timeframe="5m", product="intraday", exit={"exit_time": "16:15"})
    assert any("outside market hours" in m for m in messages(raw))


def test_parameters_are_checked() -> None:
    raw = base(
        parameters=[
            {"name": "level", "label": "Level", "default": 50, "min": 10, "max": 40},
            {"name": "level", "label": "Again", "default": 1, "min": 0, "max": 2},
        ]
    )
    raw["entry"]["long"]["right"]["value"] = "$level"
    msgs = messages(raw)
    assert any("its default is outside its range" in m for m in msgs)
    assert any("is used twice" in m for m in msgs)


def test_unknown_symbols_use_the_lookup() -> None:
    r = validate(base(), known_symbol=lambda s: s == "TCS")
    assert [i.message for i in r.issues] == ["Agora doesn't know the stock RELIANCE."]


def test_code_strategy_errors_name_the_line() -> None:
    raw = base(kind="code", code="def on_bar(ctx):\n    x = = 1\n")
    for k in ("entry", "exit"):
        raw.pop(k)
    (issue,) = validate(raw).issues
    assert issue.where == "Code, line 2"


def test_describe_paths() -> None:
    assert (
        describe(("entry", "long", "conditions", 1, "right"))
        == "Buy rule › condition 2 › right side"
    )
    assert describe(("exit", "stop_loss", "value")) == "Stop-loss › value"


def test_hash_is_stable_and_schema_exports() -> None:
    a = template_definition("rsi_mean_reversion", "IN")
    b = VisualDefinition.model_validate(a.model_dump())
    assert content_hash(a) == content_hash(b)
    schema = json_schema()
    assert schema["title"] == "VisualDefinition" and "$defs" in schema
