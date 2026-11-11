"""Idea → Strategy Definition (docs/AI_ASSISTANT.md §5.4).

The model must answer in JSON matching the visual-definition schema (Ollama structured
outputs). The result is checked by the same validator the builder uses; problems go back to
the model in plain English, at most twice. Whatever comes out is only a draft: the user sees
it in the builder and decides whether to save it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.ai import prompts
from backend.core.ai_provider import AIProvider, ChatMessage, ChatOptions
from backend.indicators import catalog
from backend.strategy.templates import template_definition
from backend.strategy.validator import Issue, validate

MAX_RETRIES = 2


@dataclass
class DraftResult:
    ok: bool
    definition: dict[str, Any] | None
    explanation: str = ""
    unsupported: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    attempts: int = 0
    transcript: list[ChatMessage] = field(default_factory=list)


def schema() -> dict[str, Any]:
    """The reply's shape: explanation + unsupported + the definition as a JSON object.

    The definition itself is not constrained here. Ollama 0.40's grammar for the full
    definition schema (nested ``$defs`` references and ``anyOf`` rule types) forced Qwen 3.5
    into the first rule type with its fields as strings ("time" rules for an RSI idea, seen on
    the laptop 2026-10-24); unconstrained, it follows the example in the prompt. The same
    validator the builder uses checks the result and sends problems back (D-104)."""
    return {
        "type": "object",
        "properties": {
            "explanation": {"type": "string"},
            "unsupported": {"type": "array", "items": {"type": "string"}},
            "definition": {"type": "object"},
        },
        "required": ["explanation", "unsupported", "definition"],
    }


def indicator_list() -> str:
    lines = []
    for ind in catalog.catalog():
        params = ", ".join(f"{p['name']}={p['default']:g}" for p in ind["params"])
        outputs = ind["outputs"]
        out = f" (outputs: {', '.join(o['key'] for o in outputs)})" if len(outputs) > 1 else ""
        lines.append(f"- {ind['key']}: {params or 'no settings'}{out}")
    return "\n".join(lines)


def _defaults(market: str) -> dict[str, Any]:
    base: dict[str, Any] = json.loads(template_definition("ma_crossover", market).model_dump_json())
    base["entry"] = {"long": None, "short": None}
    base["exit"] = {
        "long": None,
        "short": None,
        "stop_loss": None,
        "take_profit": None,
        "trailing_stop": None,
        "max_bars": None,
        "exit_time": None,
    }
    base["parameters"] = []
    return base


EXIT_KEYS = ("stop_loss", "take_profit", "trailing_stop", "max_bars", "exit_time")


def _stop(v: Any) -> Any:
    """A stop the way small models write it (5, "5%", {"type": "percent", "value": -5})
    → {"kind": "percent", "value": 5}."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        return {"kind": "percent", "value": abs(float(v))}
    if isinstance(v, str):
        try:
            return {"kind": "percent", "value": abs(float(v.strip().rstrip("%")))}
        except ValueError:
            return v
    if isinstance(v, dict):
        out = dict(v)
        if "kind" not in out and out.get("type") in ("percent", "atr"):
            out["kind"] = out.pop("type")
        if str(out.get("kind", "")).startswith("percent"):
            out["kind"] = "percent"
        if isinstance(out.get("value"), int | float):
            out["value"] = abs(float(out["value"]))
        return out
    return v


RULE_TYPES = ("compare", "between", "all", "any", "not", "time", "position")


PRICE_FIELDS = ("open", "high", "low", "close", "volume")
TYPE_ALIASES = {
    "and": "all",
    "or": "any",
    "comparison": "compare",
    "condition": "compare",
    "cross": "compare",
    "crossover": "compare",
    "crossunder": "compare",
}
OP_ALIASES = {
    ">": "above",
    "<": "below",
    ">=": "at_least",
    "<=": "at_most",
    "greater_than": "above",
    "less_than": "below",
    "gt": "above",
    "lt": "below",
    "gte": "at_least",
    "lte": "at_most",
    "cross_above": "crosses_above",
    "crossover": "crosses_above",
    "crosses_over": "crosses_above",
    "cross_below": "crosses_below",
    "crossunder": "crosses_below",
    "crosses_under": "crosses_below",
}


def _operand(v: Any) -> Any:
    """An operand the way small models write it (30, "close", {"indicator": "rsi"}) → Agora's
    shape (D-123: about a third of Metis's untestable new strategies on the laptop)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int | float):
        return {"kind": "number", "value": float(v)}
    if isinstance(v, str):
        t = v.strip().lower()
        if t in PRICE_FIELDS:
            return {"kind": "price", "field": t}
        try:
            return {"kind": "number", "value": float(t)}
        except ValueError:
            return v
    if not isinstance(v, dict):
        return v
    out = dict(v)
    if "kind" not in out and out.get("type") in ("number", "price", "indicator"):
        out["kind"] = out.pop("type")
    if "kind" not in out:
        if "indicator" in out:
            out["kind"], out["name"] = "indicator", out.pop("indicator")
        elif "name" in out:
            out["kind"] = "indicator"
        elif "field" in out:
            out["kind"] = "price"
        elif "value" in out:
            out["kind"] = "number"
    if out.get("kind") == "indicator" and "output" in out and not isinstance(out["output"], str):
        out["output"] = None  # a line given as a number or list: use the main line
    if out.get("kind") == "price" and str(out.get("field", "")).lower() in PRICE_FIELDS:
        out["field"] = str(out["field"]).lower()
    return out


def _rule(v: Any) -> Any:
    """Rules as small models write them → Agora's shape: "kind" where Agora says "type",
    a missing or other type name for a comparison, ">" for "above", bare operands."""
    if isinstance(v, list):
        return [_rule(x) for x in v]
    if not isinstance(v, dict):
        return v
    out = {k: _rule(x) if k in ("conditions", "condition") else x for k, x in v.items()}
    if "type" not in out and out.get("kind") in RULE_TYPES:
        out["type"] = out.pop("kind")
    raw_type = str(out.get("type", "")).lower()
    if raw_type in TYPE_ALIASES:
        out["type"] = TYPE_ALIASES[raw_type]
        if raw_type in ("crossover", "cross") and "op" not in out:
            out["op"] = "crosses_above"
        if raw_type == "crossunder" and "op" not in out:
            out["op"] = "crosses_below"
    if "type" not in out and "left" in out and "right" in out:
        out["type"] = "compare"
    if "op" not in out and "operator" in out:
        out["op"] = out.pop("operator")
    if isinstance(out.get("op"), str):
        op = out["op"].strip().lower().replace(" ", "_")
        out["op"] = OP_ALIASES.get(op, op)
    if out.get("type") == "compare":
        for side in ("left", "right"):
            if side in out:
                out[side] = _operand(out[side])
    return out


def _fill(raw: Any, market: str) -> dict[str, Any] | None:
    """Agora's defaults for anything the model left out; market and kind are fixed. Stops
    and targets written next to the rules instead of inside "exit" are moved there, and
    empty extras the model added are dropped (seen with Qwen 3.5 on the laptop)."""
    if not isinstance(raw, dict):
        return None
    out = _defaults(market)
    exit_extra: dict[str, Any] = {}
    for k, v in raw.items():
        if k in ("market", "kind", "schema_version"):
            continue
        if k in EXIT_KEYS:
            if v is not None:
                exit_extra[k] = v
            continue
        if k not in out and v is None:
            continue
        out[k] = v
    if isinstance(out.get("exit"), dict):
        ex = {k: v for k, v in out["exit"].items() if k in (*EXIT_KEYS, "long", "short")}
        ex = {k: _rule(v) if k in ("long", "short") else v for k, v in ex.items()}
        ex.update(exit_extra)
        for k in ("stop_loss", "take_profit", "trailing_stop"):
            if ex.get(k) is not None:
                ex[k] = _stop(ex[k])
        out["exit"] = {**_defaults(market)["exit"], **ex}
    if isinstance(out.get("entry"), dict):
        out["entry"] = {
            "long": _rule(out["entry"].get("long")),
            "short": _rule(out["entry"].get("short")),
        }
    rules = json.dumps([out.get("entry"), out.get("exit")])
    if out.get("timeframe", "1d") == "1d" and '"vwap"' in rules:
        # VWAP is a within-the-day average: an idea built on it is an intraday idea (D-123)
        out["timeframe"] = "15m"
        if market == "IN":
            out["product"] = "intraday"
    return out


def draft(
    provider: AIProvider,
    *,
    model: str,
    idea: str,
    market: str,
    num_ctx: int,
    known_symbol: Callable[[str], bool] | None = None,
) -> DraftResult:
    example = json.loads(template_definition("ma_crossover", market).model_dump_json())
    messages = [
        ChatMessage("system", prompts.system()),
        ChatMessage(
            "user",
            prompts.render(
                "draft_strategy",
                indicators=indicator_list(),
                market=market,
                example=json.dumps(example, separators=(",", ":")),
                idea=idea.strip()[:2000],
            ),
        ),
    ]
    result = DraftResult(ok=False, definition=None)
    for attempt in range(1 + MAX_RETRIES):
        result.attempts = attempt + 1
        reply = provider.chat(
            messages,
            model=model,
            stream=False,
            format=schema(),
            options=ChatOptions(num_ctx=num_ctx, temperature=0.1),
        )
        assert isinstance(reply, str)
        messages.append(ChatMessage("assistant", reply))
        try:
            obj = json.loads(reply)
        except json.JSONDecodeError:
            obj = None
        if not isinstance(obj, dict):
            problems = "- The reply wasn't valid JSON. Reply with JSON only."
        else:
            result.explanation = str(obj.get("explanation", "")).strip()
            result.unsupported = [str(x) for x in obj.get("unsupported", []) if str(x).strip()]
            definition = _fill(obj.get("definition"), market)
            if definition is None:
                problems = '- The "definition" part is missing.'
            else:
                checked = validate(definition, known_symbol=known_symbol)
                errors = [i for i in checked.issues if i.severity == "error"]
                result.definition = (
                    checked.definition.model_dump(mode="json")
                    if checked.definition is not None
                    else definition
                )
                result.issues = checked.issues
                if not errors:
                    result.ok = True
                    break
                problems = "\n".join(f"- {i.sentence()}" for i in errors[:10])
        if attempt < MAX_RETRIES:
            messages.append(ChatMessage("user", prompts.render("draft_retry", issues=problems)))
    result.transcript = messages
    return result
