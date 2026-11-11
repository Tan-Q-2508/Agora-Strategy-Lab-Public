"""Kairos's conversation loop (KAIROS §7.1).

``KairosAgent.chat`` turns one user message into a stream of events for the chat panel:

- ``thread``: which conversation this is;
- ``thinking``: the model is planning (no text yet);
- ``step``: a tool starting (``running``), reporting progress, finishing (``done``) or
  failing (``error``), with its result card and an optional "go to this screen";
- ``text``: words of the reply as they're written;
- ``done``: the saved message id and any numbers the check couldn't confirm;
- ``error``: something went wrong (plain English + what to do).

With the AI helper ready, the model chooses tools (at most 8 rounds); without it (or in
practice mode) the rule-based router plans the steps and the reply is a template. Either
way every number comes from the tools.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections.abc import Generator, Iterator, Mapping
from typing import Any

from pydantic import ValidationError

from backend.ai import numbers, reading
from backend.ai.ollama import AIUnavailable
from backend.core.ai_provider import AgentTurn, ChatOptions, ToolCall
from backend.errors import AgoraError
from backend.kairos import prompts, router, threads
from backend.kairos.tools import ALL, select_tools
from backend.kairos.tools.base import Env, Result, ThreadState, Tool
from backend.logging_setup import get_logger
from backend.settings_store import read_all

log = get_logger("kairos")

MAX_ROUNDS = 8
FOOTER = "Kairos is a research tool, not financial advice. Paper money only."
Event = dict[str, Any]


def _json_call(text: str) -> ToolCall | None:
    """A tool call the model wrote as JSON text instead of using the tools field."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool") or obj.get("function")
    args = obj.get("arguments") or obj.get("parameters") or obj.get("args") or {}
    if isinstance(name, str) and name in ALL and isinstance(args, dict):
        return ToolCall(name, args)
    return None


class KairosAgent:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        # Metis gives way while the user talks to Kairos (METIS §6): how many replies are in
        # progress, and when the last one started or ended.
        self.active = 0
        self.last_active_ms: int | None = None

    # ------------------------------------------------------------ mode

    def mode(self) -> str:
        """``ai`` (the model plans), ``practice`` (fake AI: rule-based plans), or ``basic``
        (no AI helper: rule-based plans and template replies)."""
        provider = self.ctx.ai
        if provider is None or not hasattr(provider, "chat_tools"):
            return "basic"
        if self.ctx.ai_service.status().get("state") != "ready":
            return "basic"
        return "practice" if getattr(provider, "practice", False) else "ai"

    # ------------------------------------------------------------ one message

    def chat(
        self, thread_id: int | None, text: str, page: Mapping[str, Any] | None = None
    ) -> Iterator[Event]:
        self.active += 1
        self.last_active_ms = self.ctx.clock.now_ms()
        try:
            yield from self._chat(thread_id, text, page)
        finally:
            self.active -= 1
            self.last_active_ms = self.ctx.clock.now_ms()

    def _chat(
        self, thread_id: int | None, text: str, page: Mapping[str, Any] | None = None
    ) -> Iterator[Event]:
        started = time.monotonic()
        now = self.ctx.clock.now_ms()
        page = dict(page or {})
        settings = self._settings()
        if thread_id is None or not threads.exists(self.ctx.db, thread_id):
            thread_id = threads.create(self.ctx.db, now, text, settings["ai.model"])
            state = ThreadState()
        else:
            state = threads.state(self.ctx.db, thread_id)
        history = threads.history(self.ctx.db, thread_id)
        threads.add(self.ctx.db, thread_id, "user", text, now)
        yield {"type": "thread", "thread_id": thread_id}

        steps: list[dict[str, Any]] = []
        mode = self.mode()
        reply = ""
        try:
            if mode == "ai":
                try:
                    reply = yield from self._with_model(text, history, state, page, steps, settings)
                except AIUnavailable as exc:
                    yield {"type": "notice", "text": f"{exc} I'll do what I can without it."}
                    mode = "basic"
            if mode != "ai":
                reply = yield from self._with_rules(text, state, page, steps, mode)
        except AgoraError as exc:
            yield {"type": "error", "message": exc.message, "action": exc.action}
            reply = f"{exc.message} {exc.action}"
        context = [s.get("summary", "") for s in steps] + [text]
        unchecked = numbers.unverified(reply, context) if mode == "ai" else []
        payload = {
            "steps": [{k: v for k, v in s.items() if k != "summary"} for s in steps],
            "state": state.public(),
            "mode": mode,
            "unchecked": unchecked,
        }
        mid = threads.add(
            self.ctx.db,
            thread_id,
            "assistant",
            reply,
            self.ctx.clock.now_ms(),
            payload,
            round((time.monotonic() - started) * 1000),
        )
        yield {
            "type": "done",
            "message_id": mid,
            "thread_id": thread_id,
            "mode": mode,
            "unchecked": unchecked,
            "footer": FOOTER,
        }

    # ------------------------------------------------------------ the model plans

    def _with_model(
        self,
        text: str,
        history: list[tuple[str, str]],
        state: ThreadState,
        page: dict[str, Any],
        steps: list[dict[str, Any]],
        settings: dict[str, Any],
    ) -> Generator[Event, None, str]:
        provider = self.ctx.ai
        tools = select_tools(text)
        schema = [t.schema() for t in tools]
        messages = [AgentTurn("system", self._system(text, state, page))]
        messages += [AgentTurn(role, content) for role, content in history]  # type: ignore[arg-type]
        messages.append(AgentTurn("user", text))
        opts = ChatOptions(num_ctx=reading.reading_size(settings), temperature=0.3)
        failures: dict[str, int] = {}
        final = ""
        for _round in range(MAX_ROUNDS):
            chunks: list[str] = []
            calls: list[ToolCall] = []
            thinking_sent = False
            for ev in provider.chat_tools(
                messages,
                schema,
                model=settings["ai.model"],
                options=opts,
                think=bool(settings["kairos.think"]),
            ):
                if ev.kind == "thinking" and not thinking_sent:
                    thinking_sent = True
                    yield {"type": "thinking"}
                elif ev.kind == "text":
                    chunks.append(ev.text)
                    yield {"type": "text", "delta": ev.text}
                elif ev.kind == "tool_calls":
                    calls.extend(ev.calls)
            said = "".join(chunks)
            if not calls:
                recovered = _json_call(said)
                if recovered is None:
                    final = said.strip()
                    break
                calls = [recovered]
                yield {"type": "text_reset"}
                said = ""
            messages.append(AgentTurn("assistant", said, tuple(calls)))
            for call in calls:
                tool = ALL.get(call.name)
                if tool is None:
                    messages.append(
                        AgentTurn(
                            "tool",
                            f"There is no tool called {call.name}. "
                            f"Use one of: {', '.join(t.name for t in tools)}.",
                            tool_name=call.name,
                        )
                    )
                    continue
                result = yield from self._run(tool, call.arguments, state, page, steps)
                if result is None:
                    failures[call.name] = failures.get(call.name, 0) + 1
                    note = steps[-1].get("detail", "It failed.")
                    content = f"Failed: {note}" + (
                        " Don't retry; tell the user what to do."
                        if failures[call.name] >= 2
                        else " Fix the arguments and try once more, or explain."
                    )
                else:
                    content = result.clipped()
                messages.append(AgentTurn("tool", content, tool_name=call.name))
        else:
            final = final or "I ran out of steps for this request. Here's what I did so far."
        if not final:
            final = self._template_reply(steps)
        return final

    def _system(self, text: str, state: ThreadState, page: dict[str, Any]) -> str:
        from backend.core.types import Market
        from backend.markets.status import describe, market_status

        name = None
        if state.strategy_id:
            from backend.db.models import Strategy

            with self.ctx.db.session() as s:
                row = s.get(Strategy, state.strategy_id)
                name = row.name if row else None
        settings = self._settings()
        try:
            now = self.ctx.clock.now_ms()
            status = [describe(market_status(self.ctx.calendar, m, now), now) for m in Market]
        except Exception:  # the prompt must never fail because of the clock or calendar
            status = []
        ctx_text = prompts.context_block(
            now_ms=self.ctx.clock.now_ms(),
            markets=list(settings["markets"]),
            market_status=status,
            page=page,
            state=state.public(),
            strategy_name=name,
        )
        lessons = ""
        learner = self.ctx.services.get("kairos_learning")
        if learner is not None:
            lessons = learner.lessons_for_prompt(text)
        return prompts.system_prompt(ctx_text, text, lessons)

    # ------------------------------------------------------------ rules plan

    def _with_rules(
        self,
        text: str,
        state: ThreadState,
        page: dict[str, Any],
        steps: list[dict[str, Any]],
        mode: str,
    ) -> Generator[Event, None, str]:
        calls = router.plan(self.ctx, text, state, page)
        if not calls:
            reply = router.HELP
            if mode == "basic":
                reply += (
                    " For free-form conversation, set up the AI helper in Settings → AI helper."
                )
            yield {"type": "text", "delta": reply}
            return reply
        for call in calls:
            result = yield from self._run(ALL[call.name], call.arguments, state, page, steps)
            if result is None:
                break
        reply = self._template_reply(steps)
        if mode == "basic":
            reply += (
                "\n\n(Basic mode: with the AI helper set up, I can discuss results in my own "
                "words.)"
            )
        yield {"type": "text", "delta": reply}
        return reply

    def _template_reply(self, steps: list[dict[str, Any]]) -> str:
        """The reply when Kairos follows its rules: the steps already show as cards, so the
        text gives the facts of the last result (or why it stopped)."""
        if not steps:
            return router.HELP
        failed = [s for s in steps if s["status"] != "done"]
        last = next((s for s in reversed(steps) if s["status"] == "done"), None)
        lines: list[str] = []
        if last and last.get("summary"):
            lines.append("\n".join(last["summary"].splitlines()[:8]))
        if failed:
            lines.append(f"I couldn't finish: {failed[0].get('detail') or 'a step failed.'}")
        return "\n\n".join(lines) or "Done."

    # ------------------------------------------------------------ running one tool

    def _run(
        self,
        tool: Tool,
        raw_args: Mapping[str, Any],
        state: ThreadState,
        page: dict[str, Any],
        steps: list[dict[str, Any]],
    ) -> Generator[Event, None, Result | None]:
        sid = f"s{len(steps) + 1}"
        try:
            args = tool.args.model_validate(dict(raw_args))
        except ValidationError as exc:
            problem = "; ".join(
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]
            )
            bad: dict[str, Any] = {
                "id": sid,
                "tool": tool.name,
                "status": "error",
                "label": tool.name.replace("_", " ").capitalize(),
                "detail": f"Bad arguments ({problem})",
                "args": dict(raw_args),
            }
            steps.append(bad)
            yield {"type": "step", **bad}
            return None
        label = tool.label(args)
        yield {"type": "step", "id": sid, "tool": tool.name, "status": "running", "label": label}
        updates: queue.Queue[tuple[float, str]] = queue.Queue()
        box: dict[str, Any] = {}
        env = Env(self.ctx, state, progress=lambda pct, msg: updates.put((pct, msg)), page=page)

        def work() -> None:
            try:
                box["result"] = tool.run(env, args)
            except AgoraError as exc:
                box["error"] = exc
            except Exception as exc:  # a tool bug must not break the conversation
                log.exception("Kairos tool %s failed", tool.name)
                box["error"] = AgoraError(
                    "TOOL_FAILED",
                    "Something went wrong while doing that.",
                    "Try again; if it keeps happening, check Settings → Diagnostics.",
                    detail=repr(exc),
                )

        th = threading.Thread(target=work, name=f"kairos-{tool.name}", daemon=True)
        th.start()
        last_sent = 0.0
        while th.is_alive() or not updates.empty():
            try:
                pct, msg = updates.get(timeout=0.2)
            except queue.Empty:
                continue
            if time.monotonic() - last_sent > 0.3:
                last_sent = time.monotonic()
                yield {
                    "type": "step",
                    "id": sid,
                    "tool": tool.name,
                    "status": "running",
                    "label": label,
                    "pct": round(pct, 1),
                    "message": msg,
                }
        th.join()
        if "error" in box:
            err: AgoraError = box["error"]
            failed: dict[str, Any] = {
                "id": sid,
                "tool": tool.name,
                "status": "error",
                "label": label.rstrip("…"),
                "detail": f"{err.message} {err.action}".strip(),
                "args": dict(raw_args),
            }
            steps.append(failed)
            yield {"type": "step", **failed}
            return None
        result: Result = box["result"]
        step: dict[str, Any] = {
            "id": sid,
            "tool": tool.name,
            "status": "done" if result.ok else "error",
            "label": result.label,
            "detail": result.detail,
            "card": result.card,
            "ui": result.ui,
            "args": args.model_dump(exclude_none=True),
            "summary": result.clipped(),
        }
        steps.append(step)
        yield {"type": "step", **{k: v for k, v in step.items() if k != "summary"}}
        return result if result.ok else None

    def _settings(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            return read_all(s)
