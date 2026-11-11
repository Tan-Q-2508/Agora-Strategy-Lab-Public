"""Where the trade check's experience is kept (``kairos_trade_samples``, D-71).

Every trade a backtest or paper session makes, with the market's condition when it fired,
is saved once (re-running the same backtest replaces its rows instead of counting the same
trades twice). Seeds for a new run only use results that were *complete* before the run's
first candle and were saved before it started, so a backtest can't learn from its own
future and a live session is reproducible (D-04).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.db.models import KairosTradeSample, Strategy
from backend.kairos.quality import Sample

PAPER_WEIGHT = 1.5  # live paper results count more than history


def save(
    s: Session,
    *,
    strategy_id: int,
    strategy_kind: str,
    market: str,
    timeframe: str,
    source: str,
    ref_id: int,
    samples: Iterable[Sample],
    now: int,
) -> int:
    """Upsert samples (same strategy, source, symbol, signal candle, side and origin = the
    same trade). Returns how many were written."""
    n = 0
    for smp in samples:
        origin = "shadow" if smp.source == "shadow" else "trade"
        s.execute(
            delete(KairosTradeSample).where(
                KairosTradeSample.strategy_id == strategy_id,
                KairosTradeSample.source == source,
                KairosTradeSample.symbol == smp.symbol,
                KairosTradeSample.signal_ts == smp.ts,
                KairosTradeSample.side == smp.side,
                KairosTradeSample.origin == origin,
            )
        )
        weight = smp.weight * (PAPER_WEIGHT if source == "paper" else 1.0)
        s.add(
            KairosTradeSample(
                strategy_id=strategy_id,
                strategy_kind=strategy_kind,
                market_code=market,
                timeframe=timeframe,
                source=source,
                ref_id=ref_id,
                origin=origin,
                symbol=smp.symbol,
                side=smp.side,
                signal_ts=smp.ts,
                known_ts=smp.known_ts,
                features=json.dumps(smp.features, separators=(",", ":")),
                ret_pct=float(smp.ret_pct),
                win=int(smp.win),
                weight=float(weight),
                created_at=now,
            )
        )
        n += 1
    return n


def _rows_to_samples(rows: Sequence[KairosTradeSample]) -> list[Sample]:
    out = []
    for r in rows:
        out.append(
            Sample(
                {k: float(v) for k, v in json.loads(r.features or "{}").items()},
                bool(r.win),
                float(r.ret_pct),
                float(r.weight),
                int(r.signal_ts),
                int(r.known_ts),
                int(r.side),
                r.symbol,
                "shadow" if r.origin == "shadow" else "trade",
            )
        )
    return out


def seed(
    s: Session,
    *,
    strategy_id: int,
    market: str,
    timeframe: str,
    known_before: int,
    saved_before: int,
) -> list[Sample]:
    """What the trade check already knows when a run starts at ``known_before``.

    The strategy's own results come first; Kairos strategies also share what every Kairos
    strategy in the same market and timeframe learned (they trade the same signals)."""
    kind = s.scalar(select(Strategy.kind).where(Strategy.id == strategy_id))
    q = select(KairosTradeSample).where(
        KairosTradeSample.market_code == market,
        KairosTradeSample.timeframe == timeframe,
        KairosTradeSample.known_ts < known_before,
        KairosTradeSample.created_at <= saved_before,
    )
    if kind == "kairos":
        q = q.where(KairosTradeSample.strategy_kind == "kairos")
    else:
        q = q.where(KairosTradeSample.strategy_id == strategy_id)
    rows = s.scalars(q.order_by(KairosTradeSample.known_ts, KairosTradeSample.id)).all()
    return _rows_to_samples(rows)


def for_strategy(s: Session, strategy_id: int) -> list[Sample]:
    rows = s.scalars(
        select(KairosTradeSample)
        .where(KairosTradeSample.strategy_id == strategy_id)
        .order_by(KairosTradeSample.known_ts, KairosTradeSample.id)
    ).all()
    return _rows_to_samples(rows)


def count(s: Session, strategy_id: int | None = None) -> int:
    q = select(KairosTradeSample.id)
    if strategy_id is not None:
        q = q.where(KairosTradeSample.strategy_id == strategy_id)
    return len(s.execute(q).all())
