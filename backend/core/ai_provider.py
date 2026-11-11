"""The AI-helper interface (docs/AI_ASSISTANT.md §3).

The AI helper is optional and never trades; this interface exists so every AI feature
can be tested with a fake and the app keeps working when Ollama is absent.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

AIState = Literal["not_installed", "not_running", "model_missing", "ready"]


@dataclass(frozen=True)
class AIStatus:
    state: AIState
    version: str | None = None
    models: tuple[str, ...] = ()
    sizes: Mapping[str, int] = field(default_factory=dict)  # model → bytes on disk
    # Models loaded right now → (bytes in memory, bytes of those on the graphics card).
    # Empty when nothing is loaded (Ollama unloads a model after ~5 idle minutes).
    loaded: Mapping[str, tuple[int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class PullProgress:
    status: str
    completed: int = 0
    total: int = 0


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatOptions:
    num_ctx: int = 8192
    temperature: float = 0.2
    extra: Mapping[str, Any] = field(default_factory=dict)


class AIProvider(Protocol):
    def status(self) -> AIStatus: ...

    def pull(self, model: str) -> Iterator[PullProgress]: ...

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        stream: bool = True,
        format: Mapping[str, Any] | None = None,
        options: ChatOptions | None = None,
    ) -> Iterator[str] | str:
        """Streamed text chunks when ``stream`` is True, else the whole reply."""
        ...


# ---------------------------------------------------------------- tool calling (Kairos, D-62)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentTurn:
    """One message in a tool-using conversation (Ollama's ``/api/chat`` shape)."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str | None = None


@dataclass(frozen=True)
class ChatEvent:
    """A piece of a streamed tool-calling reply."""

    kind: Literal["thinking", "text", "tool_calls", "done"]
    text: str = ""
    calls: tuple[ToolCall, ...] = ()


class ToolChat(Protocol):
    """Providers that can call tools (Ollama with a tool-capable model, and the fake)."""

    def chat_tools(
        self,
        messages: Sequence[AgentTurn],
        tools: Sequence[Mapping[str, Any]],
        *,
        model: str,
        options: ChatOptions | None = None,
        think: bool = False,
    ) -> Iterator[ChatEvent]: ...
