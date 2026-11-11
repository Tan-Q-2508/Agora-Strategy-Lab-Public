"""The headless research runner (D-143, Phase 25.3).

A sprint has four steps, each a command (``python -m backend.lab``):

1. ``run``: every family's variants, on each market and timeframe, over many stocks, on the
   history **before the vault**, split 70/30 into study and exam years. Every test goes into
   the ledger, with its numbers by regime.
2. ``pick``: the finalists, chosen by fixed rules in code (below), at most one per family,
   market and timeframe. Nobody hand-picks: a person (or Claude) choosing from hundreds of
   results is the overfitting the vault exists to catch.
3. ``vault``: the finalists run **once** on the vault. A finalist that loses money there is
   marked ``failed_vault``; the rest are ``promoted``. The vault can't be opened twice.
4. ``promote``: the promoted tests become playbook entries (``playbook.py``).

Only saved candles are used (no downloads), so a sprint never touches Yahoo's limits.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from backend.backtest.manager import BacktestRequest
from backend.backtest.run import NoData, run, warmup_ms
from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.data import store
from backend.indicators.series import BarSeries, from_bars
from backend.lab import families as fam_mod
from backend.lab import ledger, measure, vault
from backend.logging_setup import get_logger
from backend.quant import stats
from backend.strategy.definition import content_hash
from backend.strategy.validator import validate

log = get_logger("lab")
STUDY_SHARE = 0.7
MAX_STOCKS = {"1d": 30, "1h": 15, "15m": 10, "5m": 10, "1m": 10}
MIN_STOCKS = 3
MIN_HISTORY = {"1d": 750, "1h": 200, "15m": 20, "5m": 20, "1m": 5}  # trading days
REGIME_WARM_BARS = 470  # the regime map's 200-candle average + 250-candle volatility window

# The finalist rules: fixed before any result is seen (D-143). The exam must also match the
# Sharpe ratio of the index and of simply holding the strategy's own stocks: in a rising market
# any buy-only rule makes money, so making money alone proves nothing (the practice data, which
# only drifts upwards, showed it: 25 of 55 groups passed without these bars).
MIN_TRADES = {"study": 30, "exam": 12}
MIN_PROFIT_FACTOR = 1.1
MIN_BREADTH = 0.5  # share of traded stocks that made money in the study years
MIN_DSR = 0.5
MIN_VAULT_TRADES = 5

Say = Callable[[str], None]


@dataclass
class Window:
    start_ms: int
    split_ms: int
    vault_ms: int
    end_ms: int


# ---------------------------------------------------------------- stocks and periods


def universe(ctx: Any, market: str, timeframe: str, limit: int | None = None) -> list[str]:
    """The market's most traded stocks that have enough saved history on this timeframe.

    Most traded first (median daily value traded over the last year): published Indian
    evidence finds trading rules survive costs only in the most liquid stocks, the top 75–200
    (the user's Gemini research, 2026-11-03), and costs in thin stocks are higher than any
    model assumes."""
    n = limit or MAX_STOCKS.get(timeframe, 10)
    tf = Timeframe(timeframe)
    with ctx.db.session() as s:
        # every stock with saved prices, not only the starter list (D-133)
        insts = [i for i in data_service.saved_symbols(s, Market(market), tf) if not i.is_index]
        cov = store.coverage_stats(s, tf, [i.id for i in insts])
    need = MIN_HISTORY.get(timeframe, 20)
    ok = [i for i in insts if cov.get(i.id, (0, 0, 0, ""))[2] >= need]
    ranked = sorted(ok, key=lambda i: (-traded_value(ctx, i), i.symbol))
    return [i.symbol for i in ranked[:n]]


def traded_value(ctx: Any, inst: Any) -> float:
    """Median daily close × volume over the last 250 saved daily candles."""
    now = ctx.clock.now_ms()
    bars = ctx.cache.bars(inst, Timeframe.D1, now - 400 * 86_400_000, now)[-250:]
    vals = [b.close * b.volume for b in bars if b.volume]
    return float(np.median(vals)) if vals else 0.0


def window(ctx: Any, timeframe: str, symbols: Sequence[str], market: str) -> Window | None:
    """Research covers the saved history before the vault; the vault is the rest."""
    now = ctx.clock.now_ms()
    v = vault.start(timeframe, now)
    tf = Timeframe(timeframe)
    firsts = []
    with ctx.db.session() as s:
        for sym in symbols:
            inst = store.find_instrument(s, Market(market), sym)
            if inst is None:
                continue
            row = store.coverage_stats(s, tf, [inst.id]).get(inst.id)
            if row and row[0]:
                firsts.append(int(row[0]))
    if not firsts:
        return None
    # start once most stocks have history and the indicators have warmed up
    first = int(np.median(firsts)) + (365 * 86_400_000 if timeframe == "1d" else 0)
    if first >= v:
        return None
    split = first + int((v - first) * STUDY_SHARE)
    return Window(first, split, v, now)


# ---------------------------------------------------------------- one test


def _series(
    ctx: Any, symbols: Sequence[str], tf: Timeframe, market: Market, lo: int, hi: int
) -> dict[str, BarSeries]:
    """Each stock's candles (adjusted), with enough before ``lo`` for the regime map."""
    warm = warmup_ms(tf, REGIME_WARM_BARS)
    series = {}
    with ctx.db.session() as s:
        insts = {sym: store.find_instrument(s, market, sym) for sym in symbols}
    for sym, inst in insts.items():
        if inst is None:
            continue
        bars = ctx.cache.bars(inst, tf, lo - warm, hi, adjusted_prices=True)
        if bars:
            series[sym] = from_bars(bars, tf, market)
    return series


def run_one(
    ctx: Any,
    sprint: str,
    family: fam_mod.Family,
    market: str,
    timeframe: str,
    symbols: Sequence[str],
    variant: dict[str, float],
    w: Window,
) -> int | None:
    """Test one variant before the vault and record it. None when it couldn't run."""
    raw = family.definition(market, timeframe, symbols)
    res = validate(raw)
    if not res.ok or res.definition is None:
        log.warning("Lab: %s on %s isn't valid: %s", family.key, market, res.errors[0].sentence())
        return None
    d = res.definition
    h = content_hash(d)
    if ledger.seen(ctx, sprint, family.key, market, timeframe, variant):
        return None
    spec, _x = ctx.backtests.spec_for(
        d,
        BacktestRequest(
            strategy_version_id=0, symbols=list(symbols), start=w.start_ms, end=w.vault_ms
        ),
    )
    spec = replace(spec, overrides=dict(variant))
    try:
        out = run(ctx.cache, spec)
    except NoData:
        return None
    m = Market(market)
    tf = Timeframe(timeframe)
    study = {
        **measure.part(out.trades, w.start_ms, w.split_ms),
        **_no_returns(measure.curve(out.equity, m, w.start_ms, w.split_ms)),
    }
    series = _series(ctx, symbols, tf, m, w.start_ms, w.vault_ms)
    exam = {
        **measure.part(out.trades, w.split_ms, w.vault_ms),
        **measure.curve(out.equity, m, w.split_ms, w.vault_ms),
        "index_sharpe": measure.index_sharpe(out.benchmark, m, w.split_ms, w.vault_ms),
        "hold_sharpe": measure.basket_sharpe(series, m, w.split_ms, w.vault_ms),
    }
    tags = measure.regime_of_entries(out.trades, series)
    regimes = measure.by_regime(out.trades, tags, w.start_ms, w.vault_ms)
    return ledger.add(
        ctx,
        sprint=sprint,
        family=family.key,
        variant=variant,
        market_code=market,
        timeframe=timeframe,
        def_hash=h,
        definition=json.loads(d.model_dump_json()),
        symbols=list(symbols),
        start_ms=w.start_ms,
        split_ms=w.split_ms,
        vault_ms=w.vault_ms,
        end_ms=w.end_ms,
        study=study,
        exam=exam,
        regimes=regimes,
        status="tested",
    )


def _no_returns(c: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in c.items() if k != "returns"}


def run_sprint(
    ctx: Any,
    sprint: str,
    *,
    family_keys: Sequence[str] | None = None,
    markets: Sequence[str] = ("IN", "US"),
    timeframes: Sequence[str] | None = None,
    stocks: int | None = None,
    say: Say = lambda _m: None,
) -> dict[str, Any]:
    """Step 1: test every variant of the chosen families."""
    fams = fam_mod.pick(family_keys)
    done = skipped = 0
    for f in fams:
        for market in f.markets:
            if market not in markets:
                continue
            for tf in f.timeframes:
                if timeframes and tf not in timeframes:
                    continue
                syms = universe(ctx, market, tf, stocks)
                if len(syms) < MIN_STOCKS:
                    say(f"{f.key} {market} {tf}: not enough stocks with saved history; skipped.")
                    skipped += 1
                    continue
                w = window(ctx, tf, syms, market)
                if w is None:
                    say(f"{f.key} {market} {tf}: not enough history before the vault; skipped.")
                    skipped += 1
                    continue
                variants = f.variants() or [{}]
                for v in variants:
                    if run_one(ctx, sprint, f, market, tf, syms, v, w) is not None:
                        done += 1
                say(f"{f.key} {market} {tf}: {len(variants)} variants on {len(syms)} stocks.")
    return {"tested": done, "skipped": skipped, "total_in_sprint": ledger.tries(ctx, sprint)}


# ---------------------------------------------------------------- step 2: finalists


def checks(r: dict[str, Any], tries_in_family: int) -> list[tuple[str, bool]]:
    """The fixed finalist rules, as (plain sentence, passed)."""
    st, ex = r["study"], r["exam"]
    out: list[tuple[str, bool]] = []
    for name, part_ in (("study", st), ("exam", ex)):
        trades = part_.get("trades") or 0
        out.append(
            (f"{name}: at least {MIN_TRADES[name]} trades ({trades})", trades >= MIN_TRADES[name])
        )
        net = part_.get("net") or 0.0
        out.append((f"{name}: made money after costs ({net:,.0f})", net > 0))
        pf = part_.get("profit_factor")
        out.append(
            (
                f"{name}: won at least {MIN_PROFIT_FACTOR}× what it lost ({_n(pf, '.2f')})",
                pf is not None and pf >= MIN_PROFIT_FACTOR,
            )
        )
    sr = ex.get("sharpe")
    for name, bar in (
        ("the index", ex.get("index_sharpe")),
        ("holding its stocks", ex.get("hold_sharpe")),
    ):
        out.append(
            (
                f"exam: a Sharpe ratio at least {name}'s ({_n(sr, '.2f')} vs {_n(bar, '.2f')})",
                sr is not None and (bar is None or sr >= bar),
            )
        )
    stocks = st.get("stocks") or 0
    breadth = (st.get("stocks_up") or 0) / stocks if stocks else 0.0
    out.append(
        (f"study: worked on at least half its stocks ({breadth:.0%})", breadth >= MIN_BREADTH)
    )
    rets = ex.get("returns") or []
    p = luck(rets, tries_in_family)
    out.append(
        (
            f"exam: more likely real than luck over {tries_in_family} tries ({_n(p, '.0%')})",
            p is not None and p >= MIN_DSR,
        )
    )
    return out


def _n(x: float | None, fmt: str) -> str:
    return "–" if x is None else format(x, fmt)


def luck(returns: Sequence[float], tries: int) -> float | None:
    """The deflated Sharpe ratio (D-82): the chance the exam's Sharpe beats the best of
    ``tries`` lucky ones."""
    x = np.asarray(returns, dtype=float)
    if len(x) < 30 or float(np.std(x)) == 0:
        return None
    p = stats.dsr(x, max(1, tries))
    return None if not math.isfinite(p) else float(p)


def neighbours_hold(
    r: dict[str, Any], family: fam_mod.Family, same: Sequence[dict[str, Any]]
) -> bool:
    """A real edge has neighbours: most variants one grid step away also made money in the
    study years. A lone winner among losers is an isolated peak (D-89)."""
    if not family.grid:
        return True
    grid = {k: sorted(v) for k, v in family.grid.items()}
    mine = r["variant"]
    near = []
    for o in same:
        if o["id"] == r["id"]:
            continue
        diff = [k for k in grid if o["variant"].get(k) != mine.get(k)]
        if len(diff) != 1:
            continue
        k = diff[0]
        a, b = grid[k].index(mine[k]), grid[k].index(o["variant"][k])
        if abs(a - b) == 1:
            near.append(o)
    if not near:
        return True
    return sum(1 for o in near if (o["study"].get("net") or 0) > 0) * 2 >= len(near)


def _same_trades(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = ("trades", "net", "win_rate")
    return (a["market"], a["timeframe"]) == (b["market"], b["timeframe"]) and all(
        a[p].get(k) == b[p].get(k) for p in ("study", "exam") for k in keys
    )


def pick_finalists(ctx: Any, sprint: str) -> list[dict[str, Any]]:
    """Step 2: the best passing variant per family, market and timeframe (best study Sharpe;
    exam numbers only gate, they never rank)."""
    all_rows = ledger.rows(ctx, sprint)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        groups[(r["family"], r["market"], r["timeframe"])].append(r)
    chosen: list[dict[str, Any]] = []
    for (fkey, _m, _tf), rs in groups.items():
        family = fam_mod.BY_KEY.get(fkey)
        if family is None:
            continue
        tries = len(rs)
        passing = []
        for r in rs:
            if r["status"] != "tested":
                continue
            found = checks(r, tries)
            ok = all(p for _s, p in found) and neighbours_hold(r, family, rs)
            if ok:
                passing.append(r)
        if not passing:
            continue
        best = max(passing, key=lambda r: r["study"].get("sharpe") or -9.0)
        twin = next((c for c in chosen if _same_trades(c, best)), None)
        if twin is not None:
            # two families can be one rule in disguise (a close under the lower Bollinger band
            # is a z-score under −width): keep the first
            ledger.update(ctx, best["id"], note=f"Trades exactly like #{twin['id']}.")
            continue
        ledger.update(ctx, best["id"], status="finalist", note="Passed every finalist rule.")
        best["status"] = "finalist"
        chosen.append(best)
    return chosen


# ---------------------------------------------------------------- step 3: the vault


def open_vault(ctx: Any, sprint: str, say: Say = lambda _m: None) -> list[dict[str, Any]]:
    """Run each finalist once on the vault and mark it promoted or failed_vault."""
    out = []
    for r in ledger.rows(ctx, sprint, status=["finalist"]):
        if r["vault_opened_at"] is not None:
            continue  # never twice
        res = validate(r["definition"])
        if not res.ok or res.definition is None:
            continue
        d = res.definition
        spec, _x = ctx.backtests.spec_for(
            d,
            BacktestRequest(
                strategy_version_id=0, symbols=r["symbols"], start=r["vault_ms"], end=r["end_ms"]
            ),
        )
        spec = replace(spec, overrides=dict(r["variant"]))
        try:
            run_out = run(ctx.cache, spec)
        except NoData:
            continue
        m = Market(r["market"])
        v = {
            **measure.part(run_out.trades, r["vault_ms"], r["end_ms"]),
            **_no_returns(measure.curve(run_out.equity, m, r["vault_ms"], r["end_ms"])),
        }
        held = (v.get("trades") or 0) >= MIN_VAULT_TRADES and (v.get("net") or 0) > 0
        status = "promoted" if held else "failed_vault"
        note = f"Vault: {v.get('trades', 0)} trades, {v.get('net', 0):,.0f} after costs." + (
            "" if held else " Didn't hold up on history it was never chosen on."
        )
        ledger.update(
            ctx, r["id"], vault=v, vault_opened_at=ctx.clock.now_ms(), status=status, note=note
        )
        say(f"{r['family']} {r['market']} {r['timeframe']}: {status}. {note}")
        out.append({**r, "vault": v, "status": status, "note": note})
    return out


# ---------------------------------------------------------------- the report


def report(ctx: Any, sprint: str, top: int = 5) -> str:
    """A compact summary to read (study and exam only; the vault once opened)."""
    rows = ledger.rows(ctx, sprint)
    if not rows:
        return f"Sprint {sprint}: nothing tested yet."
    lines = [f"# Sprint {sprint}: {len(rows)} tests", ""]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["family"], r["market"], r["timeframe"])].append(r)
    for (f, m, tf), rs in sorted(groups.items()):
        rs.sort(key=lambda r: -(r["study"].get("sharpe") or -9.0))
        lines.append(f"## {f} · {m} · {tf} ({len(rs)} variants)")
        for r in rs[:top]:
            st, ex = r["study"], r["exam"]
            vtxt = ""
            if r["vault"]:
                vv = r["vault"]
                vtxt = f" | vault {vv.get('trades', 0)}t {vv.get('net', 0):,.0f}"
            lines.append(
                f"- #{r['id']} {json.dumps(r['variant'])} [{r['status']}] "
                f"study {st.get('trades', 0)}t SR {st.get('sharpe')} PF {st.get('profit_factor')} "
                f"WR {st.get('win_rate')} | exam {ex.get('trades', 0)}t SR {ex.get('sharpe')} "
                f"PF {ex.get('profit_factor')}{vtxt}"
            )
        best = rs[0]
        good = [
            f"{k} {v['avg_return_pct']:+.2f}%/{v['trades']}t"
            for k, v in best["regimes"].items()
            if v["trades"] >= 10
        ]
        if good:
            lines.append("  regimes (best variant): " + ", ".join(good))
        lines.append("")
    return "\n".join(lines)
