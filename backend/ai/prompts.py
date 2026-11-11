"""Versioned prompt templates (``backend/ai/prompts/*.md``, docs/AI_ASSISTANT.md §6).

Each file starts with ``<!-- prompt: name · version N -->``; the version is saved with every
conversation so a changed prompt can be traced. Placeholders use ``$name``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from string import Template

DIR = Path(__file__).parent / "prompts"
_HEADER = re.compile(r"<!--\s*prompt:\s*(\w+)\s*·\s*version\s*(\d+)\s*-->\s*\n")

# The glossary words the helper should use (docs/GLOSSARY.md), kept short for the prompt.
GLOSSARY = (
    "strategy, backtest, paper trading, total return, yearly return, worst drop (max drawdown), "
    "Sharpe ratio (return per unit of ups and downs; above 1 good, above 2 very good), "
    "win rate, profit factor (money made on winners ÷ lost on losers; above 1.5 healthy), "
    "charges, slippage, stop-loss, take-profit, candle, indicator"
)


@lru_cache(maxsize=32)
def _load(name: str) -> tuple[str, int]:
    text = (DIR / f"{name}.md").read_text(encoding="utf-8")
    m = _HEADER.match(text)
    if m is None:
        raise ValueError(f"Prompt {name} is missing its version header")
    return text[m.end() :].strip(), int(m.group(2))


def render(name: str, **values: str) -> str:
    body, _ = _load(name)
    return Template(body).safe_substitute(values)


def version(name: str) -> int:
    return _load(name)[1]


def system() -> str:
    return render("system", glossary=GLOSSARY)
