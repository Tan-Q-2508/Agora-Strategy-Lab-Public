"""Strategy research: "find the best strategy for these stocks" (KAIROS §7.3).

An honest search, in five steps:

1. **Character.** For each stock: how trendy it is (efficiency ratio, ADX), whether moves
   tend to continue or reverse (variance ratio of 10-candle returns), and how wild it is
   (ATR as % of price). This decides which candidates are tried first.
2. **Candidates.** Every starter strategy that fits the timeframe, plus the Kairos brain.
   In research the brain counts every signal the same (no learned weights), because the
   weights were measured on these same years and would flatter its out-of-sample result.
3. **In-sample tuning** on the first 70% of the period: a small grid around each
   strategy's main settings. The chosen setting is the one whose *neighbourhood* does best
   (a lone peak surrounded by losers is luck, D-41).
4. **Out-of-sample check** on the last 30%, which tuning never saw: anything that loses
   money there, or keeps less than 30% of its in-sample Sharpe, is dropped.
5. **Walk-forward** on the best survivors (re-tune on the past, test on the next slice,
   repeat); ranked by out-of-sample Sharpe with a penalty for having few trades. The
   winner is saved as a strategy with its tuned settings and backtested in full.

When nothing survives, the answer says so: that is a result too.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from typing import Any

import numpy as np
from sqlalchemy import select

from backend.backtest.run import NoData, RunSpec, run
from backend.core.types import Market, Timeframe
from backend.data import service as data_service
from backend.data.store import InstrumentRef
from backend.db.models import BrokerageProfile, SlippageProfile
from backend.indicators import vector as vx
from backend.indicators.series import BarSeries, from_bars
from backend.kairos import brain
from backend.settings_store import read_all
from backend.strategy import revisions, templates
from backend.strategy.definition import AnyDefinition, ParameterDef

DAY_MS = 86_400_000
IN_SAMPLE = 0.7
MIN_TRADES = 5
KEEP_RATIO = 0.3  # out-of-sample Sharpe must keep this share of the in-sample one
TREND_KEYS = (
    "ma_crossover",
    "donchian_breakout",
    "supertrend",
    "macd_momentum",
    "high_52w_momentum",
)
REVERSION_KEYS = ("rsi_mean_reversion", "bollinger_reversion")

Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class Config:
    """How thorough the search is (tests use a quick one)."""

    max_candidates: int = 8
    grid_params: int = 2  # how many settings are tuned
    grid_steps: int = 1  # values each side of the default
    finalists: int = 3
    folds: int = 3


QUICK = Config(max_candidates=3, grid_params=1, grid_steps=1, finalists=2, folds=2)


# ---------------------------------------------------------------- 1. character


@dataclass(frozen=True)
class Character:
    symbol: str
    efficiency: float  # 0 (choppy) … 1 (straight line), 20-candle average
    variance_ratio: float  # > 1 moves continue, < 1 they reverse
    adx: float
    atr_pct: float
    label: str  # "trending" | "mean-reverting" | "mixed"

    def public(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "efficiency": round(self.efficiency, 3),
            "variance_ratio": round(self.variance_ratio, 3),
            "adx": round(self.adx, 1),
            "atr_pct": round(self.atr_pct, 2),
            "label": self.label,
        }


def character(symbol: str, s: BarSeries) -> Character:
    c = s.close
    n = 20
    moves = np.abs(np.diff(c))
    if len(c) <= 2 * n:
        return Character(symbol, 0.0, 1.0, 0.0, 0.0, "mixed")
    path = np.convolve(moves, np.ones(n), "valid")
    net = np.abs(c[n:] - c[:-n])
    with np.errstate(invalid="ignore", divide="ignore"):
        er = float(np.nanmean(np.where(path > 0, net / path, np.nan)))
    r1 = np.diff(np.log(c))
    k = 10
    rk = np.log(c[k:] / c[:-k])
    v1 = float(np.var(r1))
    vr = float(np.var(rk) / (k * v1)) if v1 > 0 else 1.0
    adx = vx.adx(s.high, s.low, c, 14)[0]
    adx_mean = float(np.nanmean(adx)) if np.isfinite(adx).any() else 0.0
    atr = vx.atr(s.high, s.low, c, 14)
    atr_pct = float(np.nanmedian(100.0 * atr / c)) if np.isfinite(atr).any() else 0.0
    if vr >= 1.05 and (er >= 0.3 or adx_mean >= 25):
        label = "trending"
    elif vr <= 0.95:
        label = "mean-reverting"
    else:
        label = "mixed"
    return Character(symbol, er, vr, adx_mean, atr_pct, label)


# ---------------------------------------------------------------- 2. candidates


@dataclass
class Candidate:
    key: str  # template key or "kairos"
    name: str
    definition: AnyDefinition
    grid: list[dict[str, float]]
    is_sharpe: float | None = None
    is_trades: int = 0
    params: dict[str, float] = field(default_factory=dict)
    isolated: bool = False
    oos: dict[str, Any] | None = None
    wf_sharpe: float | None = None
    wf_folds: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = "not tested"
    score: float = -math.inf

    def public(self) -> dict[str, Any]:
        o = self.oos or {}
        return {
            "key": self.key,
            "name": self.name,
            "params": self.params,
            "in_sample_sharpe": _r(self.is_sharpe),
            "in_sample_trades": self.is_trades,
            "out_of_sample_sharpe": _r(o.get("sharpe")),
            "out_of_sample_return": _r(o.get("total_return"), 4),
            "out_of_sample_trades": o.get("trades"),
            "walk_forward_sharpe": _r(self.wf_sharpe),
            "isolated_peak": self.isolated,
            "verdict": self.verdict,
        }


def _r(x: Any, d: int = 2) -> float | None:
    return round(float(x), d) if isinstance(x, int | float) and math.isfinite(x) else None


def grid_for(defn: AnyDefinition, cfg: Config) -> list[dict[str, float]]:
    """A small grid around the defaults of the first ``grid_params`` settings."""
    axes: list[list[tuple[str, float]]] = []
    for p in defn.parameters[: cfg.grid_params]:
        axes.append([(p.name, v) for v in _values(p, cfg.grid_steps)])
    if not axes:
        return [{}]
    return [dict(combo) for combo in product(*axes)]


def _values(p: ParameterDef, steps: int) -> list[float]:
    step = p.step or (p.max - p.min) / 6.0
    if p.type == "int":
        step = max(1.0, round(step))
    out = []
    for k in range(-steps, steps + 1):
        v = min(p.max, max(p.min, p.default + k * step))
        v = float(round(v)) if p.type == "int" else round(v, 4)
        if v not in out:
            out.append(v)
    return out


def candidates(
    market: Market, tf: Timeframe, symbols: list[str], chars: list[Character], cfg: Config
) -> list[Candidate]:
    trending = sum(1 for c in chars if c.label == "trending")
    reverting = sum(1 for c in chars if c.label == "mean-reverting")
    first = REVERSION_KEYS if reverting > trending else TREND_KEYS
    keys = [
        k for k, t in templates.TEMPLATES.items() if (t.timeframe == "1d") == (tf is Timeframe.D1)
    ]
    keys.sort(key=lambda k: (k not in first, k))
    out: list[Candidate] = []
    kairos = brain.definition(market.value, symbols, timeframe=tf.value)
    out.append(Candidate("kairos", "Kairos brain", kairos, grid_for(kairos, cfg)))
    for k in keys:
        d = templates.template_definition(k, market.value, symbols)
        if d.timeframe != tf.value:
            d = d.model_copy(update={"timeframe": tf.value})
        out.append(Candidate(k, templates.TEMPLATES[k].name, d, grid_for(d, cfg)))
    # Kairos always competes; the rest in order of how well they fit the stocks' character.
    return [out[0], *out[1 : cfg.max_candidates]]


# ---------------------------------------------------------------- running


class Runner:
    """Backtests in memory (nothing saved) with the user's default costs and money."""

    def __init__(self, ctx: Any, market: Market, insts: list[InstrumentRef], tf: Timeframe) -> None:
        self.ctx = ctx
        self.market = market
        self.insts = insts
        self.tf = tf
        with ctx.db.session() as s:
            settings = read_all(s)
            profile = s.scalar(
                select(BrokerageProfile).where(
                    BrokerageProfile.market_code == market.value, BrokerageProfile.is_default == 1
                )
            )
            assert profile is not None
            self.rules = json.loads(profile.rules)
            self.slip = float(
                s.scalar(
                    select(SlippageProfile.bps).where(
                        SlippageProfile.market_code == market.value,
                        SlippageProfile.is_default == 1,
                    )
                )
                or 0.0
            )
        self.capital = float(settings[f"default_capital.{market.value}"])
        self.runs = 0

    def __call__(
        self, d: AnyDefinition, params: dict[str, float], lo: int, hi: int
    ) -> dict[str, Any] | None:
        self.runs += 1
        spec = RunSpec(
            definition=d,
            instruments=self.insts,
            timeframe=self.tf,
            start_ms=lo,
            end_ms=hi,
            capital=self.capital,
            brokerage_rules=self.rules,
            slippage_bps=self.slip,
            overrides=params,
        )
        try:
            m: dict[str, Any] = run(self.ctx.cache, spec).metrics
        except NoData:
            return None
        return m


def _sharpe(m: dict[str, Any] | None) -> float:
    if not m or (m.get("trades") or 0) < MIN_TRADES:
        return -math.inf
    s = m.get("sharpe")
    return float(s) if isinstance(s, int | float) and math.isfinite(s) else -math.inf


def tune(
    cand: Candidate, runner: Runner, lo: int, hi: int
) -> tuple[dict[str, float], float, int, bool]:
    """Best setting by neighbourhood: each combo's score is the mean of itself and the combos
    one step away; returns (params, its own Sharpe, its trades, was the raw best isolated)."""
    results = [(g, runner(cand.definition, g, lo, hi)) for g in cand.grid]
    sharpe = [_sharpe(m) for _, m in results]
    names = list(cand.grid[0]) if cand.grid and cand.grid[0] else []
    values = {n: sorted({g[n] for g in cand.grid}) for n in names}

    def neighbours(i: int) -> list[int]:
        g = cand.grid[i]
        out = []
        for j, h in enumerate(cand.grid):
            diff = [n for n in names if h[n] != g[n]]
            if len(diff) == 1:
                n = diff[0]
                if abs(values[n].index(h[n]) - values[n].index(g[n])) == 1:
                    out.append(j)
        return out

    def robust(i: int) -> float:
        pts = [sharpe[i], *(sharpe[j] for j in neighbours(i))]
        finite = [p for p in pts if math.isfinite(p)]
        if not math.isfinite(sharpe[i]) or not finite:
            return -math.inf
        return float(np.mean([p if math.isfinite(p) else min(finite) - 1.0 for p in pts]))

    best_raw = int(np.argmax(sharpe))
    best = max(range(len(cand.grid)), key=robust)
    nb = [sharpe[j] for j in neighbours(best_raw) if math.isfinite(sharpe[j])]
    isolated = (
        math.isfinite(sharpe[best_raw])
        and sharpe[best_raw] > 0
        and bool(neighbours(best_raw))
        and (not nb or float(np.mean(nb)) < 0.5 * sharpe[best_raw])
    )
    m = results[best][1] or {}
    return cand.grid[best], sharpe[best], int(m.get("trades") or 0), isolated


# ---------------------------------------------------------------- the search


def research(
    ctx: Any,
    insts: list[InstrumentRef],
    tf: Timeframe = Timeframe.D1,
    years: float | None = None,
    *,
    cfg: Config | None = None,
    progress: Progress | None = None,
    check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    cfg = cfg or Config()
    say = progress or (lambda _p, _m: None)
    market = insts[0].market
    now = ctx.clock.now_ms()
    yrs = years or (5.0 if tf is Timeframe.D1 else 0.25)
    start = now - int(yrs * 365.25 * DAY_MS)
    if tf is not Timeframe.D1:
        start = max(start, data_service.default_start_ms(tf, now))
    split = start + int(IN_SAMPLE * (now - start))
    symbols = [i.symbol for i in insts]

    say(2, "Reading each stock's character…")
    chars = []
    for inst in insts:
        bars = ctx.cache.bars(inst, tf, start, now + 1, adjusted_prices=True)
        if len(bars) >= 60:
            chars.append(character(inst.symbol, from_bars(bars, tf, market)))
    if not chars:
        raise NoData("No saved prices for those stocks in that period.")
    cands = candidates(market, tf, symbols, chars, cfg)
    runner = Runner(ctx, market, insts, tf)

    # 3–4: tune in-sample, check out-of-sample
    for k, cand in enumerate(cands):
        if check is not None:
            check()
        say(5 + 55 * k / len(cands), f"Testing {cand.name}…")
        params, is_sharpe, trades, isolated = tune(cand, runner, start, split)
        cand.params, cand.is_sharpe, cand.is_trades, cand.isolated = (
            params,
            is_sharpe,
            trades,
            isolated,
        )
        if not math.isfinite(is_sharpe):
            cand.verdict = "too few trades to judge"
            continue
        if is_sharpe <= 0:
            cand.verdict = "no edge even on the years it was tuned on"
            continue
        cand.oos = runner(cand.definition, params, split, now + 1) or {}
        oos = _sharpe(cand.oos)
        if not math.isfinite(oos):
            cand.verdict = "too few trades in the unseen years"
        elif oos <= 0 or (cand.oos.get("total_return") or 0) <= 0:
            cand.verdict = "lost money in the unseen years"
        elif oos < KEEP_RATIO * is_sharpe:
            cand.verdict = "fell apart in the unseen years"
        else:
            cand.verdict = "passed"
            trades_oos = int(cand.oos.get("trades") or 0)
            cand.score = oos * min(1.0, trades_oos / 20.0)

    # 5: walk-forward on the best survivors
    passed = sorted((c for c in cands if c.verdict == "passed"), key=lambda c: -c.score)
    finalists = passed[: cfg.finalists]
    edges = [start + int(f * (now - start) / (cfg.folds + 1)) for f in range(cfg.folds + 2)]
    for k, cand in enumerate(finalists):
        say(62 + 25 * k / max(1, len(finalists)), f"Walk-forward test of {cand.name}…")
        folds = []
        for f in range(cfg.folds):
            if check is not None:
                check()
            p, _, _, _ = tune(cand, runner, start, edges[f + 1])
            m = runner(cand.definition, p, edges[f + 1], edges[f + 2])
            folds.append(
                {
                    "params": p,
                    "sharpe": _r(m.get("sharpe") if m else None),
                    "trades": (m or {}).get("trades", 0),
                }
            )
        sh = [f["sharpe"] for f in folds if f["sharpe"] is not None]
        cand.wf_folds = folds
        cand.wf_sharpe = float(np.mean(sh)) if sh else None
        cand.verdict = "finalist"
    ranked = sorted(
        finalists,
        key=lambda c: -(c.score + 0.5 * (c.wf_sharpe if c.wf_sharpe is not None else -1.0)),
    )
    winner = ranked[0] if ranked and (ranked[0].wf_sharpe or 0) > 0 else None
    for c in ranked[1:]:
        c.verdict = "runner-up"

    out: dict[str, Any] = {
        "market": market.value,
        "timeframe": tf.value,
        "symbols": symbols,
        "period": {"start": start, "split": split, "end": now},
        "character": [c.public() for c in chars],
        "candidates": [c.public() for c in sorted(cands, key=lambda c: -c.score)],
        "runs": runner.runs,
        "winner": None,
        "cautions": [],
    }
    if winner is None:
        if ranked:
            ranked[0].verdict = "failed the walk-forward test"
            out["candidates"] = [c.public() for c in sorted(cands, key=lambda c: -c.score)]
        out["cautions"].append(
            "Nothing held up out of sample. The honest answer: none of the strategies Agora "
            "knows showed a lasting edge on these stocks in this period."
        )
        say(100, "Done: nothing passed.")
        return out

    winner.verdict = "winner"
    out["candidates"] = [c.public() for c in sorted(cands, key=lambda c: -c.score)]
    say(90, f"Saving {winner.name} with its tuned settings…")
    out["winner"] = _save_winner(ctx, winner, symbols, chars, start, now)
    o = winner.oos or {}
    if (o.get("trades") or 0) < 20:
        out["cautions"].append(
            f"Only {o.get('trades')} trades in the unseen years: the result could be luck."
        )
    if winner.isolated:
        out["cautions"].append(
            "Its best in-sample setting was an isolated peak, so a steadier neighbour was used."
        )
    out["cautions"].append(
        "Past results don't guarantee future ones; markets change. Paper trade it first."
    )
    say(100, "Done.")
    return out


def _save_winner(
    ctx: Any,
    c: Candidate,
    symbols: list[str],
    chars: list[Character],
    start: int,
    end: int,
) -> dict[str, Any]:
    from backend.backtest.manager import BacktestRequest

    d = c.definition
    if c.key == "kairos":  # the saved brain does use what Kairos learned
        learning = ctx.learning
        market, tf = Market(d.market), Timeframe(d.timeframe)
        info = learning.trained(market, tf)
        d = d.model_copy(
            update={
                "weights": learning.weights(market, tf),
                "trained_at": info["at"] if info else None,
            }
        )
    params = [
        p.model_copy(update={"default": c.params.get(p.name, p.default)}) for p in d.parameters
    ]
    d = d.model_copy(update={"parameters": params})
    kinds = sorted({ch.label for ch in chars})
    name = f"{c.name} · tuned for {', '.join(symbols[:3])}{'…' if len(symbols) > 3 else ''}"
    tuned = ", ".join(f"{k}={v:g}" for k, v in c.params.items()) or "defaults"
    template_key = None if c.key == "kairos" else c.key
    with ctx.db.session() as s:
        # Revision control (D-79, D-80): a strategy the user already has isn't copied. Its
        # current revision on these stocks with the tuned settings becomes an opportunity.
        found = revisions.match(s, d, template_key=template_key)
    if found is not None and c.key != "kairos":
        from backend.portfolio.service import record_research

        overrides = {k: float(v) for k, v in c.params.items()}
        try:
            opp = record_research(ctx, found.version_id, symbols, overrides)
        except Exception:
            opp = None
        run_id = ctx.backtests.submit(
            BacktestRequest(
                strategy_version_id=found.version_id,
                symbols=symbols,
                overrides=overrides,
                start=start,
                end=end,
                name=f"Research: {found.name} on {', '.join(symbols[:3])}"[:120],
            )
        )
        return {
            "strategy_id": found.strategy_id,
            "version_id": found.version_id,
            "name": found.name,
            "run_id": run_id,
            "key": c.key,
            "params": c.params,
            "reused": True,
            "opportunity_id": opp,
            "note": f"You already have this strategy (“{found.name}”, #{found.strategy_id}), so "
            "no copy was made: its tuned settings on these stocks are saved as an opportunity.",
        }
    with ctx.db.session() as s:
        saved = revisions.save(
            s,
            definition=d,
            author="kairos",
            name=name[:120],
            description=(
                f"Found by Kairos's research: the best of the strategies tried on stocks that "
                f"look {' / '.join(kinds)}. Tuned settings: {tuned}."
            ),
            now=ctx.clock.now_ms(),
            note="Kairos research winner",
            template_key=template_key,
            source="kairos-research",
        )
        sid, vid, name = saved.strategy_id, saved.version_id, saved.name
    run_id = ctx.backtests.submit(
        BacktestRequest(
            strategy_version_id=vid, start=start, end=end, name=f"Research: {name}"[:120]
        )
    )
    return {
        "strategy_id": sid,
        "version_id": vid,
        "name": name,
        "run_id": run_id,
        "key": c.key,
        "params": c.params,
        "reused": saved.outcome != "new_strategy",
    }
