"""The sandbox runs normal strategy code and refuses every escape we know of."""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.types import Market
from backend.indicators.series import from_arrays
from backend.strategy.runtime import Enter, Exit, IndicatorProvider, StrategyContext
from backend.strategy.sandbox import MAX_STEPS, SandboxError, SandboxLimit, compile_strategy

SPEC_EXAMPLE = """
def on_bar(ctx):
    rsi = ctx.ind.rsi(ctx.close, 14)
    if not ctx.position and rsi[-1] < 30:
        ctx.buy(size=ctx.size.percent_equity(10))
    elif ctx.position and rsi[-1] > 70:
        ctx.sell_all()
"""


def make_ctx(n: int = 60, falling: bool = False) -> StrategyContext:
    if falling:
        prices = [100.0 - i for i in range(n)]
    else:
        prices = [100 - i for i in range(n // 2)] + [70 + i for i in range(n - n // 2)]
    ctx = StrategyContext("TEST", Market.US, "1d", {}, IndicatorProvider(from_arrays(prices)))
    ctx._advance(n - 1, None, 100_000.0)
    return ctx


def run(code: str, ctx: StrategyContext | None = None) -> StrategyContext:
    ctx = ctx or make_ctx()
    compile_strategy(code).on_bar(ctx)
    return ctx


def test_the_spec_example_runs() -> None:
    ctx = make_ctx(30, falling=True)  # RSI is low
    run(SPEC_EXAMPLE, ctx)
    (intent,) = ctx._intents
    assert isinstance(intent, Enter) and intent.side == "long"


def test_allowed_features() -> None:
    code = """
import math
from statistics import mean
def helper(xs):
    return [x * 2 for x in xs]
def on_bar(ctx):
    closes = ctx.close.to_list(10)
    avg = mean(closes)
    m = {"a": 1}
    m["b"] = 2
    total = 0
    for i, v in enumerate(helper(closes)):
        total += v
    bb = ctx.ind.bollinger(ctx.close, period=20, mult=2)
    print("avg", round(avg, 2), math.floor(total), bb.upper[-1] > bb.lower[-1])
    if ctx.crosses_above(ctx.close, ctx.ind.sma(ctx.close, 5)):
        ctx.buy()
    ctx.sell_all("done")
"""
    ctx = run(code)
    assert ctx._logs and ctx._logs[0].startswith("avg ")
    assert isinstance(ctx._intents[-1], Exit)


ESCAPES = [
    "import os",
    "from os import path",
    "import subprocess",
    "__import__('os')",
    "open('/etc/passwd')",
    "eval('1+1')",
    "exec('x=1')",
    "compile('1', 'x', 'eval')",
    "globals()",
    "locals()",
    "vars(ctx)",
    "dir(ctx)",
    "getattr(ctx, '_provider')",
    "ctx._provider",
    "ctx.close._arr",
    "().__class__.__bases__",
    "type(ctx)",
    "'{0.__class__}'.format(1)",
    "'{x}'.format_map({'x': 1})",
    "f'{ctx.__class__}'",
    "(x for x in [1]).gi_frame",
    "breakpoint()",
    "input()",
    "math.__dict__",
    "class A:\n    pass",
    "x = 1\ndef f():\n    global x\n    x = 2",
    "setattr(ctx, 'symbol', 'X')",
    "ctx.ind.__getattr__",
    "bytes(10)",
]


@pytest.mark.parametrize("snippet", ESCAPES)
def test_escape_attempts_are_refused(snippet: str) -> None:
    code = snippet + "\ndef on_bar(ctx):\n    pass\n"
    in_bar = "def on_bar(ctx):\n" + "\n".join("    " + line for line in snippet.splitlines()) + "\n"
    for attempt in (code, in_bar):
        with pytest.raises(SandboxError):
            run(attempt)


def test_endless_loop_is_stopped() -> None:
    with pytest.raises(SandboxLimit) as exc:
        run("def on_bar(ctx):\n    while True:\n        pass\n")
    assert exc.value.line in (2, 3)
    assert f"{MAX_STEPS:,}" in exc.value.message


def test_allowed_modules_expose_only_their_functions() -> None:
    ctx = run(
        "import statistics\ndef on_bar(ctx):\n"
        "    ctx.log(statistics.sys, statistics.random, statistics.mean([1, 3]))\n"
    )
    assert ctx._logs == ["None None 2"]


@pytest.mark.parametrize(
    "expr",
    ["[0] * 10**9", "'a' * 10**9", "10 ** 10 ** 10", "1 << 10**9", "list(range(10**8))"],
)
def test_memory_bombs_are_refused(expr: str) -> None:
    with pytest.raises(SandboxLimit):
        run(f"def on_bar(ctx):\n    x = {expr}\n")


def test_inplace_growth_is_capped() -> None:
    with pytest.raises(SandboxError):
        run("def on_bar(ctx):\n    s = 'aaaa'\n    for i in range(40):\n        s *= 2\n")


def test_deep_recursion_is_reported_plainly() -> None:
    with pytest.raises(SandboxError) as exc:
        run("def f(n):\n    return f(n + 1)\ndef on_bar(ctx):\n    f(0)\n")
    assert "itself too many times" in exc.value.message or "steps" in exc.value.message


def test_runtime_errors_name_the_line() -> None:
    with pytest.raises(SandboxError) as exc:
        run("def on_bar(ctx):\n    x = 1\n    y = x / 0\n")
    assert exc.value.line == 3
    assert exc.value.message.startswith("ZeroDivisionError")


def test_missing_on_bar_and_syntax_errors() -> None:
    with pytest.raises(SandboxError, match="on_bar"):
        compile_strategy("x = 1\n")
    with pytest.raises(SandboxError) as exc:
        compile_strategy("def on_bar(ctx)\n    pass\n")
    assert exc.value.line == 1


def test_no_numpy_objects_leak() -> None:
    ctx = make_ctx()
    values = [ctx.close[-1], ctx.close.last, ctx.ind.rsi(ctx.close, 14)[-1], *ctx.close.to_list(3)]
    assert all(type(v) is float for v in values)
    assert not any(isinstance(v, np.generic) for v in values)


def test_deterministic() -> None:
    code = "def on_bar(ctx):\n    ctx.log(sum(ctx.close.to_list()))\n"
    assert run(code)._logs == run(code)._logs
