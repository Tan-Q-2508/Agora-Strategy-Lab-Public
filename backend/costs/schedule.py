"""Effective-dated charge rates (D-09), loaded once per run from ``charge_schedules``.

A rate is found by market, charge, product (exact or ``any``), side (exact or ``both``)
and the simulated trade time, so a 2018 backtest pays 2018's rates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import ChargeSchedule


@dataclass(frozen=True)
class RateRow:
    id: int
    charge: str
    product: str
    side: str
    rate_type: str
    rate: float
    cap: float | None
    effective_from: int
    effective_to: int | None
    verified: bool

    def covers(self, at_ms: int) -> bool:
        return self.effective_from <= at_ms and (
            self.effective_to is None or at_ms <= self.effective_to
        )


class ChargeTable:
    def __init__(self, rows: list[RateRow]) -> None:
        self._by_charge: dict[str, list[RateRow]] = defaultdict(list)
        for r in rows:
            self._by_charge[r.charge].append(r)

    @classmethod
    def load(cls, s: Session, market: str) -> ChargeTable:
        rows = [
            RateRow(
                r.id,
                r.charge,
                r.product,
                r.side,
                r.rate_type,
                r.rate,
                r.cap,
                r.effective_from,
                r.effective_to,
                r.verified_at is not None,
            )
            for r in s.scalars(select(ChargeSchedule).where(ChargeSchedule.market_code == market))
        ]
        return cls(rows)

    def find(self, charge: str, product: str, side: str, at_ms: int) -> RateRow | None:
        for r in self._by_charge.get(charge, ()):
            if r.product not in (product, "any"):
                continue
            if r.side not in (side, "both"):
                continue
            if r.covers(at_ms):
                return r
        return None

    def charges(self) -> list[str]:
        return list(self._by_charge)
