"""A wide list must be judged as it stood before the exam (D-231)."""

from __future__ import annotations

from backend.context import AppContext
from backend.core.types import Bar, Market, Timeframe
from backend.data import store
from backend.metis import trial

DAY = 86_400_000
AT = 1_700_000_000_000


def bars(price: float, volume: float, start: int, days: int = 15) -> list[Bar]:
    return [
        Bar(
            ts=start + i * DAY,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            source="yahoo",
        )
        for i in range(days)
    ]


def test_the_list_then_uses_only_what_was_known_then(ctx: AppContext) -> None:
    with ctx.db.session() as s:
        early = store.find_instrument(s, Market.IN, "RELIANCE")
        late = store.find_instrument(s, Market.IN, "TCS")
        assert early is not None and late is not None
        store.upsert_bars(s, early.id, Timeframe.D1, bars(100, 1000, AT - 20 * DAY), 0)
        # TCS is huge, but only after the date: hindsight must not put it on the list
        store.upsert_bars(s, late.id, Timeframe.D1, bars(100, 10**9, AT + DAY), 0)
    assert trial.list_then(ctx, Market.IN, AT, 10) == ["RELIANCE"]
