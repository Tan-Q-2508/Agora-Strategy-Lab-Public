"""How much text the AI model reads at once (its "reading size", Ollama's ``num_ctx``), D-141.

Why this matters: Metis's evidence alone is 5,000 to 10,000 tokens, and the model's thinking
comes on top. When the reading size is smaller, Ollama silently drops the start of the
conversation (Metis's instructions and the first strategies) and the model answers on what is
left. Qwen 3.5 (4B) can read 262,144 tokens, and only 8 of its 32 layers keep a memory that
grows with the text (about 32 KB a token), so 32,768 tokens need about 1 GB beside the 3.4 GB
model: that fits a 6 GB card. Since cards and other models differ, "Automatic" starts at
32,768 and steps down when Ollama reports the model no longer fits on the graphics card.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

AUTO = 0
SIZES = (4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536)
AUTO_START = 32768
AUTO_FLOOR = 8192
CHARS_PER_TOKEN = 3.0  # Qwen's tokenizer averages ~3.5–4 on English; numbers are denser
THINK_RESERVE = 6144  # room for the model's own thinking (Ollama counts it in the window)
ANSWER_RESERVE = 1536


def tokens(text: str) -> int:
    """A cautious token count (rounded up) without loading the model's tokenizer."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def reading_size(values: Mapping[str, Any]) -> int:
    """The reading size to use now: the user's choice, or the size that fit last time."""
    chosen = int(values.get("ai.num_ctx", AUTO) or AUTO)
    if chosen != AUTO:
        return chosen
    fit = int(values.get("ai.ctx_fit", AUTO_START) or AUTO_START)
    return fit if fit in SIZES else AUTO_START


def is_auto(values: Mapping[str, Any]) -> bool:
    return int(values.get("ai.num_ctx", AUTO) or AUTO) == AUTO


def prompt_budget(num_ctx: int, *, thinking: bool = True) -> int:
    """Tokens the prompt may use so the model's thinking and answer still fit."""
    reserve = ANSWER_RESERVE + (THINK_RESERVE if thinking else 0)
    return max(1024, num_ctx - reserve)


def step_down(size: int) -> int | None:
    """The next smaller size for "Automatic", or None at the floor."""
    smaller = [s for s in SIZES if AUTO_FLOOR <= s < size]
    return smaller[-1] if smaller else None
