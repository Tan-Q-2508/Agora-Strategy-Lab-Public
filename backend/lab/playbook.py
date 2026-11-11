"""The playbook: strategies that survived a research sprint, with where they work (D-143).

A playbook entry is what a sprint leaves behind for Metis and Kairos: the rules, the family's
reason, the numbers from the study, exam and vault parts, and the strategy's record in each
regime (``regime_map``). It is a committed file (``backend/seed_data/playbook.json``) holding
rules and summary numbers only, never prices (CLAUDE.md §4), so the cloud and the laptop share
it. On the user's own data each entry is tested again by Metis before anything is saved.

Why a playbook and not more AI: a 4-billion-parameter model is weak at inventing strategies
but fine at choosing between a few proven ones. With the playbook, Metis's first move is to
pick the entry that suits a stock's current regime and adapt one thing (D-144), and code can
make that match without the model at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.lab import families as fam_mod

PATH = Path(__file__).resolve().parent.parent / "seed_data" / "playbook.json"
MIN_REGIME_TRADES = 10


def load(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or PATH
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", []) if isinstance(data, dict) else []
    return [e for e in entries if isinstance(e, dict) and e.get("definition")]


def save(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    path = path or PATH
    body = {
        "note": "Strategies that survived a research sprint (docs/METIS.md §23). Rules and "
        "summary numbers only; no market data.",
        "entries": sorted(entries, key=lambda e: e["key"]),
    }
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def homes(regimes: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(regimes where it earned per trade, regimes where it lost), with enough trades."""
    good = [
        k
        for k, v in regimes.items()
        if k != "unknown" and v["trades"] >= MIN_REGIME_TRADES and v["avg_return_pct"] > 0
    ]
    bad = [
        k
        for k, v in regimes.items()
        if k != "unknown" and v["trades"] >= MIN_REGIME_TRADES and v["avg_return_pct"] <= 0
    ]
    good.sort(key=lambda k: -regimes[k]["avg_return_pct"])
    bad.sort(key=lambda k: regimes[k]["avg_return_pct"])
    return good, bad


def entry_of(row: dict[str, Any]) -> dict[str, Any]:
    """A promoted ledger row as a playbook entry."""
    f = fam_mod.BY_KEY.get(row["family"])
    good, bad = homes(row["regimes"])

    def lean(part: dict[str, Any] | None) -> dict[str, Any]:
        return {k: v for k, v in (part or {}).items() if k != "returns"}

    return {
        "key": f"{row['family']}:{row['market']}:{row['timeframe']}",
        "family": row["family"],
        "name": f.name if f else row["family"],
        "why": f.why if f else "",
        "style": f.style if f else "",
        "market": row["market"],
        "timeframe": row["timeframe"],
        "settings": row["variant"],
        "definition": row["definition"],
        "tested_on": row["symbols"],
        "sprint": row["sprint"],
        "study": lean(row["study"]),
        "exam": lean(row["exam"]),
        "vault": lean(row["vault"]),
        "regimes": row["regimes"],
        "works_in": good,
        "avoid_in": bad,
    }


def merge(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A newer sprint's entry replaces the older one with the same key."""
    by_key = {e["key"]: e for e in old}
    for e in new:
        by_key[e["key"]] = e
    return list(by_key.values())


def suits(entry: dict[str, Any], regime: str | None) -> bool:
    """Does today's regime suit this entry? Unknown regimes suit nothing in particular."""
    return regime is not None and regime in entry.get("works_in", [])


def for_regime(
    entries: list[dict[str, Any]], market: str, timeframe: str, regime: str | None
) -> list[dict[str, Any]]:
    """The entries for a market and timeframe, the ones that suit ``regime`` first (by their
    average return per trade in it), then the rest that don't avoid it."""
    mine = [e for e in entries if e["market"] == market and e["timeframe"] == timeframe]
    fit = [e for e in mine if suits(e, regime)]
    fit.sort(key=lambda e: -e["regimes"].get(regime or "", {}).get("avg_return_pct", 0.0))
    rest = [e for e in mine if e not in fit and regime not in e.get("avoid_in", [])]
    return fit + rest
