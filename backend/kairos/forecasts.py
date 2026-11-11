"""Kairos keeps every prediction it shows and checks it against the candles that actually
formed (KAIROS §5, §17, D-58, D-73).

``record`` saves a forecast once per candle and horizon: its range, its predicted candles,
each model's range and the raw (uncorrected) middle and half-range. ``score`` settles the
ones whose horizon has passed: direction right, inside the 8-in-10 range, and a candle-by-
candle review (did each predicted candle point the right way, did each close land inside
its range, how far the end was off). ``memory`` hands the misses and each model's loss back
to ``forecast.forecast`` so the next forecast is corrected by them; ``previous`` finds the
latest prediction whose candles have (partly) formed, for the chart's "prediction vs what
happened" view.

A forecast counts as a direction hit when the price moved the way its middle line pointed
(or, when that was flat, the way it gave better than even odds). Nothing here changes a
saved forecast; it only keeps score and remembers.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from backend.analysis.forecast import QUANTILES, Memory
from backend.core.types import Bar, Market, Timeframe
from backend.data.store import InstrumentRef
from backend.db.models import Instrument, KairosForecast


def record(ctx: Any, inst: InstrumentRef, tf: Timeframe, made_at: int, f: dict[str, Any]) -> None:
    """Keep the forecast made from the candle at ``made_at`` (once per candle and horizon)."""
    last = f["path"][-1]
    detail = {
        "path": f["path"][1:],
        "candles": f.get("candles") or [],
        "raw": f.get("raw") or {},
        "models": f.get("models_q") or {},
        "calibration": f.get("calibration") or {},
    }
    with ctx.db.session() as s:
        exists = s.scalar(
            select(KairosForecast.id).where(
                KairosForecast.instrument_id == inst.id,
                KairosForecast.timeframe == tf.value,
                KairosForecast.made_at == made_at,
                KairosForecast.horizon == f["horizon"],
            )
        )
        if exists is not None:
            return
        s.add(
            KairosForecast(
                instrument_id=inst.id,
                timeframe=tf.value,
                made_at=made_at,
                horizon=int(f["horizon"]),
                origin=float(f["origin"]),
                p10=float(last["p10"]),
                p25=float(last["p25"]) if "p25" in last else None,
                p50=float(last["median"]),
                p75=float(last["p75"]) if "p75" in last else None,
                p90=float(last["p90"]),
                up_prob=float(f["up_probability"]),
                detail=json.dumps(detail, separators=(",", ":")),
            )
        )


def compare(detail: dict[str, Any], origin: float, actual: Sequence[Bar]) -> dict[str, Any]:
    """Predicted candles against the candles that formed (as many as have formed)."""
    pred = list(detail.get("candles") or [])
    path = list(detail.get("path") or [])
    rows = []
    dir_hits = dir_n = inside = 0
    for k, bar in enumerate(actual):
        p = pred[k] if k < len(pred) else None
        band = path[k] if k < len(path) else None
        row: dict[str, Any] = {
            "ts": bar.ts,
            "actual": {"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close},
        }
        if p is not None:
            row["predicted"] = {x: p[x] for x in ("open", "high", "low", "close")}
            want = int(p.get("direction", 0))
            got = 0 if bar.close == bar.open else (1 if bar.close > bar.open else -1)
            if want != 0 and got != 0:
                dir_n += 1
                dir_hits += int(want == got)
                row["direction_right"] = want == got
        if band is not None:
            ok = float(band["p10"]) <= bar.close <= float(band["p90"])
            inside += int(ok)
            row["inside80"] = ok
            row["p10"], row["p90"] = band["p10"], band["p90"]
        rows.append(row)
    out: dict[str, Any] = {"candles": rows, "formed": len(rows), "horizon": len(pred) or len(path)}
    if rows:
        end_pred = float(pred[len(rows) - 1]["close"]) if len(pred) >= len(rows) else None
        end_act = rows[-1]["actual"]["close"]
        out.update(
            {
                "direction_hits": dir_hits,
                "direction_scored": dir_n,
                "inside80": inside,
                "predicted_change_pct": None
                if end_pred is None
                else round(100.0 * (end_pred / origin - 1.0), 2),
                "actual_change_pct": round(100.0 * (end_act / origin - 1.0), 2),
                "end_error_pct": None
                if end_pred is None
                else round(100.0 * (end_act / end_pred - 1.0), 2),
            }
        )
        out["text"] = compare_words(out)
    return out


def compare_words(c: dict[str, Any]) -> str:
    formed, horizon = c["formed"], c["horizon"]
    bits = [
        f"{formed} of {horizon} predicted candles have formed"
        if formed < horizon
        else f"All {horizon} predicted candles have formed"
    ]
    bits.append(f"the close stayed inside the 8-in-10 range on {c['inside80']} of {formed}")
    if c.get("direction_scored"):
        bits.append(
            f"{c['direction_hits']} of {c['direction_scored']} candles that had a direction "
            f"pointed the right way"
        )
    if c.get("predicted_change_pct") is not None:
        bits.append(
            f"Kairos expected {c['predicted_change_pct']:+.1f}% by now and the price moved "
            f"{c['actual_change_pct']:+.1f}%"
        )
    return "; ".join(bits) + "."


def _pinball(q: Sequence[float], actual: float) -> float:
    loss = 0.0
    for t, v in zip(QUANTILES, q, strict=True):
        e = actual - float(v)
        loss += max(t * e, (t - 1) * e)
    return loss / len(QUANTILES)


def score(ctx: Any, inst: InstrumentRef, tf: Timeframe, bars: list[Bar]) -> int:
    """Resolve this stock's forecasts whose horizon has passed. Returns how many."""
    if not bars:
        return 0
    index = {b.ts: k for k, b in enumerate(bars)}
    done = 0
    with ctx.db.session() as s:
        rows = s.scalars(
            select(KairosForecast).where(
                KairosForecast.instrument_id == inst.id,
                KairosForecast.timeframe == tf.value,
                KairosForecast.resolved_at.is_(None),
            )
        ).all()
        for r in rows:
            k = index.get(r.made_at)
            if k is None or k + r.horizon >= len(bars):
                continue
            end = bars[k + r.horizon]
            actual = end.close
            if r.p50 != r.origin:
                pointed_up = r.p50 > r.origin
            else:
                pointed_up = r.up_prob >= 0.5
            r.actual = actual
            r.resolved_at = end.ts
            r.hit = int(actual != r.origin and (actual > r.origin) == pointed_up)
            r.inside80 = int(r.p10 <= actual <= r.p90)
            if r.detail:
                detail = json.loads(r.detail)
                review = compare(detail, r.origin, bars[k + 1 : k + 1 + r.horizon])
                move = math.log(actual / r.origin) if actual > 0 and r.origin > 0 else 0.0
                raw = detail.get("raw") or {}
                if raw.get("half"):
                    review["miss"] = round((move - float(raw["median"])) / float(raw["half"]), 4)
                review["model_loss"] = {
                    m: round(_pinball(q, move), 6)
                    for m, q in (detail.get("models") or {}).items()
                    if len(q) == len(QUANTILES)
                }
                r.review = json.dumps(review, separators=(",", ":"))
            done += 1
    return done


def memory(ctx: Any, inst: InstrumentRef, tf: Timeframe, limit: int = 100) -> Memory:
    """What this stock's scored live forecasts taught (oldest first)."""
    with ctx.db.session() as s:
        rows = s.scalars(
            select(KairosForecast.review)
            .where(
                KairosForecast.instrument_id == inst.id,
                KairosForecast.timeframe == tf.value,
                KairosForecast.review.is_not(None),
            )
            .order_by(KairosForecast.made_at.desc())
            .limit(limit)
        ).all()
    misses: list[float] = []
    losses: dict[str, list[float]] = {}
    for raw in reversed(rows):
        rv = json.loads(raw or "{}")
        if rv.get("miss") is not None and math.isfinite(float(rv["miss"])):
            misses.append(float(rv["miss"]))
        for m, v in (rv.get("model_loss") or {}).items():
            losses.setdefault(m, []).append(float(v))
    return Memory(tuple(misses), {k: tuple(v) for k, v in losses.items()})


def previous(
    ctx: Any, inst: InstrumentRef, tf: Timeframe, bars: list[Bar]
) -> dict[str, Any] | None:
    """The latest saved prediction with formed candles: the one with the most candles
    formed (up to its horizon), the newest among equals."""
    if len(bars) < 2:
        return None
    index = {b.ts: k for k, b in enumerate(bars)}
    with ctx.db.session() as s:
        rows = s.scalars(
            select(KairosForecast)
            .where(
                KairosForecast.instrument_id == inst.id,
                KairosForecast.timeframe == tf.value,
                KairosForecast.detail.is_not(None),
                KairosForecast.made_at < bars[-1].ts,
            )
            .order_by(KairosForecast.made_at.desc())
            .limit(60)
        ).all()
        best: tuple[int, int, KairosForecast] | None = None
        for r in rows:
            k = index.get(r.made_at)
            if k is None:
                continue
            formed = min(r.horizon, len(bars) - 1 - k)
            if formed <= 0:
                continue
            key = (formed, r.made_at)
            if best is None or key > (best[0], best[1]):
                best = (formed, r.made_at, r)
        if best is None:
            return None
        r = best[2]
        k = index[r.made_at]
        detail = json.loads(r.detail or "{}")
        out = compare(detail, r.origin, bars[k + 1 : k + 1 + r.horizon])
        out.update(
            {
                "made_at": r.made_at,
                "origin": r.origin,
                "kind": "live",
                "predicted": detail.get("candles") or [],
                "path": detail.get("path") or [],
                "complete": r.resolved_at is not None,
            }
        )
        return out


def live_record(
    ctx: Any, tf: Timeframe, *, inst: InstrumentRef | None = None, market: Market | None = None
) -> dict[str, Any]:
    """How Kairos's live forecasts did (for one stock, or a whole market)."""
    with ctx.db.session() as s:
        q = select(KairosForecast.hit, KairosForecast.inside80).where(
            KairosForecast.timeframe == tf.value, KairosForecast.resolved_at.is_not(None)
        )
        if inst is not None:
            q = q.where(KairosForecast.instrument_id == inst.id)
        elif market is not None:
            q = q.join(Instrument, Instrument.id == KairosForecast.instrument_id).where(
                Instrument.market_code == market.value
            )
        rows = s.execute(q).all()
        pending_q = select(KairosForecast.id).where(
            KairosForecast.timeframe == tf.value, KairosForecast.resolved_at.is_(None)
        )
        if inst is not None:
            pending_q = pending_q.where(KairosForecast.instrument_id == inst.id)
        pending = len(s.execute(pending_q).all())
    n = len(rows)
    hits = sum(int(h or 0) for h, _ in rows)
    inside = sum(int(x or 0) for _, x in rows)
    return {"n": n, "direction_hits": hits, "inside80": inside, "pending": pending}
