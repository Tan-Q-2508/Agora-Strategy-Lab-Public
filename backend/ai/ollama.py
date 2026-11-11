"""The real AI helper: Ollama's HTTP API on the user's laptop (docs/AI_ASSISTANT.md §3).

Five endpoints are used: ``/api/version`` (is it running?), ``/api/tags`` (which
models are installed), ``/api/ps`` (is a model loaded, and how much of it on the graphics
card?), ``/api/pull`` (download a model, with progress) and ``/api/chat``.
Nothing leaves the laptop: the address is ``localhost`` unless the user changes it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from backend import actions
from backend.core.ai_provider import (
    AgentTurn,
    AIStatus,
    ChatEvent,
    ChatMessage,
    ChatOptions,
    PullProgress,
    ToolCall,
)

CHAT_TIMEOUT_S = 300.0  # the first answer after Ollama starts loads the model onto the card
KEEP_ALIVE = "30m"  # Kairos and Metis work all the time: keep the model on the card
PROBE_TIMEOUT_S = 2.0


def direct(url: str) -> str:
    """``localhost`` → ``127.0.0.1``. On Windows each new connection to "localhost" first
    tries IPv6 (::1), where Ollama doesn't listen, and loses about 2 seconds: every status
    check (three requests) took 6–7 seconds on the laptop."""
    return url.rstrip("/").replace("://localhost", "://127.0.0.1")


class AIUnavailable(Exception):
    """Ollama can't be reached or refused the request (plain-English message)."""


def _installed() -> bool:
    """Is the Ollama app on this computer at all (even if it isn't running)?"""
    if shutil.which("ollama"):
        return True
    candidates: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Ollama.app"))
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return any(p.exists() for p in candidates)


class OllamaProvider:
    def __init__(
        self,
        base_url: str | Callable[[], str] = "http://localhost:11434",
        *,
        transport: httpx.BaseTransport | None = None,
        installed: Callable[[], bool] = _installed,
    ) -> None:
        self._base = base_url
        self._transport = transport
        self._installed = installed

    def _url(self) -> str:
        base = self._base() if callable(self._base) else self._base
        return direct(base)

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url=self._url(),
            timeout=httpx.Timeout(timeout, connect=PROBE_TIMEOUT_S),
            transport=self._transport,
        )

    # ------------------------------------------------------------ status

    def status(self) -> AIStatus:
        try:
            with self._client(PROBE_TIMEOUT_S) as c:
                version = c.get("/api/version").json().get("version")
                tags = c.get("/api/tags").json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return AIStatus(state="not_running" if self._installed() else "not_installed")
        names = tuple(str(m.get("name") or m.get("model")) for m in tags)
        sizes = {str(m.get("name") or m.get("model")): int(m.get("size") or 0) for m in tags}
        return AIStatus(
            state="ready", version=version, models=names, sizes=sizes, loaded=self._loaded()
        )

    def _loaded(self) -> dict[str, tuple[int, int]]:
        """Which models sit in memory now, and how much of each on the graphics card.
        Optional: an older Ollama without ``/api/ps`` just reports nothing loaded."""
        try:
            with self._client(PROBE_TIMEOUT_S) as c:
                running = c.get("/api/ps").json().get("models", [])
        except (httpx.HTTPError, ValueError, AttributeError):
            return {}
        return {
            str(m.get("name") or m.get("model")): (
                int(m.get("size") or 0),
                int(m.get("size_vram") or 0),
            )
            for m in running
        }

    # ------------------------------------------------------------ pull

    def pull(self, model: str) -> Iterator[PullProgress]:
        try:
            with (
                self._client(CHAT_TIMEOUT_S) as c,
                c.stream("POST", "/api/pull", json={"model": model, "stream": True}) as r,
            ):
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if "error" in msg:
                        raise AIUnavailable(f"Ollama couldn't download {model}: {msg['error']}")
                    yield PullProgress(
                        status=str(msg.get("status", "")),
                        completed=int(msg.get("completed") or 0),
                        total=int(msg.get("total") or 0),
                    )
        except httpx.HTTPError as exc:
            raise AIUnavailable("Couldn't reach Ollama to download the model.") from exc

    # ------------------------------------------------------------ chat

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        stream: bool = True,
        format: Mapping[str, Any] | None = None,
        options: ChatOptions | None = None,
    ) -> Iterator[str] | str:
        opts = options or ChatOptions()
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "think": False,  # short, direct answers; thinking is slow on a 6 GB card
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": opts.num_ctx, "temperature": opts.temperature, **opts.extra},
        }
        if format is not None:
            body["format"] = dict(format)
        size = sum(len(m.content) for m in messages)
        if stream:
            return self._logged(self._stream(body), model, size)
        with actions.track("ai_call", f"Asked {model}", who="ai", prompt_chars=size) as act:
            try:
                with self._client(CHAT_TIMEOUT_S) as c:
                    r = c.post("/api/chat", json=body)
                    r.raise_for_status()
                    data = r.json()
            except httpx.TimeoutException as exc:
                raise AIUnavailable("The AI helper took too long to answer.") from exc
            except httpx.HTTPError as exc:
                raise AIUnavailable(_why(exc)) from exc
            if "error" in data:
                raise AIUnavailable(f"The AI helper refused: {data['error']}")
            reply = str(data.get("message", {}).get("content", ""))
            act.done(f"Answered in {len(reply)} characters", reply_chars=len(reply))
            return reply

    @staticmethod
    def _logged(pieces: Iterator[str], model: str, size: int) -> Iterator[str]:
        """A streamed answer's log entry ends when the answer does (D-220)."""
        got = 0
        with actions.track("ai_call", f"Asked {model}", who="ai", prompt_chars=size) as act:
            for piece in pieces:
                got += len(piece)
                yield piece
            act.done(f"Answered in {got} characters", reply_chars=got)

    def _stream(self, body: dict[str, Any]) -> Iterator[str]:
        try:
            with (
                self._client(CHAT_TIMEOUT_S) as c,
                c.stream("POST", "/api/chat", json=body) as r,
            ):
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if "error" in msg:
                        raise AIUnavailable(f"The AI helper refused: {msg['error']}")
                    piece = msg.get("message", {}).get("content", "")
                    if piece:
                        yield str(piece)
                    if msg.get("done"):
                        return
        except httpx.TimeoutException as exc:
            raise AIUnavailable("The AI helper took too long to answer.") from exc
        except httpx.HTTPError as exc:
            raise AIUnavailable(_why(exc)) from exc

    # ------------------------------------------------------------ tool calling

    def chat_tools(
        self,
        messages: Sequence[AgentTurn],
        tools: Sequence[Mapping[str, Any]],
        *,
        model: str,
        options: ChatOptions | None = None,
        think: bool = False,
    ) -> Iterator[ChatEvent]:
        """Stream a reply that may call tools (Ollama ``tools``; results go back as
        ``role: "tool"`` messages with ``tool_name``)."""
        opts = options or ChatOptions()
        body: dict[str, Any] = {
            "model": model,
            "messages": [_turn(m) for m in messages],
            "tools": list(tools),
            "stream": True,
            "think": think,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": opts.num_ctx, "temperature": opts.temperature, **opts.extra},
        }
        calls: list[ToolCall] = []
        act = actions.track("ai_call", f"Kairos asked {model}", who="kairos", tools=len(tools))
        try:
            with (
                self._client(CHAT_TIMEOUT_S) as c,
                c.stream("POST", "/api/chat", json=body) as r,
            ):
                if r.status_code >= 400:
                    r.read()
                    raise AIUnavailable(_refusal(r))
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if "error" in msg:
                        raise AIUnavailable(f"The AI helper refused: {msg['error']}")
                    m = msg.get("message", {})
                    if m.get("thinking"):
                        yield ChatEvent("thinking", str(m["thinking"]))
                    if m.get("content"):
                        yield ChatEvent("text", str(m["content"]))
                    for tc in m.get("tool_calls") or []:
                        fn = tc.get("function", {})
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            args = _json_or_empty(args)
                        calls.append(ToolCall(str(fn.get("name", "")), args))
                    if msg.get("done"):
                        break
        except httpx.TimeoutException as exc:
            act.failed("The AI helper took too long to answer.")
            raise AIUnavailable("The AI helper took too long to answer.") from exc
        except httpx.HTTPError as exc:
            act.failed(_why(exc))
            raise AIUnavailable(_why(exc)) from exc
        except AIUnavailable as exc:
            act.failed(str(exc))
            raise
        act.done(f"Answered, {len(calls)} tool calls", tool_calls=[c.name for c in calls])
        if calls:
            yield ChatEvent("tool_calls", calls=tuple(calls))
        yield ChatEvent("done")


def _turn(m: AgentTurn) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": c.name, "arguments": dict(c.arguments)}} for c in m.tool_calls
        ]
    if m.tool_name:
        out["tool_name"] = m.tool_name
    return out


def _json_or_empty(text: str) -> dict[str, Any]:
    try:
        v = json.loads(text)
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _refusal(r: httpx.Response) -> str:
    try:
        err = str(r.json().get("error", ""))
    except ValueError:
        err = r.text
    if "does not support tools" in err:
        return (
            "The chosen AI model can't use Agora's tools. Pick Qwen 3.5 (4B) in "
            "Settings → AI helper."
        )
    if r.status_code == 404:
        return "That AI model isn't downloaded yet."
    return f"The AI helper refused: {err[:200]}"


def _why(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return "That AI model isn't downloaded yet."
    if isinstance(exc, httpx.ConnectError):
        return "Ollama isn't running."
    return "The AI helper didn't answer."
