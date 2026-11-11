"""Strategy rules in plain words, for revisions, Metis's brief and Kairos.

Works on the JSON form of a definition (``model_dump(mode="json")``) so it reads any version,
old or new, the same way.
"""

from __future__ import annotations

from typing import Any

TIMEFRAME_WORD = {
    "1mo": "monthly",
    "1w": "weekly",
    "1d": "daily",
    "1h": "1-hour",
    "15m": "15-minute",
    "5m": "5-minute",
    "1m": "1-minute",
}
STOP_LABEL = {
    "stop_loss": "Stop loss",
    "take_profit": "Take profit",
    "trailing_stop": "Trailing stop",
}


def scale_text(spec: dict[str, Any] | None) -> str:
    """Partial exits in words: "sell 50% at 1R, then 25% at 2R; stop to entry after the first"."""
    if not spec:
        return "none"
    unit = {"r": "R", "percent": "% profit", "atr": " ATR"}
    steps = [
        f"{num(s.get('sell_pct'))}% at {num(s.get('value'))}{unit.get(str(s.get('kind', 'r')), '')}"
        for s in spec.get("steps") or []
    ]
    text = "sell " + ", then ".join(steps)
    if spec.get("breakeven", True):
        text += "; stop to entry after the first"
    return text


def num(v: Any) -> str:
    """A number as people write it (14, not 14.0); "$name" parameter references as they are."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return str(v)
    return f"{v:g}"


def operand(o: dict[str, Any]) -> str:
    kind = o.get("kind")
    if kind == "number":
        return num(o.get("value"))
    if kind == "price":
        txt = str(o.get("field", "close"))
    else:
        params = ", ".join(f"{k}={num(v)}" for k, v in (o.get("params") or {}).items())
        txt = f"{o.get('name')}({params})"
        if o.get("output"):
            txt += f".{o['output']}"
    if o.get("chart"):
        txt += f" on the {TIMEFRAME_WORD.get(o['chart'], o['chart'])} chart"
    if o.get("offset"):
        txt += f" {o['offset']} candles ago"
    if o.get("times") not in (None, 1, 1.0):
        txt += f" × {num(o['times'])}"
    return txt


def condition_text(c: dict[str, Any] | None) -> str:
    if not c:
        return "never"
    t = c.get("type")
    if t == "compare":
        op = str(c.get("op", "")).replace("_", " ")
        return f"{operand(c['left'])} {op} {operand(c['right'])}"
    if t == "between":
        return f"{operand(c['value'])} between {operand(c['lower'])} and {operand(c['upper'])}"
    if t in ("all", "any"):
        joiner = " AND " if t == "all" else " OR "
        return "(" + joiner.join(condition_text(x) for x in c.get("conditions", [])) + ")"
    if t == "not":
        return f"NOT {condition_text(c.get('condition'))}"
    if t == "time":
        return f"time {c.get('after') or ''}–{c.get('before') or ''}"
    if t == "position":
        return f"{str(c.get('check', '')).replace('_', ' ')} {num(c.get('value'))}"
    return str(t)


def parts(c: dict[str, Any] | None) -> list[str]:
    """A rule as its separate conditions: the parts of a top-level AND, or the rule itself."""
    if not c:
        return []
    if c.get("type") == "all":
        return [condition_text(x) for x in c.get("conditions", [])]
    return [condition_text(c)]


def stop_text(s: dict[str, Any] | None) -> str:
    if not s:
        return "none"
    if s.get("kind") == "percent":
        return f"{num(s.get('value'))}%"
    return f"{num(s.get('value'))} × ATR({s.get('atr_period', 14)})"


def sizing_text(s: dict[str, Any] | None) -> str:
    s = s or {}
    v, kind = num(s.get("value", 10)), s.get("kind", "percent_equity")
    return {
        "percent_equity": f"{v}% of the money per trade",
        "fixed_qty": f"{v} shares per trade",
        "fixed_amount": f"{v} per trade",
        "risk_percent": f"risk {v}% of the money per trade",
    }.get(str(kind), f"{kind} {v}")
