"""Real Ollama on the laptop (Settings → Diagnostics runs it). Skipped by default."""

from __future__ import annotations

import pytest

from backend.ai.ollama import OllamaProvider
from backend.core.ai_provider import ChatMessage

pytestmark = pytest.mark.live


def test_ollama_answers_when_installed() -> None:
    p = OllamaProvider()
    st = p.status()
    if st.state != "ready":
        pytest.skip(f"Ollama is {st.state.replace('_', ' ')}; the AI helper is optional")
    if not st.models:
        pytest.skip("No AI model downloaded yet")
    reply = p.chat(
        [ChatMessage("user", "Reply with the single word: ready")], model=st.models[0], stream=False
    )
    assert isinstance(reply, str) and reply.strip()
