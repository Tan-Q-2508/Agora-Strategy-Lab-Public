"""Backtest runs: start on a background worker, report progress, cancel, and save every
result with what's needed to reproduce it (SPEC §6.1, D-31).

A run's ``params`` record exactly what was asked; ``repro`` records exactly what was used
(strategy version hash, data ranges and sources, charge schedule rows, engine and data
library versions).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.backtest import robustness as rb
from backend.backtest.run import (
    ENGINE_VERSION,
    NoData,
    RunOutput,
    RunSpec,
    _clean,
    run,
    warmup_ms,
)
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import service as data_service
from backend.data import store
from backend.data.store import InstrumentRef
from backend.db.models import (
    BacktestEquity,
    BacktestOrder,
    BacktestRun,
    BacktestTrade,
    BrokerageProfile,
    ChargeSchedule,
    SlippageProfile,
    Strategy,
    StrategyVersion,
    UniverseMember,
)
from backend.engine.types import ChargeTotals
from backend.errors import AgoraError
from backend.jobs import JobCancelled, JobContext
from backend.logging_setup import get_logger
from backend.metrics import performance, tearsheet
from backend.metrics.summary import honesty, summary
from backend.quant import overfit, stats
from backend.settings_store import read_all
from backend.strategy import service as strategies
from backend.strategy.compiler import CompileError
from backend.strategy.definition import AnyDefinition, Sizing
from backend.strategy.sandbox import SandboxError

log = get_logger("backtest")
MAX_EQUITY_POINTS = 5000
MAX_CHILD_POINTS = 400
MAX_ORDERS = 20_000
BENCH_NAME = {Market.IN: "Nifty 50", Market.US: "S&P 500 (SPY)"}


class SweepParamIn(BaseModel):
    name: str
    values: list[float] = Field(min_length=1, max_length=50)


class SweepIn(BaseModel):
    params: list[SweepParamIn] = Field(min_length=1, max_length=2)
    metric: Literal["sharpe", "total_return", "cagr", "profit_factor", "calmar"] = "sharpe"


class WalkForwardIn(BaseModel):
    train_days: int = Field(365, ge=30, le=3650)
    test_days: int = Field(90, ge=5, le=1000)
    params: list[SweepParamIn] = Field(min_length=1, max_length=2)
    metric: Literal["sharpe", "total_return", "cagr", "profit_factor", "calmar"] = "sharpe"


class BacktestRequest(BaseModel):
    strategy_version_id: int
    symbols: list[str] | None = None
    timeframe: Literal["1d", "1h", "15m", "5m", "1m"] | None = None
    start: int | None = None
    end: int | None = None
    capital: float | None = Field(None, gt=0, le=1e12)
    brokerage_profile_id: int | None = None
    slippage_bps: float | None = Field(None, ge=0, le=500)
    mode: Literal["single", "oos", "sweep", "walk_forward"] = "single"
    overrides: dict[str, float] = Field(default_factory=dict)
    # D-80: % of the money per trade instead of the strategy's own sizing (portfolio sleeves)
    size_pct: float | None = Field(None, gt=0, le=100)
    oos_fraction: float = Field(0.7, ge=0.3, le=0.9)
    sweep: SweepIn | None = None
    walk_forward: WalkForwardIn | None = None
    name: str | None = Field(None, max_length=120)
    # Kairos's trade check (KAIROS §16): skip signals it has learned tend to lose after costs
    trade_check: Literal["off", "learn", "balanced", "strict"] = "off"


def _err(code: str, message: str, action: str, detail: str = "", status: int = 422) -> AgoraError:
    return AgoraError(code, message, action, detail=detail, status=status)


@dataclass
class Prepared:
    run_id: int
    spec: RunSpec
    request: BacktestRequest
    version: strategies.SavedVersion
    strategy_name: str
    survivorship: bool


class BacktestManager:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx  # AppContext (typed loosely to avoid an import cycle)

    # ------------------------------------------------------------ lifecycle

    def recover(self) -> None:
        """Runs that were in progress when Agora closed can't continue (D-06)."""
        with self.ctx.db.session() as s:
            s.execute(
                update(BacktestRun)
                .where(BacktestRun.status.in_(("queued", "running")))
                .values(
                    status="failed",
                    error_plain="Agora was closed while this backtest was running. Run it again.",
                    finished_at=self.ctx.clock.now_ms(),
                )
            )

    def start(self) -> None:
        """Called when the app starts."""
        self.recover()

    def submit(self, req: BacktestRequest, *, priority: bool = False) -> int:
        """``priority``: Kairos runs it to answer the user in a chat (D-115)."""
        prep = self._prepare(req)
        self.ctx.jobs.submit(
            "backtest",
            f"Backtest: {prep.strategy_name}",
            lambda job: self._work(job, prep),
            job_id=f"backtest-{prep.run_id}",
            priority=priority,
        )
        return prep.run_id

    def cancel(self, run_id: int) -> bool:
        return bool(self.ctx.jobs.cancel(f"backtest-{run_id}"))

    # ------------------------------------------------------------ preparing

    def _prepare(self, req: BacktestRequest) -> Prepared:
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            version = strategies.get_version(s, req.strategy_version_id)
            if version is None:
                raise _err(
                    "STRATEGY_NOT_FOUND",
                    "That strategy version doesn't exist.",
                    "Pick a strategy from the list.",
                    status=404,
                )
            strat = s.get(Strategy, version.strategy_id)
            assert strat is not None
            d = version.definition
        spec, extra = self.spec_for(d, req)
        market, tf = spec.market, spec.timeframe
        instruments, survivorship = spec.instruments, bool(extra["survivorship"])
        start, end, capital = spec.start_ms, spec.end_ms, spec.capital
        if req.trade_check != "off":
            from backend.kairos import samples as kairos_samples

            with self.ctx.db.session() as s:
                spec.trade_check = req.trade_check
                spec.trade_check_seed = kairos_samples.seed(
                    s,
                    strategy_id=strat.id,
                    market=market.value,
                    timeframe=tf.value,
                    known_before=start,
                    saved_before=now,
                )
        self._check_mode(req, d)
        params = {
            **req.model_dump(),
            "strategy_id": strat.id,
            "strategy_name": strat.name,
            "version": version.version,
            "market": market.value,
            "timeframe": tf.value,
            "symbols": [i.symbol for i in instruments],
            "start": start,
            "end": end,
            "capital": capital,
            "brokerage_profile_id": extra["profile_id"],
            "brokerage_profile": extra["profile_name"],
            "slippage_bps": spec.slippage_bps,
            "product": d.product,
        }
        with self.ctx.db.session() as s:
            row = BacktestRun(
                strategy_version_id=version.id,
                status="queued",
                params=json.dumps(params),
                created_at=now,
                name=req.name,
                progress=0.0,
            )
            s.add(row)
            s.flush()
            run_id = row.id
        return Prepared(run_id, spec, req, version, strat.name, survivorship)

    def spec_for(self, d: AnyDefinition, req: BacktestRequest) -> tuple[RunSpec, dict[str, Any]]:
        """What a run of definition ``d`` would use (stocks, period, money, costs), without
        saving anything. Metis uses it to test ideas that aren't strategies yet (METIS §4)."""
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            market = Market(d.market)
            tf = Timeframe(req.timeframe or d.timeframe)
            instruments, survivorship, membership = self._instruments(s, d, req.symbols, market)
            settings = read_all(s)
            capital = req.capital or float(settings[f"default_capital.{market.value}"])
            profile = self._profile(s, market, req.brokerage_profile_id)
            slip = req.slippage_bps
            if slip is None:
                slip = (
                    s.scalar(
                        select(SlippageProfile.bps).where(
                            SlippageProfile.market_code == market.value,
                            SlippageProfile.is_default == 1,
                        )
                    )
                    or 0.0
                )
            bench = store.find_instrument(s, market, data_service.BENCHMARK[market])
        end = req.end or now
        start = req.start or data_service.default_start_ms(tf, now) + (
            365 * 86_400_000 if tf is Timeframe.D1 else 0
        )
        if start >= end:
            raise _err(
                "BAD_DATES", "The start date must be before the end date.", "Pick a later end date."
            )
        if tf is Timeframe.D1 and end - start < 30 * 86_400_000:
            raise _err(
                "SHORT_PERIOD",
                "That period is too short for daily candles.",
                "Use at least a month.",
            )
        defn: AnyDefinition = (
            d.model_copy(update={"timeframe": tf.value}) if tf.value != d.timeframe else d
        )
        if req.size_pct:
            defn = defn.model_copy(
                update={"sizing": Sizing(kind="percent_equity", value=float(req.size_pct))}
            )
        spec = RunSpec(
            definition=defn,
            instruments=instruments,
            timeframe=tf,
            start_ms=start,
            end_ms=end,
            capital=capital,
            brokerage_rules=json.loads(profile.rules),
            slippage_bps=float(slip),
            volume_cap_pct=float(settings["volume_cap_pct"]),
            square_off=str(settings["intraday_square_off_time"]),
            overrides=dict(req.overrides),
            benchmark=bench,
            membership=membership,
        )
        extra = {
            "survivorship": survivorship,
            "profile_id": profile.id,
            "profile_name": profile.name,
        }
        return spec, extra

    def _instruments(
        self,
        s: Session,
        d: AnyDefinition,
        symbols: list[str] | None,
        market: Market,
    ) -> tuple[list[InstrumentRef], bool, dict[int, list[tuple[int, int | None]]]]:
        survivorship = False
        membership: dict[int, list[tuple[int, int | None]]] = {}
        if symbols:
            names = symbols
        elif d.universe.kind == "symbols":
            names = d.universe.symbols
        else:
            uid = data_service.universe_id(s, data_service.UNIVERSE[market])
            if market is Market.IN and data_service.has_membership_history(s, uid):
                rows = s.scalars(
                    select(UniverseMember).where(UniverseMember.universe_id == uid)
                ).all()
                for r in rows:
                    membership.setdefault(r.instrument_id, []).append((r.valid_from, r.valid_to))
                insts = [
                    x for x in (store.get_instrument(s, iid) for iid in membership) if x is not None
                ]
            else:
                insts = data_service.members(s, uid)
                survivorship = market is Market.IN
            return sorted(insts, key=lambda i: i.symbol), survivorship, membership
        out = []
        missing = []
        for sym in names:
            inst = store.find_instrument(s, market, sym)
            if inst is None:
                missing.append(sym)
            else:
                out.append(inst)
        if missing:
            raise _err(
                "UNKNOWN_SYMBOLS",
                f"Agora doesn't know {', '.join(missing)}.",
                "Pick stocks from the list.",
            )
        if not out:
            raise _err("NO_SYMBOLS", "No stocks were chosen.", "Pick at least one stock.")
        if market is Market.IN and d.universe.kind == "all":
            survivorship = True
        return out, survivorship, membership

    def _profile(self, s: Session, market: Market, profile_id: int | None) -> BrokerageProfile:
        if profile_id is not None:
            p = s.get(BrokerageProfile, profile_id)
            if p is None or p.market_code != market.value:
                raise _err(
                    "BAD_PROFILE",
                    "That brokerage profile doesn't fit this market.",
                    "Pick another profile.",
                )
            return p
        p = s.scalar(
            select(BrokerageProfile).where(
                BrokerageProfile.market_code == market.value, BrokerageProfile.is_default == 1
            )
        )
        if p is None:
            raise _err(
                "NO_PROFILE",
                "No brokerage profile is set up.",
                "Restart Agora to restore the defaults.",
                status=500,
            )
        return p

    def _check_mode(self, req: BacktestRequest, d: AnyDefinition) -> None:
        names = {p.name for p in d.parameters}
        specs = (
            req.sweep.params
            if req.mode == "sweep" and req.sweep
            else req.walk_forward.params
            if req.mode == "walk_forward" and req.walk_forward
            else []
        )
        if req.mode == "sweep" and not req.sweep:
            raise _err(
                "SWEEP_MISSING",
                "Choose which parameters to sweep.",
                "Pick one or two parameters and their values.",
            )
        if req.mode == "walk_forward" and not req.walk_forward:
            raise _err(
                "WF_MISSING",
                "Walk-forward needs window sizes and parameters.",
                "Fill in the walk-forward settings.",
            )
        for p in specs:
            if p.name not in names:
                raise _err(
                    "BAD_PARAM",
                    f"The strategy has no parameter called “{p.name}”.",
                    "Pick one of the strategy's parameters.",
                )
        for k in req.overrides:
            if k not in names:
                raise _err(
                    "BAD_PARAM",
                    f"The strategy has no parameter called “{k}”.",
                    "Pick one of the strategy's parameters.",
                )
        if specs:
            try:
                rb.grid([rb.SweepParam(p.name, p.values) for p in specs])
            except ValueError as exc:
                raise _err("BAD_SWEEP", str(exc), "Use fewer values.") from exc

    # ------------------------------------------------------------ the job

    def _set(self, run_id: int, **values: Any) -> None:
        with self.ctx.db.session() as s:
            s.execute(update(BacktestRun).where(BacktestRun.id == run_id).values(**values))

    def _work(self, job: JobContext, prep: Prepared) -> dict[str, Any]:
        run_id = prep.run_id
        self._set(run_id, status="running", started_at=self.ctx.clock.now_ms())
        last_saved = [0.0]

        def progress(pct: float, message: str) -> None:
            job.progress(pct, message)
            if pct - last_saved[0] >= 5 or pct >= 100:
                last_saved[0] = pct
                self._set(run_id, progress=pct)

        try:
            self._ensure_data(prep, progress, job.check)
            mode = prep.request.mode
            if mode == "sweep":
                result = self._sweep(prep, progress, job.check)
            elif mode == "walk_forward":
                result = self._walk_forward(prep, progress, job.check)
            else:
                result = self._single(prep, progress, job.check)
            self._set(run_id, status="done", progress=100.0, finished_at=self.ctx.clock.now_ms())
            progress(100, "Backtest finished.")
            return {"run_id": run_id, **result}
        except JobCancelled:
            self._set(run_id, status="cancelled", finished_at=self.ctx.clock.now_ms())
            raise
        except NoData as exc:
            self._fail(
                run_id,
                str(exc),
                "Download prices on the Data screen, then run the backtest again.",
                "",
            )
            raise _err(
                "NO_DATA",
                str(exc),
                "Download prices on the Data screen, then run the backtest again.",
            ) from exc
        except SandboxError as exc:
            msg = f"Your strategy code stopped: {exc.sentence()}"
            self._fail(run_id, msg, "Fix the code in the strategy editor and run again.", repr(exc))
            raise _err(
                "STRATEGY_ERROR", msg, "Fix the code in the strategy editor and run again."
            ) from exc
        except (CompileError, ValueError) as exc:
            self._fail(
                run_id,
                f"The strategy couldn't run: {exc}",
                "Check the strategy's settings.",
                repr(exc),
            )
            raise _err(
                "STRATEGY_ERROR",
                f"The strategy couldn't run: {exc}",
                "Check the strategy's settings.",
            ) from exc
        except Exception as exc:
            log.exception("Backtest %s failed", run_id)
            self._fail(
                run_id,
                "The backtest stopped because of an unexpected problem.",
                "Try again. If it keeps happening, create a support bundle in "
                "Settings → Diagnostics.",
                repr(exc),
            )
            raise

    def _fail(self, run_id: int, plain: str, action: str, detail: str) -> None:
        self._set(
            run_id,
            status="failed",
            error_plain=f"{plain} {action}".strip(),
            error_detail=detail[:4000],
            finished_at=self.ctx.clock.now_ms(),
        )

    def _ensure_data(
        self, prep: Prepared, progress: Callable[[float, str], None], check: Callable[[], None]
    ) -> None:
        self.ensure_data_for(prep.spec, progress, check)

    def ensure_data_for(
        self,
        spec: RunSpec,
        progress: Callable[[float, str], None] = lambda _p, _m: None,
        check: Callable[[], None] = lambda: None,
    ) -> None:
        """Download whatever prices the run needs (plus warm-up) that aren't stored yet."""
        from backend.strategy.compiler import compile_definition

        program = compile_definition(spec.definition, spec.overrides)
        lo = spec.start_ms - warmup_ms(spec.timeframe, program.warmup)
        targets = list(spec.instruments)
        for n, inst in enumerate(targets):
            check()
            progress(3 * n / max(len(targets), 1), f"Checking prices for {inst.symbol}…")
            self.ctx.cache.ensure(inst, spec.timeframe, lo, spec.end_ms)
        if spec.benchmark is not None:
            self.ctx.cache.ensure(
                spec.benchmark, Timeframe.D1, spec.start_ms - 10 * 86_400_000, spec.end_ms
            )

    # -- modes

    def _single(
        self, prep: Prepared, progress: Callable[[float, str], None], check: Callable[[], None]
    ) -> dict[str, Any]:
        out = run(
            self.ctx.cache,
            prep.spec,
            progress=lambda p, m: progress(3 + p * 0.95, m),
            check_cancel=check,
        )
        tz = ZoneInfo(MARKET_TZ[prep.spec.market])
        if prep.request.mode == "oos":
            span = prep.spec.end_ms - prep.spec.start_ms
            split = prep.spec.start_ms + int(span * prep.request.oos_fraction)
            out.metrics["periods"] = rb.split_metrics(
                out.equity, out.trades, prep.spec.capital, split, tz
            )
        self._save(prep.run_id, prep, out, full=True)
        return {"metrics": _headline(out.metrics)}

    def _sweep(
        self, prep: Prepared, progress: Callable[[float, str], None], check: Callable[[], None]
    ) -> dict[str, Any]:
        assert prep.request.sweep is not None
        params = [rb.SweepParam(p.name, p.values) for p in prep.request.sweep.params]
        metric = prep.request.sweep.metric
        cells = rb.grid(params)
        results: list[dict[str, Any]] = []
        daily: list[list[tuple[str, float]]] = []  # each cell's daily returns, for PBO
        tz = MARKET_TZ[prep.spec.market]
        for k, overrides in enumerate(cells):
            check()
            spec = _with(prep.spec, overrides={**prep.spec.overrides, **overrides})
            label = ", ".join(f"{n}={_fmt(v)}" for n, v in overrides.items())
            progress(3 + 92 * k / len(cells), f"Testing {label} ({k + 1} of {len(cells)})…")
            out = run(self.ctx.cache, spec, check_cancel=check)
            pts = stats.daily_points(out.equity, tz)
            rets = stats.returns_of([prep.spec.capital] + [v for _d, v in pts])
            daily.append([(d, float(r)) for (d, _v), r in zip(pts, rets, strict=True)])
            child = self._child(prep, overrides, out)
            results.append(
                {"run_id": child, "overrides": overrides, "metrics": _headline(out.metrics)}
            )
        best = max(results, key=lambda c: rb.score(c["metrics"], metric))
        peak = rb.isolated_peak(results, metric, params)
        _days, table = overfit.aligned(daily)
        pbo: dict[str, Any] = (
            overfit.pbo(table) if len(cells) >= 2 else {"pbo": None, "tries": len(cells)}
        )
        pbo["text"] = overfit.words(pbo, "settings")
        best_spec = _with(prep.spec, overrides={**prep.spec.overrides, **best["overrides"]})
        out = run(self.ctx.cache, best_spec, check_cancel=check)
        out.metrics["sweep"] = {
            "params": [{"name": p.name, "values": p.values} for p in params],
            "metric": metric,
            "cells": results,
            "best": best["overrides"],
            "isolated_peak": peak,
            "pbo": pbo,
        }
        self._save(
            prep.run_id,
            prep,
            out,
            full=True,
            extra_warnings=_peak_warning(peak) + _pbo_warning(pbo),
        )
        return {"best": best["overrides"], "isolated_peak": peak, "pbo": pbo.get("pbo")}

    def _walk_forward(
        self, prep: Prepared, progress: Callable[[float, str], None], check: Callable[[], None]
    ) -> dict[str, Any]:
        wf = prep.request.walk_forward
        assert wf is not None
        params = [rb.SweepParam(p.name, p.values) for p in wf.params]
        cells = rb.grid(params)
        wins = rb.windows(prep.spec.start_ms, prep.spec.end_ms, wf.train_days, wf.test_days)
        total = len(wins) * (len(cells) + 1)
        done = 0
        tests: list[RunOutput] = []
        table: list[dict[str, Any]] = []
        for w in wins:
            best_score, best = -math.inf, cells[0]
            for overrides in cells:
                check()
                progress(3 + 92 * done / total, f"Tuning window {len(table) + 1} of {len(wins)}…")
                spec = _with(
                    prep.spec,
                    start_ms=w.train_start,
                    end_ms=w.train_end,
                    overrides={**prep.spec.overrides, **overrides},
                )
                sc = rb.score(run(self.ctx.cache, spec, check_cancel=check).metrics, wf.metric)
                if sc > best_score:
                    best_score, best = sc, overrides
                done += 1
            spec = _with(
                prep.spec,
                start_ms=w.test_start,
                end_ms=w.test_end,
                overrides={**prep.spec.overrides, **best},
            )
            out = run(self.ctx.cache, spec, check_cancel=check)
            done += 1
            tests.append(out)
            child = self._child(prep, best, out, window=w)
            table.append(
                {
                    "train_start": w.train_start,
                    "train_end": w.train_end,
                    "test_start": w.test_start,
                    "test_end": w.test_end,
                    "best": best,
                    "train_score": best_score if math.isfinite(best_score) else None,
                    "test_return": out.metrics.get("total_return"),
                    "run_id": child,
                }
            )
        tz = ZoneInfo(MARKET_TZ[prep.spec.market])
        stitched = rb.stitch([t.equity for t in tests], prep.spec.capital)
        trades = [t for o in tests for t in o.trades]
        charges = sum(float(o.charges.total) for o in tests)
        notional = sum(o.traded_notional for o in tests)
        bench_spec = _with(prep.spec, start_ms=wins[0].test_start, end_ms=wins[-1].test_end)
        from backend.backtest.run import benchmark_curve

        bench = benchmark_curve(self.ctx.cache, bench_spec, prep.spec.capital)
        metrics = performance.compute(
            stitched,
            trades,
            prep.spec.capital,
            tz,
            charges_total=charges,
            traded_notional=notional,
            benchmark=bench,
        )
        metrics["walk_forward"] = {
            "metric": wf.metric,
            "params": [{"name": p.name, "values": p.values} for p in params],
            "windows": table,
        }
        merged = RunOutput(
            trades=trades,
            equity=stitched,
            orders=[o for t in tests for o in t.orders],
            logs=[line for t in tests for line in t.logs],
            charges=_merge_charges([t.charges for t in tests]),
            metrics=metrics,
            per_symbol=performance.per_symbol(trades),
            benchmark=bench,
            data=tests[0].data if tests else {},
            program=tests[0].program,
            traded_notional=notional,
        )
        self._save(prep.run_id, prep, merged, full=True)
        return {"windows": len(table)}

    # ------------------------------------------------------------ saving

    def _child(
        self,
        prep: Prepared,
        overrides: dict[str, float],
        out: RunOutput,
        window: rb.Window | None = None,
    ) -> int:
        now = self.ctx.clock.now_ms()
        with self.ctx.db.session() as s:
            parent = s.get(BacktestRun, prep.run_id)
            assert parent is not None
            params = json.loads(parent.params)
            params.update(
                {"overrides": {**prep.spec.overrides, **overrides}, "mode": "single", "child": True}
            )
            if window is not None:
                params.update({"start": window.test_start, "end": window.test_end})
            row = BacktestRun(
                strategy_version_id=prep.version.id,
                status="done",
                params=json.dumps(params),
                metrics=json.dumps(out.metrics),
                summary_text=None,
                progress=100.0,
                created_at=now,
                started_at=now,
                finished_at=now,
                parent_run_id=prep.run_id,
            )
            s.add(row)
            s.flush()
            self._equity_rows(s, row.id, out, prep.spec.capital, MAX_CHILD_POINTS)
            return row.id

    def _equity_rows(
        self, s: Session, run_id: int, out: RunOutput, capital: float, limit: int
    ) -> None:
        pts = out.equity
        dd = performance.underwater([(p.ts, p.equity) for p in pts], capital)
        step = max(1, math.ceil(len(pts) / limit))
        keep = list(range(0, len(pts), step))
        if pts and keep[-1] != len(pts) - 1:
            keep.append(len(pts) - 1)
        s.bulk_insert_mappings(
            BacktestEquity,
            [
                {
                    "run_id": run_id,
                    "ts": pts[i].ts,
                    "equity": pts[i].equity,
                    "cash": pts[i].cash,
                    "exposure": pts[i].exposure,
                    "drawdown": dd[i][1],
                }
                for i in keep
            ],
        )

    def _save(
        self,
        run_id: int,
        prep: Prepared,
        out: RunOutput,
        *,
        full: bool,
        extra_warnings: list[dict[str, str]] | None = None,
    ) -> None:
        spec = prep.spec
        market = spec.market
        with self.ctx.db.session() as s:
            unverified = bool(
                out.charges.schedule_ids
                and s.scalar(
                    select(ChargeSchedule.id)
                    .where(
                        ChargeSchedule.id.in_(out.charges.schedule_ids),
                        ChargeSchedule.verified_at.is_(None),
                    )
                    .limit(1)
                )
            )
        warnings = honesty(
            out.metrics,
            market=market,
            product=spec.definition.product,
            timeframe=spec.timeframe.value,
            data=out.data,
            data_mode=self.ctx.data_mode,
            survivorship=prep.survivorship,
            unverified_rates=unverified,
            has_shorts=any(t.side == "short" for t in out.trades),
        ) + (extra_warnings or [])
        text = summary(out.metrics, market, BENCH_NAME[market])
        # the tear sheet (D-89): a sweep's best cell was chosen from all its cells (luck check)
        trials = len((out.metrics.get("sweep") or {}).get("cells") or []) or 1
        out.metrics["tear_sheet"] = _clean(
            tearsheet.compute(
                [(p.ts, p.equity) for p in out.equity],
                [t.net_pnl for t in out.trades if t.closed],
                spec.capital,
                ZoneInfo(MARKET_TZ[market]),
                n_trials=trials,
            )
        )
        out.metrics["per_symbol"] = out.per_symbol
        out.metrics["benchmark_curve"] = _downsample(out.benchmark, MAX_EQUITY_POINTS)
        repro = {
            "strategy_version_id": prep.version.id,
            "content_hash": prep.version.content_hash,
            "engine_version": ENGINE_VERSION,
            "yfinance_version": _version("yfinance"),
            "data_mode": self.ctx.data_mode,
            "data": out.data,
            "charge_schedule_ids": sorted(out.charges.schedule_ids),
            "parameters": out.program.params,
            "logs": out.logs[-200:],
        }
        with self.ctx.db.session() as s:
            s.execute(
                update(BacktestRun)
                .where(BacktestRun.id == run_id)
                .values(
                    metrics=json.dumps(out.metrics),
                    warnings=json.dumps(warnings),
                    summary_text=text,
                    repro=json.dumps(repro),
                )
            )
            if full:
                s.bulk_insert_mappings(
                    BacktestTrade,
                    [
                        {
                            "run_id": run_id,
                            "instrument_id": t.instrument_id,
                            "side": t.side,
                            "qty": t.qty,
                            "entry_ts": t.entry_ts,
                            "entry_price": t.entry_price,
                            "exit_ts": t.exit_ts,
                            "exit_price": t.exit_price,
                            "gross_pnl": t.gross_pnl,
                            "charges": t.charges,
                            "net_pnl": t.net_pnl,
                            "return_pct": t.return_pct,
                            "bars_held": t.bars_held,
                            "entry_reason": t.entry_reason,
                            "exit_reason": t.exit_reason,
                        }
                        for t in out.trades
                    ],
                )
                self._equity_rows(s, run_id, out, spec.capital, MAX_EQUITY_POINTS)
                if out.check_samples:
                    from backend.kairos import samples as kairos_samples

                    kairos_samples.save(
                        s,
                        strategy_id=prep.version.strategy_id,
                        strategy_kind=spec.definition.kind,
                        market=market.value,
                        timeframe=spec.timeframe.value,
                        source="backtest",
                        ref_id=run_id,
                        samples=out.check_samples,
                        now=self.ctx.clock.now_ms(),
                    )
                s.bulk_insert_mappings(
                    BacktestOrder,
                    [
                        {
                            "run_id": run_id,
                            "ts": o.ts,
                            "instrument_id": o.instrument_id,
                            "type": o.type,
                            "side": o.side,
                            "qty": o.qty,
                            "status": o.status,
                            "reason": o.reason,
                        }
                        for o in out.orders[:MAX_ORDERS]
                    ],
                )


def _merge_charges(parts: list[ChargeTotals]) -> ChargeTotals:
    out = ChargeTotals()
    for c in parts:
        out.total += c.total
        for k, v in c.by_type.items():
            out.by_type[k] = out.by_type.get(k, 0) + v
        out.schedule_ids.update(c.schedule_ids)
    return out


def _with(spec: RunSpec, **changes: Any) -> RunSpec:
    from dataclasses import replace

    return replace(spec, **changes)


def _fmt(v: float) -> str:
    return f"{v:g}"


def _headline(m: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe",
        "sortino",
        "calmar",
        "win_rate",
        "trades",
        "profit_factor",
        "final_equity",
    )
    return {k: m.get(k) for k in keys}


def _peak_warning(peak: bool) -> list[dict[str, str]]:
    if not peak:
        return []
    return [
        {
            "level": "warn",
            "code": "isolated_peak",
            "title": "The best setting is a lone peak",
            "text": "Settings next to the best one did much worse. That usually means "
            "overfitting: the result is unlikely to repeat.",
        }
    ]


def _pbo_warning(pbo: dict[str, Any]) -> list[dict[str, str]]:
    p = pbo.get("pbo")
    if p is None or p < 0.5:
        return []
    return [
        {
            "level": "warn",
            "code": "overfit",
            "title": f"{p * 100:.0f}% chance the best setting is just the luckiest",
            "text": "Testing every half of the history against the other, the setting that did "
            "best on one half usually didn't on the other (probability of backtest "
            "overfitting). Expect less than this backtest shows.",
        }
    ]


def _downsample(points: list[tuple[int, float]], limit: int) -> list[tuple[int, float]]:
    step = max(1, math.ceil(len(points) / limit))
    out = points[::step]
    if points and out[-1] != points[-1]:
        out.append(points[-1])
    return out


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def latest_run_for(s: Session, strategy_id: int) -> BacktestRun | None:
    return s.scalar(
        select(BacktestRun)
        .join(StrategyVersion, StrategyVersion.id == BacktestRun.strategy_version_id)
        .where(
            StrategyVersion.strategy_id == strategy_id,
            BacktestRun.parent_run_id.is_(None),
            BacktestRun.status == "done",
        )
        .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
        .limit(1)
    )
