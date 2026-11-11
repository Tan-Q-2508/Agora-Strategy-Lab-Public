"""Deterministic stand-in for Ollama, used in tests and cloud sessions."""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from backend.core.ai_provider import (
    AgentTurn,
    AIState,
    AIStatus,
    ChatEvent,
    ChatMessage,
    ChatOptions,
    PullProgress,
    ToolCall,
)

DEFAULT_REPLY = "This is a canned reply from the fake AI helper."

# What the fake answers to a structured (JSON) request with nothing scripted: a small,
# valid strategy draft, so the drafting flow works end to end without Ollama.
DEFAULT_DRAFT = json.dumps(
    {
        "explanation": "Buys when the 20-day average crosses above the 50-day average and "
        "sells when it crosses back below. (Practice reply from the fake AI helper.)",
        "unsupported": [],
        "definition": {
            "timeframe": "1d",
            "entry": {
                "long": {
                    "type": "compare",
                    "left": {"kind": "indicator", "name": "sma", "params": {"period": 20}},
                    "op": "crosses_above",
                    "right": {"kind": "indicator", "name": "sma", "params": {"period": 50}},
                },
                "short": None,
            },
            "exit": {
                "long": {
                    "type": "compare",
                    "left": {"kind": "indicator", "name": "sma", "params": {"period": 20}},
                    "op": "crosses_below",
                    "right": {"kind": "indicator", "name": "sma", "params": {"period": 50}},
                },
                "short": None,
                "stop_loss": {"kind": "percent", "value": 8},
                "take_profit": None,
                "trailing_stop": None,
                "max_bars": None,
                "exit_time": None,
            },
        },
    }
)


def practice_research(messages: Sequence[AgentTurn]) -> str:
    """What the fake answers when Metis asks for ideas with nothing scripted: a filter on the
    first strategy it was shown and a new strategy, so the research flow works end to end
    without Ollama (docs/METIS.md)."""
    text = messages[-1].content if messages else ""
    found = re.search(r"STRATEGY #(\d+)", text)
    ideas: list[dict[str, Any]] = []
    if found:
        ideas.append(
            {
                "kind": "filter",
                "strategy_id": int(found.group(1)),
                "title": "Only trade when a trend is under way",
                "why": "Practice reply from the fake AI helper: skip entries when ADX says "
                "there is no trend.",
                "conditions": [
                    {"indicator": "adx", "params": {"period": 14}, "op": "at_least", "value": 20}
                ],
                "side": "both",
            }
        )
    ideas.append(
        {
            "kind": "new_strategy",
            "title": "Moving-average trend follower",
            "why": "Practice reply from the fake AI helper.",
            "idea": "Buy when the 20-day average crosses above the 50-day average and sell when "
            "it crosses back below.",
            "market": None,
            "symbols": [],
        }
    )
    return json.dumps(
        {
            "noticed": "Practice reply from the fake AI helper (no real AI on this computer).",
            "ideas": ideas,
        }
    )


class FakeAIProvider:
    """Replies come from a script (in order), then fall back to ``DEFAULT_REPLY``.

    ``calls`` records every chat request so tests can assert on prompts and schemas.
    """

    def __init__(
        self,
        state: AIState = "ready",
        models: Iterable[str] = ("qwen3.5:4b",),
        replies: Iterable[str] = (),
    ) -> None:
        self.state: AIState = state
        self.models = list(models)
        self._replies: deque[str] = deque(replies)
        self.calls: list[dict[str, Any]] = []
        self._tool_script: deque[dict[str, Any]] = deque()
        self.tool_calls: list[dict[str, Any]] = []
        # model → (bytes in memory, bytes on the graphics card); tests set it
        self.loaded: dict[str, tuple[int, int]] = {}

    def queue(self, *replies: str) -> None:
        self._replies.extend(replies)

    def queue_tools(self, *rounds: dict[str, Any]) -> None:
        """Script Kairos rounds: each ``{"calls": [(name, args), ...]}`` and/or
        ``{"text": "..."}`` (and optionally ``"thinking": "..."``)."""
        self._tool_script.extend(rounds)

    @property
    def practice(self) -> bool:
        """Nothing scripted: Kairos plans with its rules (practice mode, D-62)."""
        return not self._tool_script

    def status(self) -> AIStatus:
        version = None if self.state == "not_installed" else "0.0.0-fake"
        models = tuple(self.models) if self.state in ("ready", "model_missing") else ()
        return AIStatus(state=self.state, version=version, models=models, loaded=self.loaded)

    def pull(self, model: str) -> Iterator[PullProgress]:
        total = 4
        for step in range(1, total + 1):
            yield PullProgress(status="downloading", completed=step, total=total)
        if model not in self.models:
            self.models.append(model)
        if self.state == "model_missing":
            self.state = "ready"
        yield PullProgress(status="success", completed=total, total=total)

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        stream: bool = True,
        format: Mapping[str, Any] | None = None,
        options: ChatOptions | None = None,
    ) -> Iterator[str] | str:
        if self.state != "ready":
            raise RuntimeError(f"Fake AI helper is not ready (state={self.state}).")
        self.calls.append({"messages": list(messages), "model": model, "format": format})
        if self._replies:
            reply = self._replies.popleft()
        else:
            reply = DEFAULT_DRAFT if format is not None else DEFAULT_REPLY
        if not stream:
            return reply
        return _chunks(reply)

    def chat_tools(
        self,
        messages: Sequence[AgentTurn],
        tools: Sequence[Mapping[str, Any]],
        *,
        model: str,
        options: ChatOptions | None = None,
        think: bool = False,
    ) -> Iterator[ChatEvent]:
        if self.state != "ready":
            raise RuntimeError(f"Fake AI helper is not ready (state={self.state}).")
        self.tool_calls.append(
            {
                "messages": list(messages),
                "tools": [t["function"]["name"] for t in tools],
                "think": think,
                "options": options,
            }
        )
        if self._tool_script:
            step: dict[str, Any] = self._tool_script.popleft()
        elif not tools and messages and messages[0].content.startswith("You are Metis"):
            step = {
                "thinking": "Practice thinking from the fake AI helper.",
                "text": practice_research(messages),
            }
        else:
            step = {"text": DEFAULT_REPLY}
        if step.get("thinking"):
            yield ChatEvent("thinking", str(step["thinking"]))
        if step.get("text"):
            for piece in _chunks(str(step["text"])):
                yield ChatEvent("text", piece)
        planned: list[tuple[str, dict[str, Any]]] = list(step.get("calls", []))
        calls = tuple(ToolCall(name, dict(args)) for name, args in planned)
        if calls:
            yield ChatEvent("tool_calls", calls=calls)
        yield ChatEvent("done")


def _chunks(text: str) -> Iterator[str]:
    words = text.split(" ")
    for i, word in enumerate(words):
        yield word if i == len(words) - 1 else word + " "
