"""Are the charges on every paper fill what the cost model says? (WEEKEND_BRIEF §3)

Recomputes each fill with the same ``CostModel`` the golden tests prove against
``docs/COST_MODEL.md``, at the fill's own date, so a change in the tables or a fill saved with the
wrong product shows up. ``db`` is an ordinary ``Database``; nothing is written.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from backend.costs.model import CostModel
from backend.costs.schedule import ChargeTable
from backend.db.models import (
    BrokerageProfile,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperSession,
    StrategyVersion,
)
from backend.diagnosis.reconcile import Check

TOLERANCE = 0.02  # money units: rounding of a saved float


def charges_match_model(db: Any) -> Check:
    chk = Check("charges_match_model", "Do the charges on every fill match the cost model?")
    models: dict[int, CostModel] = {}
    with db.session() as s:
        tables = {m: ChargeTable.load(s, m) for m in ("IN", "US")}
        for sess in s.scalars(select(PaperSession)):
            acct = s.get(PaperAccount, sess.account_id)
            version = s.get(StrategyVersion, sess.strategy_version_id)
            profile = s.get(BrokerageProfile, acct.brokerage_profile_id) if acct else None
            if acct is None or version is None or profile is None:
                continue
            product = json.loads(version.definition).get("product", "delivery")
            market = acct.market_code
            models[sess.id] = CostModel(market, product, json.loads(profile.rules), tables[market])
        rows = s.execute(
            select(PaperFill, PaperOrder.session_id, PaperOrder.side).join(
                PaperOrder, PaperOrder.id == PaperFill.order_id
            )
        ).all()
        for fill, sid, side in rows:
            model = models.get(sid)
            if model is None:
                continue
            chk.checked += 1
            want = float(model.order(side, fill.qty, fill.price, fill.ts).total)
            if abs(want - fill.charges) > max(TOLERANCE, want * 0.001):
                chk.faults.append(
                    f"session {sid} fill {fill.id}: {side} {fill.qty:g} at {fill.price:g}: "
                    f"saved {fill.charges:.2f}, model {want:.2f}"
                )
    return chk
