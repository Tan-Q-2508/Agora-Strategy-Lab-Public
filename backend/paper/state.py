"""Save and restore the engine's account state, so a paper session resumes after a restart.

Only what the engine can't rebuild from prices is saved: cash, open positions (with their
stops and targets), the day's starting equity, the daily-loss pause, and the orders waiting
for the next candle. A waiting order comes back only if no candle has closed since it was
placed: the candle it waits for is still ahead, so it fills exactly as if Agora had stayed
open (a daily desk decides at the close and buys at the next open, so closing Agora
overnight used to throw away every daily order, D-152). If a candle closed while Agora was
away, the moment has passed and filling it now would be a trade the session never really
took (D-06).
"""

from __future__ import annotations

import bisect
from decimal import Decimal
from typing import Any

from backend.costs.model import Charges
from backend.engine.core import Engine, rescale
from backend.engine.types import PendingOrder, Position, ScaleLevel
from backend.strategy.runtime import ScaleOut, ScaleStep, StopRule


def _rule(r: StopRule | None) -> dict[str, Any] | None:
    return None if r is None else {"kind": r.kind, "value": r.value, "atr_period": r.atr_period}


def _unrule(d: dict[str, Any] | None) -> StopRule | None:
    return None if d is None else StopRule(d["kind"], float(d["value"]), int(d["atr_period"]))


def _scale(s: ScaleOut | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "steps": [{"kind": x.kind, "value": x.value, "sell_pct": x.sell_pct} for x in s.steps],
        "breakeven": s.breakeven,
    }


def _unscale(d: dict[str, Any] | None) -> ScaleOut | None:
    if d is None:
        return None
    steps = tuple(ScaleStep(x["kind"], float(x["value"]), float(x["sell_pct"])) for x in d["steps"])
    return ScaleOut(steps, bool(d.get("breakeven", True)))


def _order(o: PendingOrder) -> dict[str, Any]:
    return {
        "kind": o.kind,
        "side": o.side,
        "qty": o.qty,
        "created_ts": o.created_ts,
        "created_day": o.created_day,
        "reason": o.reason,
        "exit_kind": o.exit_kind,
        "stop_loss": _rule(o.stop_loss),
        "take_profit": _rule(o.take_profit),
        "trailing_stop": _rule(o.trailing_stop),
        "atr_raw": o.atr_raw,
        "scale_out": _scale(o.scale_out),
    }


def _unorder(d: dict[str, Any], index: int) -> PendingOrder:
    return PendingOrder(
        d["kind"],
        d["side"],
        float(d["qty"]),
        int(d["created_ts"]),
        index,
        d["created_day"],
        d["reason"],
        exit_kind=d.get("exit_kind", "signal"),
        stop_loss=_unrule(d.get("stop_loss")),
        take_profit=_unrule(d.get("take_profit")),
        trailing_stop=_unrule(d.get("trailing_stop")),
        atr_raw=d.get("atr_raw"),
        scale_out=_unscale(d.get("scale_out")),
    )


def snapshot(engine: Engine) -> dict[str, Any]:
    positions: dict[str, Any] = {}
    for st in engine.symbols:
        p = st.position
        if p is None:
            continue
        positions[str(st.inst.id)] = {
            "side": p.side,
            "qty": p.qty,
            "entry_price": p.entry_price,
            "entry_ts": p.entry_ts,
            "entry_reason": p.entry_reason,
            "entry_charges": {k: str(v) for k, v in p.entry_charges.items.items()},
            "dividends": p.dividends,
            "stop": p.stop,
            "target": p.target,
            "trail": _rule(p.trail),
            "trail_level": p.trail_level,
            "peak": p.peak,
            "atr_raw": p.atr_raw,
            "signal_ts": p.signal_ts,
            # partial exits (D-125)
            "start_qty": p.start_qty,
            "scale": [[lv.price, lv.qty] for lv in p.scale],
            "scale_breakeven": p.scale_breakeven,
            "partials": p.partials,
            "sold_qty": p.sold_qty,
            "sold_value": p.sold_value,
            "sold_gross": p.sold_gross,
            "sold_charges": {k: str(v) for k, v in p.sold_charges.items.items()},
            "factor": st.raw[st.last_index].split_factor if st.last_index >= 0 else 1.0,
        }
    return {
        "cash": engine.cash,
        "day": engine._day,
        "day_start_equity": engine._day_start_equity,
        "entries_paused_day": engine._entries_paused_day,
        "last_sell_day": {str(st.inst.id): st.last_sell_day for st in engine.symbols},
        "positions": positions,
        "orders": {
            str(st.inst.id): [_order(o) for o in st.pending] for st in engine.symbols if st.pending
        },
    }


def restore(engine: Engine, data: dict[str, Any]) -> list[str]:
    """Put a snapshot back into a freshly built engine whose symbols hold the candles up to
    now. Returns plain-English notes (e.g. a split while Agora was closed)."""
    notes: list[str] = []
    engine.cash = float(data["cash"])
    engine._day = data.get("day")
    engine._day_start_equity = float(data.get("day_start_equity", engine.cash))
    engine._entries_paused_day = data.get("entries_paused_day")
    sells = data.get("last_sell_day", {})
    for st in engine.symbols:
        st.last_index = len(st.raw) - 1
        st.last_sell_day = sells.get(str(st.inst.id))
        saved = data.get("positions", {}).get(str(st.inst.id))
        if saved is None or not st.raw:
            continue
        stamps = [b.ts for b in st.raw]
        entry_index = bisect.bisect_left(stamps, int(saved["entry_ts"]))
        p = Position(
            side=saved["side"],
            qty=float(saved["qty"]),
            entry_price=float(saved["entry_price"]),
            entry_ts=int(saved["entry_ts"]),
            entry_index=entry_index,
            entry_reason=saved["entry_reason"],
            entry_charges=Charges({k: Decimal(v) for k, v in saved["entry_charges"].items()}),
            dividends=float(saved["dividends"]),
            stop=saved["stop"],
            target=saved["target"],
            trail=_unrule(saved["trail"]),
            trail_level=saved["trail_level"],
            peak=float(saved["peak"]),
            atr_raw=saved["atr_raw"],
            signal_ts=int(saved.get("signal_ts") or 0),
            start_qty=float(saved.get("start_qty") or saved["qty"]),
            scale=[ScaleLevel(float(a), float(b)) for a, b in saved.get("scale", [])],
            scale_breakeven=bool(saved.get("scale_breakeven", False)),
            partials=int(saved.get("partials", 0)),
            sold_qty=float(saved.get("sold_qty", 0.0)),
            sold_value=float(saved.get("sold_value", 0.0)),
            sold_gross=float(saved.get("sold_gross", 0.0)),
            sold_charges=Charges({k: Decimal(v) for k, v in saved.get("sold_charges", {}).items()}),
        )
        now_factor = st.raw[-1].split_factor
        if now_factor != saved["factor"]:  # a split happened while Agora was closed
            ratio = now_factor / float(saved["factor"])
            p.qty *= ratio
            p.entry_price /= ratio
            p.peak /= ratio
            for attr in ("stop", "target", "trail_level", "atr_raw"):
                v = getattr(p, attr)
                if v is not None:
                    setattr(p, attr, v / ratio)
            rescale(p, ratio)
            notes.append(f"{st.inst.symbol} split {ratio:g}-for-1 while Agora was closed.")
        st.position = p
    engine.last_equity = engine.equity_now()
    return notes


def restore_orders(engine: Engine, data: dict[str, Any]) -> tuple[int, int]:
    """Put back the waiting orders whose candle is still ahead: the newest saved candle is the
    one they were placed on, so no candle closed while Agora was away (D-152). Returns
    (kept, cancelled). Call after ``restore``."""
    kept = dropped = 0
    saved = data.get("orders", {})
    for st in engine.symbols:
        orders = saved.get(str(st.inst.id), [])
        if not orders:
            continue
        last = st.raw[-1].ts if st.raw else None
        for d in orders:
            if last is not None and int(d["created_ts"]) == last:
                if d["kind"] == "exit" and st.position is None:
                    dropped += 1
                    continue
                st.pending.append(_unorder(d, len(st.raw) - 1))
                kept += 1
            else:
                dropped += 1
    return kept, dropped
