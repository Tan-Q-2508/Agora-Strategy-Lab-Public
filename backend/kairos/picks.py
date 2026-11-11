"""Kairos picks its own stocks (SPEC §18, D-99): no watchlist needed from the user.

**Which stocks (D-177).** Every desk trades the market's ``N_PICKS`` (250) most traded stocks: the
user asked (2026-11-05) for the top 250 by volume, because a desk on 10–30 stocks "that no one is
trading" is no use. "Most traded" is money traded a day (price × shares, the median of the last
``TRADED_DAYS`` days): share counts favour cheap stocks, and one day's count lets a single block
deal swap a stock in and out. The thin-stock floor (``MIN_TRADED``) still applies.

**In what order.** The 250 are ordered (not chosen) by Kairos's strength score, so when more of
them signal at once than the desk has room for, the strongest get the slots first. From every
stock of the market Agora has fresh daily prices for (not only an index, D-133) it scores, in this
order of weight:

- **relative strength**: the 3-month return beyond the index (z-scored across the pool);
- **momentum**: the 12-month return leaving out the latest month;
- **closeness to the 52-week high**;
- **an uptrend** (price above a rising 50-day average above a rising 200-day average): a bonus;
- **its sector**: booming or strong sectors lift it, weak or slumping ones hold it back (money
  tends to keep flowing where it has been flowing);
- **the world**: what today's world events mean for it beyond the market (``backend/world``).

No sector cap on the list (the desk holds at most ``brain.MAX_PER_SECTOR`` open trades per
sector, D-168, which is where concentration matters). The result is saved as the watchlist
"Kairos · Picks …" with a note for every stock and the reason; the autopilot's desks trade it.
Code, not the AI, makes the picks.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.watchlists import factors, seed

N_PICKS = 250
TRADED_DAYS = 20
# How many stocks each desk follows (D-177): a desk polls each of its stocks every candle and
# Yahoo answers about one request a second, so 250 stocks take about four minutes a candle; the
# 5- and 1-minute desks were retired, which is what makes 250 possible on the 15-minute one, and
# India and the US never trade at the same time.
DESK_SIZE = {"1d": N_PICKS, "1h": N_PICKS, "15m": N_PICKS}
SECTOR_BONUS = {"boom": 1.0, "strong": 0.6, "neutral": 0.0, "weak": -0.6, "slump": -1.0}
# Traded value a day below which a stock is too thin to trade, on the median of both the last
# 20 and the last 120 days, so a burst of trading can't lift a thin stock in (D-155: KABRAEXTRU,
# ₹1 crore a day over the year, passed ₹5 crore on 20 days and sat on the India daily desk).
# The sprint's evidence: rules survive costs only in the most traded stocks (D-143).
MIN_TRADED = {"IN": 2e8, "US": 2e7}  # ₹20 crore, $20 million
STEADY_DAYS = (20, 120)
FRESH_MS = 10 * 86_400_000  # the last saved daily candle at most this old
BEHIND_MS = 4 * 86_400_000  # … and at most this far behind the market's newest (D-182)
NAME = {"IN": "Picks India", "US": "Picks US"}


def _z(values: dict[int, float]) -> dict[int, float]:
    if len(values) < 2:
        return {k: 0.0 for k in values}
    arr = np.array(list(values.values()))
    sd = float(np.std(arr)) or 1.0
    mu = float(np.mean(arr))
    return {k: float(np.clip((v - mu) / sd, -3, 3)) for k, v in values.items()}


def rank(ctx: Any, market: str, n: int = N_PICKS) -> list[dict[str, Any]]:
    """The best ``n`` stocks for Kairos's desk, each with its score and reasons."""
    from backend.core.types import Market
    from backend.data import store
    from backend.db.models import Instrument, InstrumentProfile

    lists = ctx.watchlists
    lists.ensure()
    with ctx.db.session() as s:
        ids = seed.members(s, market, {})  # every stock with a profile: the whole market
    traded: dict[int, float] = {}
    closes = pool(ctx, market, ids, traded)
    if not closes:
        return []
    # the n most traded (D-177); the score below only orders them
    keep = set(sorted(closes, key=lambda i: -traded.get(i, 0.0))[:n])
    closes = {i: c for i, c in closes.items() if i in keep}

    with ctx.db.session() as s:
        bench_ref = store.find_instrument(s, Market(market), "NIFTY50" if market == "IN" else "SPY")
        info = {
            iid: (sym, prof.sector, [t for t in prof.tags.split(";") if t])
            for iid, sym, prof in s.execute(
                ctx_select_profiles(Instrument, InstrumentProfile, list(closes))
            ).all()
        }
    bench = lists.closes([bench_ref.id]).get(bench_ref.id) if bench_ref else None
    rs, mom, near, trend = {}, {}, {}, {}
    for iid, c in closes.items():
        if (got := factors.score("relative_strength", c, bench)) is not None:
            rs[iid] = got[0]
        if (got := factors.score("momentum", c)) is not None:
            mom[iid] = got[0]
        if (got := factors.score("near_high", c)) is not None:
            near[iid] = got[0]
        trend[iid] = factors.score("trend", c) is not None
    zr, zm, zn = _z(rs), _z(mom), _z(near)
    sectors = {r["name"]: r for r in ctx.sectors.overview(market)["sectors"]}
    world = ctx.world.view(market)
    wv = {x["instrument_id"]: x for x in [*world["helped"], *world["hurt"]]}
    rows: list[dict[str, Any]] = []
    for iid in closes:
        if iid not in info:
            continue
        sym, sector, _tags = info[iid]
        sec = sectors.get(sector)
        state = sec["state"] if sec else "neutral"
        w = wv.get(iid)
        score = (
            0.35 * zr.get(iid, 0.0)
            + 0.25 * zm.get(iid, 0.0)
            + 0.2 * zn.get(iid, 0.0)
            + (0.3 if trend.get(iid) else 0.0)
            + 0.4 * SECTOR_BONUS.get(state, 0.0)
            + (0.3 * float(w["vs_market"]) if w else 0.0)
        )
        why: list[str] = []
        if iid in rs:
            why.append(f"{rs[iid] * 100:+.0f}% vs the index over 3 months")
        if trend.get(iid):
            why.append("in an uptrend")
        if iid in near and near[iid] >= 0.95:
            why.append("near its 52-week high")
        if sec and state != "neutral":
            why.append(f"{sector} is {state}")
        if w and w["why"]:
            why.append("world events: " + w["why"][-1])
        rows.append(
            {
                "instrument_id": iid,
                "symbol": sym,
                "sector": sector,
                "score": round(score, 3),
                "traded": traded.get(iid, 0.0),
                "why": why,
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["symbol"]))
    return rows[:n]


def pool(
    ctx: Any, market: str, ids: list[int], traded: dict[int, float] | None = None
) -> dict[int, np.ndarray]:
    """Closes of the stocks worth ranking: 130+ days of saved prices, the latest fresh, and traded
    enough each day (saved prices only, no downloading). ``traded`` receives each one's money
    traded a day (the median of the last ``TRADED_DAYS``)."""
    from backend.core.types import Timeframe
    from backend.data import store

    now = ctx.clock.now_ms()
    with ctx.db.session() as s:
        refs = [r for i in ids if (r := store.get_instrument(s, i)) is not None]
    out: dict[int, np.ndarray] = {}
    found: list[tuple[Any, list[Any]]] = []
    for ref in refs:
        bars = ctx.cache.bars(
            ref, Timeframe.D1, now - 420 * 86_400_000, now + 1, adjusted_prices=True
        )
        if len(bars) < 130 or now - bars[-1].ts > FRESH_MS:
            continue
        found.append((ref, bars))
    # current with the market (D-182): a stock whose prices stopped days before the others is
    # ranked on old prices, so it is left out
    newest = max((b[-1].ts for _, b in found), default=0)
    for ref, bars in found:
        if newest - bars[-1].ts > BEHIND_MS:
            continue
        value = [b.close * b.volume for b in bars]
        steady = min(float(np.median(value[-n:])) for n in STEADY_DAYS)
        if steady < MIN_TRADED[market]:
            continue
        out[ref.id] = np.array([b.close for b in bars], dtype=np.float64)
        if traded is not None:
            traded[ref.id] = float(np.median(value[-TRADED_DAYS:]))
    return out


def ctx_select_profiles(instrument: Any, profile: Any, ids: list[int]) -> Any:
    from sqlalchemy import select

    return (
        select(instrument.id, instrument.symbol, profile)
        .join(profile, profile.instrument_id == instrument.id)
        .where(instrument.id.in_(ids))
    )


def save(ctx: Any, market: str, picks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Save the picks as Kairos's list (updated in place each time)."""
    if not picks:
        return None
    reason = (
        "Kairos's own stocks for its desks: the 250 most traded "
        + ("Indian" if market == "IN" else "US")
        + " stocks (money traded a day, the median of the last 20 days), strongest first by "
        "relative strength, momentum and closeness to their highs, favouring leading sectors and "
        "the stocks today's world events help."
    )
    notes = {p["symbol"]: "; ".join(p["why"]) for p in picks}
    saved: dict[str, Any] | None = ctx.watchlists.save_for_agent(
        "kairos", market, NAME[market], [p["symbol"] for p in picks], reason, notes
    )
    return saved
