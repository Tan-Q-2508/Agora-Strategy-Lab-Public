"""Run the look-ahead check (``backend/strategy/lookahead.py``, D-88) on a saved strategy
version: the same stocks, period and costs a backtest would use (``spec_for``), with the extra
older candles the history part needs, as a background job. The result is saved, so the builder
can show the last check of each version."""

from __future__ import annotations

import bisect
from typing import Any

from pydantic import BaseModel, Field

from backend.backtest.manager import BacktestRequest
from backend.backtest.run import warmup_ms
from backend.checks import store
from backend.data.adjust import adjusted
from backend.db.models import Strategy
from backend.errors import AgoraError
from backend.jobs import JobContext
from backend.strategy import lookahead
from backend.strategy import service as strategies
from backend.strategy.compiler import CompileError, compile_definition
from backend.strategy.sandbox import SandboxError

MAX_SYMBOLS = 8
EXTRA_MIN = 250  # older candles the history part loads on top of the usual warm-up


class LookaheadRequest(BaseModel):
    version_id: int | None = None  # default: the newest version
    symbols: list[str] | None = Field(None, max_length=50)
    start: int | None = None
    end: int | None = None


def _version(ctx: Any, strategy_id: int, version_id: int | None) -> strategies.SavedVersion:
    with ctx.db.session() as s:
        if s.get(Strategy, strategy_id) is None:
            raise AgoraError(
                "STRATEGY_NOT_FOUND",
                "That strategy doesn't exist.",
                "Pick a strategy from the list.",
                status=404,
            )
        if version_id is not None:
            v = strategies.get_version(s, version_id)
        else:
            vs = strategies.versions(s, strategy_id)
            v = vs[0] if vs else None
    if v is None or v.strategy_id != strategy_id:
        raise AgoraError(
            "VERSION_NOT_FOUND",
            "That version of the strategy doesn't exist.",
            "Pick a version from the strategy's revisions.",
            status=404,
        )
    return v


def submit(ctx: Any, strategy_id: int, req: LookaheadRequest) -> str:
    v = _version(ctx, strategy_id, req.version_id)
    job = ctx.jobs.submit(
        "lookahead",
        "Look-ahead check",
        lambda jc: run(ctx, strategy_id, v, req, jc),
        job_id=f"lookahead-{strategy_id}-{v.id}-{ctx.clock.now_ms()}",
        key=f"strategy:{strategy_id}",
    )
    return str(job.id)


def run(
    ctx: Any,
    strategy_id: int,
    v: strategies.SavedVersion,
    req: LookaheadRequest,
    jc: JobContext | None = None,
) -> dict[str, Any]:
    def say(pct: float, message: str) -> None:
        if jc is not None:
            jc.progress(pct, message)

    def check() -> None:
        if jc is not None:
            jc.check()

    breq = BacktestRequest(
        strategy_version_id=v.id, symbols=req.symbols, start=req.start, end=req.end
    )
    spec, _extra = ctx.backtests.spec_for(v.definition, breq)
    try:
        program = compile_definition(spec.definition, spec.overrides)
    except (CompileError, SandboxError, ValueError) as exc:
        msg = exc.sentence() if isinstance(exc, SandboxError) else str(exc)
        raise AgoraError(
            "STRATEGY_ERROR", f"The strategy couldn't run: {msg}", "Fix it and check again."
        ) from exc
    extra = max(program.warmup, EXTRA_MIN)
    normal_from = spec.start_ms - warmup_ms(spec.timeframe, program.warmup)
    long_from = spec.start_ms - warmup_ms(spec.timeframe, program.warmup + extra)
    data: list[lookahead.SymbolBars] = []
    insts = spec.instruments[:MAX_SYMBOLS]
    for n, inst in enumerate(insts):
        check()
        say(10 * n / max(1, len(insts)), f"Loading prices for {inst.symbol}…")
        ctx.cache.ensure(inst, spec.timeframe, long_from, spec.end_ms)
        bars = [adjusted(b) for b in ctx.cache.bars(inst, spec.timeframe, long_from, spec.end_ms)]
        ts = [b.ts for b in bars]
        data.append(
            lookahead.SymbolBars(
                inst.symbol,
                bars,
                normal_from=bisect.bisect_left(ts, normal_from),
                start=bisect.bisect_left(ts, spec.start_ms),
            )
        )
    try:
        result = lookahead.check(
            spec.definition,
            data,
            overrides=spec.overrides,
            progress=lambda p, m: say(10 + 0.88 * p, m),
            check_cancel=check,
        )
    except SandboxError as exc:
        raise AgoraError(
            "STRATEGY_ERROR",
            f"Your strategy code stopped: {exc.sentence()}",
            "Fix the code in the strategy editor and check again.",
        ) from exc
    result.update(
        {
            "version": v.version,
            "timeframe": spec.timeframe.value,
            "start": spec.start_ms,
            "end": spec.end_ms,
            "left_out": [i.symbol for i in spec.instruments[MAX_SYMBOLS:]],
        }
    )
    if len(spec.instruments) > MAX_SYMBOLS:
        result["notes"].append(
            f"Checked the first {MAX_SYMBOLS} of {len(spec.instruments)} stocks: the rules are "
            "the same on every stock, so a few are enough."
        )
    with ctx.db.session() as s:
        row = store.save(
            s,
            kind="lookahead",
            now=ctx.clock.now_ms(),
            strategy_id=strategy_id,
            version_id=v.id,
            result=result,
        )
        out = store.public(row, v.version)
    say(100, result["title"])
    return out
