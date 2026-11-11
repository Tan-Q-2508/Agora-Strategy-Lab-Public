"""The graphics-card guard (D-101): reading Ollama's log, and when it restarts Ollama."""

from __future__ import annotations

from typing import Any

from backend.ai.gpu import MAX_RESTARTS, GpuGuard, log_says_cpu_only
from backend.context import AppContext

CPU_START = (
    'time=1 level=INFO msg="Listening on 127.0.0.1:11434 (version 0.40.10)"\n'
    'time=2 level=INFO msg="dropping integrated GPU" library=Vulkan\n'
    'time=3 level=INFO source=types.go:50 msg="inference compute" id=cpu library=cpu '
    'total="15.4 GiB"\n'
)
GPU_START = (
    'time=4 level=INFO msg="Listening on 127.0.0.1:11434 (version 0.40.10)"\n'
    'time=5 level=INFO source=types.go:32 msg="inference compute" id=0 library=CUDA '
    "compute=8.6 name=CUDA0\n"
)


def test_log_reading_uses_the_latest_start() -> None:
    assert log_says_cpu_only(CPU_START) is True
    assert log_says_cpu_only(CPU_START + GPU_START) is False
    assert log_says_cpu_only(GPU_START + CPU_START) is True
    still_looking = 'time=9 msg="Listening on 127.0.0.1:11434"\nmsg="discovering available GPUs..."'
    assert log_says_cpu_only(CPU_START + still_looking) is None


def guard(ctx: AppContext, log: str, nvidia: bool = True) -> tuple[GpuGuard, list[int]]:
    calls: list[int] = []

    def restart() -> bool:
        calls.append(1)
        return True

    g = GpuGuard(ctx, has_nvidia=lambda: nvidia, read_log=lambda: log, restart=restart)
    g.warm_up = lambda cfg: None  # type: ignore[method-assign]
    return g, calls


def test_restarts_ollama_when_it_missed_the_card(ctx: AppContext) -> None:
    g, calls = guard(ctx, CPU_START)
    assert g.check()["action"] == "restarted" and calls == [1]
    for _ in range(5):
        g.check()
    assert len(calls) == MAX_RESTARTS  # never loops restarting


def test_leaves_ollama_alone(ctx: AppContext, client: Any) -> None:
    g, calls = guard(ctx, CPU_START + GPU_START)
    assert g.check()["action"] == "none"
    g, calls = guard(ctx, CPU_START, nvidia=False)
    assert g.check()["why"] == "no NVIDIA card"
    g, calls = guard(ctx, CPU_START)
    ctx.services["metis"].working = True
    assert "idle" in g.check()["why"] and not calls
    ctx.services["metis"].working = False
    client.put("/api/settings", json={"ai.fix_gpu": False})
    assert g.check()["why"] == "off" and not calls


def test_starts_ollama_when_it_isnt_running(ctx: AppContext, monkeypatch: Any) -> None:
    """Agora keeps Ollama on while it is open (D-108), but doesn't hammer it."""
    state = {"now": "not_running", "clock": 1000.0}
    launches: list[int] = []

    def launch() -> bool:
        launches.append(1)
        state["now"] = "ready"
        return True

    monkeypatch.setattr(ctx.ai_service, "status", lambda fresh=False: {"state": state["now"]})
    g = GpuGuard(
        ctx,
        has_nvidia=lambda: False,
        read_log=lambda: None,
        launch=launch,
        monotonic=lambda: float(state["clock"]),
    )
    g.warm_up = lambda cfg: None  # type: ignore[method-assign]
    assert g.keep_running()["action"] == "started" and launches == [1]
    assert g.keep_running()["why"] == "Ollama is ready"
    state["now"] = "not_running"  # stopped again a moment later: wait before the next try
    assert "a moment ago" in g.keep_running()["why"] and launches == [1]
    state["clock"] += 301
    assert g.keep_running()["action"] == "started" and launches == [1, 1]
    state["now"] = "not_installed"
    state["clock"] += 1000
    assert g.keep_running()["action"] == "none" and launches == [1, 1]
