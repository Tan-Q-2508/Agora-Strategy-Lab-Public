"""Kairos's trade judge: should the desk take *this* entry? (D-145, Phase 25.7)

Kairos's brain scores each candle from signals whose weights were learned one at a time
(D-61), and the trade check (D-71) splits ten readings into thirds, again one at a time. Neither
can learn a *combination*: "a breakout signal is good when volatility is low and the trend is
up, poor when the stock is already stretched far above its average". Quant desks handle this
with **meta-labeling** (López de Prado 2018): a second model that only decides whether to act
on the first model's signal.

- **Lessons**: every entry the brain would have made in history (``exits.entries``, one per
  10 candles per stock) becomes a row: about 25 readings at the signal candle (the brain's score
  and parts, the trade check's readings, the stock's regime) and the trade's result in R after
  costs under the settings' exits.
- **Model**: gradient-boosted small trees (depth 2, numpy only), which find such combinations
  without being told, and can't fit noise far with 2-split trees, a learning rate of 0.1 and
  at least ``MIN_LEAF`` lessons a leaf.
- **Honest by construction**: lessons are ordered in time. The first 70% is the study (the
  model learns on its first 80% and chooses how picky to be on the last 20%), then a gap as long
  as a trade can last (so no lesson's outcome overlaps the exam), then the exam. The judge is
  **switched on** for a desk only if, on the exam, the trades it would have taken earned at least
  ``MIN_GAIN_R`` more per trade than taking them all, by at least two standard errors (so pure
  noise can't switch it on), ranked winners above losers (AUC ≥ 0.53), with enough trades kept.
  Otherwise it only watches.
- **A warning, never a bench** (D-147, D-215; ``stand_aside`` in the model): if, on the exam,
  the entries the desk would take (the judge's picks when it is on, else all) *lost* after costs,
  by at least ``MIN_LOSS_R`` a trade and two standard errors, the desk's card says so. The desk
  keeps trading at full size: the user wants it free to trade, make mistakes and learn from them,
  so this verdict changes neither whether it trades nor how much.
- **Live only**: desks ask the judge before each entry; backtests don't, so a backtest of
  Kairos stays reproducible (like the learned weights and exits, D-140).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from backend.analysis import regime_map
from backend.kairos import quality

COMPONENTS = ("trend", "momentum", "volume", "patterns", "levels", "divergence", "candles")
READING_KEYS = tuple(r.key for r in quality.READINGS)
FEATURES = (
    "side",
    "score",
    *(f"part_{c}" for c in COMPONENTS),
    "reasons",
    "fresh",
    *(f"read_{k}" for k in READING_KEYS),
    "regime_trend",
    "regime_vol",
)
WORDS = {
    "side": "buying or shorting",
    "score": "Kairos's score",
    "reasons": "how many signals agreed",
    "fresh": "a signal that just fired",
    "regime_trend": "the stock's trend (up, sideways, down)",
    "regime_vol": "how jumpy the stock is against its own past",
    **{f"part_{c}": f"the {c} part of the score" for c in COMPONENTS},
    **{f"read_{r.key}": r.label for r in quality.READINGS},
}

BINS = 16
TREES = 120
DEPTH = 2
RATE = 0.1
L2 = 1.0
MIN_LEAF = 25
MIN_LESSONS = 400
STUDY_SHARE = 0.7
TRAIN_SHARE = 0.8  # of the study: the rest picks how picky to be
KEEP_CHOICES = (0.5, 0.6, 0.7, 0.8, 0.9)
MIN_KEPT = 30
MIN_GAIN_R = 0.05
MIN_Z = 2.0  # the exam gain in standard errors
MIN_AUC = 0.53
MIN_LOSS_R = 0.05  # entries must lose at least this per trade, by MIN_Z errors, to stand aside


# ---------------------------------------------------------------- lessons


@dataclass
class Lesson:
    ts: int
    x: list[float]
    r: float  # the trade's result in R after costs

    @property
    def won(self) -> bool:
        return self.r > 0


class Reader:
    """The judge's readings for one stock's history, computed once (causal, like every
    catalog indicator: the value at candle ``i`` uses candles ``0..i``)."""

    def __init__(self, series: Any) -> None:
        self.book = quality.FeatureBook(series)
        self.trend = regime_map.trend_axis(series.close, series.high, series.low)
        self.vol = regime_map.vol_rank(series.high, series.low, series.close)

    def at(self, i: int, side: int, d: Any) -> list[float]:
        reads = self.book.at(i, side)
        trend = self.trend[i] if 0 <= i < len(self.trend) else None
        t = {"up": 1.0, "sideways": 0.0, "down": -1.0}.get(trend or "", math.nan)
        v = float(self.vol[i]) if 0 <= i < len(self.vol) else math.nan
        fresh = d.fresh(side) if hasattr(d, "fresh") else []
        return [
            float(side),
            float(d.score) * side,
            *(float(d.components.get(c, 0.0)) * side for c in COMPONENTS),
            float(len(d.reasons(side))) if hasattr(d, "reasons") else 0.0,
            1.0 if fresh else 0.0,
            *(float(reads.get(k, math.nan)) for k in READING_KEYS),
            t * side,
            v,
        ]


# ---------------------------------------------------------------- the model


@dataclass
class Tree:
    feature: list[int]  # per node (root, left, right): the feature split on, -1 = none
    cut: list[float]  # x <= cut goes left; missing values go right
    leaves: list[float]  # four leaf values (left-left, left-right, right-left, right-right)

    def predict(self, X: np.ndarray) -> np.ndarray:
        out = np.empty(len(X))
        go_left = _left(X, self.feature[0], self.cut[0])
        for side, mask in ((0, go_left), (1, ~go_left)):
            node = 1 + side
            sub = X[mask]
            left = _left(sub, self.feature[node], self.cut[node])
            vals = np.where(left, self.leaves[2 * side], self.leaves[2 * side + 1])
            out[mask] = vals
        return out


def _left(X: np.ndarray, f: int, cut: float) -> np.ndarray:
    if f < 0:
        return np.ones(len(X), dtype=bool)
    col = X[:, f]
    with np.errstate(invalid="ignore"):
        return np.isfinite(col) & (col <= cut)


@dataclass
class Model:
    base: float
    trees: list[Tree]
    threshold: float = 0.0  # take an entry when its chance is at least this
    active: bool = False
    stand_aside: bool = False  # the desk's entries lost on unseen past trades (D-147)
    report: dict[str, Any] = field(default_factory=dict)

    def chance(self, x: Sequence[float]) -> float:
        return float(self.chances(np.asarray([x], dtype=float))[0])

    def chances(self, X: np.ndarray) -> np.ndarray:
        raw = np.full(len(X), self.base)
        for t in self.trees:
            raw += t.predict(X)
        return np.asarray(1.0 / (1.0 + np.exp(-raw)))

    def take(self, x: Sequence[float]) -> bool:
        return not self.active or self.chance(x) >= self.threshold

    def to_json(self) -> dict[str, Any]:
        return {
            "features": list(FEATURES),
            "base": self.base,
            "trees": [{"f": t.feature, "c": t.cut, "v": t.leaves} for t in self.trees],
            "threshold": self.threshold,
            "active": self.active,
            "stand_aside": self.stand_aside,
            "report": self.report,
        }

    @staticmethod
    def from_json(d: Mapping[str, Any]) -> Model | None:
        if list(d.get("features", [])) != list(FEATURES):
            return None  # made for another list of readings: study again
        trees = [Tree(list(t["f"]), list(t["c"]), list(t["v"])) for t in d["trees"]]
        return Model(
            float(d["base"]),
            trees,
            float(d["threshold"]),
            bool(d["active"]),
            bool(d.get("stand_aside", False)),
            dict(d.get("report", {})),
        )


def _cuts(X: np.ndarray) -> list[np.ndarray]:
    out = []
    for j in range(X.shape[1]):
        col = X[:, j]
        col = col[np.isfinite(col)]
        if len(col) == 0:
            out.append(np.array([]))
            continue
        qs = np.unique(np.quantile(col, np.linspace(0, 1, BINS + 1)[1:-1]))
        out.append(qs)
    return out


def _best_split(
    X: np.ndarray, g: np.ndarray, h: np.ndarray, cuts: list[np.ndarray]
) -> tuple[int, float, float]:
    """(feature, cut, gain) of the best split of these rows; feature −1 when none helps."""
    G, H = float(g.sum()), float(h.sum())
    parent = G * G / (H + L2)
    best = (-1, 0.0, 0.0)
    n = len(g)
    for j, cs in enumerate(cuts):
        col = X[:, j]
        finite = np.isfinite(col)
        for c in cs:
            left = finite & (col <= c)
            nl = int(left.sum())
            if nl < MIN_LEAF or n - nl < MIN_LEAF:
                continue
            gl, hl = float(g[left].sum()), float(h[left].sum())
            gr, hr = G - gl, H - hl
            gain = gl * gl / (hl + L2) + gr * gr / (hr + L2) - parent
            if gain > best[2]:
                best = (j, float(c), gain)
    return best


def _leaf(g: np.ndarray, h: np.ndarray) -> float:
    return float(-RATE * g.sum() / (h.sum() + L2)) if len(g) else 0.0


def boost(X: np.ndarray, y: np.ndarray, trees: int = TREES) -> Model:
    """Gradient boosting on log-loss with depth-2 trees."""
    p0 = float(np.clip(y.mean(), 0.02, 0.98)) if len(y) else 0.5
    base = math.log(p0 / (1 - p0))
    raw = np.full(len(y), base)
    cuts = _cuts(X)
    out: list[Tree] = []
    for _ in range(trees):
        p = 1.0 / (1.0 + np.exp(-raw))
        g, h = p - y, p * (1 - p)
        f0, c0, gain0 = _best_split(X, g, h, cuts)
        if f0 < 0 or gain0 <= 0:
            break
        root_left = _left(X, f0, c0)
        feats, cutv, leaves = [f0, -1, -1], [c0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]
        for side, mask in ((0, root_left), (1, ~root_left)):
            f1, c1, _g = _best_split(X[mask], g[mask], h[mask], cuts)
            feats[1 + side], cutv[1 + side] = f1, c1
            sub_left = _left(X[mask], f1, c1)
            gm, hm = g[mask], h[mask]
            leaves[2 * side] = _leaf(gm[sub_left], hm[sub_left])
            leaves[2 * side + 1] = _leaf(gm[~sub_left], hm[~sub_left])
        t = Tree(feats, cutv, leaves)
        out.append(t)
        raw += t.predict(X)
    return Model(base, out)


def auc(p: np.ndarray, y: np.ndarray) -> float | None:
    """Area under the ROC curve (the chance a winner is ranked above a loser)."""
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    # ties share their average rank
    _, inv, counts = np.unique(p, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, ranks)
    ranks = sums[inv] / counts[inv]
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


# ---------------------------------------------------------------- learning, honestly


def learn(lessons: Sequence[Lesson], embargo_ms: int) -> Model | None:
    """Train, choose how picky to be, and decide whether the judge earns its place."""
    if len(lessons) < MIN_LESSONS:
        return None
    ls = sorted(lessons, key=lambda x: x.ts)
    t0, t1 = ls[0].ts, ls[-1].ts
    exam_from = t0 + int((t1 - t0) * STUDY_SHARE)
    study = [x for x in ls if x.ts < exam_from - embargo_ms]
    exam = [x for x in ls if x.ts >= exam_from]
    if len(study) < MIN_LESSONS // 2 or len(exam) < MIN_KEPT * 2:
        return None
    cut = int(len(study) * TRAIN_SHARE)
    train, pick = study[:cut], study[cut:]

    def arrays(rows: Sequence[Lesson]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        X = np.asarray([r.x for r in rows], dtype=float)
        y = np.asarray([1.0 if r.won else 0.0 for r in rows])
        R = np.asarray([r.r for r in rows])
        return X, y, R

    Xt, yt, _Rt = arrays(train)
    Xp, _yp, Rp = arrays(pick)
    Xe, ye, Re = arrays(exam)
    model = boost(Xt, yt)
    pp = model.chances(Xp)
    best_keep, best_gain = 1.0, 0.0
    for keep in KEEP_CHOICES:
        th = float(np.quantile(pp, 1 - keep))
        kept = Rp[pp >= th]
        if len(kept) < MIN_KEPT:
            continue
        gain = float(kept.mean() - Rp.mean())
        if gain > best_gain:
            best_keep, best_gain = keep, gain
    th = float(np.quantile(pp, 1 - best_keep)) if best_keep < 1.0 else 0.0
    pe = model.chances(Xe)
    kept = Re[pe >= th] if th > 0 else Re
    gain = float(kept.mean() - Re.mean()) if len(kept) else 0.0
    exam_auc = auc(pe, ye)
    # the gain must stand out from chance: a subset of n_k of n trades differs from the whole
    # by σ·√(1/n_k − 1/n) on its own
    nk, na = len(kept), len(Re)
    spread = float(np.std(Re)) * math.sqrt(max(1.0 / nk - 1.0 / na, 0.0)) if nk else math.inf
    z = gain / spread if spread > 0 else 0.0
    active = (
        best_keep < 1.0
        and nk >= MIN_KEPT
        and gain >= MIN_GAIN_R
        and z >= MIN_Z
        and (exam_auc or 0.0) >= MIN_AUC
    )
    model.threshold = th
    model.active = active
    # the trades the desk would actually take on the exam: lost clearly, after costs?
    taken = kept if active else Re
    err = float(np.std(taken)) / math.sqrt(len(taken)) if len(taken) > 1 else math.inf
    taken_r = float(taken.mean()) if len(taken) else 0.0
    model.stand_aside = (
        len(taken) >= MIN_KEPT and taken_r <= -MIN_LOSS_R and err > 0 and -taken_r / err >= MIN_Z
    )
    model.report = {
        "lessons": len(ls),
        "study": len(study),
        "exam": len(exam),
        "keep_share": best_keep,
        "exam_all_r": round(float(Re.mean()), 3),
        "exam_taken_r": round(taken_r, 3),
        "exam_taken": len(taken),
        "exam_kept_r": round(float(kept.mean()), 3) if len(kept) else None,
        "exam_kept": len(kept),
        "exam_gain_r": round(gain, 3),
        "exam_z": round(z, 2),
        "exam_auc": None if exam_auc is None else round(exam_auc, 3),
        "exam_win_all": round(float(ye.mean()), 3),
        "exam_win_kept": round(float((kept > 0).mean()), 3) if len(kept) else None,
        "top": top_features(model),
    }
    return model


def top_features(model: Model, n: int = 5) -> list[str]:
    """The readings the trees split on most (their plain names)."""
    count: dict[int, int] = {}
    for t in model.trees:
        for f in t.feature:
            if f >= 0:
                count[f] = count.get(f, 0) + 1
    order = sorted(count, key=lambda f: -count[f])[:n]
    return [WORDS.get(FEATURES[f], FEATURES[f]) for f in order]


def words(model: Model | None) -> str:
    """What the judge does now, in plain English."""
    if model is None:
        return "Not enough past trades to judge entries yet."
    r = model.report
    if model.stand_aside:
        return (
            f"Warning: on {r.get('exam_taken', 0)} unseen past trades its entries on this "
            f"chart lost {r.get('exam_taken_r', 0):+.2f}R each after costs"
            + (", even the judge's picks" if model.active else "")
            + ". The desk keeps trading at full size and learns from each trade."
        )
    if not model.active:
        return (
            f"Watching only: on {r.get('exam', 0)} unseen past trades, being picky didn't earn "
            f"enough more per trade ({r.get('exam_gain_r', 0):+.2f}R)."
        )
    return (
        f"On: takes the best {r['keep_share']:.0%} of entries. On {r['exam']} unseen past trades "
        f"the ones it kept earned {r['exam_kept_r']:+.2f}R each against {r['exam_all_r']:+.2f}R "
        f"for all, winning {r['exam_win_kept']:.0%} against {r['exam_win_all']:.0%}. It looks "
        f"most at: {', '.join(r['top'][:3])}."
    )


# ---------------------------------------------------------------- storage


def path(data_dir: Path, market: str, timeframe: str) -> Path:
    return data_dir / "kairos" / f"judge_{market}_{timeframe}.json"


def save(data_dir: Path, market: str, timeframe: str, model: Model | None) -> None:
    p = path(data_dir, market, timeframe)
    p.parent.mkdir(parents=True, exist_ok=True)
    if model is None:
        p.unlink(missing_ok=True)
        return
    p.write_text(json.dumps(model.to_json()), encoding="utf-8")


def load(data_dir: Path, market: str, timeframe: str) -> Model | None:
    p = path(data_dir, market, timeframe)
    if not p.exists():
        return None
    try:
        return Model.from_json(json.loads(p.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError):
        return None
