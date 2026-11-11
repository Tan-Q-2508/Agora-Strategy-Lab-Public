"""Runs user-written strategy code safely (SPEC §5.3).

The code is compiled with RestrictedPython and executed with:
- **no imports** except ``math`` and ``statistics`` (handed over as plain namespaces of
  their public functions, so nothing like ``statistics.sys`` is reachable);
- **no file, network or OS access**: the builtins are a short allow-list; ``open``,
  ``eval``, ``exec``, ``getattr``, ``type``, ``globals`` and friends don't exist; names
  starting with ``_`` and frame/generator internals can't be touched;
- **limits per candle**: at most ``MAX_STEPS`` executed lines and ``MAX_CPU_S`` seconds of
  CPU time per ``on_bar`` call; ``range`` is capped; ``*``, ``**`` and ``<<`` refuse to
  build giant lists, strings or numbers (the usual ways to exhaust memory);
- **determinism**: no randomness or clock is available, so a run always repeats.

Errors are reported with the line number and a plain-English hint.
"""

from __future__ import annotations

import ast
import math
import operator
import re
import statistics
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType, SimpleNamespace
from typing import Any

from RestrictedPython.compile import compile_restricted_exec
from RestrictedPython.Guards import (
    full_write_guard,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safe_builtins,
    safer_getattr,
)
from RestrictedPython.transformer import RestrictingNodeTransformer

from backend.strategy.runtime import StrategyContext

FILENAME = "<strategy>"
MAX_STEPS = 200_000
MAX_CPU_S = 0.5
MAX_RANGE = 1_000_000
MAX_SEQ = 1_000_000
MAX_INT_BITS = 10_000
ALLOWED_MODULES = ("math", "statistics")


class SandboxError(Exception):
    """A problem with the code itself (found before or while running it)."""

    def __init__(self, message: str, hint: str = "", line: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.line = line

    def sentence(self) -> str:
        where = f"Line {self.line}: " if self.line else ""
        return f"{where}{self.message} {self.hint}".strip()


class SandboxLimit(SandboxError):
    pass


# ---------------------------------------------------------------- compile-time policy


class _Policy(RestrictingNodeTransformer):
    """RestrictedPython's rules plus ours: no classes, and size-checked * ** <<."""

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.error(node, "Classes aren't allowed in strategies; use functions instead.")
        return node

    def visit_Global(self, node: ast.Global) -> Any:
        self.error(node, "'global' isn't allowed; keep state in a dict or list instead.")
        return node

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        out = super().visit_BinOp(node)
        if isinstance(out, ast.BinOp) and isinstance(out.op, ast.Mult | ast.Pow | ast.LShift):
            node = out
        else:
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult | ast.Pow | ast.LShift):
            sym = {ast.Mult: "*", ast.Pow: "**", ast.LShift: "<<"}[type(node.op)]
            call = ast.Call(
                func=ast.Name(id="_safe_op_", ctx=ast.Load()),
                args=[ast.Constant(sym), node.left, node.right],
                keywords=[],
            )
            return ast.fix_missing_locations(ast.copy_location(call, node))
        return node


def _size(x: Any) -> int:
    try:
        return len(x)
    except TypeError:
        return 1


def _safe_op(sym: str, a: Any, b: Any) -> Any:
    if sym == "*":
        if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool):
            if abs(a).bit_length() + abs(b).bit_length() > MAX_INT_BITS:
                raise SandboxLimit("That number is too big to compute.", "Use smaller numbers.")
        elif isinstance(a, str | list | tuple | bytes) or isinstance(b, str | list | tuple | bytes):
            n = b if isinstance(b, int) else a if isinstance(a, int) else 0
            seq = a if not isinstance(a, int) else b
            if isinstance(n, int) and n * _size(seq) > MAX_SEQ:
                raise SandboxLimit(
                    "That would build a list or text that is too large.",
                    "Use a smaller repeat count.",
                )
        return a * b
    if sym == "**":
        big = isinstance(a, int) and isinstance(b, int) and b > 0 and abs(a) > 1
        if big and b * math.log2(abs(a)) > MAX_INT_BITS:
            raise SandboxLimit("That power is too big to compute.", "Use a smaller exponent.")
        return a**b
    if isinstance(b, int) and b > MAX_INT_BITS:
        raise SandboxLimit("That shift is too big to compute.", "Use a smaller number.")
    return a << b


_INPLACE: dict[str, Callable[[Any, Any], Any]] = {
    "+=": operator.iadd,
    "-=": operator.isub,
    "*=": lambda a, b: _safe_op("*", a, b),
    "/=": operator.itruediv,
    "//=": operator.ifloordiv,
    "%=": operator.imod,
    "**=": lambda a, b: _safe_op("**", a, b),
    "<<=": lambda a, b: _safe_op("<<", a, b),
    ">>=": operator.irshift,
    "&=": operator.iand,
    "|=": operator.ior,
    "^=": operator.ixor,
}


def _inplacevar(op: str, a: Any, b: Any) -> Any:
    fn = _INPLACE.get(op)
    if fn is None:
        raise SandboxError(f"The operator {op} isn't supported.")
    result = fn(a, b)
    if isinstance(result, list | str | dict) and _size(result) > MAX_SEQ:
        raise SandboxLimit("A list or text grew too large.", "Keep fewer values.")
    return result


# ---------------------------------------------------------------- runtime guards


def _module(mod: Any, names: list[str] | None = None) -> SimpleNamespace:
    """A plain namespace with only the module's public functions and constants."""
    keep = names or [n for n in dir(mod) if not n.startswith("_")]
    return SimpleNamespace(
        **{
            n: getattr(mod, n)
            for n in keep
            if callable(getattr(mod, n)) or isinstance(getattr(mod, n), float | int)
        }
    )


MODULES = {
    "math": _module(math),
    "statistics": _module(
        statistics,
        [
            "fmean",
            "mean",
            "median",
            "median_high",
            "median_low",
            "mode",
            "multimode",
            "pstdev",
            "pvariance",
            "stdev",
            "variance",
            "quantiles",
            "correlation",
            "covariance",
            "linear_regression",
            "geometric_mean",
            "harmonic_mean",
        ],
    ),
}


def _import(
    name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0
) -> Any:
    if level == 0 and name in MODULES:
        return MODULES[name]
    allowed = " and ".join(ALLOWED_MODULES)
    raise SandboxError(f"Importing “{name}” isn't allowed.", f"Only {allowed} can be imported.")


def _range(*args: int) -> range:
    r = range(*args)
    if len(r) > MAX_RANGE:
        raise SandboxLimit("That range is too long.", f"Use at most {MAX_RANGE:,} steps.")
    return r


_DENY_ATTRS = frozenset(
    {"format", "format_map", "mro", "gi_frame", "gi_code", "cr_frame", "ag_frame", "f_back"}
)


def _getattr(obj: Any, name: str, default: Any = None) -> Any:
    if name in _DENY_ATTRS:
        raise SandboxError(f"Using “.{name}” isn't allowed in strategies.")
    return safer_getattr(obj, name, default)  # type: ignore[no-untyped-call]


class _Printer:
    """``print`` writes to the strategy log instead of the console."""

    def __init__(self, _getattr_: Any = None) -> None:
        self.parts: list[str] = []

    def _call_print(self, *objects: Any, **kwargs: Any) -> None:
        log = _CURRENT.log
        if log is not None and len(log) < 2000:
            log.append(" ".join(str(o) for o in objects)[:500])

    def __call__(self) -> str:
        return ""


class _Current(threading.local):
    log: list[str] | None = None


_CURRENT = _Current()

_EXTRA = {
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "enumerate": enumerate,
    "zip": zip,
    "sorted": sorted,
    "reversed": reversed,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
    "all": all,
    "any": any,
    "map": map,
    "filter": filter,
    "len": len,
    "float": float,
    "int": int,
    "bool": bool,
    "str": str,
    "isinstance": isinstance,
    "range": _range,
    "__import__": _import,
}
_REMOVED = {
    "setattr",
    "delattr",
    "__build_class__",
    "bytes",
    "pow",
    "id",
    "hash",
    "issubclass",
    "SystemExit",
    "KeyboardInterrupt",
    "GeneratorExit",
    "BaseException",
    "complex",
    "_getattr_",
}
BUILTINS: dict[str, Any] = {k: v for k, v in safe_builtins.items() if k not in _REMOVED}
BUILTINS.update(_EXTRA)


def _globals() -> dict[str, Any]:
    return {
        "__builtins__": BUILTINS,
        "__name__": "strategy",
        "_getattr_": _getattr,
        "_getitem_": operator.getitem,
        "_getiter_": iter,
        "_write_": full_write_guard,
        "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        "_unpack_sequence_": guarded_unpack_sequence,
        "_inplacevar_": _inplacevar,
        "_safe_op_": _safe_op,
        "_print_": _Printer,
        "math": MODULES["math"],
    }


# ---------------------------------------------------------------- step and CPU limits


class _Budget:
    def __init__(self) -> None:
        self.steps = 0
        self.started = 0.0

    def tracer(self, frame: FrameType, event: str, arg: Any) -> Any:
        if event == "call" and frame.f_code.co_filename == FILENAME:
            return self._line
        return None

    def _line(self, frame: FrameType, event: str, arg: Any) -> Any:
        if event == "line":
            self.steps += 1
            if self.steps > MAX_STEPS:
                raise SandboxLimit(
                    f"The strategy ran more than {MAX_STEPS:,} steps on one candle.",
                    "Look for a loop that never ends.",
                    frame.f_lineno,
                )
            if self.steps % 2000 == 0 and time.thread_time() - self.started > MAX_CPU_S:
                raise SandboxLimit(
                    f"The strategy took more than {MAX_CPU_S:g} s on one candle.",
                    "Simplify the calculation or loop over fewer values.",
                    frame.f_lineno,
                )
        return self._line


def _run_limited(fn: Callable[..., Any], *args: Any) -> Any:
    budget = _Budget()
    budget.started = time.thread_time()
    previous = sys.gettrace()
    sys.settrace(budget.tracer)
    try:
        return fn(*args)
    finally:
        sys.settrace(previous)


def _line_of(exc: BaseException) -> int | None:
    tb = exc.__traceback__
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == FILENAME:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


_LINE = re.compile(r"Line (\d+)")


@dataclass
class CodeStrategy:
    code: str
    _fn: Callable[[Any], Any]

    def on_bar(self, ctx: StrategyContext) -> None:
        _CURRENT.log = ctx._logs
        try:
            _run_limited(self._fn, ctx)
        except SandboxError as exc:
            if exc.line is None:
                exc.line = _line_of(exc)
            raise
        except RecursionError as exc:
            raise SandboxLimit(
                "A function called itself too many times.",
                "Check for endless recursion.",
                _line_of(exc),
            ) from exc
        except Exception as exc:
            raise SandboxError(
                f"{type(exc).__name__}: {exc}",
                "Fix this line and run again.",
                _line_of(exc),
            ) from exc
        finally:
            _CURRENT.log = None


def compile_strategy(code: str) -> CodeStrategy:
    """Compile and load user code; it must define ``on_bar(ctx)``."""
    result = compile_restricted_exec(code, filename=FILENAME, policy=_Policy)
    if result.errors:
        first = result.errors[0]
        m = _LINE.search(first)
        msg = _LINE.sub("", first).lstrip(": ").strip()
        msg = msg.replace("SyntaxError: ", "")
        return_hint = "Check the spelling, brackets and indentation on that line."
        raise SandboxError(f"{msg}", return_hint, int(m.group(1)) if m else None)
    env = _globals()
    try:
        _run_limited(exec, result.code, env)
    except SandboxError as exc:
        if exc.line is None:
            exc.line = _line_of(exc)
        raise
    except Exception as exc:
        raise SandboxError(
            f"{type(exc).__name__}: {exc}", "Fix this line and try again.", _line_of(exc)
        ) from exc
    fn = env.get("on_bar")
    if not callable(fn):
        raise SandboxError(
            "Your code needs a function called on_bar(ctx).",
            "Start with:  def on_bar(ctx):",
        )
    return CodeStrategy(code, fn)
