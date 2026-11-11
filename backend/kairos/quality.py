"""Kairos's trade check: learn which trades a strategy should skip (KAIROS §16, D-71).

A strategy's rules say *when* to trade. They can't say whether this is a good moment for
*that* strategy: a breakout rule fires the same way in a quiet trend and in a choppy,
news-driven market, and only one of those usually pays after costs. The trade check
learns that from the strategy's own results.

**What it looks at.** For every trade (and every skipped signal) it records the market's
condition on the signal candle with ten plain readings, all from the indicator catalog so
any lesson can be written back into a strategy as an ordinary rule: trend strength (ADX),
choppiness, RSI, volatility (ATR %), relative volume, stretch from the 20-candle average
(z-score), distance from the 50- and 200-candle averages, where the close sits in its
recent range (stochastic %K) and, when Kairos's own reading is available, its score.
Readings that have a direction (RSI, stretch, distances, range position, score) are turned
round for short trades, so "with the trend" means the same thing on both sides.

**How it learns.** Each reading is split into low / middle / high thirds of what the
strategy has seen. For each third it counts how often trades *made money after costs*
(a Beta average shrunk toward the strategy's overall win rate, so ten trades can't make a
rule). The chance for a new trade adds up how far each of its thirds sits from the
overall rate, in log-odds, times a damping factor that is chosen by leave-one-out so the
chances are honest rather than over-confident (readings overlap: ADX and choppiness say
much the same thing).

**What it does.** ``learn`` only watches. ``balanced`` skips trades that look clearly
worse than this strategy's usual one or whose expected result after costs is negative.
``strict`` aims for a high win rate: it takes only trades whose chance is at least 50%
(and 5 points above the usual), never fewer than the best ~30% of past trades. Nothing is
skipped until 30 results have been seen.

**Never stops learning.** A skipped signal is followed anyway ("shadow" trade: the return
over the strategy's typical holding time, minus its typical costs), so a rule that turns
out wrong is unlearned. Everything is causal: a sample only counts once its outcome is
known, so a backtest with the check and live paper trading with it behave the same way
(D-04).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from backend.indicators import catalog
from backend.indicators.series import F64, BarSeries

Mode = Literal["off", "learn", "balanced", "strict"]
MODES: tuple[Mode, ...] = ("off", "learn", "balanced", "strict")
MIN_SAMPLES = 30  # results needed before anything is skipped
PRIOR = 10.0  # pseudo-trades pulling each third toward the overall win rate
SHADOW_WEIGHT = 0.5  # a followed-but-skipped signal counts half as much as a real trade
MAX_SAMPLES = 3000


@dataclass(frozen=True)
class Reading:
    key: str
    label: str
    indicator: str
    params: Mapping[str, float]
    output: str | None
    directional: bool  # turned round for shorts
    flip: Literal["neg", "mirror100"] = "neg"  # how: −x, or 100 − x
    unit: str = ""
    low_word: str = "low"
    high_word: str = "high"


READINGS: tuple[Reading, ...] = (
    Reading(
        "adx",
        "Trend strength (ADX 14)",
        "adx",
        {"period": 14},
        "adx",
        False,
        low_word="the trend is weak",
        high_word="the trend is strong",
    ),
    Reading(
        "chop",
        "Choppiness (14)",
        "chop",
        {"period": 14},
        None,
        False,
        low_word="the market is trending",
        high_word="the market is choppy",
    ),
    Reading(
        "rsi",
        "RSI (14)",
        "rsi",
        {"period": 14},
        None,
        True,
        "mirror100",
        low_word="momentum is weak",
        high_word="momentum is strong",
    ),
    Reading(
        "natr",
        "Volatility (ATR % 14)",
        "natr",
        {"period": 14},
        None,
        False,
        unit="%",
        low_word="the stock is quiet",
        high_word="the stock is volatile",
    ),
    Reading(
        "rvol",
        "Relative volume (20)",
        "rvol",
        {"period": 20},
        None,
        False,
        unit="×",
        low_word="volume is thin",
        high_word="volume is heavy",
    ),
    Reading(
        "stretch",
        "Stretch from the 20-candle average (z-score)",
        "zscore",
        {"period": 20},
        None,
        True,
        low_word="price has pulled back from its 20-candle average",
        high_word="price is stretched from its 20-candle average",
    ),
    Reading(
        "mid_trend",
        "Distance from the 50-candle average",
        "disparity",
        {"period": 50},
        None,
        True,
        unit="%",
        low_word="price is against its 50-candle trend",
        high_word="price is far along its 50-candle trend",
    ),
    Reading(
        "long_trend",
        "Distance from the 200-candle average",
        "disparity",
        {"period": 200},
        None,
        True,
        unit="%",
        low_word="price is against its 200-candle trend",
        high_word="price is far along its 200-candle trend",
    ),
    Reading(
        "range_pos",
        "Place in the recent range (stochastic %K)",
        "stochastic",
        {"k": 14, "smooth": 3, "d": 3},
        "k",
        True,
        "mirror100",
        low_word="price is near the bottom of its recent range",
        high_word="price is near the top of its recent range",
    ),
)
SCORE = Reading(
    "score",
    "Kairos's score",
    "",
    {},
    None,
    True,
    low_word="Kairos's score is weaker",
    high_word="Kairos's score is stronger",
)
BY_KEY = {r.key: r for r in (*READINGS, SCORE)}
THIRDS = ("low", "middle", "high")


def past(words: str) -> str:
    """ "the market is choppy" → "the market was choppy" (for describing past trades)."""
    for now, then in ((" is ", " was "), (" are ", " were "), (" has ", " had ")):
        if now in words:
            return words.replace(now, then, 1)
    return words


def middle_words(r: Reading) -> str:
    return f"{r.label.split(' (')[0].lower()} is middling"


def _align(r: Reading, value: float, side: int) -> float:
    if not r.directional or side > 0 or not math.isfinite(value):
        return value
    return 100.0 - value if r.flip == "mirror100" else -value


class FeatureBook:
    """The readings for one symbol's series, computed once (values at candle ``i`` only
    use candles ``0..i``, like every catalog indicator)."""

    def __init__(self, series: BarSeries, score: F64 | None = None) -> None:
        self.n = len(series)
        self.arrays: dict[str, F64] = {}
        for r in READINGS:
            try:
                out = catalog.compute(r.indicator, series, r.params)
            except Exception:  # an indicator that can't run on this series just isn't used
                continue
            arr = out[r.output] if r.output else next(iter(out.values()))
            self.arrays[r.key] = np.asarray(arr, dtype=np.float64)
        if score is not None and len(score) == self.n:
            self.arrays["score"] = np.asarray(score, dtype=np.float64)

    def at(self, i: int, side: int) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, arr in self.arrays.items():
            if 0 <= i < len(arr):
                v = float(arr[i])
                if math.isfinite(v):
                    out[k] = round(_align(BY_KEY[k], v, side), 4)
        return out


@dataclass
class Sample:
    """One trade (or followed skipped signal) and the market's condition when it fired."""

    features: dict[str, float]
    win: bool
    ret_pct: float  # after costs, % of the money put in
    weight: float = 1.0
    ts: int = 0  # signal candle
    known_ts: int = 0  # when the outcome became known (exit)
    side: int = 1
    symbol: str = ""
    source: str = "trade"  # trade | shadow


@dataclass(frozen=True)
class Part:
    """One reading's say in a chance."""

    key: str
    label: str
    value: float
    third: str
    words: str
    win_rate: float
    count: float
    effect: float  # log-odds versus the overall rate (before damping)


@dataclass(frozen=True)
class Verdict:
    take: bool
    chance: float  # estimated chance this trade makes money after costs
    usual: float  # the strategy's overall win rate
    expected_pct: float  # expected result after costs, % (None-like 0 when unknown)
    parts: tuple[Part, ...]
    reason: str
    learned_from: float


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _wquantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), cum, v))


@dataclass
class _Stat:
    edges: tuple[float, float]
    wins: list[float]
    n: list[float]

    def third(self, x: float) -> int:
        return 0 if x < self.edges[0] else 2 if x > self.edges[1] else 1


@dataclass
class Model:
    """The fitted trade check: per-reading thirds with their win rates."""

    base: float
    n: float
    stats: dict[str, _Stat]
    damp: float
    avg_win: float
    avg_loss: float
    hold: float  # typical candles held
    cost_pct: float  # typical round-trip costs, % of the money put in
    threshold_strict: float

    def parts(self, features: Mapping[str, float]) -> list[Part]:
        out = []
        for k, st in self.stats.items():
            x = features.get(k)
            if x is None:
                continue
            b = st.third(x)
            rate = (st.wins[b] + PRIOR * self.base) / (st.n[b] + PRIOR)
            r = BY_KEY[k]
            word = r.low_word if b == 0 else r.high_word if b == 2 else middle_words(r)
            out.append(
                Part(
                    k, r.label, x, THIRDS[b], word, rate, st.n[b], _logit(rate) - _logit(self.base)
                )
            )
        return out

    def chance(self, features: Mapping[str, float], damp: float | None = None) -> float:
        d = self.damp if damp is None else damp
        z = _logit(self.base) + d * sum(p.effect for p in self.parts(features))
        return _sigmoid(z)

    def expected(self, p: float) -> float:
        return p * self.avg_win - (1 - p) * self.avg_loss

    def public(self) -> dict[str, Any]:
        """The learned picture, for the panels and Kairos's explanations."""
        rows = []
        for k, st in self.stats.items():
            r = BY_KEY[k]
            thirds: list[dict[str, Any]] = []
            for b in range(3):
                rate = (st.wins[b] + PRIOR * self.base) / (st.n[b] + PRIOR)
                thirds.append(
                    {"third": THIRDS[b], "count": round(st.n[b], 1), "win_rate": round(rate, 3)}
                )
            rows.append(
                {
                    "key": k,
                    "label": r.label,
                    "edges": [round(e, 3) for e in st.edges],
                    "unit": r.unit,
                    "thirds": thirds,
                    "spread": round(
                        max(t["win_rate"] for t in thirds) - min(t["win_rate"] for t in thirds), 3
                    ),
                }
            )
        rows.sort(key=lambda x: -float(x["spread"]))
        return {
            "usual_win_rate": round(self.base, 3),
            "learned_from": round(self.n, 1),
            "readings": rows,
            "typical_hold": round(self.hold, 1),
            "typical_cost_pct": round(self.cost_pct, 3),
        }


def fit(samples: Sequence[Sample]) -> Model | None:
    """Fit the trade check on samples whose outcome is known. ``None`` with no samples."""
    if not samples:
        return None
    w = np.array([s.weight for s in samples], dtype=np.float64)
    y = np.array([1.0 if s.win else 0.0 for s in samples])
    total = float(w.sum())
    base = (float((w * y).sum()) + 1.0) / (total + 2.0)
    stats: dict[str, _Stat] = {}
    for key in BY_KEY:
        idx = [j for j, s in enumerate(samples) if key in s.features]
        if len(idx) < 9:
            continue
        x = np.array([samples[j].features[key] for j in idx])
        ww, yy = w[idx], y[idx]
        e1, e2 = _wquantile(x, ww, 1 / 3), _wquantile(x, ww, 2 / 3)
        st = _Stat((e1, e2), [0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        for xv, wv, yv in zip(x, ww, yy, strict=True):
            b = st.third(float(xv))
            st.n[b] += float(wv)
            st.wins[b] += float(wv * yv)
        stats[key] = st
    rets = np.array([s.ret_pct for s in samples if s.source == "trade"] or [0.0])
    wins = rets[rets > 0]
    losses = -rets[rets <= 0]
    model = Model(
        base=base,
        n=total,
        stats=stats,
        damp=0.5,
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(losses.mean()) if len(losses) else 0.0,
        hold=10.0,
        cost_pct=0.3,
        threshold_strict=0.5,
    )
    model.damp = _choose_damp(model, samples)
    chances = np.array([model.chance(s.features) for s in samples])
    top30 = float(np.quantile(chances, 0.7)) if len(chances) else 0.5
    model.threshold_strict = min(max(0.5, base + 0.05), top30)
    return model


def _choose_damp(model: Model, samples: Sequence[Sample]) -> float:
    """The damping with the best leave-one-out log loss (each sample judged by a model
    that never counted it), so chances aren't over-confident."""
    if len(samples) < 20:
        return 0.35
    grid = (0.15, 0.25, 0.35, 0.5, 0.7, 1.0)
    effects: list[float] = []
    for s in samples:
        tot = 0.0
        for k, st in model.stats.items():
            x = s.features.get(k)
            if x is None:
                continue
            b = st.third(x)
            n = st.n[b] - s.weight
            wins = st.wins[b] - (s.weight if s.win else 0.0)
            rate = (wins + PRIOR * model.base) / (max(n, 0.0) + PRIOR)
            tot += _logit(rate) - _logit(model.base)
        effects.append(tot)
    best, best_loss = 0.35, float("inf")
    lb = _logit(model.base)
    for d in grid:
        loss = 0.0
        for s, eff in zip(samples, effects, strict=True):
            p = _sigmoid(lb + d * eff)
            loss -= s.weight * math.log(p if s.win else 1 - p)
        if loss < best_loss - 1e-9:
            best, best_loss = d, loss
    return best


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _value(r: Reading, v: float) -> str:
    if r.unit == "%":
        return f"{v:+.1f}%" if r.directional else f"{v:.1f}%"
    if r.unit == "×":
        return f"{v:.1f}×"
    return f"{v:.0f}" if abs(v) >= 10 else f"{v:.1f}"


def describe_parts(parts: Iterable[Part], against: bool, n: int = 2) -> str:
    """The readings that pull the chance down (``against``) or up, in plain words."""
    chosen = sorted(
        (p for p in parts if (p.effect < 0) == against and abs(p.effect) > 0.05),
        key=lambda p: p.effect if against else -p.effect,
    )[:n]
    bits = [
        f"{p.words} ({_value(BY_KEY[p.key], p.value)}; trades like that won "
        f"{_pct(p.win_rate)} of {p.count:.0f})"
        for p in chosen
    ]
    return " and ".join(bits)


def judge(
    model: Model | None, features: Mapping[str, float], mode: Mode, *, proven: bool = True
) -> Verdict:
    """Take or skip one signal. Unknown or too-new models, and checks that haven't yet
    proven their judgement (``proven``), always take the trade."""
    if model is None or mode in ("off", "learn") or model.n < MIN_SAMPLES or not proven:
        n = 0.0 if model is None else model.n
        p = model.chance(features) if model is not None else 0.5
        usual = model.base if model is not None else 0.5
        parts = tuple(model.parts(features)) if model is not None else ()
        return Verdict(True, p, usual, model.expected(p) if model else 0.0, parts, "", n)
    p = model.chance(features)
    parts = tuple(model.parts(features))
    exp = model.expected(p)
    if mode == "strict":
        bar = model.threshold_strict
        take = p >= bar and exp > 0
    else:
        bar = model.base - 0.08
        take = p >= bar and exp > -0.05 * model.avg_loss
    reason = ""
    if not take:
        why = describe_parts(parts, against=True)
        cost_note = (
            f" After costs, trades like this were expected to lose {abs(exp):.2f}% on average."
            if exp <= 0
            else ""
        )
        reason = (
            f"Kairos's trade check skipped this signal: its chance of making money after costs "
            f"looked {_pct(p)}, against {_pct(model.base)} for this strategy's usual trade"
            + (f", because {why}" if why else "")
            + "."
            + cost_note
        )
    return Verdict(take, p, model.base, exp, parts, reason[:600], model.n)


# ---------------------------------------------------------------- earning the right to skip

PROOF_MIN = 30  # judged results needed before the check may skip anything
PROOF_SKILL = 0.02  # and it must beat "every trade is the usual trade" by this much (Brier)
PROOF_WINDOW = 300  # the most recent judged results count


def brier_skill(scored: Sequence[tuple[float, float, bool]]) -> float:
    """1 − Brier(chances) / Brier(the usual win rate at the time): > 0 means the chances
    told good trades from bad better than treating every trade alike."""
    if not scored:
        return 0.0
    model = sum((p - (1.0 if w else 0.0)) ** 2 for p, _, w in scored)
    base = sum((b - (1.0 if w else 0.0)) ** 2 for _, b, w in scored)
    return 1.0 - model / base if base > 0 else 0.0


def prequential(samples: Sequence[Sample], chunk: int = 30, last: int = 600) -> list[Any]:
    """Judge past results the honest way: each block of results by a check fitted only on
    results known before the block began. Returns (chance, usual rate, won) triples."""
    ordered = sorted(samples, key=lambda x: (x.known_ts, x.ts))
    start = max(PROOF_MIN * 2, len(ordered) - last)
    out: list[tuple[float, float, bool]] = []
    for k in range(start, len(ordered), chunk):
        block = ordered[k : k + chunk]
        first_signal = min(x.ts for x in block)
        known = [x for x in ordered[:k] if x.known_ts <= first_signal]
        m = fit(known)
        if m is None or m.n < MIN_SAMPLES:
            continue
        out.extend((m.chance(x.features), m.base, x.win) for x in block)
    return out


# ---------------------------------------------------------------- the engine's hook


@dataclass
class _Shadow:
    symbol_key: int
    side: int
    features: dict[str, float]
    ts: int  # the signal candle (times, not indices: live sessions trim old candles)


@dataclass
class CheckStats:
    checked: int = 0
    skipped: int = 0
    shadow_wins: int = 0
    shadow_losses: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


class TradeCheck:
    """Plugged into the engine (``Engine.check``): judges each entry signal and learns
    from every closed trade and followed skipped signal, in time order."""

    def __init__(
        self,
        mode: Mode,
        seed: Sequence[Sample] = (),
        *,
        score_for: Callable[[Any], F64 | None] | None = None,
        refit_every: int = 5,
    ) -> None:
        self.mode: Mode = mode
        self.samples: list[Sample] = list(seed)[-MAX_SAMPLES:]
        self.new_samples: list[Sample] = []
        self.model = fit(self.samples)
        self._books: dict[int, tuple[int, FeatureBook]] = {}
        self._open: dict[tuple[int, int], dict[str, float]] = {}  # (symbol, signal ts)
        self._shadows: list[_Shadow] = []
        self._since_fit = 0
        self.refit_every = refit_every
        self.score_for = score_for
        self.stats = CheckStats()
        self._holds: list[float] = []
        self._costs: list[float] = []
        # Every judgement is scored once its result is known; the check only skips trades
        # after those scores show it can tell good trades from bad (PROOF_*).
        self._preds: dict[tuple[int, int], tuple[float, float]] = {}
        self.scored: list[tuple[float, float, bool]] = prequential(self.samples)

    def skill(self) -> tuple[float, int]:
        recent = self.scored[-PROOF_WINDOW:]
        return brier_skill(recent), len(recent)

    def proven(self) -> bool:
        sk, n = self.skill()
        return n >= PROOF_MIN and sk > PROOF_SKILL

    # -- features

    def book(self, key: int, series: BarSeries) -> FeatureBook:
        hit = self._books.get(key)
        if hit is not None and hit[0] == len(series):
            return hit[1]
        score = self.score_for(series) if self.score_for is not None else None
        b = FeatureBook(series, score)
        self._books[key] = (len(series), b)
        return b

    # -- the engine calls these

    def check(self, key: int, symbol: str, series: BarSeries, i: int, side: int) -> str | None:
        """None to take the signal, or the plain-English reason it was skipped."""
        feats = self.book(key, series).at(i, side)
        self.stats.checked += 1
        v = judge(self.model, feats, self.mode, proven=self.proven())
        ts = int(series.ts[i])
        if self.model is not None:
            self._preds[(key, ts)] = (v.chance, self.model.base)
        if v.take:
            self._open[(key, ts)] = feats
            return None
        self.stats.skipped += 1
        top = min(v.parts, key=lambda p: p.effect).words if v.parts else "low chance"
        self.stats.reasons[top] = self.stats.reasons.get(top, 0) + 1
        self._shadows.append(_Shadow(key, side, feats, ts))
        return v.reason

    def closed(
        self,
        key: int,
        symbol: str,
        series: BarSeries,
        signal_ts: int,
        side: int,
        net_pnl: float,
        ret_pct: float,
        bars_held: int,
        charges_pct: float,
        exit_ts: int,
    ) -> None:
        feats = self._open.pop((key, signal_ts), None)
        if feats is None:
            i = int(np.searchsorted(series.ts, signal_ts))
            feats = self.book(key, series).at(i, side) if i < len(series) else {}
        s = Sample(feats, net_pnl > 0, ret_pct, 1.0, signal_ts, exit_ts, side, symbol, "trade")
        pred = self._preds.pop((key, signal_ts), None)
        if pred is not None:
            self.scored.append((pred[0], pred[1], s.win))
        self._holds.append(float(max(bars_held, 1)))
        self._costs.append(charges_pct)
        self._add(s)

    def observe(self, key: int, series: BarSeries, i: int) -> None:
        """Each new candle: settle skipped signals whose typical holding time has passed."""
        if not self._shadows:
            return
        hold = int(np.median(self._holds) + 0.5) if self._holds else 10
        cost = float(np.median(self._costs)) if self._costs else 0.3
        keep = []
        for sh in self._shadows:
            if sh.symbol_key != key:
                keep.append(sh)
                continue
            at = int(np.searchsorted(series.ts, sh.ts))
            end = at + 1 + hold
            if end > i or end >= len(series):
                keep.append(sh)
                continue
            entry = float(series.open[at + 1])
            exit_ = float(series.close[end])
            if entry <= 0:
                continue
            ret = sh.side * (exit_ / entry - 1.0) * 100.0 - cost
            win = ret > 0
            pred = self._preds.pop((key, sh.ts), None)
            if pred is not None:
                self.scored.append((pred[0], pred[1], win))
            if win:
                self.stats.shadow_wins += 1
            else:
                self.stats.shadow_losses += 1
            self._add(
                Sample(
                    sh.features,
                    win,
                    ret,
                    SHADOW_WEIGHT,
                    sh.ts,
                    int(series.ts[end]),
                    sh.side,
                    "",
                    "shadow",
                )
            )
        self._shadows = keep

    def _add(self, s: Sample) -> None:
        self.samples.append(s)
        self.new_samples.append(s)
        if len(self.samples) > MAX_SAMPLES:
            self.samples = self.samples[-MAX_SAMPLES:]
        self._since_fit += 1
        if self._since_fit >= self.refit_every or self.model is None:
            self.model = fit(self.samples)
            if self.model is not None and self._holds:
                self.model.hold = float(np.median(self._holds))
                self.model.cost_pct = float(np.median(self._costs))
            self._since_fit = 0

    def summary(self) -> dict[str, Any]:
        st = self.stats
        top = sorted(st.reasons.items(), key=lambda kv: -kv[1])[:5]
        shadow_n = st.shadow_wins + st.shadow_losses
        return {
            "mode": self.mode,
            "checked": st.checked,
            "skipped": st.skipped,
            "skipped_followed": shadow_n,
            "skipped_would_have_won": st.shadow_wins,
            "skipped_would_have_lost": st.shadow_losses,
            "top_reasons": [{"words": w, "count": c} for w, c in top],
            "learned_from": round(self.model.n, 1) if self.model else 0,
            "proven": self.proven(),
            "skill": round(self.skill()[0], 3),
            "judged": self.skill()[1],
            "usual_win_rate": round(self.model.base, 3) if self.model else None,
        }


def sample_to_json(s: Sample) -> dict[str, Any]:
    return {
        "features": s.features,
        "win": s.win,
        "ret_pct": round(s.ret_pct, 4),
        "weight": s.weight,
        "ts": s.ts,
        "known_ts": s.known_ts,
        "side": s.side,
        "symbol": s.symbol,
        "source": s.source,
    }


def sample_from_json(d: Mapping[str, Any]) -> Sample:
    return Sample(
        {str(k): float(v) for k, v in dict(d.get("features") or {}).items()},
        bool(d.get("win")),
        float(d.get("ret_pct") or 0.0),
        float(d.get("weight") or 1.0),
        int(d.get("ts") or 0),
        int(d.get("known_ts") or 0),
        int(d.get("side") or 1),
        str(d.get("symbol") or ""),
        str(d.get("source") or "trade"),
    )


def score_reader() -> Callable[[BarSeries], F64 | None]:
    """Kairos's score on every candle (neutral weights, so it's the same for everyone),
    computed once per series and shared with the brain's cache."""

    def read(series: BarSeries) -> F64 | None:
        from backend.kairos import brain

        if len(series) < 60:
            return None
        ss = brain.shared_signals(series)
        return np.array([brain.decide(ss, i, {}).score for i in range(len(series))])

    return read
