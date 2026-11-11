"""The look-ahead check (LANDSCAPE §4, task 16.1, D-88): Freqtrade's lookahead and recursive
analyses as one click.

A backtest is only honest if every decision could have been made at the time. Agora's runtime
is built so a strategy can't read a candle that hasn't closed (``SeriesView``), and every
indicator is tested for it; this check proves it for one strategy by *running* it, so it also
covers code strategies, Kairos brains and anything added later:

1. **Hide the future.** Run the rules over the whole period, then again on growing slices that
   end at the candles where they signalled (and at evenly spread candles in between). Every
   signal and every indicator value up to a slice's last candle must be identical to the full
   run's. If one differs, the rules used candles that hadn't closed yet.
2. **More history.** Run again with many more older candles loaded. The signals in the tested
   period must be identical. If they aren't, the rules depend on how much history happens to be
   loaded (an indicator that hasn't settled, an average of "all prices so far", counting candles
   from the start), so a backtest and a paper session, which load different amounts, disagree.

It uses the builder's signal trace (each stock on its own, no fills), started at the tested
period's first candle as the engine starts deciding there: what is checked is the rules, which
the shared engine runs unchanged (D-04). Every run compiles the rules afresh, so code that keeps
state between candles starts clean each time.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Bar, Market, Timeframe
from backend.indicators import catalog
from backend.indicators.series import F64, BarSeries, from_bars
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import AnyDefinition
from backend.strategy.runtime import IndicatorProvider
from backend.strategy.signals import Signal, trace_with
from backend.strategy.words import num

EVEN_SLICES = 8  # slices at evenly spread candles, besides the ones at signals
MAX_SLICES = 40  # per stock
MAX_STEPS = 150_000  # candles of rules run in all (keeps the check to a minute or so)
MAX_SECONDS = 90.0  # slow code gets fewer slices rather than a longer wait
MIN_EXTRA = 20  # fewer extra older candles than this and the history part is skipped
SETTLED = 0.001  # an indicator differing by more than 0.1% with more history hasn't settled
MAX_FINDINGS = 12

DID = {
    "buy": "bought",
    "short": "sold short",
    "sell": "sold",
    "cover": "bought back",
    None: "did nothing",
}

Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class SymbolBars:
    """One stock's split-adjusted candles, oldest first, from the extra-history start."""

    symbol: str
    bars: Sequence[Bar]
    normal_from: int  # the first candle a normal backtest loads (its warm-up start)
    start: int  # the first candle of the tested period


@dataclass
class _Run:
    signals: list[Signal]
    provider: IndicatorProvider


def _trace(
    definition: AnyDefinition,
    overrides: Mapping[str, float],
    series: BarSeries,
    market: Market,
    symbol: str,
    start: int,
) -> _Run:
    program = compile_definition(definition, dict(overrides))  # fresh: no state carried over
    signals, provider = trace_with(program, series, market, symbol, start=start)
    return _Run(signals, provider)


def indicator_label(key: str, params: Mapping[str, float], source: str | None, line: str) -> str:
    """ "EMA (20)", "ADX (14) +DI", "SMA (50) of high": how an indicator line reads to people."""
    ind = catalog.get(key)
    settings = ", ".join(num(params[p.name]) for p in ind.params if p.name in params)
    short = ind.label.split("(")[-1].rstrip(")") if ind.label.endswith(")") else ind.label
    text = f"{short} ({settings})" if settings else short
    if len(ind.outputs) > 1:
        text += f" {dict(ind.outputs).get(line, line)}"
    if source and ind.uses_source and source != ind.default_source:
        text += f" of {source}"
    return text


def _lines(run: _Run) -> dict[tuple[Any, ...], tuple[str, F64]]:
    out: dict[tuple[Any, ...], tuple[str, F64]] = {}
    for key, params, source, lines in run.provider.computed():
        for line, arr in lines.items():
            ident = (key, tuple(sorted(params.items())), source, line)
            out[ident] = (indicator_label(key, params, source, line), arr)
    return out


def _same(a: F64, b: F64) -> np.ndarray:
    """Element-wise: equal, both missing, or equal to floating-point noise."""
    both_nan = np.isnan(a) & np.isnan(b)
    with np.errstate(invalid="ignore"):
        close = np.isclose(a, b, rtol=1e-9, atol=1e-12)
    return np.asarray(both_nan | close)


def _pick_slices(signal_idx: Sequence[int], start: int, n: int, budget: int) -> list[int]:
    """Where to end the slices: at signals (evenly sampled) and at evenly spread candles, within
    a budget of candles run. A slice ending at candle c costs c - start + 1 candles."""
    last = n - 1  # a slice ending at the last candle would be the full run
    if last <= start:
        return []
    avg = max(1, (last - start) // 2)
    room = int(min(MAX_SLICES, max(4, budget // avg)))
    span = last - 1 - start
    n_even = min(EVEN_SLICES, max(2, room // 4))
    even = {start + round(k * span / max(1, n_even - 1)) for k in range(n_even)} if span else set()
    even = {i for i in even if start <= i < last}
    pool = sorted({i for i in signal_idx if start <= i < last} - even)
    left = max(0, room - len(even))
    if len(pool) > left:
        step = len(pool) / max(1, left)
        pool = [pool[int(k * step)] for k in range(left)]
    return sorted(set(pool) | even)


def _when(ts: int, tz: ZoneInfo, intraday: bool) -> str:
    fmt = "%d %b %Y %H:%M" if intraday else "%d %b %Y"
    return ms_to_dt(ts, tz).strftime(fmt).lstrip("0")


def _first_mismatch(
    a: Sequence[tuple[int, str]], b: Sequence[tuple[int, str]]
) -> tuple[int, str | None, str | None] | None:
    """The first candle where two signal lists differ: (index, a's action, b's action)."""
    da, db = dict(a), dict(b)
    for idx in sorted(set(da) | set(db)):
        if da.get(idx) != db.get(idx):
            return idx, da.get(idx), db.get(idx)
    return None


def _fmt(v: float) -> str:
    return "missing" if not math.isfinite(v) else f"{v:,.4g}"


def check(
    definition: AnyDefinition,
    data: Sequence[SymbolBars],
    *,
    overrides: Mapping[str, float] | None = None,
    max_steps: int = MAX_STEPS,
    max_seconds: float = MAX_SECONDS,
    progress: Progress | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Both parts of the check on the given stocks. Pure: no database, no clock."""
    market = Market(definition.market)
    tf = Timeframe(definition.timeframe)
    tz = ZoneInfo(MARKET_TZ[market])
    intraday = tf.is_intraday
    overrides = dict(overrides or {})
    usable = [d for d in data if d.start < len(d.bars) and d.normal_from <= d.start]
    look_findings: list[dict[str, Any]] = []
    leaky: dict[str, str] = {}
    hist_findings: list[dict[str, Any]] = []
    unsettled: dict[str, float] = {}
    slices = signals_checked = indicators_checked = 0
    extra_min: int | None = None
    hist_signals = 0
    total_signals = 0
    per_symbol_budget = max_steps // max(1, len(usable))
    t0 = time.monotonic()
    cut_short = False
    for k, d in enumerate(usable):
        if check_cancel:
            check_cancel()
        if progress:
            progress(100 * k / max(1, len(usable)), f"Checking {d.symbol}…")
        normal = from_bars(list(d.bars[d.normal_from :]), tf, market)
        start = d.start - d.normal_from
        full = _trace(definition, overrides, normal, market, d.symbol, start)
        total_signals += len(full.signals)
        full_lines = _lines(full)
        full_pairs = [(x.index, x.action) for x in full.signals]
        cuts = _pick_slices([x.index for x in full.signals], start, len(normal), per_symbol_budget)
        # each stock gets an equal share of the time that's left
        deadline = time.monotonic() + (max_seconds - (time.monotonic() - t0)) / (len(usable) - k)
        for n_cut, c in enumerate(cuts):
            if check_cancel:
                check_cancel()
            if n_cut >= 2 and time.monotonic() > deadline:
                cut_short = True
                break
            cut = _trace(definition, overrides, normal.upto(c + 1), market, d.symbol, start)
            slices += 1
            mine = [p for p in full_pairs if p[0] <= c]
            signals_checked += len(mine)
            miss = _first_mismatch(mine, [(x.index, x.action) for x in cut.signals])
            if miss is not None and len(look_findings) < MAX_FINDINGS:
                idx, saw, hid = miss
                when = _when(int(normal.ts[idx]), tz, intraday)
                look_findings.append(
                    {
                        "symbol": d.symbol,
                        "ts": int(normal.ts[idx]),
                        "kind": "signal",
                        "with_future": saw,
                        "without_future": hid,
                        "text": f"{d.symbol}, {when}: with later candles visible the rules "
                        f"{DID[saw]}; with them hidden they {DID[hid]}.",
                    }
                )
            for ident, (label, arr) in _lines(cut).items():
                other = full_lines.get(ident)
                if other is None:
                    continue
                indicators_checked += 1
                a, b = other[1][: c + 1], arr[: c + 1]
                bad = np.flatnonzero(~_same(a, b))
                if len(bad) and label not in leaky:
                    i = int(bad[0])
                    when = _when(int(normal.ts[i]), tz, intraday)
                    leaky[label] = when
                    if len(look_findings) < MAX_FINDINGS:
                        look_findings.append(
                            {
                                "symbol": d.symbol,
                                "ts": int(normal.ts[i]),
                                "kind": "indicator",
                                "indicator": label,
                                "text": f"{d.symbol}, {when}: {label} was {_fmt(float(a[i]))} "
                                f"with later candles visible but {_fmt(float(b[i]))} with them "
                                "hidden.",
                            }
                        )
        # part 2: more history
        extra = d.normal_from
        if extra < MIN_EXTRA:
            continue
        extra_min = extra if extra_min is None else min(extra_min, extra)
        longer = from_bars(list(d.bars), tf, market)
        long_run = _trace(definition, overrides, longer, market, d.symbol, d.start)
        usual = [(int(normal.ts[x.index]), x.action) for x in full.signals]
        more = [(int(longer.ts[x.index]), x.action) for x in long_run.signals]
        hist_signals += len(usual)
        miss = _first_mismatch(usual, more)
        if miss is not None and len(hist_findings) < MAX_FINDINGS:
            ts, normal_did, long_did = miss
            when = _when(ts, tz, intraday)
            hist_findings.append(
                {
                    "symbol": d.symbol,
                    "ts": ts,
                    "usual": normal_did,
                    "more_history": long_did,
                    "text": f"{d.symbol}, {when}: with {extra} more older candles loaded the "
                    f"rules {DID[long_did]}; with the usual history they {DID[normal_did]}.",
                }
            )
        long_lines = _lines(long_run)
        for ident, (label, arr) in full_lines.items():
            other = long_lines.get(ident)
            if other is None:
                continue
            a, b = arr[start:], other[1][d.start :]
            m = min(len(a), len(b))
            a, b = a[:m], b[:m]
            ok = np.isfinite(a) & np.isfinite(b)
            if not ok.any():
                continue
            x, y = a[ok], b[ok]
            rel = np.abs(x - y) / np.maximum(np.maximum(np.abs(x), np.abs(y)), 1e-12)
            worst = float(rel.max()) if len(rel) else 0.0
            if worst > SETTLED:
                unsettled[label] = max(unsettled.get(label, 0.0), worst)
    if progress:
        progress(100, "Check finished.")
    return _verdict(
        symbols=[d.symbol for d in usable],
        skipped=[d.symbol for d in data if d not in usable],
        look_findings=look_findings,
        leaky=leaky,
        slices=slices,
        signals_checked=signals_checked,
        indicators_checked=indicators_checked,
        total_signals=total_signals,
        hist_findings=hist_findings,
        unsettled=unsettled,
        extra_min=extra_min,
        hist_signals=hist_signals,
        cut_short=cut_short,
    )


def _verdict(
    *,
    symbols: list[str],
    skipped: list[str],
    look_findings: list[dict[str, Any]],
    leaky: dict[str, str],
    slices: int,
    signals_checked: int,
    indicators_checked: int,
    total_signals: int,
    hist_findings: list[dict[str, Any]],
    unsettled: dict[str, float],
    extra_min: int | None,
    hist_signals: int,
    cut_short: bool = False,
) -> dict[str, Any]:
    n = len(symbols)
    stocks = f"{n} stock{'s' if n != 1 else ''}"
    notes: list[str] = []
    if not symbols:
        verdict, title = "no_data", "Nothing to check: there are no saved prices for the period."
        text = "Download prices on the Data screen, then run the check again."
    elif look_findings:
        verdict = "lookahead"
        title = "Look-ahead found: the rules used candles that hadn't closed yet."
        text = (
            "When later candles were hidden the rules behaved differently, so the backtest used "
            "information it couldn't have had. Its results can't be trusted until this is fixed: "
            "look for anything that reads a later candle or works out a value from the whole "
            "price history at once."
        )
    elif hist_findings:
        verdict = "history"
        title = "The rules depend on how much history is loaded."
        text = (
            f"With {extra_min} more older candles the signals changed, so a backtest and a paper "
            "session (which load different amounts of history) would disagree. Common causes: "
            "an indicator with a very long period that hasn't settled, an average over all the "
            "prices so far (e.g. ctx.close.to_list() without a number), or counting candles "
            "with ctx.bar_index. Use a fixed number of candles instead."
        )
    else:
        verdict = "clean"
        title = "No look-ahead found."
        parts = [
            f"Hiding later candles never changed a signal or an indicator value in {slices} "
            f"slice{'s' if slices != 1 else ''} of history on {stocks}"
        ]
        if extra_min is not None:
            parts.append(f"and loading {extra_min} more older candles gave the same signals")
        text = " ".join(parts) + "."
        if total_signals < 3:
            notes.append(
                "The rules hardly signalled in this period, so the check had little to compare; "
                "try a longer period or more stocks."
            )
    if extra_min is None and symbols:
        notes.append("There weren't enough older prices to test with more history.")
    if unsettled and verdict != "lookahead":
        worst = sorted(unsettled.items(), key=lambda x: -x[1])[:4]
        listed = ", ".join(f"{k} (up to {v * 100:.1f}%)" for k, v in worst)
        notes.append(
            f"Some indicators still change with more history: {listed}. The signals "
            + ("didn't change." if verdict == "clean" else "changed too.")
        )
    if cut_short:
        notes.append(
            "The rules are slow to run, so fewer slices were checked to keep the wait short."
        )
    if skipped:
        notes.append(f"Left out (no prices in the period): {', '.join(skipped[:8])}.")
    return {
        "verdict": verdict,
        "title": title,
        "text": text,
        "notes": notes,
        "symbols": symbols,
        "lookahead": {
            "slices": slices,
            "signals_checked": signals_checked,
            "indicators_checked": indicators_checked,
            "findings": look_findings,
            "leaky_indicators": sorted(leaky),
        },
        "history": {
            "extra_candles": extra_min,
            "signals_compared": hist_signals,
            "findings": hist_findings,
            "unsettled": [
                {"indicator": k, "max_change_pct": round(v * 100, 3)}
                for k, v in sorted(unsettled.items(), key=lambda x: -x[1])
            ],
        },
        "signals": total_signals,
    }
