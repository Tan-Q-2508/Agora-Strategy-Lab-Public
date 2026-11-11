"""Kairos conversations, saved in ``kairos_threads`` / ``kairos_messages``.

An assistant message's payload holds the steps Kairos took (tool, label, result line,
card, navigation) and the conversation state after that turn ("the current strategy"),
so a conversation can be reopened exactly as it was and continued.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select

from backend.db.models import KairosMessage, KairosThread
from backend.errors import AgoraError
from backend.kairos.tools.base import ThreadState

HISTORY_TURNS = 6


def create(db: Any, now: int, first_message: str, model: str | None) -> int:
    title = " ".join(first_message.split())[:60] or "New conversation"
    with db.session() as s:
        t = KairosThread(title=title, model=model, created_at=now, updated_at=now)
        s.add(t)
        s.flush()
        return t.id


def exists(db: Any, thread_id: int) -> bool:
    with db.session() as s:
        return s.get(KairosThread, thread_id) is not None


def add(
    db: Any,
    thread_id: int,
    role: str,
    content: str,
    now: int,
    payload: dict[str, Any] | None = None,
    latency_ms: int | None = None,
) -> int:
    with db.session() as s:
        m = KairosMessage(
            thread_id=thread_id,
            role=role,
            content=content,
            payload=json.dumps(payload or {}),
            created_at=now,
            latency_ms=latency_ms,
        )
        s.add(m)
        t = s.get(KairosThread, thread_id)
        if t is not None:
            t.updated_at = now
        s.flush()
        return m.id


def listing(db: Any, limit: int = 50) -> list[dict[str, Any]]:
    with db.session() as s:
        rows = s.scalars(
            select(KairosThread).order_by(KairosThread.updated_at.desc()).limit(limit)
        ).all()
        return [
            {"id": t.id, "title": t.title, "created_at": t.created_at, "updated_at": t.updated_at}
            for t in rows
        ]


def messages(db: Any, thread_id: int) -> list[dict[str, Any]]:
    with db.session() as s:
        t = s.get(KairosThread, thread_id)
        if t is None:
            raise AgoraError(
                "THREAD_NOT_FOUND",
                "That conversation doesn't exist any more.",
                "Start a new one.",
                status=404,
            )
        rows = s.scalars(
            select(KairosMessage)
            .where(KairosMessage.thread_id == thread_id)
            .order_by(KairosMessage.id)
        ).all()
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "payload": json.loads(m.payload or "{}"),
                "created_at": m.created_at,
            }
            for m in rows
        ]


def remove(db: Any, thread_id: int) -> None:
    with db.session() as s:
        s.execute(delete(KairosMessage).where(KairosMessage.thread_id == thread_id))
        s.execute(delete(KairosThread).where(KairosThread.id == thread_id))


def state(db: Any, thread_id: int) -> ThreadState:
    """The conversation state saved with the latest reply."""
    for m in reversed(messages(db, thread_id)):
        if m["role"] == "assistant" and "state" in m["payload"]:
            return ThreadState.load(m["payload"]["state"])
    return ThreadState()


def history(db: Any, thread_id: int, turns: int = HISTORY_TURNS) -> list[tuple[str, str]]:
    """The last few (role, text) pairs for the model; replies carry a one-line note of the
    steps taken so the model remembers what it already did."""
    out: list[tuple[str, str]] = []
    for m in messages(db, thread_id):
        if m["role"] == "user":
            out.append(("user", m["content"][:800]))
        elif m["role"] == "assistant":
            steps = m["payload"].get("steps") or []
            did = "; ".join(
                f"{st.get('label', '')} ({st.get('detail', '')})"
                for st in steps
                if st.get("status") == "done"
            )
            text = m["content"][:700] + (f"\n[Done: {did}]" if did else "")
            out.append(("assistant", text))
    return out[-2 * turns :]
