"""Every indicator's own signal, classic strategy entries and quant signals (D-138).

``signals.py`` reads charts the way a chart reader does (patterns, levels, trendlines, candles,
divergences, RSI and MACD). The user asked on 2026-10-28 that Kairos also trade on *all* the
indicators, the classic strategies and quant. Each rule below is the textbook signal of one
indicator or strategy, flagged on the candle whose close completes it, from that candle and
earlier ones only (no look-ahead: the Ichimoku lagging span, fractals and the centred DPO are
left out for that reason). Kairos doesn't take them on trust: training measures how often each
one was right on the market's history and every desk trade updates that record, so the learned
weight (0 … 2) keeps the ones that work and switches off the ones that don't (``learning.py``).

- ``momentum``: oscillators leaving extremes or crossing their signal lines (momentum part);
- ``trend``: trend indicators flipping (Supertrend, SAR, ADX/DI, Ichimoku, Aroon, …; trend part);
- ``volume``: volume indicators turning (OBV, money flow, force, ease of movement; volume part);
- ``strategy``: classic strategies' entries (Turtle, Connors RSI-2, Bollinger reversion, VWAP,
  opening range, …; patterns part);
- ``quant``: statistical signals (z-score snap-back, 12-1 momentum, regression fit, volatility
  breakout; momentum part).

The brain hears them as a chorus whose agreement moves each part of its score a bounded amount
(``brain.decide``), so adding indicators adds evidence, not loudness.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from backend.indicators import vector as vx
from backend.indicators import vector_extra as vxe
from backend.indicators import vector_world as vw
from backend.indicators.series import F64, BarSeries

# How strongly each family votes in the brain's chorus (``brain.decide``): a classic strategy's
# entry is a fuller signal than one oscillator crossing; what each is worth is then learned.
STRENGTH = {"momentum": 0.8, "trend": 0.8, "volume": 0.8, "strategy": 1.0, "quant": 0.8}

Idx = np.ndarray
Rule = Callable[[BarSeries], tuple[Idx, Idx]]


def _up(a: F64, b: F64 | float) -> Idx:
    """Candles where ``a`` closes above ``b`` having been at or below it the candle before."""
    a = np.asarray(a, dtype=np.float64)
    bb = np.broadcast_to(np.asarray(b, dtype=np.float64), a.shape)
    if len(a) < 2:
        return np.array([], dtype=np.int64)
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(a[1:]) & np.isfinite(a[:-1]) & np.isfinite(bb[1:]) & np.isfinite(bb[:-1])
        hit = ok & (a[1:] > bb[1:]) & (a[:-1] <= bb[:-1])
    return np.flatnonzero(hit) + 1


def _down(a: F64, b: F64 | float) -> Idx:
    return _up(-np.asarray(a, dtype=np.float64), -np.asarray(b, dtype=np.float64))


def _shift(x: F64, k: int = 1) -> F64:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _where(idx: Idx, cond: np.ndarray) -> Idx:
    return idx[cond[idx]] if len(idx) else idx


def _has_volume(s: BarSeries) -> bool:
    return bool(np.nansum(s.volume) > 0)


def _pair(a: F64, b: F64) -> tuple[Idx, Idx]:
    return _up(a, b), _down(a, b)


# ---------------------------------------------------------------- oscillators (momentum)


def _stochastic(s: BarSeries) -> tuple[Idx, Idx]:
    k, d = vx.stochastic(s.high, s.low, s.close)
    k_prev = _shift(k)
    with np.errstate(invalid="ignore"):
        return _where(_up(k, d), k_prev < 20), _where(_down(k, d), k_prev > 80)


def _stoch_rsi(s: BarSeries) -> tuple[Idx, Idx]:
    k, _ = vxe.stoch_rsi(s.close)
    return _up(k, 20.0), _down(k, 80.0)


def _cci(s: BarSeries) -> tuple[Idx, Idx]:
    x = vx.cci(s.high, s.low, s.close)
    return _up(x, -100.0), _down(x, 100.0)


def _williams(s: BarSeries) -> tuple[Idx, Idx]:
    x = vxe.williams_r(s.high, s.low, s.close)
    return _up(x, -80.0), _down(x, -20.0)


def _mfi(s: BarSeries) -> tuple[Idx, Idx]:
    if not _has_volume(s):
        return _none()
    x = vxe.mfi(s.high, s.low, s.close, s.volume)
    return _up(x, 20.0), _down(x, 80.0)


def _roc(s: BarSeries) -> tuple[Idx, Idx]:
    x = vx.roc(s.close)
    return _up(x, 0.0), _down(x, 0.0)


def _cmo(s: BarSeries) -> tuple[Idx, Idx]:
    x = vw.cmo(s.close)
    return _up(x, -50.0), _down(x, 50.0)


def _ultimate(s: BarSeries) -> tuple[Idx, Idx]:
    x = vw.ultimate(s.high, s.low, s.close)
    return _up(x, 30.0), _down(x, 70.0)


def _awesome(s: BarSeries) -> tuple[Idx, Idx]:
    ao, _ = vw.awesome(s.high, s.low)
    return _up(ao, 0.0), _down(ao, 0.0)


def _coppock(s: BarSeries) -> tuple[Idx, Idx]:
    x = vw.coppock(s.close)
    return _up(x, 0.0), _down(x, 0.0)


def _stc(s: BarSeries) -> tuple[Idx, Idx]:
    x = vw.stc(s.close)
    return _up(x, 25.0), _down(x, 75.0)


def _connors(s: BarSeries) -> tuple[Idx, Idx]:
    x = vw.connors_rsi(s.close)
    return _down(x, 10.0), _up(x, 90.0)  # a deep dip is a buy, a spike a sell (mean reversion)


def _wavetrend(s: BarSeries) -> tuple[Idx, Idx]:
    w1, w2 = vw.wavetrend(s.high, s.low, s.close)
    with np.errstate(invalid="ignore"):
        return _where(_up(w1, w2), w1 < -53), _where(_down(w1, w2), w1 > 53)


def _smi(s: BarSeries) -> tuple[Idx, Idx]:
    x, sig_ = vw.smi(s.high, s.low, s.close)
    with np.errstate(invalid="ignore"):
        return _where(_up(x, sig_), x < -40), _where(_down(x, sig_), x > 40)


def _signal_cross(fn: Callable[[BarSeries], tuple[F64, F64]]) -> Rule:
    def rule(s: BarSeries) -> tuple[Idx, Idx]:
        a, b = fn(s)
        return _pair(a, b)

    return rule


# ---------------------------------------------------------------- trend indicators


def _supertrend(s: BarSeries) -> tuple[Idx, Idx]:
    _, direction = vx.supertrend(s.high, s.low, s.close)
    return _up(direction, 0.0), _down(direction, 0.0)


def _psar(s: BarSeries) -> tuple[Idx, Idx]:
    sar = vxe.psar(s.high, s.low, s.close)
    return _up(s.close, sar), _down(s.close, sar)


def _adx(s: BarSeries) -> tuple[Idx, Idx]:
    strength, plus, minus = vx.adx(s.high, s.low, s.close)
    with np.errstate(invalid="ignore"):
        strong = strength > 20
    return _where(_up(plus, minus), strong), _where(_down(plus, minus), strong)


def _cloud(s: BarSeries) -> tuple[Idx, Idx]:
    _, _, a, b = vxe.ichimoku(s.high, s.low)
    return _up(s.close, np.fmax(a, b)), _down(s.close, np.fmin(a, b))


def _tk(s: BarSeries) -> tuple[Idx, Idx]:
    tenkan, kijun, _, _ = vxe.ichimoku(s.high, s.low)
    return _pair(tenkan, kijun)


def _aroon(s: BarSeries) -> tuple[Idx, Idx]:
    up, down, _ = vxe.aroon(s.high, s.low)
    return _pair(up, down)


def _vortex(s: BarSeries) -> tuple[Idx, Idx]:
    plus, minus = vw.vortex(s.high, s.low, s.close)
    return _pair(plus, minus)


def _ema_cross(s: BarSeries) -> tuple[Idx, Idx]:
    return _pair(vx.ema(s.close, 9), vx.ema(s.close, 21))


def _sma200(s: BarSeries) -> tuple[Idx, Idx]:
    return _pair(s.close, vx.sma(s.close, 200))


def _kama(s: BarSeries) -> tuple[Idx, Idx]:
    return _pair(s.close, vxe.kama(s.close))


def _hma_turn(s: BarSeries) -> tuple[Idx, Idx]:
    h = vxe.hma(s.close, 20)
    slope = h - _shift(h)
    return _up(slope, 0.0), _down(slope, 0.0)


def _heikin(s: BarSeries) -> tuple[Idx, Idx]:
    c, o, _, _ = vw.heikin_ashi(s.open, s.high, s.low, s.close)
    colour = np.sign(c - o)
    return _up(colour, 0.0), _down(colour, 0.0)


def _impulse(s: BarSeries) -> tuple[Idx, Idx]:
    x = vw.elder_impulse(s.close)
    return _up(x, 0.5), _down(x, -0.5)


# ---------------------------------------------------------------- volume indicators


def _volume_rule(fn: Callable[[BarSeries], F64]) -> Rule:
    def rule(s: BarSeries) -> tuple[Idx, Idx]:
        if not _has_volume(s):
            return _none()
        x = fn(s)
        return _up(x, 0.0), _down(x, 0.0)

    return rule


def _obv(s: BarSeries) -> tuple[Idx, Idx]:
    if not _has_volume(s):
        return _none()
    x = vx.obv(s.close, s.volume)
    return _up(x, _shift(vx.rolling_max(x, 20))), _down(x, _shift(vx.rolling_min(x, 20)))


def _klinger(s: BarSeries) -> tuple[Idx, Idx]:
    if not _has_volume(s):
        return _none()
    k, sig_ = vw.klinger(s.high, s.low, s.close, s.volume)
    return _pair(k, sig_)


# ---------------------------------------------------------------- classic strategies


def _turtle(s: BarSeries) -> tuple[Idx, Idx]:
    """Turtle system 1 (Dennis, Eckhardt): a close beyond the last 20 candles' high (low)."""
    hi = _shift(vx.rolling_max(s.high, 20))
    lo = _shift(vx.rolling_min(s.low, 20))
    return _up(s.close, hi), _down(s.close, lo)


def _rsi2(s: BarSeries) -> tuple[Idx, Idx]:
    """Connors' RSI-2: a dip below 10 in a long uptrend, a pop above 90 in a downtrend."""
    r = vx.rsi(s.close, 2)
    long_ma = vx.sma(s.close, 200)
    with np.errstate(invalid="ignore"):
        return _where(_down(r, 10.0), s.close > long_ma), _where(_up(r, 90.0), s.close < long_ma)


def _bollinger_reversion(s: BarSeries) -> tuple[Idx, Idx]:
    """Back inside the Bollinger Bands after closing outside them (mean reversion)."""
    _, upper, lower = vx.bollinger(s.close)
    return _up(s.close, lower), _down(s.close, upper)


def _pullback(s: BarSeries) -> tuple[Idx, Idx]:
    """Buy the first dip to the 20 EMA in an uptrend (50 above 200), and the mirror image."""
    c = s.close
    e20, m50, m200 = vx.ema(c, 20), vx.sma(c, 50), vx.sma(c, 200)
    with np.errstate(invalid="ignore"):
        up_trend = (c > m50) & (m50 > m200)
        down_trend = (c < m50) & (m50 < m200)
        dip = up_trend & (s.low <= e20) & (c > e20)
        rally = down_trend & (s.high >= e20) & (c < e20)
    first_dip = dip & ~np.concatenate(([False], dip[:-1]))
    first_rally = rally & ~np.concatenate(([False], rally[:-1]))
    return np.flatnonzero(first_dip), np.flatnonzero(first_rally)


def _macd_zero(s: BarSeries) -> tuple[Idx, Idx]:
    line, _, _ = vx.macd(s.close)
    return _up(line, 0.0), _down(line, 0.0)


def _vwap(s: BarSeries) -> tuple[Idx, Idx]:
    """Intraday: the price reclaims (loses) the session's volume-weighted average price."""
    if not s.timeframe.is_intraday or not _has_volume(s):
        return _none()
    x = vx.vwap(s.high, s.low, s.close, s.volume, s.session)
    return _pair(s.close, x)


def _orb(s: BarSeries) -> tuple[Idx, Idx]:
    """Intraday: a close beyond the first 15 minutes' range (opening range breakout)."""
    if not s.timeframe.is_intraday:
        return _none()
    hi, lo = vx.opening_range(
        s.high, s.low, s.ts, s.session, s.session_open, s.timeframe.minutes, 15
    )
    return _up(s.close, hi), _down(s.close, lo)


# ---------------------------------------------------------------- quant


def _zscore(s: BarSeries) -> tuple[Idx, Idx]:
    """Back within two standard deviations of the 20-candle mean (statistical snap-back)."""
    z = vw.zscore(s.close, 20)
    return _up(z, -2.0), _down(z, 2.0)


def _momentum_12_1(s: BarSeries) -> tuple[Idx, Idx]:
    """The 12-1 momentum factor (Jegadeesh & Titman): the return from 252 to 21 candles ago
    turns positive (negative)."""
    c = s.close
    ret = _shift(c, 21) / _shift(c, 252) - 1.0
    return _up(ret, 0.0), _down(ret, 0.0)


def _fit(s: BarSeries) -> tuple[Idx, Idx]:
    """A clean straight-line trend appears: the 50-candle regression's R² rises above 0.7."""
    _, slope, r2 = vw.linreg(s.close, 50)
    crossed = _up(r2, 0.7)
    with np.errstate(invalid="ignore"):
        return _where(crossed, slope > 0), _where(crossed, slope < 0)


def _vol_breakout(s: BarSeries) -> tuple[Idx, Idx]:
    """Volatility contraction, then expansion: the 20-candle volatility sat at its lowest of
    120 candles within the last 5, and the price closes beyond its 20-candle range."""
    vol = vw.hv(s.close, 20)
    with np.errstate(invalid="ignore"):
        quiet = vol <= 1.05 * vx.rolling_min(vol, 120)
    was_quiet = np.nan_to_num(quiet.astype(np.float64))
    recent = vx.rolling_max(was_quiet, 5) > 0
    up, down = _turtle(s)
    return _where(up, recent), _where(down, recent)


def _none() -> tuple[Idx, Idx]:
    return np.array([], dtype=np.int64), np.array([], dtype=np.int64)


# key → (rule, bullish label, bearish label)
RULES: dict[str, tuple[Rule, str, str]] = {
    "momentum:stochastic": (
        _stochastic,
        "Stochastic crossed up from oversold",
        "Stochastic crossed down from overbought",
    ),
    "momentum:stoch_rsi": (
        _stoch_rsi,
        "Stochastic RSI climbed back above 20",
        "Stochastic RSI dropped back below 80",
    ),
    "momentum:cci": (_cci, "CCI climbed back above −100", "CCI dropped back below +100"),
    "momentum:williams_r": (
        _williams,
        "Williams %R left oversold",
        "Williams %R left overbought",
    ),
    "momentum:mfi": (_mfi, "Money flow index left oversold", "Money flow index left overbought"),
    "momentum:roc": (_roc, "Rate of change turned positive", "Rate of change turned negative"),
    "momentum:cmo": (_cmo, "Chande momentum left oversold", "Chande momentum left overbought"),
    "momentum:ultimate": (
        _ultimate,
        "Ultimate oscillator climbed above 30",
        "Ultimate oscillator dropped below 70",
    ),
    "momentum:awesome": (
        _awesome,
        "Awesome oscillator crossed above zero",
        "Awesome oscillator crossed below zero",
    ),
    "momentum:coppock": (
        _coppock,
        "Coppock curve turned positive",
        "Coppock curve turned negative",
    ),
    "momentum:stc": (_stc, "Schaff trend cycle turned up", "Schaff trend cycle turned down"),
    "momentum:connors_rsi": (
        _connors,
        "Connors RSI fell into a deep dip",
        "Connors RSI spiked to an extreme",
    ),
    "momentum:wavetrend": (
        _wavetrend,
        "WaveTrend crossed up from oversold",
        "WaveTrend crossed down from overbought",
    ),
    "momentum:smi": (
        _smi,
        "Stochastic momentum index crossed up from oversold",
        "Stochastic momentum index crossed down from overbought",
    ),
    "momentum:trix": (
        _signal_cross(lambda s: vw.trix(s.close)),
        "TRIX crossed above its signal line",
        "TRIX crossed below its signal line",
    ),
    "momentum:tsi": (
        _signal_cross(lambda s: vw.tsi(s.close)),
        "True strength index crossed above its signal line",
        "True strength index crossed below its signal line",
    ),
    "momentum:kst": (
        _signal_cross(lambda s: vw.kst(s.close)),
        "Know Sure Thing crossed above its signal line",
        "Know Sure Thing crossed below its signal line",
    ),
    "momentum:fisher": (
        _signal_cross(lambda s: vw.fisher(s.high, s.low)),
        "Fisher transform crossed up",
        "Fisher transform crossed down",
    ),
    "momentum:rvi": (
        _signal_cross(lambda s: vw.rvi(s.open, s.high, s.low, s.close)),
        "Relative vigor crossed above its signal line",
        "Relative vigor crossed below its signal line",
    ),
    "trend:supertrend": (_supertrend, "Supertrend turned up", "Supertrend turned down"),
    "trend:psar": (_psar, "Parabolic SAR flipped below the price", "Parabolic SAR flipped above"),
    "trend:adx": (_adx, "+DI crossed above −DI in a trending market", "−DI crossed above +DI"),
    "trend:ichimoku_cloud": (
        _cloud,
        "Closed above the Ichimoku cloud",
        "Closed below the Ichimoku cloud",
    ),
    "trend:ichimoku_tk": (
        _tk,
        "Ichimoku conversion line crossed above the base line",
        "Ichimoku conversion line crossed below the base line",
    ),
    "trend:aroon": (_aroon, "Aroon up crossed above Aroon down", "Aroon down crossed above up"),
    "trend:vortex": (_vortex, "Vortex turned up (VI+ above VI−)", "Vortex turned down"),
    "trend:ema_9_21": (_ema_cross, "The 9 EMA crossed above the 21 EMA", "The 9 EMA crossed below"),
    "trend:sma200": (
        _sma200,
        "Closed above the 200-candle average",
        "Closed below the 200-candle average",
    ),
    "trend:kama": (_kama, "Closed above Kaufman's adaptive average", "Closed below Kaufman's"),
    "trend:hma": (_hma_turn, "The Hull average turned up", "The Hull average turned down"),
    "trend:heikin_ashi": (_heikin, "Heikin-Ashi candles turned up", "Heikin-Ashi turned down"),
    "trend:elder_impulse": (_impulse, "Elder impulse turned green", "Elder impulse turned red"),
    "volume:obv": (_obv, "On-balance volume made a 20-candle high", "OBV made a 20-candle low"),
    "volume:cmf": (
        _volume_rule(lambda s: vxe.cmf(s.high, s.low, s.close, s.volume)),
        "Chaikin money flow turned positive",
        "Chaikin money flow turned negative",
    ),
    "volume:chaikin_osc": (
        _volume_rule(lambda s: vw.chaikin_osc(s.high, s.low, s.close, s.volume)),
        "Chaikin oscillator crossed above zero",
        "Chaikin oscillator crossed below zero",
    ),
    "volume:force_index": (
        _volume_rule(lambda s: vw.force_index(s.close, s.volume)),
        "Force index turned positive",
        "Force index turned negative",
    ),
    "volume:eom": (
        _volume_rule(lambda s: vw.eom(s.high, s.low, s.volume)),
        "Ease of movement turned positive",
        "Ease of movement turned negative",
    ),
    "volume:klinger": (
        _klinger,
        "Klinger oscillator crossed above its signal",
        "Klinger oscillator crossed below its signal",
    ),
    "strategy:turtle": (
        _turtle,
        "Turtle breakout: closed above the 20-candle high",
        "Turtle breakdown: closed below the 20-candle low",
    ),
    "strategy:rsi2": (
        _rsi2,
        "Connors RSI-2 dip in an uptrend",
        "Connors RSI-2 pop in a downtrend",
    ),
    "strategy:bollinger_reversion": (
        _bollinger_reversion,
        "Back inside the lower Bollinger Band",
        "Back inside the upper Bollinger Band",
    ),
    "strategy:pullback": (
        _pullback,
        "First pullback to the 20 EMA in an uptrend",
        "First rally to the 20 EMA in a downtrend",
    ),
    "strategy:macd_zero": (_macd_zero, "MACD crossed above zero", "MACD crossed below zero"),
    "strategy:vwap": (_vwap, "Reclaimed the day's VWAP", "Lost the day's VWAP"),
    "strategy:opening_range": (
        _orb,
        "Opening range breakout",
        "Opening range breakdown",
    ),
    "quant:zscore": (
        _zscore,
        "Snapped back from 2 standard deviations below the mean",
        "Snapped back from 2 standard deviations above the mean",
    ),
    "quant:momentum_12_1": (
        _momentum_12_1,
        "12-1 momentum turned positive",
        "12-1 momentum turned negative",
    ),
    "quant:fit": (_fit, "A clean straight-line uptrend formed", "A clean downtrend formed"),
    "quant:vol_breakout": (
        _vol_breakout,
        "Broke out up after a volatility squeeze",
        "Broke down after a volatility squeeze",
    ),
}

# every key this module can produce → (label, direction)
INFO: dict[str, tuple[str, int]] = {}
for _key, (_rule, _bull, _bear) in RULES.items():
    INFO[f"{_key}:up"] = (_bull, 1)
    INFO[f"{_key}:down"] = (_bear, -1)


def detect(series: BarSeries) -> list[tuple[str, int, int]]:
    """Every signal in the series as (key, candle index, direction), in no particular order."""
    out: list[tuple[str, int, int]] = []
    for key, (rule, _, _) in RULES.items():
        up, down = rule(series)
        out += [(f"{key}:up", int(i), 1) for i in up]
        out += [(f"{key}:down", int(i), -1) for i in down]
    return out
