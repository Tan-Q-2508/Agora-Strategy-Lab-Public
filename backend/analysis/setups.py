"""Setups: the price events traders scan for every day (Phase 10.3).

Each is a rule on the last few candles that a scanner would flag on that candle's close.
Bulkowski calls the gap and reversal ones "event patterns"; the rest are well-known named
setups. Every flag at candle ``i`` uses candles up to ``i`` only.

| Key | Bias | Rule (on candle i) | Known from |
|---|---|---|---|
| ``breakaway_gap_up`` / ``_down`` | ± | the whole candle gaps beyond yesterday's range *and* closes beyond the last 20 candles' range, on 1.5× average volume (when there is volume) | Edwards & Magee |
| ``island_top`` / ``island_bottom`` | ∓ | a gap up (down), 1–10 candles, then a gap down (up) that leaves them stranded | Edwards & Magee, Bulkowski |
| ``nr7_up`` / ``nr7_down`` | ± | yesterday had the narrowest range of the last 7 candles; today closes beyond its high (low) | Toby Crabel |
| ``inside_break_up`` / ``_down`` | ± | yesterday was an inside candle; today closes beyond the mother candle's high (low) | — |
| ``spring`` / ``upthrust`` | ± | today trades below (above) the 20-candle low (high), set at least 4 candles ago, then closes back inside: a false break | Wyckoff; Connors' "turtle soup" |
| ``key_reversal_up`` / ``_down`` | ± | a new 10-candle low (high), then a close beyond yesterday's close in the top (bottom) half of the candle | — |
| ``pocket_pivot`` | + | an up close above the 10-candle average on more volume than any down day of the last 10 | Morales & Kacher |
| ``new_high_52w`` / ``new_low_52w`` | ± | the first close beyond the previous 252 candles' extreme in 20 candles | O'Neil, George & Hwang |
| ``golden_cross`` / ``death_cross`` | ± | the 50-candle SMA crosses the 200-candle SMA | — |
| ``squeeze_up`` / ``squeeze_down`` | ± | yesterday the Bollinger Bands (20, 2) sat inside the Keltner Channel (20, 1.5 ATR); today closes outside the upper (lower) band | John Carter |
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backend.indicators import vector as vx
from backend.indicators.series import F64

B = NDArray[np.bool_]


@dataclass(frozen=True)
class SetupInfo:
    key: str
    name: str
    bias: int  # +1 bullish, −1 bearish
    meaning: str


INFO: dict[str, SetupInfo] = {
    s.key: s
    for s in (
        SetupInfo(
            "breakaway_gap_up",
            "Breakaway gap up",
            1,
            "A gap up out of a range on heavy volume: often the start of a new move, and the gap tends not to fill.",
        ),
        SetupInfo(
            "breakaway_gap_down",
            "Breakaway gap down",
            -1,
            "A gap down out of a range on heavy volume: often the start of a new decline.",
        ),
        SetupInfo(
            "island_top",
            "Island top",
            -1,
            "A gap up, a few candles, then a gap down: buyers left stranded on an island above.",
        ),
        SetupInfo(
            "island_bottom",
            "Island bottom",
            1,
            "A gap down, a few candles, then a gap up: sellers left stranded below.",
        ),
        SetupInfo(
            "nr7_up",
            "NR7 breakout up",
            1,
            "The quietest candle of the week, then a close above it: a volatility expansion upward (Crabel).",
        ),
        SetupInfo(
            "nr7_down",
            "NR7 breakout down",
            -1,
            "The quietest candle of the week, then a close below it: a volatility expansion downward.",
        ),
        SetupInfo(
            "inside_break_up",
            "Inside-bar breakout up",
            1,
            "After an inside candle, a close above the candle that contained it.",
        ),
        SetupInfo(
            "inside_break_down",
            "Inside-bar breakout down",
            -1,
            "After an inside candle, a close below the candle that contained it.",
        ),
        SetupInfo(
            "spring",
            "Spring (false breakdown)",
            1,
            "A dip below the recent low that closes back above it: sellers trapped (Wyckoff's spring, Connors' turtle soup).",
        ),
        SetupInfo(
            "upthrust",
            "Upthrust (false breakout)",
            -1,
            "A poke above the recent high that closes back below it: buyers trapped.",
        ),
        SetupInfo(
            "key_reversal_up",
            "Bullish key reversal",
            1,
            "A new low, then a strong close above the previous close: a one-day turn.",
        ),
        SetupInfo(
            "key_reversal_down",
            "Bearish key reversal",
            -1,
            "A new high, then a weak close below the previous close: a one-day turn.",
        ),
        SetupInfo(
            "pocket_pivot",
            "Pocket pivot",
            1,
            "An up day above the 10-day average on more volume than any recent down day: institutional buying (Morales & Kacher).",
        ),
        SetupInfo(
            "new_high_52w",
            "New 52-week high",
            1,
            "The first close above the past year's high in a month: momentum stocks tend to keep leading.",
        ),
        SetupInfo(
            "new_low_52w",
            "New 52-week low",
            -1,
            "The first close below the past year's low in a month: weak stocks tend to stay weak.",
        ),
        SetupInfo(
            "golden_cross",
            "Golden cross",
            1,
            "The 50-day average crossed above the 200-day: a long-term trend turning up (slow, often late).",
        ),
        SetupInfo(
            "death_cross",
            "Death cross",
            -1,
            "The 50-day average crossed below the 200-day: a long-term trend turning down (slow, often late).",
        ),
        SetupInfo(
            "squeeze_up",
            "Squeeze breakout up",
            1,
            "Volatility was coiled (Bollinger inside Keltner) and the price broke out upward (Carter's squeeze).",
        ),
        SetupInfo(
            "squeeze_down",
            "Squeeze breakout down",
            -1,
            "Volatility was coiled and the price broke out downward.",
        ),
    )
}


def _shift(x: F64, k: int = 1) -> F64:
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def _prev_max(x: F64, n: int) -> F64:
    """Highest of the previous ``n`` values (excluding today)."""
    return _shift(vx.rolling_max(x, n), 1)


def _prev_min(x: F64, n: int) -> F64:
    return _shift(vx.rolling_min(x, n), 1)


def _first_in(flags: B, n: int) -> B:
    """Only the first flag in any ``n`` candles (so a run of new highs is one event)."""
    out = np.zeros(len(flags), dtype=bool)
    last = -(10**9)
    for i in np.flatnonzero(flags):
        if i - last > n:
            out[i] = True
        last = int(i)
    return out


def detect(o: F64, h: F64, lo: F64, c: F64, v: F64) -> dict[str, B]:
    """A boolean array per setup: True on the candle a scanner would flag it."""
    n = len(c)
    ph, pl, pc = _shift(h), _shift(lo), _shift(c)
    rng = h - lo
    has_vol = np.nansum(v) > 0
    with np.errstate(invalid="ignore"):
        avg_v = _shift(vx.sma(v, 20))
        heavy = (v >= 1.5 * avg_v) if has_vol else np.ones(n, dtype=bool)
        out: dict[str, B] = {
            "breakaway_gap_up": (lo > ph) & (c > _prev_max(h, 20)) & heavy,
            "breakaway_gap_down": (h < pl) & (c < _prev_min(lo, 20)) & heavy,
        }
        # NR7: yesterday's range the narrowest of the 7 candles ending yesterday
        nr7 = _shift(rng) <= _shift(vx.rolling_min(rng, 7))
        out["nr7_up"] = nr7 & (c > ph)
        out["nr7_down"] = nr7 & (c < pl)
        inside_y = (ph < _shift(h, 2)) & (pl > _shift(lo, 2))
        out["inside_break_up"] = inside_y & (c > _shift(h, 2))
        out["inside_break_down"] = inside_y & (c < _shift(lo, 2))
        lo20, hi20 = _prev_min(lo, 20), _prev_max(h, 20)
        # the extreme must be at least 4 candles old (Connors): not inside the last 3
        lo_old = lo20 < _prev_min(lo, 3)
        hi_old = hi20 > _prev_max(h, 3)
        out["spring"] = (lo < lo20) & (c > lo20) & lo_old
        out["upthrust"] = (h > hi20) & (c < hi20) & hi_old
        top_half = c >= (h + lo) / 2.0
        out["key_reversal_up"] = (lo < _prev_min(lo, 10)) & (c > pc) & top_half
        out["key_reversal_down"] = (h > _prev_max(h, 10)) & (c < pc) & ~top_half
        down_v = np.where(c < pc, v, 0.0)
        out["pocket_pivot"] = (
            (c > pc) & (c >= vx.sma(c, 10)) & (v > _prev_max(down_v, 10)) & has_vol
        )
        out["new_high_52w"] = _first_in(c > _prev_max(h, 252), 20)
        out["new_low_52w"] = _first_in(c < _prev_min(lo, 252), 20)
        s50, s200 = vx.sma(c, 50), vx.sma(c, 200)
        diff, pdiff = s50 - s200, _shift(s50 - s200)
        out["golden_cross"] = (diff > 0) & (pdiff <= 0)
        out["death_cross"] = (diff < 0) & (pdiff >= 0)
        _, bb_up, bb_dn = vx.bollinger(c, 20, 2.0)
        km, a = vx.ema(c, 20), vx.atr(h, lo, c, 20)
        squeezed = _shift(((bb_up < km + 1.5 * a) & (bb_dn > km - 1.5 * a)).astype(float)) > 0
        out["squeeze_up"] = squeezed & (c > bb_up)
        out["squeeze_down"] = squeezed & (c < bb_dn)
    out.update(_islands(h, lo))
    return {k: np.asarray(x, dtype=bool) for k, x in out.items()}


def _islands(h: F64, lo: F64, longest: int = 10) -> dict[str, B]:
    """A gap one way at candle j, 1-``longest`` candles, then a gap the other way at i that
    clears every candle since j (the island)."""
    n = len(h)
    top = np.zeros(n, dtype=bool)
    bottom = np.zeros(n, dtype=bool)
    for i in range(2, n):
        for j in range(max(1, i - longest), i):
            isl_lo, isl_hi = float(lo[j:i].min()), float(h[j:i].max())
            if lo[j] > h[j - 1] and h[i] < isl_lo and isl_lo > h[j - 1]:
                top[i] = True
            if h[j] < lo[j - 1] and lo[i] > isl_hi and isl_hi < lo[j - 1]:
                bottom[i] = True
    return {"island_top": top, "island_bottom": bottom}


def stop_for(key: str, i: int, h: F64, lo: F64) -> float | None:
    """Where the setup is proved wrong: beyond the candle that triggered it (for gaps and
    islands, beyond the gap)."""
    info = INFO[key]
    if key.startswith("breakaway_gap") or key.startswith("island"):
        return float(h[i - 1] if info.bias > 0 else lo[i - 1]) if i > 0 else None
    return float(lo[i] if info.bias > 0 else h[i])
