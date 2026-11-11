"""OllamaProvider against a mocked Ollama HTTP API (the real one runs only on the laptop)."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.ai.ollama import AIUnavailable, OllamaProvider
from backend.core.ai_provider import ChatMessage


def ndjson(*rows: dict[str, object]) -> bytes:
    return b"\n".join(json.dumps(r).encode() for r in rows) + b"\n"


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/version":
        return httpx.Response(200, json={"version": "0.12.0"})
    if path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b", "size": 3_400_000_000}]})
    if path == "/api/ps":
        # Loaded, but only 1 of its 4 GB on the graphics card
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen3.5:4b", "size": 4_000_000_000, "size_vram": 1_000_000_000}
                ]
            },
        )
    if path == "/api/pull":
        return httpx.Response(
            200,
            content=ndjson(
                {"status": "pulling manifest"},
                {"status": "downloading", "completed": 50, "total": 100},
                {"status": "success"},
            ),
        )
    if path == "/api/chat":
        body = json.loads(request.content)
        if body["model"] == "missing:1b":
            return httpx.Response(404, json={"error": "model not found"})
        assert body["think"] is False and body["options"]["num_ctx"] == 8192
        if body["stream"]:
            return httpx.Response(
                200,
                content=ndjson(
                    {"message": {"content": "Hello "}, "done": False},
                    {"message": {"content": "there."}, "done": False},
                    {"message": {"content": ""}, "done": True},
                ),
            )
        assert body["format"]["type"] == "object"
        return httpx.Response(200, json={"message": {"content": '{"a": 1}'}, "done": True})
    return httpx.Response(404)


def provider() -> OllamaProvider:
    return OllamaProvider("http://ollama.test", transport=httpx.MockTransport(handler))


def test_status_lists_models_with_sizes() -> None:
    st = provider().status()
    assert st.state == "ready" and st.version == "0.12.0"
    assert st.models == ("qwen3.5:4b",) and st.sizes["qwen3.5:4b"] == 3_400_000_000
    assert st.loaded == {"qwen3.5:4b": (4_000_000_000, 1_000_000_000)}


def test_status_without_api_ps_still_ready() -> None:
    """An older Ollama without /api/ps: still ready, just nothing reported as loaded."""

    def old(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if request.url.path == "/api/ps" else handler(request)

    st = OllamaProvider("http://ollama.test", transport=httpx.MockTransport(old)).status()
    assert st.state == "ready" and st.loaded == {}


def test_status_tells_not_running_from_not_installed() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    down = httpx.MockTransport(refuse)
    assert (
        OllamaProvider("http://x", transport=down, installed=lambda: True).status().state
        == "not_running"
    )
    assert (
        OllamaProvider("http://x", transport=down, installed=lambda: False).status().state
        == "not_installed"
    )


def test_pull_reports_progress() -> None:
    steps = list(provider().pull("qwen3.5:4b"))
    assert [s.status for s in steps] == ["pulling manifest", "downloading", "success"]
    assert steps[1].completed == 50 and steps[1].total == 100


def test_chat_streams_and_answers_structured_requests() -> None:
    p = provider()
    msgs = [ChatMessage("user", "hi")]
    assert "".join(p.chat(msgs, model="qwen3.5:4b")) == "Hello there."
    assert p.chat(msgs, model="qwen3.5:4b", stream=False, format={"type": "object"}) == '{"a": 1}'
    with pytest.raises(AIUnavailable, match="isn't downloaded"):
        p.chat(msgs, model="missing:1b", stream=False)
