"""Grounded context for each AI feature (docs/AI_ASSISTANT.md §5).

The helper only ever sees what is built here: the user's own results, as compact JSON
with readable dates (so dates in its reply can be checked too). It never sees anything
outside Agora.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.backtest.run import warmup_ms
from backend.core.clock import ms_to_dt
from backend.core.types import MARKET_TZ, Market, Timeframe
from backend.data import store
from backend.data.adjust import adjusted
from backend.db.models import (
    BacktestRun,
    BacktestTrade,
    Instrument,
    PaperEquity,
    PaperEvent,
    PaperFill,
    PaperOrder,
    PaperSession,
    PaperTrade,
    Strategy,
)
from backend.errors import AgoraError
from backend.indicators import catalog
from backend.indicators.series import from_bars
from backend.strategy import service as strategies
from backend.strategy.compiler import compile_definition
from backend.strategy.definition import IndicatorOperand, VisualDefinition
from backend.strategy.validator import iter_operands

HEADLINE = (
    "total_return",
    "cagr",
    "max_drawdown",
    "max_drawdown_days",
    "sharpe",
    "sortino",
    "volatility",
    "win_rate",
    "profit_factor",
    "trades",
    "expectancy",
    "avg_win",
    "avg_loss",
    "largest_win",
    "largest_loss",
    "avg_hold_days",
    "time_in_market",
    "charges_total",
    "net_pnl",
    "final_equity",
    "benchmark",
    "vs_benchmark",
)


def money_words(amount: float, market: Market) -> str:
    """Money the way the user reads it: lakh and crore for India, plain dollars for the US.
    Small models write "₹227k" or "₹1m" when given raw numbers (seen on the laptop)."""
    sign = "-" if amount < 0 else ""
    a = abs(amount)
    if market is Market.IN:
        if a >= 1e7:
            return f"{sign}₹{a / 1e7:.2f} crore"
        if a >= 1e5:
            return f"{sign}₹{a / 1e5:.2f} lakh"
        return f"{sign}₹{a:,.0f}"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.2f} million"
    return f"{sign}${a:,.0f}"


def _money_in_words(
    metrics: dict[str, Any], capital: float | None, market: Market
) -> dict[str, str]:
    out: dict[str, str] = {}
    if capital:
        out["starting_money"] = money_words(capital, market)
    for key in ("final_equity", "net_pnl", "largest_win", "largest_loss", "charges_total"):
        v = metrics.get(key)
        if isinstance(v, int | float):
            out[key] = money_words(float(v), market)
    return out


def _missing(what: str) -> AgoraError:
    return AgoraError(
        "NOT_FOUND", f"That {what} doesn't exist.", "Go back and pick another.", status=404
    )


def _rd(x: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = _r(x)
    return out


def _r(x: Any) -> Any:
    """Round floats so the prompt stays short and the model quotes tidy numbers."""
    if isinstance(x, float):
        if not math.isfinite(x):
            return None
        return round(x, 4) if abs(x) < 10 else round(x, 2)
    if isinstance(x, dict):
        return {k: _r(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_r(v) for v in x]
    return x


def _when(ms: int | None, market: Market, *, time: bool = False) -> str | None:
    if ms is None:
        return None
    d = ms_to_dt(ms, ZoneInfo(MARKET_TZ[market]))
    return d.strftime("%Y-%m-%d %H:%M" if time else "%Y-%m-%d")


def _strategy_text(d: Any) -> Any:
    if d.kind == "code":
        return {"kind": "code", "code": d.code[:4000]}
    data = json.loads(d.model_dump_json(exclude_defaults=True))
    return data


def as_json(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- backtest


def backtest(ctx: Any, run_id: int) -> dict[str, Any]:
    with ctx.db.session() as s:
        run = s.get(BacktestRun, run_id)
        if run is None:
            raise _missing("backtest")
        if run.status != "done":
            raise AgoraError(
                "NOT_READY",
                "This backtest hasn't finished.",
                "Wait for it to finish, then ask again.",
            )
        version = strategies.get_version(s, run.strategy_version_id)
        assert version is not None
        strat = s.get(Strategy, version.strategy_id)
        params = json.loads(run.params)
        metrics = json.loads(run.metrics or "{}")
        warnings = json.loads(run.warnings or "[]")
        market = Market(params["market"])
        names = dict(s.execute(select(Instrument.id, Instrument.symbol)).all())
        trades = s.scalars(
            select(BacktestTrade).where(
                BacktestTrade.run_id == run_id, BacktestTrade.exit_reason != "end_of_test"
            )
        ).all()
        summary = run.summary_text
    ranked = sorted(trades, key=lambda t: t.net_pnl)
    pick = ranked[-5:][::-1] + ranked[:5] if len(ranked) > 10 else ranked[::-1]

    def trade(t: BacktestTrade) -> dict[str, Any]:
        return {
            "stock": names.get(t.instrument_id, "?"),
            "side": t.side,
            "opened": _when(t.entry_ts, market),
            "closed": _when(t.exit_ts, market),
            "net_profit": t.net_pnl,
            "return_pct": t.return_pct,
            "why_opened": t.entry_reason,
            "why_closed": t.exit_reason,
        }

    monthly = metrics.get("monthly_returns") or {}
    return _rd(
        {
            "strategy": strat.name if strat else "Strategy",
            "rules": _strategy_text(version.definition),
            "settings": {
                "market": params.get("market"),
                "timeframe": params.get("timeframe"),
                "stocks": params.get("symbols", [])[:20],
                "from": _when(params.get("start"), market),
                "to": _when(params.get("end"), market),
                "starting_money": params.get("capital"),
                "brokerage": params.get("brokerage_profile"),
                "slippage_bps": params.get("slippage_bps"),
            },
            "results": {k: metrics[k] for k in HEADLINE if k in metrics},
            "money_in_words": _money_in_words(metrics, params.get("capital"), market),
            "monthly_returns": dict(list(monthly.items())[-24:]),
            "per_stock": (metrics.get("per_symbol") or [])[:10],
            "warnings": [{"title": w.get("title"), "text": w.get("text")} for w in warnings],
            "best_and_worst_trades": [trade(t) for t in pick],
            "agora_summary": summary,
        }
    )


# ---------------------------------------------------------------- one trade


def trade(ctx: Any, trade_id: int) -> dict[str, Any]:
    with ctx.db.session() as s:
        t = s.get(BacktestTrade, trade_id)
        if t is None:
            raise _missing("trade")
        run = s.get(BacktestRun, t.run_id)
        assert run is not None
        version = strategies.get_version(s, run.strategy_version_id)
        assert version is not None
        inst = store.get_instrument(s, t.instrument_id)
        assert inst is not None
        params = json.loads(run.params)
    d = version.definition
    market = inst.market
    tf = Timeframe(params.get("timeframe", d.timeframe))
    program = compile_definition(d)
    lo = t.entry_ts - warmup_ms(tf, program.warmup)
    hi = (t.exit_ts or t.entry_ts) + warmup_ms(tf, 3)
    raw = ctx.cache.bars(inst, tf, lo, hi)
    bars = [adjusted(b) for b in raw]
    stamps = [b.ts for b in bars]
    entry_i = next((i for i, ts in enumerate(stamps) if ts >= t.entry_ts), len(bars) - 1)
    exit_i = next(
        (i for i, ts in enumerate(stamps) if t.exit_ts is not None and ts >= t.exit_ts),
        len(bars) - 1,
    )
    if exit_i - entry_i <= 30:
        idx = list(range(max(0, entry_i - 8), min(len(bars), exit_i + 3)))
    else:  # long trades: the run-up to the entry and to the exit
        idx = list(range(max(0, entry_i - 8), entry_i + 3)) + list(
            range(max(0, exit_i - 8), min(len(bars), exit_i + 3))
        )
    candles = [
        {
            "time": _when(bars[i].ts, market, time=tf.is_intraday),
            "open": bars[i].open,
            "high": bars[i].high,
            "low": bars[i].low,
            "close": bars[i].close,
        }
        for i in idx
    ]
    indicators: dict[str, Any] = {}
    if isinstance(d, VisualDefinition) and bars:
        series = from_bars(bars, tf, market)
        seen: set[str] = set()
        rules = [d.entry.long, d.entry.short, d.exit.long, d.exit.short]
        for rule in rules:
            if rule is None:
                continue
            for op in iter_operands(rule):
                if not isinstance(op, IndicatorOperand):
                    continue
                p = {k: _num(v, program.params) for k, v in op.params.items()}
                label = f"{op.name}({','.join(f'{v:g}' for v in p.values())})"
                if op.output:
                    label += f".{op.output}"
                if label in seen:
                    continue
                seen.add(label)
                try:
                    out = catalog.compute(op.name, series, p, op.source)
                except (KeyError, ValueError):
                    continue
                arr = out.get(op.output) if op.output else next(iter(out.values()))
                if arr is None:
                    continue
                indicators[label] = {
                    "before_entry": _val(arr, entry_i - 1),
                    "before_exit": _val(arr, exit_i - 1),
                }
    return _rd(
        {
            "stock": inst.symbol,
            "market": market.value,
            "timeframe": tf.value,
            "rules": _strategy_text(d),
            "trade": {
                "side": t.side,
                "shares": t.qty,
                "opened": _when(t.entry_ts, market, time=tf.is_intraday),
                "entry_price": t.entry_price,
                "closed": _when(t.exit_ts, market, time=tf.is_intraday),
                "exit_price": t.exit_price,
                "gross_profit": t.gross_pnl,
                "charges": t.charges,
                "net_profit": t.net_pnl,
                "return_pct": t.return_pct,
                "candles_held": t.bars_held,
                "why_opened": t.entry_reason,
                "why_closed": t.exit_reason,
            },
            "candles_split_adjusted": candles,
            "indicator_values": indicators,
        }
    )


def _num(v: Any, params: dict[str, float]) -> float:
    if isinstance(v, str) and v.startswith("$"):
        return float(params.get(v[1:], 0.0))
    return float(v)


def _val(arr: Any, i: int) -> float | None:
    if i < 0 or i >= len(arr):
        return None
    v = float(arr[i])
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- metric


def metric(ctx: Any, run_id: int | None) -> dict[str, Any]:
    if run_id is None:
        return {}
    full = backtest(ctx, run_id)
    return {"strategy": full["strategy"], "results": full["results"]}


# ---------------------------------------------------------------- paper day


def paper_day(ctx: Any, session_id: int) -> dict[str, Any]:
    from backend.paper.compare import vs_backtest

    with ctx.db.session() as s:
        row = s.get(PaperSession, session_id)
        if row is None:
            raise _missing("paper session")
        version = strategies.get_version(s, row.strategy_version_id)
        assert version is not None
        strat = s.get(Strategy, version.strategy_id)
        market = Market(version.definition.market)
        zone = ZoneInfo(MARKET_TZ[market])
        last = row.last_bar_ts
        if last is None:
            raise AgoraError(
                "NOT_READY",
                "This session hasn't processed any candles yet.",
                "Ask again after it has run for a while.",
            )
        day = ms_to_dt(last, zone).date()
        start = int(datetime.combine(day, datetime.min.time(), zone).timestamp() * 1000)
        end = start + 86_400_000
        names = dict(s.execute(select(Instrument.id, Instrument.symbol)).all())
        trades = s.scalars(
            select(PaperTrade).where(
                PaperTrade.session_id == session_id,
                PaperTrade.exit_ts >= start,
                PaperTrade.exit_ts < end,
            )
        ).all()
        fills = s.execute(
            select(PaperOrder, PaperFill)
            .join(PaperFill, PaperFill.order_id == PaperOrder.id)
            .where(PaperOrder.session_id == session_id, PaperFill.ts >= start, PaperFill.ts < end)
        ).all()
        eq = s.execute(
            select(PaperEquity.ts, PaperEquity.equity)
            .where(PaperEquity.session_id == session_id, PaperEquity.ts < end)
            .order_by(PaperEquity.ts)
        ).all()
        events = s.scalars(
            select(PaperEvent).where(
                PaperEvent.session_id == session_id,
                PaperEvent.kind != "strategy_log",
                PaperEvent.ts >= start,
                PaperEvent.ts < end,
            )
        ).all()
    before = [v for ts, v in eq if ts < start]
    today = [v for ts, v in eq if ts >= start]
    open_value = before[-1] if before else (today[0] if today else None)
    close_value = today[-1] if today else open_value
    cmp = vs_backtest(ctx, session_id)
    return _rd(
        {
            "strategy": strat.name if strat else "Strategy",
            "day": day.isoformat(),
            "money_at_start_of_day": open_value,
            "money_at_end_of_day": close_value,
            "profit_or_loss_today": (close_value - open_value)
            if open_value is not None and close_value is not None
            else None,
            "trades_closed_today": [
                {
                    "stock": names.get(t.instrument_id, "?"),
                    "side": t.side,
                    "net_profit": t.net_pnl,
                    "return_pct": t.return_pct,
                    "why_closed": t.exit_reason,
                }
                for t in trades
            ],
            "fills_today": [
                {
                    "stock": names.get(o.instrument_id, "?"),
                    "side": o.side,
                    "shares": f.qty,
                    "price": f.price,
                    "reason": o.reason,
                }
                for o, f in fills[:30]
            ],
            "events_today": [e.message_plain for e in events][:20],
            "vs_backtest": {
                "live_return_pct": cmp["live"]["total_return"],
                "backtest_return_pct": cmp["backtest"]["total_return"],
                "notes": cmp["reasons"],
            }
            if cmp.get("ready")
            else None,
        }
    )
