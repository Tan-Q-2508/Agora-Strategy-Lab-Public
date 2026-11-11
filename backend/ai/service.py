"""The AI helper service: status, model download, explanations and strategy drafts.

Everything here is optional (CLAUDE.md §4): when Ollama is missing, stopped, or the AI is
turned off in Settings, the endpoints say so in plain English and the rest of Agora is
unaffected. Nothing here ever touches orders.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select

from backend.ai import context as contexts
from backend.ai import numbers, prompts, reading
from backend.ai.draft import DraftResult, draft
from backend.ai.ollama import AIUnavailable
from backend.core.ai_provider import AIProvider, AIStatus, ChatMessage, ChatOptions
from backend.db.models import AIConversation, AIMessage
from backend.errors import AgoraError
from backend.logging_setup import get_logger
from backend.settings_store import read_all, update

log = get_logger("ai.service")

STATUS_TTL_S = 5.0
GB = 1024**3
VRAM_SAFE_BYTES = int(4.5 * GB)  # model files above this rarely fit a 6 GB card with context
RECOMMENDED = (
    {
        "name": "qwen3.5:4b",
        "label": "Qwen 3.5 (4B)",
        "note": "Recommended. Fits a 6 GB graphics card with room to read your results.",
    },
    {
        "name": "gemma4:e4b",
        "label": "Gemma 4 (E4B)",
        "note": "Writes well, but is larger; on a 6 GB card it may run slowly.",
    },
)
KINDS = {"backtest": "backtest", "trade": "trade", "metric": "general", "paper_day": "paper_day"}
AI_NOTE = "AI-generated. Check important numbers."


GPU_FIX = (
    "Plug in the charger and, if your laptop has a power or graphics mode app (Lenovo Vantage, "
    "Armoury Crate, Omen Gaming Hub…), choose a mode that keeps the NVIDIA card on. Then "
    "right-click the Ollama icon by the clock, choose Quit Ollama, start Ollama again from "
    "the Start menu, and ask the AI helper something."
)


def where_it_runs(loaded: tuple[int, int] | None) -> dict[str, Any] | None:
    """Is the model on the graphics card (fast) or in ordinary memory (several times
    slower)? None when it isn't loaded: Ollama loads it on the first question."""
    if loaded is None or loaded[0] <= 0:
        return None
    size, vram = loaded
    share = round(100 * min(vram, size) / size)
    if share >= 95:
        return {"where": "gpu", "gpu_percent": share, "text": "The graphics card (fast)."}
    if share > 0:
        return {
            "where": "partly",
            "gpu_percent": share,
            "text": f"Partly the graphics card ({share}%); the rest runs on the processor, "
            "which is slower. A smaller reading size can help.",
            "fix": GPU_FIX,
        }
    return {
        "where": "cpu",
        "gpu_percent": 0,
        "text": "The processor, not the graphics card, so answers are several times slower.",
        "fix": GPU_FIX,
    }


def _err(code: str, message: str, action: str, status: int = 409) -> AgoraError:
    return AgoraError(code, message, action, status=status)


class AIService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._cache: tuple[float, AIStatus] | None = None
        self._lock = threading.Lock()

    @property
    def provider(self) -> AIProvider | None:
        p: AIProvider | None = self.ctx.ai
        return p

    def _settings(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            v = read_all(s)
        return {
            "enabled": bool(v["ai.enabled"]),
            "model": str(v["ai.model"]),
            "num_ctx": reading.reading_size(v),
            "auto_ctx": reading.is_auto(v),
        }

    def check_fit(self) -> int | None:
        """On Automatic, step the reading size down when the model no longer fits on the
        graphics card (Ollama runs part of it on the processor: several times slower).

        Only "partly on the card" counts: a model wholly on the processor means the card is
        off (power mode; ``gpu.py`` handles that), not that the reading size is too big.
        Returns the new size when it changed."""
        cfg = self._settings()
        if not cfg["auto_ctx"]:
            return None
        st = self._raw_status(fresh=True)
        if st is None:
            return None
        where = where_it_runs(st.loaded.get(cfg["model"]))
        if where is None or where["where"] != "partly":
            return None
        smaller = reading.step_down(cfg["num_ctx"])
        if smaller is None:
            return None
        with self.ctx.db.session() as s:
            update(s, {"ai.ctx_fit": smaller}, self.ctx.clock)
        log.info(
            "Reading size %s didn't fit the graphics card (%s%%); now %s",
            cfg["num_ctx"],
            where["gpu_percent"],
            smaller,
        )
        return smaller

    def _raw_status(self, fresh: bool = False) -> AIStatus | None:
        p = self.provider
        if p is None:
            return None
        with self._lock:
            if not fresh and self._cache and time.monotonic() - self._cache[0] < STATUS_TTL_S:
                return self._cache[1]
        try:
            st = p.status()
        except Exception as exc:  # the optional helper must never break a screen
            log.warning("AI status failed: %r", exc)
            return None
        with self._lock:
            self._cache = (time.monotonic(), st)
        return st

    # ------------------------------------------------------------ status

    def status(self, fresh: bool = False) -> dict[str, Any]:
        cfg = self._settings()
        st = self._raw_status(fresh)
        installed = list(st.models) if st else []
        state: str = "error" if st is None else st.state
        if st is not None and st.state == "ready" and cfg["model"] not in installed:
            state = "model_missing"
        if not cfg["enabled"]:
            state = "disabled"
        size = st.sizes.get(cfg["model"]) if st else None
        warning = None
        if size and size > VRAM_SAFE_BYTES:
            warning = (
                f"{cfg['model']} is {size / GB:.1f} GB. On a 6 GB graphics card it may not fit "
                "and will answer slowly. Qwen 3.5 (4B) is the safer choice."
            )
        elif cfg["num_ctx"] > reading.AUTO_START and not cfg["auto_ctx"]:
            warning = "A large reading size needs more graphics memory and may slow answers."
        runs_on = where_it_runs(st.loaded.get(cfg["model"])) if st else None
        return {
            "enabled": cfg["enabled"],
            "state": state,
            "version": st.version if st else None,
            "model": cfg["model"],
            "num_ctx": cfg["num_ctx"],
            "auto_ctx": cfg["auto_ctx"],
            "models": [
                {"name": n, "size_gb": round((st.sizes.get(n, 0) if st else 0) / GB, 1)}
                for n in installed
            ],
            "recommended": list(RECOMMENDED),
            "warning": warning,
            "runs_on": runs_on,
        }

    def _ready(self) -> tuple[AIProvider, dict[str, Any]]:
        info = self.status()
        p = self.provider
        state = info["state"]
        if state == "ready" and p is not None:
            return p, self._settings()
        msg = {
            "disabled": ("The AI helper is turned off.", "Turn it on in Settings → AI helper."),
            "not_installed": (
                "The free AI helper isn't installed.",
                "Open Settings → AI helper to set it up (optional).",
            ),
            "not_running": (
                "The AI helper (Ollama) isn't running.",
                "Start Ollama from your Start menu, then try again.",
            ),
            "model_missing": (
                f"The AI model {info['model']} isn't downloaded yet.",
                "Download it in Settings → AI helper.",
            ),
        }.get(state, ("The AI helper isn't available right now.", "Try again in a moment."))
        raise _err("AI_UNAVAILABLE", msg[0], msg[1])

    # ------------------------------------------------------------ download

    def pull(self, model: str | None = None) -> str:
        p = self.provider
        if p is None:
            raise _err("AI_UNAVAILABLE", "The AI helper isn't set up.", "Restart Agora.")
        name = (model or self._settings()["model"]).strip()
        if not name:
            raise _err("BAD_MODEL", "Pick a model to download.", "Choose one from the list.", 422)

        def work(job: Any) -> dict[str, Any]:
            job.progress(0, f"Starting the download of {name}…")
            for step in p.pull(name):
                job.check()
                if step.total:
                    pct = 100.0 * step.completed / step.total
                    got = step.completed / GB
                    job.progress(
                        min(pct, 99.0), f"Downloading {name}: {got:.1f} of {step.total / GB:.1f} GB"
                    )
                elif step.status:
                    job.progress(0, step.status.capitalize())
            with self._lock:
                self._cache = None
            return {"model": name}

        job = self.ctx.jobs.submit(
            "ai_pull", f"Download AI model {name}", work, job_id=f"ai-pull-{name}"
        )
        return str(job.id)

    # ------------------------------------------------------------ explanations

    def _context(self, kind: str, ref: int | None) -> tuple[dict[str, Any], str]:
        if kind == "backtest" and ref is not None:
            return contexts.backtest(self.ctx, ref), "explain_backtest"
        if kind == "trade" and ref is not None:
            return contexts.trade(self.ctx, ref), "explain_trade"
        if kind == "paper_day" and ref is not None:
            return contexts.paper_day(self.ctx, ref), "paper_day"
        if kind == "metric":
            return contexts.metric(self.ctx, ref), "metric"
        raise _err("BAD_REQUEST", "That kind of explanation isn't available.", "Go back.", 422)

    def explain(self, kind: str, ref: int | None, question: str | None) -> Iterator[dict[str, Any]]:
        """Stream ``{type: start|text|done|error}`` events. Errors before the first word
        raise (so the API answers with a normal error); later ones arrive as events."""
        provider, cfg = self._ready()
        data, template = self._context(kind, ref)
        q = (question or "").strip()[:500]
        if kind == "metric" and not q:
            raise _err(
                "BAD_REQUEST", "Type a question first.", "For example: what is Sharpe ratio?", 422
            )
        user = prompts.render(template, context=contexts.as_json(data), question=q)
        messages = [ChatMessage("system", prompts.system()), ChatMessage("user", user)]
        conv_id = self._start_conversation(KINDS[kind], ref, cfg["model"], template, user, q)
        return self._stream(provider, cfg, messages, data, conv_id)

    def _stream(
        self,
        provider: AIProvider,
        cfg: dict[str, Any],
        messages: list[ChatMessage],
        data: dict[str, Any],
        conv_id: int,
    ) -> Iterator[dict[str, Any]]:
        yield {"type": "start", "conversation_id": conv_id}
        t0 = time.monotonic()
        parts: list[str] = []
        try:
            stream = provider.chat(
                messages,
                model=cfg["model"],
                stream=True,
                options=ChatOptions(num_ctx=cfg["num_ctx"]),
            )
            for piece in stream:
                parts.append(piece)
                yield {"type": "text", "text": piece}
        except AIUnavailable as exc:
            yield {"type": "error", "message": str(exc), "action": "Check Settings → AI helper."}
            return
        except Exception as exc:
            log.exception("AI chat failed")
            yield {
                "type": "error",
                "message": "The AI helper stopped unexpectedly.",
                "action": "Try again.",
                "detail": repr(exc),
            }
            return
        reply = "".join(parts)
        try:
            self.check_fit()
        except Exception:  # the size check must never spoil an answer
            log.exception("Reading size check failed")
        unchecked = numbers.unverified(reply, data)
        self._finish_conversation(conv_id, reply, int((time.monotonic() - t0) * 1000))
        yield {"type": "done", "unverified": unchecked, "note": AI_NOTE}

    # ------------------------------------------------------------ drafts

    def draft(self, idea: str, market: str) -> dict[str, Any]:
        provider, cfg = self._ready()
        if len(idea.strip()) < 8:
            raise _err(
                "BAD_REQUEST",
                "Describe the idea in a sentence or two.",
                "For example: buy when the price crosses above its 50-day average.",
                422,
            )
        from backend.api.strategy_defs import known_symbol_checker

        try:
            result: DraftResult = draft(
                provider,
                model=cfg["model"],
                idea=idea,
                market=market,
                num_ctx=cfg["num_ctx"],
                known_symbol=known_symbol_checker(self.ctx, market),
            )
        except AIUnavailable as exc:
            raise _err("AI_UNAVAILABLE", str(exc), "Check Settings → AI helper.") from exc
        conv = self._start_conversation(
            "strategy_draft",
            None,
            cfg["model"],
            "draft_strategy",
            result.transcript[1].content,
            idea,
        )
        self._finish_conversation(conv, json.dumps({"explanation": result.explanation}), None)
        return {
            "ok": result.ok,
            "definition": result.definition,
            "explanation": result.explanation,
            "unsupported": result.unsupported,
            "issues": [i.public() for i in result.issues],
            "attempts": result.attempts,
            "conversation_id": conv,
            "note": AI_NOTE,
        }

    # ------------------------------------------------------------ history

    def _start_conversation(
        self, kind: str, ref: int | None, model: str, template: str, prompt: str, question: str
    ) -> int:
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            conv = AIConversation(context_kind=kind, context_id=ref, model=model, created_at=now)
            s.add(conv)
            s.flush()
            s.add(
                AIMessage(
                    conversation_id=conv.id,
                    role="system",
                    content=f"prompt {template} v{prompts.version(template)}",
                    created_at=now,
                )
            )
            s.add(
                AIMessage(
                    conversation_id=conv.id, role="user", content=question or prompt, created_at=now
                )
            )
            return int(conv.id)

    def _finish_conversation(self, conv_id: int, reply: str, latency_ms: int | None) -> None:
        with self.ctx.db.session() as s:
            s.add(
                AIMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=reply,
                    created_at=self.ctx.clock.now_ms(),
                    latency_ms=latency_ms,
                )
            )

    def conversation(self, conv_id: int) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            conv = s.get(AIConversation, conv_id)
            if conv is None:
                raise _err("NOT_FOUND", "That conversation doesn't exist.", "Go back.", 404)
            msgs = s.scalars(
                select(AIMessage)
                .where(AIMessage.conversation_id == conv_id, AIMessage.role != "system")
                .order_by(AIMessage.id)
            ).all()
            return {
                "id": conv.id,
                "kind": conv.context_kind,
                "context_id": conv.context_id,
                "model": conv.model,
                "created_at": conv.created_at,
                "messages": [
                    {"role": m.role, "content": m.content, "created_at": m.created_at} for m in msgs
                ],
            }
