"""The "no invented numbers" check (docs/AI_ASSISTANT.md §5.1).

Every number in the AI's reply should come from the data Agora gave it. The check is
forgiving about formatting (12% vs 0.12, ₹10,00,000 vs 1000000, rounding) and ignores
small counting words ("2–3 ideas") and years. What remains is shown to the user as
"couldn't check these numbers", never silently trusted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_NUM = re.compile(r"(?<![\w.])[-−+]?\d[\d,]*(?:\.\d+)?")
SMALL = 12  # counts like "2 trades" or "3 ideas" are not checked


def numbers_in(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from numbers_in(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from numbers_in(v)
    elif isinstance(value, str):
        yield from _parse(value)


def _parse(text: str) -> Iterable[float]:
    for m in _NUM.finditer(text):
        raw = m.group(0).replace(",", "").replace("−", "-")
        try:
            yield float(raw)
        except ValueError:
            continue


def _known(context: Any) -> list[float]:
    out: list[float] = []
    for v in numbers_in(context):
        out += [abs(v), abs(v) * 100.0, abs(v) / 100.0]
    return out


def _matches(x: float, known: list[float]) -> bool:
    for k in known:
        tol = max(0.051, 0.006 * abs(k))
        if abs(x - k) <= tol:
            return True
    return False


def unverified(reply: str, context: Any) -> list[str]:
    """Numbers in ``reply`` that don't appear (in any usual form) in ``context``."""
    known = _known(context)
    bad: list[str] = []
    for m in _NUM.finditer(reply):
        token = m.group(0)
        raw = token.replace(",", "").replace("−", "-")
        try:
            x = abs(float(raw))
        except ValueError:
            continue
        if x <= SMALL or (1900 <= x <= 2100 and float(x).is_integer()):
            continue
        if not _matches(x, known) and token not in bad:
            bad.append(token.lstrip("+"))
    return bad
