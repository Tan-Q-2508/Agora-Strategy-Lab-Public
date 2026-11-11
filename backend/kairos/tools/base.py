"""What a Kairos tool is, and what it gives back (KAIROS §7.2).

Each tool is one high-level job (read a chart, run a backtest, start paper trading) so a
small model needs only one call per job. A tool returns:

- ``summary``: compact facts for the model to explain (≤ 1,500 characters),
- ``label`` / ``detail``: the step line the user sees ("Backtested MA crossover · +31%"),
- ``card``: a result card for the chat (with links to the right screen),
- ``ui``: an optional "go to this screen" instruction the app follows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

MAX_SUMMARY = 1500


class Args(BaseModel):
    """Tool arguments: unknown keys are ignored (small models add extras)."""

    model_config = ConfigDict(extra="ignore")


@dataclass
class ThreadState:
    """What "it", "this strategy" and "those stocks" refer to in a conversation."""

    strategy_id: int | None = None
    run_id: int | None = None
    session_id: int | None = None
    symbols: list[str] = field(default_factory=list)
    market: str | None = None
    runs: list[int] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "symbols": self.symbols,
            "market": self.market,
            "runs": self.runs[-6:],
        }

    @classmethod
    def load(cls, data: dict[str, Any]) -> ThreadState:
        return cls(
            strategy_id=data.get("strategy_id"),
            run_id=data.get("run_id"),
            session_id=data.get("session_id"),
            symbols=list(data.get("symbols") or []),
            market=data.get("market"),
            runs=list(data.get("runs") or []),
        )


@dataclass
class Env:
    """Everything a tool may use: the app, the conversation's state, a progress line."""

    ctx: Any
    state: ThreadState
    progress: Callable[[float, str], None] = lambda _pct, _msg: None
    page: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    ok: bool
    summary: str
    label: str
    detail: str = ""
    card: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None

    def clipped(self) -> str:
        s = self.summary.strip()
        return s if len(s) <= MAX_SUMMARY else s[: MAX_SUMMARY - 1] + "…"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[Args]
    run: Callable[[Env, Any], Result]
    label: Callable[[Any], str]  # the "doing it now" line
    group: str = "core"

    def schema(self) -> dict[str, Any]:
        """The Ollama ``tools`` entry: a flat JSON schema (no $defs) small models handle."""
        js = self.args.model_json_schema()
        props = {
            k: {
                kk: vv
                for kk, vv in v.items()
                if kk in ("type", "description", "enum", "items", "anyOf")
            }
            for k, v in js.get("properties", {}).items()
        }
        for v in props.values():
            if "anyOf" in v:  # Optional[X] → X (the model may simply leave it out)
                options: list[dict[str, Any]] = v.pop("anyOf")
                first = next((o for o in options if o.get("type") != "null"), {})
                v.update({kk: vv for kk, vv in first.items() if kk in ("type", "enum", "items")})
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": js.get("required", []),
                },
            },
        }


def money(value: float, market: str) -> str:
    sym = "₹" if market == "IN" else "$"
    return f"{'−' if value < 0 else ''}{sym}{abs(value):,.2f}"


def pct(ratio: float | None, digits: int = 1) -> str:
    if ratio is None:
        return "n/a"
    return f"{ratio * 100:+.{digits}f}%"
