"""Shared fixtures for the lab's tests."""

from __future__ import annotations

import pytest

from backend.context import AppContext
from backend.core.types import Market, Timeframe
from backend.data import service as data_service

DAY = 86_400_000


@pytest.fixture
def stocked(ctx: AppContext) -> AppContext:
    """Every Indian practice stock's daily candles saved, like a laptop after downloads."""
    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        insts = data_service.default_symbols(s, Market.IN)
    for inst in insts:
        ctx.cache.ensure(inst, Timeframe.D1, now - 12 * 365 * DAY, now)
    return ctx
