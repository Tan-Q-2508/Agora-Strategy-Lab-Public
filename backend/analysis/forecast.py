"""Forecasts: a likely price range for the next few candles, with a track record (D-58).

Nobody can predict prices reliably, so Kairos never gives a single number. It blends three
simple models into a distribution of possible paths and reports the median and the
10/25/75/90% bands:

1. **Volatility** — a random walk whose step size is today's EWMA volatility (λ 0.94) and
   whose drift is a quarter of the last 250 candles' average move (shrunk: past drift
   barely persists).
2. **Analogues** — the 50 past moments (this stock and peers) whose last 20 candles moved
   most like the last 20, and what happened next, rescaled to today's volatility. Only
   moments whose outcome was complete before today are used.
3. **Trend** — the regression slope of the last 50 log-closes, fading by 10% a candle, with
   the same volatility.

4. **Analyst** (when Kairos's per-candle score is given, KAIROS §17) — the chart reading
   turned into a drift: how far this stock's next moves have followed Kairos's score in the
   past (a ridge regression of the next ``horizon`` candles' move, in volatility units, on
   the score, fitted only on outcomes complete before each forecast). Live forecasts also
   lean it by the stock's own news (±10 score points, like the desk's news guard) and widen
   every model when the market's news risk is high.

The blend starts at analogues 0.5, volatility 0.4, trend 0.1 (with the analyst: 0.45, 0.35,
0.05, 0.15) and moves toward whichever model's ranges have fitted reality better (lower
quantile loss) on this stock so far, including Kairos's live forecasts once they're scored.

**Learning from misses** (``calibrate``): every past forecast's miss is measured in units
of its own 80% half-range. When ranges held the price less often than 8 times in 10 they
are widened, when far more often narrowed, and a forecast that kept leaning the wrong way
is shifted back (all shrunk toward "no change" while evidence is thin). The walk-forward
test applies the same correction using only earlier misses, so the track record shows the
corrected forecasts.

**Predicted candles** (``expected_candles``): of all the sampled paths, the one that stays
closest to the middle path, drawn as candles. The middle path itself barely moves from one
candle to the next (ups and downs cancel out), so it would draw a row of dojis; the typical
path has the texture of real candles yet ends near the most likely price. Each candle opens
where the previous one closed; its wicks have the size this stock's candles usually have at
today's volatility. A likely shape, never certainty: the ranges around them are the honest
part.

**Track record**: the same procedure is run every 5 candles over the recent past, each
time using only the candles known then, and scored against what happened: how often the
direction was right (a coin flip is 50%), how the median's error compares with simply
assuming "no change" (skill), and how often the 80% range contained the outcome.

Sampling uses a fixed seed, so the same data always gives the same forecast.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.indicators.series import F64

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
DEFAULT_WEIGHTS = {"analogues": 0.5, "volatility": 0.4, "trend": 0.1}
WITH_ANALYST = {"analogues": 0.45, "volatility": 0.35, "trend": 0.05, "analyst": 0.15}
RIDGE = 5.0  # pulls the analyst's fit toward "the score means nothing"
LIVE_COPIES = 3  # a scored live forecast counts like three walk-forward tests
WINDOW = 20  # candles compared by the analogue search
NEIGHBOURS = 50
SAMPLES = 1200
LAMBDA = 0.94
SEED = 20261021


@dataclass(frozen=True)
class Distribution:
    """Quantiles (rows = QUANTILES) of the cumulative log return at each horizon step."""

    q: NDArray[np.float64]  # shape (5, H)
    up: float  # share of paths ending above today


@dataclass(frozen=True)
class TrackRecord:
    tests: int
    direction_hits: int
    skill: float  # 1 − error(median) / error(no change); > 0 beats "no change"
    band80: float  # share of outcomes inside the 80% range
    band50: float
    model_loss: dict[str, float] = field(default_factory=dict)

    @property
    def direction_rate(self) -> float:
        return self.direction_hits / self.tests if self.tests else 0.0


@dataclass(frozen=True)
class Calibration:
    """How past misses changed this forecast (KAIROS §17)."""

    width: float = 1.0  # ranges multiplied by this
    bias: float = 0.0  # middle shifted by this many 80%-half-ranges (at the horizon)
    tests: int = 0  # walk-forward misses used
    live: int = 0  # scored live forecasts used
    coverage: float | None = None  # how often the raw 80% range held the price


@dataclass(frozen=True)
class Memory:
    """What Kairos's scored live forecasts for this stock taught it."""

    misses: tuple[float, ...] = ()  # (actual − raw median) / raw 80% half-range, log terms
    model_losses: dict[str, tuple[float, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Forecast:
    horizon: int
    origin: float
    quantiles: NDArray[np.float64]  # prices, shape (5, H)
    up_probability: float
    weights: dict[str, float]
    model_medians: dict[str, float]  # each model's median % change at the horizon
    track: TrackRecord | None
    sigma: float = 0.0  # today's volatility per candle (log terms)
    calibration: Calibration = field(default_factory=Calibration)
    raw_median: float = 0.0  # uncalibrated blend at the horizon (log return), for scoring
    raw_half: float = 0.0  # its 80% half-range
    model_q: dict[str, list[float]] = field(
        default_factory=dict
    )  # each model's horizon quantiles (log)
    analyst: dict[str, float] = field(default_factory=dict)  # beta, score, news tilt used
    # One real sampled path (cumulative log returns) that hugs the middle path most closely:
    # it has the texture of real candles but ends near the most likely price.
    typical: NDArray[np.float64] | None = None


def _log_returns(close: F64) -> F64:
    c = np.asarray(close, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(c))
    return np.where(np.isfinite(r), r, 0.0)


def ewma_sigma(r: F64, lam: float = LAMBDA) -> float:
    """RiskMetrics volatility of the returns ``r`` (per candle), seeded with their variance."""
    if len(r) == 0:
        return 0.0
    tail = r[-500:]
    var = float(np.var(tail[: min(30, len(tail))])) if len(tail) > 1 else float(tail[0] ** 2)
    for x in tail:
        var = lam * var + (1.0 - lam) * float(x) ** 2
    return float(np.sqrt(max(var, 1e-12)))


class AnalogueLibrary:
    """Every 20-candle window of returns (z-scored) with the H-candle path that followed.

    ``returns[0]`` is the stock being forecast; the others are peers that end on the same
    candle. Each window's end is stored on the forecast stock's index, so "only outcomes
    complete before candle t" means the same moment for every series (no look-ahead)."""

    def __init__(self, returns: Sequence[F64], horizon: int) -> None:
        feats, outs, ends, scale = [], [], [], []
        n_own = len(returns[0]) if returns else 0
        for r in returns:
            n = len(r)
            if n < WINDOW + horizon + 1:
                continue
            win = np.lib.stride_tricks.sliding_window_view(r, WINDOW)[: n - WINDOW - horizon + 1]
            fut = np.lib.stride_tricks.sliding_window_view(r[WINDOW:], horizon)[: len(win)]
            sd = win.std(axis=1)
            sd = np.where(sd > 0, sd, 1.0)
            feats.append((win - win.mean(axis=1, keepdims=True)) / sd[:, None])
            outs.append(np.cumsum(fut, axis=1))
            # index of the window's last return, on the forecast stock's clock
            ends.append(np.arange(WINDOW - 1, WINDOW - 1 + len(win)) + (n_own - n))
            scale.append(sd)
        self.empty = not feats
        if self.empty:
            return
        self.feats = np.concatenate(feats)
        self.outs = np.concatenate(outs)
        self.ends = np.concatenate(ends)
        self.scale = np.concatenate(scale)

    def paths(self, recent: F64, sigma_now: float, cutoff: int, horizon: int) -> F64 | None:
        """Outcome paths of the windows most like the last 20 returns of ``recent``, using
        only windows whose whole outcome ended at or before return index ``cutoff``."""
        if self.empty or len(recent) < WINDOW:
            return None
        ok = self.ends + horizon <= cutoff
        if ok.sum() < 10:
            return None
        w = recent[-WINDOW:]
        sd = float(w.std()) or 1.0
        z = (w - w.mean()) / sd
        d = np.sum((self.feats[ok] - z) ** 2, axis=1)
        k = min(NEIGHBOURS, len(d))
        idx = np.argpartition(d, k - 1)[:k]
        out = self.outs[ok][idx][:, :horizon]
        # Rescale each analogue's path to today's volatility.
        ratio = sigma_now / np.maximum(self.scale[ok][idx], 1e-9)
        return np.asarray(out * ratio[:, None], dtype=np.float64)


def ewma_sigmas(r: F64, lam: float = LAMBDA) -> F64:
    """``out[t]`` = the EWMA volatility known at candle ``t`` (returns ``r[:t]`` only)."""
    n = len(r)
    out = np.zeros(n + 1)
    if n == 0:
        return out
    var = float(np.var(r[: min(30, n)])) if n > 1 else float(r[0] ** 2)
    out[0] = np.sqrt(max(var, 1e-12))
    for t in range(n):
        var = lam * var + (1.0 - lam) * float(r[t]) ** 2
        out[t + 1] = np.sqrt(max(var, 1e-12))
    return out


class AnalystFit:
    """Ridge regression of the next ``horizon`` candles' move (in volatility units) on
    Kairos's score, with prefix sums so a fit "as of candle o" costs nothing."""

    def __init__(self, r: F64, scores: F64, horizon: int) -> None:
        n = len(r)
        self.h = horizon
        sig = ewma_sigmas(r)
        x = np.nan_to_num(np.asarray(scores[: n + 1], dtype=np.float64) / 100.0)
        cum = np.concatenate([[0.0], np.cumsum(r)])
        y = np.zeros(n + 1)
        ok = np.zeros(n + 1, dtype=bool)
        for t in range(60, n + 1 - horizon):
            y[t] = (cum[t + horizon] - cum[t]) / (sig[t] * np.sqrt(horizon))
            ok[t] = True
        xy = np.where(ok, x * y, 0.0)
        xx = np.where(ok, x * x, 0.0)
        self.cxy = np.concatenate([[0.0], np.cumsum(xy)])
        self.cxx = np.concatenate([[0.0], np.cumsum(xx)])
        self.x = x
        self.sig = sig

    def beta(self, origin: int) -> float:
        """Fitted on candles whose whole outcome was known at ``origin``."""
        last = origin - self.h  # outcome of candle t ends at t + h ≤ origin
        if last < 60:
            return 0.0
        return float(self.cxy[last + 1] / (self.cxx[last + 1] + RIDGE))

    def drift(self, origin: int, tilt: float = 0.0) -> tuple[F64, float, float]:
        """Per-step drift for a forecast made at candle ``origin`` (and beta, score)."""
        b = self.beta(origin)
        xo = float(np.clip(self.x[origin] + tilt, -1.0, 1.0)) if origin < len(self.x) else 0.0
        total = b * xo * float(self.sig[origin]) * np.sqrt(self.h)
        return np.full(self.h, total / self.h), b, xo


def calibrate_from(misses: Sequence[float]) -> tuple[float, float]:
    """(width, bias) from past misses in 80%-half-range units: width makes 8 in 10 of them
    fit, bias undoes a steady lean; both shrunk toward (1, 0) while there are few."""
    n = len(misses)
    if n < 8:
        return 1.0, 0.0
    z = np.asarray(misses, dtype=np.float64)
    f = float(np.quantile(np.abs(z), 0.8))
    f = 1.0 + (f - 1.0) * n / (n + 20.0)
    b = float(np.mean(z)) * n / (n + 30.0)
    return float(np.clip(f, 0.6, 2.0)), float(np.clip(b, -0.5, 0.5))


def _apply(samples: F64, width: float, bias: float) -> F64:
    """Stretch the paths around their middle path and shift it (bias grows over the
    horizon, reaching ``bias`` 80%-half-ranges at the end)."""
    if width == 1.0 and bias == 0.0:
        return samples
    med = np.median(samples, axis=0)
    q10, q90 = np.quantile(samples[:, -1], [0.1, 0.9])
    half = max(float(q90 - q10) / 2.0, 1e-9)
    h = samples.shape[1]
    shift = bias * half * np.arange(1, h + 1, dtype=np.float64) / h
    return np.asarray(med + (samples - med) * width + shift, dtype=np.float64)


def _normal_paths(rng: np.random.Generator, n: int, h: int, sigma: float, drift: F64) -> F64:
    steps = rng.standard_normal((n, h)) * sigma + drift[None, :]
    return np.asarray(np.cumsum(steps, axis=1), dtype=np.float64)


def _model_paths(
    r: F64,
    lib: AnalogueLibrary | None,
    horizon: int,
    rng: np.random.Generator,
    analyst: AnalystFit | None = None,
    tilt: float = 0.0,
    vol_scale: float = 1.0,
) -> dict[str, F64]:
    """Sample paths (cumulative log returns) from each model, using returns ``r`` only."""
    sigma = ewma_sigma(r) * vol_scale
    mu = 0.25 * float(np.mean(r[-250:])) if len(r) else 0.0
    out: dict[str, F64] = {
        "volatility": _normal_paths(rng, SAMPLES, horizon, sigma, np.full(horizon, mu))
    }
    tail = r[-50:]
    if len(tail) >= 20:
        logp = np.concatenate([[0.0], np.cumsum(tail)])
        x = np.arange(len(logp), dtype=np.float64)
        slope = float(np.polyfit(x, logp, 1)[0])
        fade = 0.9 ** np.arange(1, horizon + 1, dtype=np.float64)
        out["trend"] = _normal_paths(rng, SAMPLES, horizon, sigma, np.asarray(slope * fade))
    if lib is not None:
        a = lib.paths(r, sigma, len(r) - 1, horizon)
        if a is not None:
            out["analogues"] = a
    if analyst is not None:
        drift, _, _ = analyst.drift(len(r), tilt)
        out["analyst"] = _normal_paths(rng, SAMPLES, horizon, sigma, drift)
    return out


def _blend(paths: dict[str, F64], weights: dict[str, float], rng: np.random.Generator) -> F64:
    use = {k: w for k, w in weights.items() if k in paths and w > 0}
    total = sum(use.values())
    parts = []
    for k, w in use.items():
        n = max(1, round(SAMPLES * w / total))
        src = paths[k]
        parts.append(src[rng.integers(0, len(src), n)])
    return np.concatenate(parts)


def _dist(samples: F64) -> Distribution:
    q = np.quantile(samples, QUANTILES, axis=0)
    return Distribution(np.asarray(q, dtype=np.float64), float((samples[:, -1] > 0).mean()))


def _pinball(q: NDArray[np.float64], actual: float) -> float:
    """Average quantile (pinball) loss of the horizon-end quantiles: lower fits better."""
    loss = 0.0
    for t, v in zip(QUANTILES, q[:, -1], strict=True):
        e = actual - float(v)
        loss += max(t * e, (t - 1) * e)
    return loss / len(QUANTILES)


def earned_weights(
    losses: dict[str, list[float]], defaults: dict[str, float] | None = None
) -> dict[str, float]:
    """Defaults, nudged toward models with lower average loss once ≥ 10 tests exist:
    weight ∝ default × (best loss / own loss)²."""
    base = DEFAULT_WEIGHTS if defaults is None else defaults
    means = {k: float(np.mean(v)) for k, v in losses.items() if len(v) >= 10 and k in base}
    if len(means) < 2:
        return dict(base)
    best = min(means.values())
    raw = {
        k: base[k] * ((best / means[k]) ** 2 if k in means and means[k] > 0 else 1.0) for k in base
    }
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def _q_end(samples: F64) -> tuple[float, float]:
    """Median and 80% half-range of the horizon-end outcome."""
    q10, q50, q90 = np.quantile(samples[:, -1], [0.1, 0.5, 0.9])
    return float(q50), max(float(q90 - q10) / 2.0, 1e-9)


def forecast(
    close: F64,
    horizon: int = 10,
    *,
    peers: Sequence[F64] = (),
    tests: int = 50,
    every: int = 5,
    scores: F64 | None = None,
    news_tilt: float = 0.0,
    vol_scale: float = 1.0,
    memory: Memory | None = None,
) -> Forecast:
    """Forecast the next ``horizon`` candles of ``close`` (≥ 60 candles needed), with a
    walk-forward track record over the last ``tests`` × ``every`` candles. ``peers`` must
    end on the same candle as ``close`` (they widen the analogue search). ``scores`` is
    Kairos's score on every candle of ``close`` (adds the analyst model); ``news_tilt``
    (−1…+1) and ``vol_scale`` apply to today's forecast only (news has no history);
    ``memory`` holds what scored live forecasts taught."""
    c = np.asarray(close, dtype=np.float64)
    if len(c) < 60:
        raise ValueError("Kairos needs at least 60 candles to forecast.")
    horizon = max(1, min(int(horizon), 30))
    r = _log_returns(c)
    lib = AnalogueLibrary([r, *(_log_returns(p) for p in peers)], horizon)
    lib_or_none = None if lib.empty else lib
    analyst = (
        AnalystFit(r, np.asarray(scores, dtype=np.float64), horizon)
        if scores is not None and len(scores) == len(c)
        else None
    )
    defaults = WITH_ANALYST if analyst is not None else DEFAULT_WEIGHTS
    mem = memory or Memory()
    rng = np.random.default_rng(SEED)

    # Walk forward: forecast from past origins with only what was known then.
    losses: dict[str, list[float]] = {k: [] for k in defaults}
    misses: list[float] = []
    hits = n = in80 = in50 = 0
    err_model = err_naive = 0.0
    last_origin = len(r) - horizon
    origins = [
        o for o in range(last_origin - (tests - 1) * every, last_origin + 1, every) if o >= 120
    ]
    for o in origins:
        past = r[:o]
        actual = float(np.sum(r[o : o + horizon]))
        paths = _model_paths(past, lib_or_none, horizon, rng, analyst)
        w = earned_weights(losses, defaults)
        raw = _blend(paths, w, rng)
        width, bias = calibrate_from(misses)
        d = _dist(_apply(raw, width, bias))
        for k, p in paths.items():
            losses[k].append(_pinball(np.quantile(p, QUANTILES, axis=0), actual))
        med_raw, half_raw = _q_end(raw)
        misses.append((actual - med_raw) / half_raw)
        med = float(d.q[2, -1])
        if med != 0 and actual != 0:
            n += 1
            hits += int(np.sign(med) == np.sign(actual))
        err_model += abs(actual - med)
        err_naive += abs(actual)
        in80 += int(d.q[0, -1] <= actual <= d.q[4, -1])
        in50 += int(d.q[1, -1] <= actual <= d.q[3, -1])
    track = None
    if origins:
        track = TrackRecord(
            tests=n,
            direction_hits=hits,
            skill=1.0 - err_model / err_naive if err_naive > 0 else 0.0,
            band80=in80 / len(origins),
            band50=in50 / len(origins),
            model_loss={k: float(np.mean(v)) for k, v in losses.items() if v},
        )

    # Today's forecast: everything above plus what the live forecasts taught.
    for k, extra in mem.model_losses.items():
        if k in losses:
            losses[k].extend(list(extra) * LIVE_COPIES)
    live_misses = list(mem.misses)[-100:]
    all_misses = misses + live_misses * LIVE_COPIES
    tilt = 0.1 * float(np.clip(news_tilt, -1.0, 1.0))
    paths = _model_paths(r, lib_or_none, horizon, rng, analyst, tilt, vol_scale)
    weights = earned_weights(losses, defaults)
    raw = _blend(paths, weights, rng)
    width, bias = calibrate_from(all_misses)
    final = _apply(raw, width, bias)
    d = _dist(final)
    typical = final[int(np.argmin(np.sum((final - d.q[2][None, :]) ** 2, axis=1)))]
    med_raw, half_raw = _q_end(raw)
    coverage = float(np.mean(np.abs(all_misses) <= 1.0)) if all_misses else None
    origin = float(c[-1])
    medians = {k: float(100.0 * (np.exp(np.median(p[:, -1])) - 1.0)) for k, p in paths.items()}
    info: dict[str, float] = {}
    if analyst is not None:
        _, b, xo = analyst.drift(len(r), tilt)
        info = {"beta": round(b, 4), "score": round(100 * xo, 1), "news_tilt": round(tilt * 100, 1)}
    return Forecast(
        horizon=horizon,
        origin=origin,
        quantiles=origin * np.exp(d.q),
        up_probability=d.up,
        weights={k: round(v, 3) for k, v in _normalised(weights, paths).items()},
        model_medians={k: round(v, 2) for k, v in medians.items()},
        track=track,
        sigma=ewma_sigma(r) * vol_scale,
        calibration=Calibration(
            width=round(width, 3),
            bias=round(bias, 3),
            tests=len(misses),
            live=len(live_misses),
            coverage=None if coverage is None else round(coverage, 3),
        ),
        raw_median=med_raw,
        raw_half=half_raw,
        model_q={k: [float(x) for x in np.quantile(p[:, -1], QUANTILES)] for k, p in paths.items()},
        analyst=info,
        typical=np.asarray(typical, dtype=np.float64),
    )


def _normalised(weights: dict[str, float], paths: dict[str, F64]) -> dict[str, float]:
    use = {k: v for k, v in weights.items() if k in paths}
    total = sum(use.values()) or 1.0
    return {k: v / total for k, v in use.items()}


def expected_candles(
    f: Forecast,
    open_: F64,
    high: F64,
    low: F64,
    close: F64,
    future_ts: Sequence[int],
) -> list[dict[str, Any]]:
    """The predicted candles (KAIROS §17): closes follow the typical path (a real sampled
    path that stays closest to the middle of the forecast, so the candles have realistic
    bodies yet end near the most likely price; the plain middle path when there is none).
    Wick sizes come from this stock's last 60 candles, measured in units of the volatility
    of their time, applied to today's."""
    o, h, lo, c = (np.asarray(x[-61:], dtype=np.float64) for x in (open_, high, low, close))
    r = _log_returns(c)
    sd = float(np.std(r)) if len(r) > 2 else 0.0
    sd = sd if sd > 0 else max(f.sigma, 1e-4)
    top = np.maximum(o, c)
    bottom = np.minimum(o, c)
    with np.errstate(divide="ignore", invalid="ignore"):
        up = np.nanmedian(np.where(c > 0, (h - top) / c, np.nan)) / sd
        dn = np.nanmedian(np.where(c > 0, (bottom - lo) / c, np.nan)) / sd
    up = float(np.clip(np.nan_to_num(up, nan=0.4), 0.1, 2.0))
    dn = float(np.clip(np.nan_to_num(dn, nan=0.4), 0.1, 2.0))
    sig = max(f.sigma, 1e-6)
    out = []
    prev = f.origin
    for step in range(f.horizon):
        if step >= len(future_ts):
            break
        close_p = (
            f.origin * float(np.exp(f.typical[step]))
            if f.typical is not None and step < len(f.typical)
            else float(f.quantiles[2, step])
        )
        open_p = prev
        hi = max(open_p, close_p) * (1.0 + up * sig)
        lo_p = min(open_p, close_p) * (1.0 - dn * sig)
        body = (close_p / open_p - 1.0) if open_p else 0.0
        out.append(
            {
                "ts": int(future_ts[step]),
                "open": round(open_p, 4),
                "high": round(hi, 4),
                "low": round(lo_p, 4),
                "close": round(close_p, 4),
                "p10": round(float(f.quantiles[0, step]), 4),
                "p90": round(float(f.quantiles[4, step]), 4),
                # a body under a tenth of a typical move is "flat": no direction claimed
                "direction": 0 if abs(body) < 0.1 * sig else (1 if body > 0 else -1),
            }
        )
        prev = close_p
    return out


def calibration_words(cal: Calibration) -> str:
    """What past misses changed, in one sentence."""
    if cal.tests + cal.live < 8:
        return "Not enough past forecasts yet to learn from their misses."
    held = "" if cal.coverage is None else f"held the price {cal.coverage * 100:.0f}% of the time"
    parts = []
    if cal.width >= 1.05:
        parts.append(f"widened them by {(cal.width - 1) * 100:.0f}%")
    elif cal.width <= 0.95:
        parts.append(f"narrowed them by {(1 - cal.width) * 100:.0f}%")
    if cal.bias >= 0.1:
        parts.append("leaned the middle higher (past forecasts were too low)")
    elif cal.bias <= -0.1:
        parts.append("leaned the middle lower (past forecasts were too high)")
    src = f"{cal.tests} tested forecasts" + (f" and {cal.live} live ones" if cal.live else "")
    if not parts:
        return f"From {src}: the raw 8-in-10 ranges {held}, close to the aim, so no correction."
    return (
        f"From {src}: the raw 8-in-10 ranges {held} (aim 80%), so Kairos "
        + " and ".join(parts)
        + "."
    )


def _span_words(horizon: int, minutes: int) -> str:
    if minutes >= 1440:
        return f"{horizon} trading days"
    total = horizon * minutes
    span = f"{total // 60} hour{'s' if total >= 120 else ''}" if total >= 60 else f"{total} minutes"
    return f"{horizon} candles (about {span} of trading)"


def describe(
    f: Forecast, *, symbol: str, money: Callable[[float], str], minutes: int
) -> dict[str, Any]:
    """Plain-English text and the honest verdict on the track record."""
    lo, mid, hi = f.quantiles[0, -1], f.quantiles[2, -1], f.quantiles[4, -1]
    span = _span_words(f.horizon, minutes)
    text = (
        f"Over the next {span}, {symbol} will most likely be between {money(lo)} and "
        f"{money(hi)} (an 8-in-10 range), with the middle of the range at {money(mid)}. "
        f"Chance of ending higher than today: {f.up_probability * 100:.0f}%."
    )
    verdict = "Not enough history to test these forecasts yet."
    t = f.track
    if t is not None and t.tests >= 10:
        rate = t.direction_rate * 100
        edge = t.direction_rate >= 0.55 and t.skill > 0.02
        if edge:
            verdict = (
                f"Tested {t.tests} times on {symbol}: the direction was right {t.direction_hits} "
                f"times ({rate:.0f}%; a coin flip gets about 50%). A small edge, never a promise."
            )
        else:
            verdict = (
                f"Tested {t.tests} times on {symbol}: the direction was right {t.direction_hits} "
                f"times ({rate:.0f}%), no better than a coin flip, so read this as a range, not a "
                f"prediction."
            )
        verdict += f" The 8-in-10 range held the outcome {t.band80 * 100:.0f}% of the time."
    return {
        "text": text,
        "verdict": verdict,
        "edge": bool(t and t.tests >= 10 and t.direction_rate >= 0.55 and t.skill > 0.02),
    }


def to_json(f: Forecast, future_ts: Sequence[int], origin_ts: int) -> dict[str, Any]:
    names = ("p10", "p25", "median", "p75", "p90")
    path = [{"ts": int(origin_ts), **{n: round(f.origin, 4) for n in names}}]
    for h in range(f.horizon):
        if h >= len(future_ts):
            break
        path.append(
            {
                "ts": int(future_ts[h]),
                **{n: round(float(f.quantiles[j, h]), 4) for j, n in enumerate(names)},
            }
        )
    t = f.track
    cal = f.calibration
    return {
        "calibration": {
            "width": cal.width,
            "bias": cal.bias,
            "tests": cal.tests,
            "live": cal.live,
            "coverage": cal.coverage,
            "text": calibration_words(cal),
        },
        "analyst": f.analyst or None,
        "horizon": f.horizon,
        "origin": round(f.origin, 4),
        "path": path,
        "up_probability": round(f.up_probability, 3),
        "median_change_pct": round(100.0 * (f.quantiles[2, -1] / f.origin - 1.0), 2),
        "range80_pct": [
            round(100.0 * (f.quantiles[0, -1] / f.origin - 1.0), 2),
            round(100.0 * (f.quantiles[4, -1] / f.origin - 1.0), 2),
        ],
        "weights": f.weights,
        "model_medians_pct": f.model_medians,
        "track": None
        if t is None
        else {
            "tests": t.tests,
            "direction_hits": t.direction_hits,
            "direction_rate": round(t.direction_rate, 3),
            "skill_pct": round(100.0 * t.skill, 1),
            "band80": round(t.band80, 3),
            "band50": round(t.band50, 3),
        },
    }
