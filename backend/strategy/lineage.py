"""Is it the same strategy? (docs/REVISIONS.md §3, D-79)

A strategy is its logic. Kairos and Metis must never save a copy of a strategy the user already
has, so before saving anything "new" they ask this module for its *family*: an existing strategy
with the same logic, whatever the numbers.

The check is structural, so it is fast and easy to explain:

- Each visual condition becomes a token: the side (buys, short sales, selling, covering), the
  left operand (indicator name and output, or price field), the direction (up: above, at least,
  crosses above; down: below, at most, crosses below) and the kind of right operand (a number,
  a price field, or an indicator's name). Settings and numbers are ignored, and a number on the
  left is turned round ("30 above RSI" is "RSI below 30").
- Similarity = 0.75 × overlap (Jaccard) of the entry tokens + 0.25 × overlap of the exit
  tokens, for the same market and kind; 0 otherwise.
- Same family when similarity ≥ 0.75; or when one's entry tokens contain the other's with at
  most two extra (a filtered variant: Metis's filters make revisions, not strategies); or when
  both came from the same starter template.
- Code strategies are the same when their code matches once comments, spacing and numbers are
  removed. The Kairos brain is one strategy per market.
"""

from __future__ import annotations

import io
import json
import re
import tokenize
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Strategy
from backend.strategy.definition import AnyDefinition

SAME = 0.75
MAX_EXTRA_FILTERS = 2
UP = {"above", "at_least", "crosses_above"}
FLIP = {
    "above": "below",
    "below": "above",
    "at_least": "at_most",
    "at_most": "at_least",
    "crosses_above": "crosses_below",
    "crosses_below": "crosses_above",
}


@dataclass(frozen=True)
class Signature:
    kind: str
    market: str
    entry: Counter[str]
    exits: Counter[str]
    code: str = ""


@dataclass(frozen=True)
class Family:
    """The existing strategy a definition belongs to, and how alike they are."""

    strategy_id: int
    name: str
    similarity: float
    why: str  # plain words: "the same rules", "a filtered version", "the same template"


def _operand_key(o: dict[str, Any]) -> str:
    kind = o.get("kind")
    if kind == "number":
        return "number"
    chart = f"@{o['chart']}" if o.get("chart") else ""
    if kind == "price":
        return f"price:{o.get('field', 'close')}{chart}"
    out = f"ind:{o.get('name')}"
    if o.get("output"):
        out += f".{o['output']}"
    return out + chart


def _tokens(c: dict[str, Any] | None, side: str, out: Counter[str]) -> None:
    if not c:
        return
    t = c.get("type")
    if t == "compare":
        left, right, op = c["left"], c["right"], str(c.get("op"))
        if left.get("kind") == "number" and right.get("kind") != "number":
            left, right, op = right, left, FLIP.get(op, op)
        direction = "up" if op in UP else "down"
        out[f"{side}|{_operand_key(left)}|{direction}|{_operand_key(right)}"] += 1
    elif t == "between":
        out[f"{side}|{_operand_key(c['value'])}|between"] += 1
    elif t in ("all", "any"):
        for x in c.get("conditions", []):
            _tokens(x, side, out)
    elif t == "not":
        inner: Counter[str] = Counter()
        _tokens(c.get("condition"), side, inner)
        for k, v in inner.items():
            out[f"not:{k}"] += v
    elif t == "time":
        out[f"{side}|time"] += 1
    elif t == "position":
        out[f"{side}|position:{c.get('check')}"] += 1


_NUMBER = re.compile(r"^\d")


def _code_skeleton(code: str) -> str:
    """The code without comments, spacing or numbers."""
    words: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT):
                continue
            if tok.type in (tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            words.append("N" if tok.type == tokenize.NUMBER else tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return " ".join(_NUMBER.sub("N", w) for w in code.split())
    return " ".join(words)


def signature(d: AnyDefinition | dict[str, Any]) -> Signature:
    data = d if isinstance(d, dict) else d.model_dump(mode="json")
    entry: Counter[str] = Counter()
    exits: Counter[str] = Counter()
    kind = str(data.get("kind"))
    if kind == "visual":
        _tokens((data.get("entry") or {}).get("long"), "buy", entry)
        _tokens((data.get("entry") or {}).get("short"), "short", entry)
        ex = data.get("exit") or {}
        _tokens(ex.get("long"), "sell", exits)
        _tokens(ex.get("short"), "cover", exits)
        for key in ("stop_loss", "take_profit", "trailing_stop"):
            if ex.get(key):
                exits[f"{key}:{ex[key].get('kind')}"] += 1
        if ex.get("max_bars"):
            exits["max_bars"] += 1
    if kind == "ranking":  # the logic is what it ranks by; the rest are numbers (D-91)
        rk = data.get("ranking") or {}
        entry[f"rank:{rk.get('rank_by')}"] += 1
    code = _code_skeleton(str(data.get("code") or "")) if kind == "code" else ""
    return Signature(kind, str(data.get("market")), entry, exits, code)


def _jaccard(a: Counter[str], b: Counter[str]) -> float:
    if not a and not b:
        return 1.0
    inter = sum((a & b).values())
    union = sum((a | b).values())
    return inter / union if union else 0.0


def _filtered_variant(a: Counter[str], b: Counter[str]) -> bool:
    """One rule set is the other plus at most two extra conditions (and shares its trigger)."""
    small, big = (a, b) if sum(a.values()) <= sum(b.values()) else (b, a)
    if not small:
        return False
    return not (small - big) and sum((big - small).values()) <= MAX_EXTRA_FILTERS


def similarity(a: Signature, b: Signature) -> float:
    """0 (different strategies) … 1 (the same rules)."""
    if a.kind != b.kind or a.market != b.market:
        return 0.0
    if a.kind == "kairos":
        return 1.0
    if a.kind == "code":
        return 1.0 if a.code == b.code else 0.0
    if a.kind == "ranking":
        return 1.0 if a.entry == b.entry else 0.0
    return 0.75 * _jaccard(a.entry, b.entry) + 0.25 * _jaccard(a.exits, b.exits)


def same(
    a: Signature,
    b: Signature,
    *,
    template_a: str | None = None,
    template_b: str | None = None,
) -> tuple[bool, float, str]:
    """(same strategy?, similarity, why in plain words)."""
    sim = similarity(a, b)
    if a.kind != b.kind or a.market != b.market:
        return False, 0.0, ""
    if template_a and template_a == template_b:
        return True, max(sim, SAME), "the same starter template"
    if a.kind == "kairos":
        return True, 1.0, "the Kairos brain for this market"
    if a.kind == "code":
        return sim >= 1.0, sim, "the same code apart from its numbers" if sim >= 1.0 else ""
    if a.kind == "ranking":
        return sim >= 1.0, sim, "the same ranking with different numbers" if sim >= 1.0 else ""
    if sim >= 0.999:
        return True, sim, "the same rules with different numbers"
    if _filtered_variant(a.entry, b.entry):
        return True, max(sim, SAME), "the same rules with a filter or two more or fewer"
    if sim >= SAME:
        return True, sim, "nearly the same rules"
    return False, sim, ""


def find_family(
    s: Session,
    definition: AnyDefinition,
    *,
    template_key: str | None = None,
    exclude: int | None = None,
) -> Family | None:
    """The existing (not archived) strategy with the same logic, the most alike first."""
    from backend.strategy import service

    sig = signature(definition)
    rows = s.scalars(
        select(Strategy).where(
            Strategy.archived_at.is_(None),
            Strategy.kind == definition.kind,
            Strategy.market_code == definition.market,
        )
    ).all()
    best: Family | None = None
    for row in rows:
        if row.id == exclude:
            continue
        latest = service.latest_version(s, row.id)
        if latest is None:
            continue
        ok, sim, why = same(
            sig, signature(latest.definition), template_a=template_key, template_b=row.template_key
        )
        if ok and (best is None or sim > best.similarity):
            best = Family(row.id, row.name, round(sim, 3), why)
    return best


def families(s: Session, strategy_id: int) -> list[Family]:
    """Other strategies that are the same logic as this one (copies saved before Phase 13)."""
    from backend.strategy import service

    row = s.get(Strategy, strategy_id)
    latest = service.latest_version(s, strategy_id)
    if row is None or latest is None:
        return []
    sig = signature(latest.definition)
    out = []
    for other in s.scalars(
        select(Strategy).where(
            Strategy.archived_at.is_(None),
            Strategy.kind == row.kind,
            Strategy.market_code == row.market_code,
            Strategy.id != strategy_id,
        )
    ):
        v = service.latest_version(s, other.id)
        if v is None:
            continue
        ok, sim, why = same(
            sig,
            signature(v.definition),
            template_a=row.template_key,
            template_b=other.template_key,
        )
        if ok:
            out.append(Family(other.id, other.name, round(sim, 3), why))
    return sorted(out, key=lambda f: -f.similarity)


def describe(sig: Signature) -> str:
    """A short, stable description of the logic (for Metis's list of families)."""
    return json.dumps(sorted(sig.entry.elements()))
