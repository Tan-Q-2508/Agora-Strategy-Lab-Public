"""What changed between two revisions of a strategy, in plain words (docs/REVISIONS.md, D-79).

Code works it out when a revision is saved, so the history says "Added to buys: adx(period=14)
at least 20" rather than leaving the user to compare two sets of rules. Only differences are
listed; two identical definitions give an empty list.
"""

from __future__ import annotations

import difflib
from typing import Any

from backend.strategy.definition import AnyDefinition
from backend.strategy.words import (
    STOP_LABEL,
    TIMEFRAME_WORD,
    condition_text,
    num,
    parts,
    scale_text,
    sizing_text,
    stop_text,
)

RULES = (
    ("entry", "long", "buys"),
    ("entry", "short", "short sales"),
    ("exit", "long", "selling"),
    ("exit", "short", "covering shorts"),
)
KAIROS_LABEL = {
    "entry_score": "Entry score",
    "exit_score": "Exit score",
    "stop_atr": "Widest stop (ATRs)",
    "target_r": "Target (× risk)",
    "trail_atr": "Trailing stop (ATRs)",
    "max_bars": "Time limit (candles)",
    "allow_short": "Short selling",
}


def _listing(items: list[str], limit: int = 6) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _universe(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    ua, ub = a.get("universe") or {}, b.get("universe") or {}
    if ua.get("kind") == "all" and ub.get("kind") == "all":
        return []
    if ua.get("kind") == "all" or ub.get("kind") == "all":
        new = "the whole market" if ub.get("kind") == "all" else _listing(ub.get("symbols") or [])
        return [f"Stocks: now {new}."]
    sa, sb = list(ua.get("symbols") or []), list(ub.get("symbols") or [])
    added = [x for x in sb if x not in sa]
    removed = [x for x in sa if x not in sb]
    out = []
    if added:
        out.append(f"Stocks added: {_listing(added)}.")
    if removed:
        out.append(f"Stocks removed: {_listing(removed)}.")
    return out


def _parameters(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    pa = {p["name"]: p for p in a.get("parameters") or []}
    pb = {p["name"]: p for p in b.get("parameters") or []}
    out = []
    for name, p in pb.items():
        if name not in pa:
            out.append(f"New setting {p['label']} ({name}) = {num(p['default'])}.")
        elif pa[name]["default"] != p["default"]:
            out.append(f"{p['label']} ({name}): {num(pa[name]['default'])} → {num(p['default'])}.")
        elif (pa[name]["min"], pa[name]["max"]) != (p["min"], p["max"]):
            out.append(f"{p['label']} ({name}) may now range {num(p['min'])} to {num(p['max'])}.")
    out.extend(f"Setting removed: {pa[n]['label']} ({n})." for n in pa if n not in pb)
    return out


def _rule(a: dict[str, Any], b: dict[str, Any], group: str, side: str, word: str) -> list[str]:
    ra, rb = (a.get(group) or {}).get(side), (b.get(group) or {}).get(side)
    if ra == rb:
        return []
    if ra is None:
        return [f"Rule for {word} added: {condition_text(rb)}."]
    if rb is None:
        return [f"Rule for {word} removed (was: {condition_text(ra)})."]
    pa, pb = parts(ra), parts(rb)
    simple = ra.get("type") in ("all", "compare", "between") and rb.get("type") in (
        "all",
        "compare",
        "between",
    )
    added = [x for x in pb if x not in pa]
    removed = [x for x in pa if x not in pb]
    if simple and (added or removed):
        out = [f"Added to {word}: {x}." for x in added]
        out += [f"Removed from {word}: {x}." for x in removed]
        return out
    return [f"Rule for {word} changed: {condition_text(ra)} → {condition_text(rb)}."]


def _exits(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    ea, eb = a.get("exit") or {}, b.get("exit") or {}
    out = []
    for key, label in STOP_LABEL.items():
        sa, sb = ea.get(key), eb.get(key)
        if sa == sb:
            continue
        if sa is None:
            out.append(f"{label} added: {stop_text(sb)}.")
        elif sb is None:
            out.append(f"{label} removed (was {stop_text(sa)}).")
        else:
            out.append(f"{label}: {stop_text(sa)} → {stop_text(sb)}.")
    if ea.get("scale_out") != eb.get("scale_out"):
        out.append(
            f"Partial exits: {scale_text(ea.get('scale_out'))} → {scale_text(eb.get('scale_out'))}."
        )
    if ea.get("max_bars") != eb.get("max_bars"):
        old, new = ea.get("max_bars"), eb.get("max_bars")
        old_t = "none" if old is None else f"{num(old)} candles"
        new_t = "none" if new is None else f"{num(new)} candles"
        out.append(f"Time limit: {old_t} → {new_t}.")
    if ea.get("exit_time") != eb.get("exit_time"):
        out.append(f"Exit time: {ea.get('exit_time') or 'none'} → {eb.get('exit_time') or 'none'}.")
    return out


def _limits(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    la, lb = a.get("limits") or {}, b.get("limits") or {}
    out = []
    if la.get("max_open_positions") != lb.get("max_open_positions"):
        out.append(
            f"Most open trades: {la.get('max_open_positions')} → {lb.get('max_open_positions')}."
        )
    if la.get("max_daily_loss_pct") != lb.get("max_daily_loss_pct"):

        def word(v: Any) -> str:
            return "none" if v is None else f"{num(v)}%"

        out.append(
            f"Daily loss limit: {word(la.get('max_daily_loss_pct'))} → "
            f"{word(lb.get('max_daily_loss_pct'))}."
        )
    return out


def _code(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    ca, cb = str(a.get("code") or ""), str(b.get("code") or "")
    if ca == cb:
        return []
    changed = sum(
        1
        for line in difflib.unified_diff(ca.splitlines(), cb.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )
    return [f"Code changed ({changed} line{'s' if changed != 1 else ''} added or removed)."]


def _kairos(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    ka, kb = a.get("kairos") or {}, b.get("kairos") or {}
    out = [
        f"{KAIROS_LABEL.get(k, k)}: {num(ka.get(k))} → {num(v)}."
        for k, v in kb.items()
        if ka.get(k) != v
    ]
    wa, wb = a.get("weights") or {}, b.get("weights") or {}
    moved = [k for k in set(wa) | set(wb) if wa.get(k) != wb.get(k)]
    if moved:
        out.append(f"Learned signal weights updated ({len(moved)} signals).")
    return out


RANKING_LABEL = {
    "rank_by": "Ranks by",
    "lookback_months": "Months ranked on",
    "skip_months": "Latest months left out",
    "hold": "Stocks held",
    "trend_filter": "Trend filter",
}
RANK_WORD = {"momentum": "momentum", "low_volatility": "low volatility", True: "on", False: "off"}


def _ranking(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    ra, rb = a.get("ranking") or {}, b.get("ranking") or {}
    out = []
    for k, label in RANKING_LABEL.items():
        if ra.get(k) != rb.get(k):
            old, new = ra.get(k), rb.get(k)
            out.append(f"{label}: {RANK_WORD.get(old, num(old))} → {RANK_WORD.get(new, num(new))}.")
    return out


def changes_json(a: dict[str, Any] | None, b: dict[str, Any]) -> list[str]:
    """Plain-English differences from definition ``a`` to ``b`` (JSON form)."""
    if a is None:
        return ["First version."]
    out: list[str] = []
    if a.get("kind") != b.get("kind"):
        out.append(f"Turned from a {a.get('kind')} strategy into a {b.get('kind')} strategy.")
    if a.get("market") != b.get("market"):
        out.append(f"Market: {a.get('market')} → {b.get('market')}.")
    if a.get("timeframe") != b.get("timeframe"):
        old = TIMEFRAME_WORD.get(str(a.get("timeframe")), a.get("timeframe"))
        new = TIMEFRAME_WORD.get(str(b.get("timeframe")), b.get("timeframe"))
        out.append(f"Candles: {old} → {new}.")
    if a.get("product") != b.get("product"):
        out.append(f"Product: {a.get('product')} → {b.get('product')}.")
    out += _universe(a, b)
    out += _parameters(a, b)
    if a.get("kind") == b.get("kind") == "visual":
        for group, side, word in RULES:
            out += _rule(a, b, group, side, word)
        out += _exits(a, b)
    elif a.get("kind") == b.get("kind") == "code":
        out += _code(a, b)
    elif a.get("kind") == b.get("kind") == "kairos":
        out += _kairos(a, b)
    elif a.get("kind") == b.get("kind") == "ranking":
        out += _ranking(a, b)
        return out  # its trade size and open-trade limit follow from the stocks held
    if a.get("sizing") != b.get("sizing"):
        out.append(f"Trade size: {sizing_text(a.get('sizing'))} → {sizing_text(b.get('sizing'))}.")
    out += _limits(a, b)
    return out


def changes(a: AnyDefinition | None, b: AnyDefinition) -> list[str]:
    """Plain-English differences from revision ``a`` to revision ``b``."""
    return changes_json(None if a is None else a.model_dump(mode="json"), b.model_dump(mode="json"))
