"""Kairos's options tool: the numbers behind any option or futures strategy (KAIROS §19).

Agora has no option chains, so premiums are *estimated* with Black-Scholes from the stock's
own recent volatility (annualised from the last 60 daily moves) and labelled as estimates.
Everything else (maximum profit and loss, break-evens, chance of profit, Greeks) follows
from the legs by arithmetic (``backend/analysis/options.py``).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import Field

from backend.analysis import options as opt
from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.data.store import InstrumentRef, find_instrument
from backend.errors import AgoraError
from backend.kairos import resolve
from backend.kairos.tools.base import Args, Env, Result, Tool, money

# NSE index lot sizes from the January 2026 contracts (NSE circular of 3 Oct 2025).
INDEX_LOTS = {"NIFTY50": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120}
RATE = {Market.IN: 0.06, Market.US: 0.04}  # rough risk-free rates; matter little here


class OptionArgs(Args):
    strategy: str = Field(
        description="The strategy, e.g. 'iron condor', 'covered call', 'bull call spread'."
    )
    symbol: str | None = Field(None, description="Stock or index, e.g. 'Nifty', 'TCS', 'AAPL'.")
    days: int | None = Field(
        None, description="Days to expiry (default 7 for an index, 30 for a stock)."
    )
    volatility: float | None = Field(
        None,
        description="Implied volatility in % if known (default: the stock's recent volatility).",
    )
    lots: float = Field(1.0, description="How many lots.")


def _underlying(env: Env, text: str | None) -> InstrumentRef:
    low = (text or "").lower()
    if any(w in low.replace(" ", "") for w in ("banknifty", "finnifty", "midcap", "sensex")):
        raise AgoraError(
            "NO_INDEX_PRICES",
            "Agora keeps prices for the Nifty 50 index, not that one.",
            "Ask about Nifty or a stock; the rules and strategy shapes are the same.",
        )
    if not text or ("nifty" in low and not resolve.find_in_text(env.ctx, low.replace("nifty", ""))):
        with env.ctx.db.session() as s:
            idx = find_instrument(s, Market.IN, data_service.BENCHMARK[Market.IN])
        if idx is not None:
            return idx
    return resolve.stock(env.ctx, text or "NIFTY50", resolve.market_of(env.state.market))


def option_strategy(env: Env, a: OptionArgs) -> Result:
    info = opt.find_strategy(a.strategy)
    if info is None:
        names = ", ".join(s.name.lower() for s in list(opt.STRATEGIES.values())[:12])
        raise AgoraError(
            "UNKNOWN_STRATEGY",
            f"I don't know an option strategy called “{a.strategy}”.",
            f"Try one of: {names}, …",
        )
    inst = _underlying(env, a.symbol)
    now = env.ctx.clock.now_ms()
    bars = env.ctx.cache.bars(
        inst, Timeframe.D1, now - 200 * 86_400_000, now + 1, adjusted_prices=True
    )
    if len(bars) < 30:
        raise AgoraError(
            "NOT_ENOUGH_PRICES",
            f"I need {inst.symbol}'s recent daily prices to work this out.",
            "Download its history on the Data screen, then ask again.",
        )
    closes = np.array([b.close for b in bars[-61:]], dtype=np.float64)
    spot = float(closes[-1])
    hist_vol = float(np.std(np.diff(np.log(closes))) * math.sqrt(252))
    vol = a.volatility / 100.0 if a.volatility else max(hist_vol, 0.05)
    days = a.days or (7 if inst.is_index else 30)
    gap = opt.strike_gap(spot)
    atm = round(spot / gap) * gap
    market = inst.market
    an = opt.analyze(info.build(atm, gap), spot, days, vol, RATE[market])
    lot = (
        INDEX_LOTS.get(inst.symbol, 1)
        if market is Market.IN and inst.is_index
        else (100 if market is Market.US else 1)
    )
    per = "per lot" if lot > 1 else "per share (multiply by the lot size)"
    size = lot * a.lots
    m = market.value
    lines = [
        f"{info.name} on {inst.symbol} at {spot:,.2f}, {days} days to expiry, volatility "
        f"{vol * 100:.0f}%{' (its own recent volatility)' if not a.volatility else ''}. "
        f"Money figures are {per}" + (f" ({lot} units)" if lot > 1 else "") + ".",
        *opt.describe(an, info, size, lambda v: money(v, m)),
        "Premiums are estimates from a pricing model; the option chain's real prices "
        "(and their implied volatility) will differ. Agora doesn't trade options.",
    ]
    card: dict[str, Any] = {
        "type": "options",
        "title": f"{info.name} · {inst.symbol}",
        "market": m,
        "spot": spot,
        "days": days,
        "vol": round(vol, 4),
        "legs": [
            {
                "label": leg.label(),
                "premium": None if leg.premium is None else round(leg.premium, 2),
            }
            for leg in an.legs
        ],
        "net": round(an.net_premium * size, 2),
        "max_profit": None if an.max_profit is None else round(an.max_profit * size, 2),
        "max_loss": None if an.max_loss is None else round(an.max_loss * size, 2),
        "breakevens": an.breakevens,
        "pop": an.pop,
        "grid": an.grid,
        "at_expiry": [round(v * size, 2) for v in an.at_expiry],
        "today": [round(v * size, 2) for v in an.today],
        "lot": lot,
    }
    return Result(
        True,
        "\n".join(lines),
        f"Worked out a {info.name.lower()}",
        f"{inst.symbol} · {an.pop * 100:.0f}% chance of profit",
        card,
    )


TOOLS = [
    Tool(
        "option_strategy",
        "The numbers for an option or futures strategy on a stock or index: legs with estimated "
        "premiums, cost or credit, maximum profit and loss, break-evens, chance of profit and "
        "Greeks. Agora doesn't trade options; this is for learning and planning.",
        OptionArgs,
        option_strategy,
        lambda a: f"Working out the {a.strategy}…",
        group="options",
    )
]
