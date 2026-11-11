"""Charges per executed order (COST_MODEL.md §1–2), in ``Decimal``.

Rounding follows contract-note practice and lives only here: each charge is rounded to
the paisa/cent (half-up); India STT to the nearest rupee; the US SEC fee up to the next
cent (as brokers pass it on). GST is computed on the already-rounded brokerage, exchange
charge, SEBI fee and DP charge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any, Literal

from backend.costs.schedule import ChargeTable, RateRow

D0 = Decimal(0)
CENT = Decimal("0.01")
RUPEE = Decimal(1)
CRORE = Decimal(10_000_000)
MILLION = Decimal(1_000_000)
OrderSide = Literal["buy", "sell"]

LABELS = {
    "brokerage": "Brokerage",
    "commission": "Commission",
    "stt": "Securities transaction tax (STT)",
    "exchange_txn": "Exchange transaction charge",
    "sebi_fee": "SEBI fee",
    "stamp_duty": "Stamp duty",
    "gst": "GST",
    "dp_charge": "Depository (DP) charge",
    "sec_fee": "SEC fee",
    "finra_taf": "FINRA trading activity fee",
}


def dec(x: float | int | str) -> Decimal:
    return Decimal(str(x))


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Charges:
    items: dict[str, Decimal] = field(default_factory=dict)
    schedule_ids: tuple[int, ...] = ()

    @property
    def total(self) -> Decimal:
        return sum(self.items.values(), D0)

    def __add__(self, other: Charges) -> Charges:
        items = dict(self.items)
        for k, v in other.items.items():
            items[k] = items.get(k, D0) + v
        return Charges(items, tuple(sorted(set(self.schedule_ids) | set(other.schedule_ids))))

    def public(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.items.items() if v}


ZERO = Charges()


def _apply(row: RateRow, turnover: Decimal, qty: Decimal) -> Decimal:
    rate = dec(row.rate)
    if row.rate_type == "percent":
        value = turnover * rate / 100
    elif row.rate_type == "per_crore":
        value = turnover * rate / CRORE
    elif row.rate_type == "per_million":
        value = turnover * rate / MILLION
    elif row.rate_type == "per_share":
        value = qty * rate
    else:  # flat_per_order / flat_per_scrip_day
        value = rate
    if row.cap is not None:
        value = min(value, dec(row.cap))
    return value


def brokerage(rules: dict[str, Any], turnover: Decimal, qty: Decimal) -> Decimal:
    """A profile rule: any of ``flat``, ``percent``, ``per_share``, ``min``, ``cap``."""
    value = D0
    if "flat" in rules:
        value += dec(rules["flat"])
    if "percent" in rules:
        value += turnover * dec(rules["percent"]) / 100
    if "per_share" in rules:
        value += qty * dec(rules["per_share"])
    if "cap" in rules:
        value = min(value, dec(rules["cap"]))
    if "min" in rules:
        value = max(value, dec(rules["min"]))
    return r2(value)


class CostModel:
    """Charges for one market + trade type with one brokerage profile."""

    def __init__(
        self, market: str, product: str, brokerage_rules: dict[str, Any], table: ChargeTable
    ) -> None:
        self.market = market
        self.product = product
        self.rules: dict[str, Any] = brokerage_rules.get(product, {})
        self.table = table

    @classmethod
    def from_profile_json(
        cls, market: str, product: str, rules_json: str, table: ChargeTable
    ) -> CostModel:
        return cls(market, product, json.loads(rules_json), table)

    def order(
        self,
        side: str,
        qty: float,
        price: float,
        at_ms: int,
        *,
        first_sell_of_day: bool = True,
    ) -> Charges:
        """Charges for one executed order (``side`` is "buy" or "sell").
        ``first_sell_of_day`` controls the India DP
        charge, which is levied once per stock per day on delivery sells."""
        q = dec(qty)
        turnover = dec(price) * q
        items: dict[str, Decimal] = {}
        ids: list[int] = []

        def rate(charge: str) -> RateRow | None:
            row = self.table.find(charge, self.product, side, at_ms)
            if row is not None:
                ids.append(row.id)
            return row

        if self.market == "IN":
            items["brokerage"] = brokerage(self.rules, turnover, q)
            row = rate("stt")
            items["stt"] = (
                _apply(row, turnover, q).quantize(RUPEE, rounding=ROUND_HALF_UP) if row else D0
            )
            for charge in ("exchange_txn", "sebi_fee", "stamp_duty"):
                row = rate(charge)
                items[charge] = r2(_apply(row, turnover, q)) if row else D0
            dp = D0
            if side == "sell" and self.product == "delivery" and first_sell_of_day:
                row = rate("dp_charge")
                dp = r2(_apply(row, turnover, q)) if row else D0
            items["dp_charge"] = dp
            row = rate("gst")
            base = items["brokerage"] + items["exchange_txn"] + items["sebi_fee"] + dp
            items["gst"] = r2(base * dec(row.rate) / 100) if row else D0
        else:
            items["commission"] = brokerage(self.rules, turnover, q)
            row = rate("sec_fee")
            items["sec_fee"] = (
                _apply(row, turnover, q).quantize(CENT, rounding=ROUND_UP) if row else D0
            )
            row = rate("finra_taf")
            items["finra_taf"] = r2(_apply(row, turnover, q)) if row else D0
        return Charges(items, tuple(sorted(set(ids))))


def slipped(price: float, bps: float, *, paying: bool) -> float:
    """Slippage always works against the trader: buys pay more, sells receive less."""
    factor = 1.0 + bps / 10_000.0 if paying else 1.0 - bps / 10_000.0
    return round(price * factor, 6)
