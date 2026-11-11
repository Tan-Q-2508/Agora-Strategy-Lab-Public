"""Idea → strategy draft: schema, validation, retry with plain-English problems."""

from __future__ import annotations

import json

from backend.ai.draft import _fill, draft, schema
from backend.fakes.ai_provider import FakeAIProvider

GOOD = {
    "explanation": "Buys on RSI below 30.",
    "unsupported": ["news sentiment"],
    "definition": {
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
    },
}
BAD = {
    **GOOD,
    "definition": {
        **GOOD["definition"],
        "entry": {
            "long": {
                "type": "compare",
                "left": {"kind": "indicator", "name": "magic_line", "params": {}},
                "op": "above",
                "right": {"kind": "number", "value": 1},
            }
        },
    },
}


def test_schema_leaves_the_definition_to_the_validator() -> None:
    # Ollama's grammar for the full definition schema forced nonsense rules (D-104).
    s = schema()
    assert "$defs" not in s and s["properties"]["definition"] == {"type": "object"}
    assert s["required"] == ["explanation", "unsupported", "definition"]


def test_small_model_slips_are_tidied() -> None:
    raw = {
        "entry": {
            "long": {
                "type": "all",
                "conditions": [
                    {
                        "kind": "compare",
                        "left": {"kind": "indicator", "name": "rsi", "params": {"period": 14}},
                        "op": "below",
                        "right": {"kind": "number", "value": 30},
                    }
                ],
            }
        },
        "exit": {"long": None},
        "stop_loss": {"type": "percent", "value": -5},
        "short": None,
    }
    out = _fill(raw, "IN")
    assert out is not None and "stop_loss" not in out and "short" not in out
    assert out["exit"]["stop_loss"] == {"kind": "percent", "value": 5.0}
    assert out["entry"]["long"]["conditions"][0]["type"] == "compare"
    assert out["entry"]["long"]["conditions"][0]["left"]["kind"] == "indicator"


def test_invalid_draft_is_retried_with_the_problems() -> None:
    ai = FakeAIProvider(replies=[json.dumps(BAD), json.dumps(GOOD)])
    r = draft(ai, model="m", idea="buy oversold stocks", market="IN", num_ctx=8192)
    assert r.ok and r.attempts == 2
    assert r.unsupported == ["news sentiment"]
    assert r.definition is not None and r.definition["market"] == "IN"
    assert r.definition["product"] == "delivery"
    retry = ai.calls[1]["messages"][-1].content
    assert retry.startswith("That strategy has problems Agora found:\n- ")
    assert ai.calls[0]["format"]["properties"]["definition"]


def test_gives_up_after_two_retries() -> None:
    ai = FakeAIProvider(replies=["not json", json.dumps(BAD), json.dumps(BAD)])
    r = draft(ai, model="m", idea="something odd", market="US", num_ctx=8192)
    assert not r.ok and r.attempts == 3
    assert r.issues and any(i.severity == "error" for i in r.issues)
    assert "wasn't valid JSON" in ai.calls[1]["messages"][-1].content


def test_more_small_model_slips_become_valid_rules() -> None:
    """D-123: bare numbers and price names, ">" for "above", missing or other type names."""
    from backend.strategy.validator import validate

    raw = {
        "timeframe": "1d",
        "entry": {
            "long": {
                "type": "and",
                "conditions": [
                    {
                        "left": {"indicator": "rsi", "params": {"period": 14}},
                        "op": "<",
                        "right": 30,
                    },
                    {
                        "type": "crossover",
                        "left": "close",
                        "right": {"name": "sma", "params": {"period": 50}},
                    },
                ],
            }
        },
        "exit": {
            "long": {
                "left": {"indicator": "rsi", "params": {"period": 14}},
                "operator": ">=",
                "right": "70",
            }
        },
    }
    out = _fill(raw, "IN")
    assert out is not None
    c1, c2 = out["entry"]["long"]["conditions"]
    assert out["entry"]["long"]["type"] == "all"
    assert c1 == {
        "type": "compare",
        "left": {"kind": "indicator", "name": "rsi", "params": {"period": 14}},
        "op": "below",
        "right": {"kind": "number", "value": 30.0},
    }
    assert c2["type"] == "compare" and c2["op"] == "crosses_above"
    assert c2["left"] == {"kind": "price", "field": "close"}
    assert out["exit"]["long"]["op"] == "at_least"
    assert validate(out).ok, validate(out).errors


def test_a_vwap_idea_runs_on_intraday_candles() -> None:
    raw = {
        "entry": {
            "long": {
                "left": "close",
                "op": "crosses_above",
                "right": {"indicator": "vwap", "output": 0},
            }
        },
    }
    out = _fill(raw, "IN")
    assert out is not None and out["timeframe"] == "15m" and out["product"] == "intraday"
    assert out["entry"]["long"]["right"] == {"kind": "indicator", "name": "vwap", "output": None}
