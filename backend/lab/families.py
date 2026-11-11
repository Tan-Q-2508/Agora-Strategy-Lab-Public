"""Strategy families for research sprints (D-143, Phase 25.5).

Each family is one hypothesis with an economic or behavioural reason (who is on the other
side, why the edge should last), a definition built from Agora's own rules, and a small grid
of settings. The sprint tests every variant on both markets; the ledger keeps every result.

Why families and not single strategies: a real edge shows up across neighbouring settings
and many stocks. A setting that works alone, with its neighbours failing, is luck (the
"isolated peak" check, D-89). Grids are kept small and round on purpose: a family with 9
variants costs the luck check much less than one with 200.

The reasons cite the research they rest on; ``backend/metis/library`` has the longer story.
None of this is advice: every family must earn its place on the user's own data.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

Json = dict[str, Any]


# ---------------------------------------------------------------- a small rule language


def ind(
    name: str, output: str | None = None, offset: int = 0, chart: str | None = None, **p: Any
) -> Json:
    """An indicator operand; settings may be numbers or "$parameter"."""
    return {
        "kind": "indicator",
        "name": name,
        "params": p,
        "output": output,
        "offset": offset,
        "chart": chart,
    }


def price(
    field_name: str = "close", offset: int = 0, times: float | str = 1.0, chart: str | None = None
) -> Json:
    return {"kind": "price", "field": field_name, "offset": offset, "times": times, "chart": chart}


def num(v: float | str) -> Json:
    return {"kind": "number", "value": v}


def cmp(left: Json, op: str, right: Json) -> Json:
    return {"type": "compare", "left": left, "op": op, "right": right}


def all_of(*cs: Json) -> Json:
    return cs[0] if len(cs) == 1 else {"type": "all", "conditions": list(cs)}


def any_of(*cs: Json) -> Json:
    return cs[0] if len(cs) == 1 else {"type": "any", "conditions": list(cs)}


def window(after: str | None, before: str | None) -> Json:
    return {"type": "time", "after": after, "before": before}


def stop(kind: str, value: float | str) -> Json:
    return {"kind": kind, "value": value, "atr_period": 14}


def uptrend() -> Json:
    """The long-term trend filter every dip-buyer needs: above the 200-candle average."""
    return cmp(price(), "above", ind("sma", period=200))


def downtrend() -> Json:
    return cmp(price(), "below", ind("sma", period=200))


# ---------------------------------------------------------------- families


@dataclass(frozen=True)
class Family:
    key: str
    name: str
    why: str  # the hypothesis and its reason, in plain words
    style: str  # trend | reversion | breakout | momentum | intraday
    grid: dict[str, Sequence[float]]
    build: Callable[[str, str], Json]  # (market, timeframe) → definition without parameters
    timeframes: tuple[str, ...] = ("1d",)
    markets: tuple[str, ...] = ("IN", "US")
    labels: dict[str, str] = field(default_factory=dict)
    valid: Callable[[dict[str, float]], bool] = lambda _v: True  # skip senseless combinations

    def variants(self) -> list[dict[str, float]]:
        keys = list(self.grid)
        combos = (dict(zip(keys, c, strict=True)) for c in itertools.product(*self.grid.values()))
        return [v for v in combos if self.valid(v)]

    def definition(self, market: str, timeframe: str, symbols: Sequence[str] = ()) -> Json:
        d = self.build(market, timeframe)
        d.setdefault("schema_version", 1)
        d["market"] = market
        d["timeframe"] = timeframe
        d.setdefault("kind", "visual")
        d["universe"] = {"kind": "symbols", "symbols": list(symbols)}
        if "product" not in d:
            d["product"] = _product(market, timeframe)
        d.setdefault("sizing", {"kind": "percent_equity", "value": 10.0})
        d.setdefault(
            "limits",
            {"max_open_positions": 10, "max_per_symbol": 1, "max_position_pct": 10.0},
        )
        if d["kind"] == "visual":
            d["parameters"] = [self._param(k, v) for k, v in self.grid.items()]
        elif d["kind"] == "ranking" and symbols:
            # a ranking must choose from several times the stocks it holds
            r = d["ranking"]
            r["hold"] = max(1, min(int(r["hold"]), len(symbols) // 3))
        return d

    def _param(self, name: str, values: Sequence[float]) -> Json:
        whole = all(float(v).is_integer() for v in values)
        mid = sorted(values)[len(values) // 2]
        return {
            "name": name,
            "label": self.labels.get(name, name.replace("_", " ").capitalize())[:60],
            "type": "int" if whole else "float",
            "default": float(mid),
            "min": float(min(values)),
            "max": float(max(values)),
            "step": None,
        }


def _product(market: str, timeframe: str) -> str:
    if market == "US":
        return "cash"
    return "delivery" if timeframe == "1d" else "intraday"


def visual(
    long: Json | None,
    exit_long: Json | None,
    *,
    short: Json | None = None,
    exit_short: Json | None = None,
    stop_loss: Json | None = None,
    take_profit: Json | None = None,
    trailing: Json | None = None,
    max_bars: float | str | None = None,
    exit_time: str | None = None,
    scale_out: Json | None = None,
) -> Json:
    return {
        "kind": "visual",
        "entry": {"long": long, "short": short},
        "exit": {
            "long": exit_long,
            "short": exit_short,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop": trailing,
            "scale_out": scale_out,
            "max_bars": max_bars,
            "exit_time": exit_time,
        },
    }


def _session(market: str) -> tuple[str, str, str]:
    """(morning starts, morning ends, square off) in the market's own time."""
    return ("09:30", "11:30", "15:10") if market == "IN" else ("09:45", "11:45", "15:50")


FAMILIES: list[Family] = [
    # ------------------------------------------------ buying dips inside uptrends (reversion)
    Family(
        "trend_dip_rsi",
        "Short dips in an uptrend (RSI)",
        "Short-term overreactions reverse: forced and impatient sellers push a stock below fair "
        "value for a few days, and the buyer who provides liquidity is paid for it (Lehmann "
        "1990; Connors). Only inside a long uptrend, where the dip is noise, not news.",
        "reversion",
        {"rsi_len": (2, 3, 5), "dip": (5, 10, 20)},
        lambda m, tf: visual(
            all_of(uptrend(), cmp(ind("rsi", period="$rsi_len"), "below", num("$dip"))),
            cmp(ind("rsi", period="$rsi_len"), "above", num(70)),
            stop_loss=stop("atr", 3),
            max_bars=10,
        ),
        labels={"rsi_len": "RSI length", "dip": "RSI below"},
    ),
    Family(
        "trend_dip_bollinger",
        "Lower Bollinger band in an uptrend",
        "Same reason as RSI dips, measured in the stock's own volatility: a close under the "
        "lower band is a statistically unusual fall that tends to snap back to the average.",
        "reversion",
        {"length": (10, 20), "width": (1.5, 2.0, 2.5)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(price(), "below", ind("bollinger", "lower", period="$length", mult="$width")),
            ),
            cmp(price(), "above", ind("bollinger", "middle", period="$length", mult="$width")),
            stop_loss=stop("atr", 3),
            max_bars=15,
        ),
    ),
    Family(
        "trend_dip_zscore",
        "Two-sigma dips in an uptrend",
        "A close two standard deviations under its 20-candle average is rare; inside an uptrend "
        "most such falls are liquidity events that revert within days.",
        "reversion",
        {"length": (10, 20, 50), "depth": (-1.5, -2.0, -2.5)},
        lambda m, tf: visual(
            all_of(uptrend(), cmp(ind("zscore", period="$length"), "below", num("$depth"))),
            cmp(ind("zscore", period="$length"), "above", num(0)),
            stop_loss=stop("atr", 3),
            max_bars=15,
        ),
    ),
    Family(
        "trend_dip_connors",
        "Connors RSI dips in an uptrend",
        "Connors RSI adds the length of the down streak and how big today's fall is against "
        "the last 100 days, so it catches exhausted selling better than plain RSI.",
        "reversion",
        {"level": (5, 10, 15, 20)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(ind("connors_rsi", rsi=3, streak=2, rank=100), "below", num("$level")),
            ),
            cmp(ind("connors_rsi", rsi=3, streak=2, rank=100), "above", num(70)),
            stop_loss=stop("atr", 3),
            max_bars=10,
        ),
    ),
    Family(
        "trend_dip_williams",
        "Williams %R pullbacks in an uptrend",
        "Buying a close near the bottom of the recent range when the bigger trend is up: "
        "momentum traders buy the dip back, so these pullbacks are usually short.",
        "reversion",
        {"length": (5, 10, 14), "level": (-90, -95)},
        lambda m, tf: visual(
            all_of(uptrend(), cmp(ind("williams_r", period="$length"), "below", num("$level"))),
            cmp(ind("williams_r", period="$length"), "above", num(-30)),
            stop_loss=stop("atr", 3),
            max_bars=10,
        ),
    ),
    Family(
        "trend_dip_stochastic",
        "Stochastic turn up from oversold in an uptrend",
        "Waiting for the stochastic to turn back up from oversold, rather than buying the fall, "
        "trades a little later but skips dips that keep falling.",
        "reversion",
        {"k": (5, 14), "level": (20, 30)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(
                    ind("stochastic", "k", k="$k", smooth=3, d=3),
                    "crosses_above",
                    ind("stochastic", "d", k="$k", smooth=3, d=3),
                ),
                cmp(ind("stochastic", "k", k="$k", smooth=3, d=3), "below", num("$level")),
            ),
            cmp(ind("stochastic", "k", k="$k", smooth=3, d=3), "above", num(80)),
            stop_loss=stop("atr", 3),
            max_bars=12,
        ),
    ),
    Family(
        "trend_dip_mfi",
        "Money flow washout in an uptrend",
        "Money Flow Index weighs falls by volume: heavy-volume selling into an uptrend is often "
        "capitulation by weak holders, bought by patient money.",
        "reversion",
        {"length": (10, 14), "level": (15, 20, 25)},
        lambda m, tf: visual(
            all_of(uptrend(), cmp(ind("mfi", period="$length"), "below", num("$level"))),
            cmp(ind("mfi", period="$length"), "above", num(60)),
            stop_loss=stop("atr", 3),
            max_bars=15,
        ),
    ),
    Family(
        "ema_pullback",
        "Pullback to the 20 EMA in a stacked trend",
        "In a strong trend (50 above 200) prices pause at the short average and resume: "
        "continuation after a pause, the trader's 'buy the first pullback'.",
        "trend",
        {"fast": (10, 20), "trail": (2.5, 3.5)},
        lambda m, tf: visual(
            all_of(
                cmp(ind("sma", period=50), "above", ind("sma", period=200)),
                cmp(price("low", offset=1), "below", ind("ema", period="$fast", offset=1)),
                cmp(price(), "crosses_above", ind("ema", period="$fast")),
            ),
            cmp(price(), "below", ind("sma", period=50)),
            stop_loss=stop("atr", 2),
            trailing=stop("atr", "$trail"),
        ),
    ),
    # ------------------------------------------------ trend following and breakouts
    Family(
        "donchian_breakout",
        "Channel breakout (Donchian)",
        "Time-series momentum: assets that rose keep rising for months because news spreads "
        "slowly and investors under-react (Moskowitz, Ooi, Pedersen 2012). Buying a new N-candle "
        "high is the simplest way to ride it.",
        "breakout",
        {"entry_len": (20, 55), "exit_len": (10, 20), "trail": (3.0, 4.0)},
        lambda m, tf: visual(
            cmp(price(), "above", ind("donchian", "upper", offset=1, period="$entry_len")),
            cmp(price(), "below", ind("donchian", "lower", offset=1, period="$exit_len")),
            stop_loss=stop("atr", 2.5),
            trailing=stop("atr", "$trail"),
        ),
    ),
    Family(
        "breakout_52w",
        "New 52-week high",
        "Investors anchor on the 52-week high and hesitate to buy above it, so news that "
        "justifies a breakout is priced in slowly (George and Hwang 2004).",
        "momentum",
        {"trail": (2.5, 3.5, 4.5)},
        lambda m, tf: visual(
            cmp(price(), "crosses_above", ind("high_52w", offset=1)),
            cmp(price(), "below", ind("sma", period=50)),
            stop_loss=stop("atr", 2.5),
            trailing=stop("atr", "$trail"),
        ),
    ),
    Family(
        "squeeze_release",
        "Volatility squeeze release",
        "Volatility clusters and mean-reverts: after a quiet spell (Bollinger inside Keltner) a "
        "big move tends to follow. Enter in the direction of momentum when the squeeze ends.",
        "breakout",
        {"kc": (1.5, 2.0), "trail": (2.5, 3.5)},
        lambda m, tf: visual(
            all_of(
                cmp(
                    ind("squeeze", "on", offset=1, period=20, bb=2, kc="$kc"), "at_least", num(0.5)
                ),
                cmp(ind("squeeze", "on", period=20, bb=2, kc="$kc"), "at_most", num(0.5)),
                cmp(ind("squeeze", "momentum", period=20, bb=2, kc="$kc"), "above", num(0)),
                cmp(price(), "above", ind("sma", period=50)),
            ),
            cmp(ind("squeeze", "momentum", period=20, bb=2, kc="$kc"), "below", num(0)),
            stop_loss=stop("atr", 2),
            trailing=stop("atr", "$trail"),
        ),
    ),
    Family(
        "keltner_volume_breakout",
        "Keltner breakout on heavy volume",
        "A close above the Keltner band on twice the usual volume says big buyers are in "
        "(institutions split orders over days, so their buying keeps coming).",
        "breakout",
        {"rvol": (1.5, 2.0), "mult": (1.5, 2.0)},
        lambda m, tf: visual(
            all_of(
                cmp(
                    price(),
                    "crosses_above",
                    ind("keltner", "upper", period=20, mult="$mult", atr_period=10),
                ),
                cmp(ind("rvol", period=20), "at_least", num("$rvol")),
            ),
            cmp(price(), "below", ind("keltner", "middle", period=20, mult="$mult", atr_period=10)),
            stop_loss=stop("atr", 2),
            trailing=stop("atr", 3),
        ),
    ),
    # The four below replicate the rules that survived a strict multiple-testing check on 78
    # liquid NSE stocks, 2015–2025, after 0.05% round-trip costs (Pillai 2026, from the user's
    # Gemini research, 2026-11-03): channel breakouts, plain crossovers, a slowed MACD, and RSI
    # only at extremes. They are tested here as hypotheses on the user's own data.
    Family(
        "sma_cross",
        "Plain moving-average crossover",
        "Time-series momentum on single stocks: the 10/50 and 20/100 crossovers earned a Sharpe "
        "ratio near 1.1–1.3 on liquid NSE stocks in 2015–2025 after costs and survived a "
        "multiple-testing correction (Pillai 2026). Institutions split big orders over weeks "
        "and retail chases trends, so trends last longer than costs.",
        "trend",
        {"fast": (10, 20, 50), "slow": (50, 100, 200)},
        lambda m, tf: visual(
            cmp(ind("sma", period="$fast"), "crosses_above", ind("sma", period="$slow")),
            cmp(ind("sma", period="$fast"), "crosses_below", ind("sma", period="$slow")),
        ),
        valid=lambda v: v["slow"] >= 2.5 * v["fast"],
    ),
    Family(
        "macd_slow",
        "Slowed MACD crossover",
        "The same trends with a slower MACD (26/52/18 against the usual 12/26/9): half the "
        "trades, so half the costs, and a better result after costs on NSE stocks (Pillai 2026).",
        "trend",
        {"fast": (12, 26), "slow": (26, 52), "signal": (9, 18)},
        lambda m, tf: visual(
            cmp(
                ind("macd", "macd", fast="$fast", slow="$slow", signal="$signal"),
                "crosses_above",
                ind("macd", "signal", fast="$fast", slow="$slow", signal="$signal"),
            ),
            cmp(
                ind("macd", "macd", fast="$fast", slow="$slow", signal="$signal"),
                "crosses_below",
                ind("macd", "signal", fast="$fast", slow="$slow", signal="$signal"),
            ),
        ),
        valid=lambda v: v["slow"] >= 2 * v["fast"],
    ),
    Family(
        "rsi_extremes",
        "RSI only at extremes",
        "Standard RSI rules (30/70) lost to costs on NSE stocks; only the extreme 20/80 rule "
        "survived, because it trades rare capitulation events (Pillai 2026). Tested without a "
        "trend filter, exactly as published.",
        "reversion",
        {"low": (15, 20, 25), "high": (75, 80)},
        lambda m, tf: visual(
            cmp(ind("rsi", period=14), "crosses_below", num("$low")),
            cmp(ind("rsi", period=14), "crosses_above", num("$high")),
            stop_loss=stop("atr", 4),
        ),
    ),
    Family(
        "ma_cross_adx",
        "Average crossover with a trend-strength filter",
        "Crossovers catch trends but whipsaw in flat markets; requiring ADX above 20 keeps only "
        "crosses in markets that are actually trending.",
        "trend",
        {"fast": (10, 20), "slow": (50, 100), "adx_min": (20, 25)},
        lambda m, tf: visual(
            all_of(
                cmp(ind("ema", period="$fast"), "crosses_above", ind("ema", period="$slow")),
                cmp(ind("adx", "adx", period=14), "at_least", num("$adx_min")),
            ),
            cmp(ind("ema", period="$fast"), "crosses_below", ind("ema", period="$slow")),
            stop_loss=stop("atr", 3),
            trailing=stop("atr", 4),
        ),
    ),
    Family(
        "supertrend_trend",
        "Supertrend flip in a long uptrend",
        "Supertrend is an ATR trailing line; a flip to up inside a long uptrend is a resumed "
        "trend, while flips against the 200-candle average are mostly noise.",
        "trend",
        {"length": (10, 14), "mult": (2.0, 3.0)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(
                    ind("supertrend", "direction", period="$length", mult="$mult"),
                    "crosses_above",
                    num(0),
                ),
            ),
            cmp(
                ind("supertrend", "direction", period="$length", mult="$mult"),
                "crosses_below",
                num(0),
            ),
            stop_loss=stop("atr", 3),
        ),
    ),
    Family(
        "macd_trend",
        "MACD turn up above zero",
        "A MACD histogram turning positive while MACD is above zero is momentum resuming within "
        "an established up-move, not a bottom-pick.",
        "trend",
        {"fast": (8, 12), "slow": (21, 26)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(ind("macd", "macd", fast="$fast", slow="$slow", signal=9), "above", num(0)),
                cmp(
                    ind("macd", "histogram", fast="$fast", slow="$slow", signal=9),
                    "crosses_above",
                    num(0),
                ),
            ),
            cmp(
                ind("macd", "histogram", fast="$fast", slow="$slow", signal=9),
                "crosses_below",
                num(0),
            ),
            stop_loss=stop("atr", 2.5),
            trailing=stop("atr", 3.5),
        ),
    ),
    Family(
        "roc_momentum",
        "Six-month momentum turning up",
        "Stocks that rose over the past months tend to keep rising (Jegadeesh and Titman 1993; "
        "strong in India too). Enter when medium-term momentum turns positive in an uptrend.",
        "momentum",
        {"length": (63, 126), "trail": (3.0, 4.0)},
        lambda m, tf: visual(
            all_of(uptrend(), cmp(ind("roc", period="$length"), "crosses_above", num(0))),
            cmp(ind("roc", period="$length"), "below", num(0)),
            stop_loss=stop("atr", 3),
            trailing=stop("atr", "$trail"),
        ),
    ),
    Family(
        "aroon_trend",
        "Aroon trend start",
        "Aroon measures how recently the high and low were made: a fresh run of new highs with "
        "no new lows marks the start of a trend.",
        "trend",
        {"length": (14, 25), "level": (50, 70)},
        lambda m, tf: visual(
            all_of(
                cmp(ind("aroon", "oscillator", period="$length"), "crosses_above", num("$level")),
                cmp(price(), "above", ind("sma", period=50)),
            ),
            cmp(ind("aroon", "oscillator", period="$length"), "below", num(0)),
            stop_loss=stop("atr", 2.5),
            trailing=stop("atr", 3.5),
        ),
    ),
    Family(
        "ichimoku_cloud",
        "Above the Ichimoku cloud",
        "The cloud is a support zone from past mid-prices; a conversion-line cross above the base "
        "line while price is above the cloud is a trend continuation signal.",
        "trend",
        {"trail": (3.0, 4.0)},
        lambda m, tf: visual(
            all_of(
                cmp(
                    price(),
                    "above",
                    ind("ichimoku", "span_a", conversion=9, base=26, span=52, shift=26),
                ),
                cmp(
                    price(),
                    "above",
                    ind("ichimoku", "span_b", conversion=9, base=26, span=52, shift=26),
                ),
                cmp(
                    ind("ichimoku", "conversion", conversion=9, base=26, span=52, shift=26),
                    "crosses_above",
                    ind("ichimoku", "base", conversion=9, base=26, span=52, shift=26),
                ),
            ),
            cmp(
                price(), "below", ind("ichimoku", "base", conversion=9, base=26, span=52, shift=26)
            ),
            stop_loss=stop("atr", 2.5),
            trailing=stop("atr", "$trail"),
        ),
    ),
    Family(
        "accumulation_breakout",
        "Breakout with money flowing in",
        "A new 20-candle high while Chaikin money flow is positive: price strength backed by "
        "closes near the highs on volume, the footprint of accumulation.",
        "breakout",
        {"cmf_min": (0.05, 0.1), "trail": (3.0, 4.0)},
        lambda m, tf: visual(
            all_of(
                cmp(price(), "above", ind("highest", offset=1, period=20)),
                cmp(ind("cmf", period=20), "above", num("$cmf_min")),
                uptrend(),
            ),
            cmp(ind("cmf", period=20), "below", num(-0.05)),
            stop_loss=stop("atr", 2.5),
            trailing=stop("atr", "$trail"),
        ),
    ),
    Family(
        "trend_partials",
        "Breakout with partial profits",
        "Breakouts win big but rarely; selling a third at 1R and 2R banks part of the move and "
        "raises the win rate, while the rest rides the trend (scaling out, D-125).",
        "breakout",
        {"entry_len": (20, 50), "trail": (3.0, 4.0)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(price(), "above", ind("donchian", "upper", offset=1, period="$entry_len")),
            ),
            cmp(price(), "below", ind("sma", period=50)),
            stop_loss=stop("atr", 2),
            trailing=stop("atr", "$trail"),
            scale_out={
                "steps": [
                    {"kind": "r", "value": 1, "sell_pct": 33},
                    {"kind": "r", "value": 2, "sell_pct": 33},
                ],
                "breakeven": True,
            },
        ),
    ),
    # ------------------------------------------------ cross-sectional (ranking, D-91)
    Family(
        "ranking_momentum",
        "Monthly top momentum stocks",
        "Cross-sectional momentum: each month hold the strongest risers of the last year, "
        "skipping the latest month (which tends to reverse). The most documented anomaly in "
        "the world, including Indian stocks.",
        "momentum",
        {},
        lambda m, tf: {
            "kind": "ranking",
            "ranking": {
                "rank_by": "momentum",
                "lookback_months": 12,
                "skip_months": 1,
                "hold": 10,
                "trend_filter": True,
            },
        },
    ),
    Family(
        "ranking_momentum_6m",
        "Monthly top momentum stocks (six months)",
        "The same anomaly over six months: reacts faster to new leaders, at the price of more "
        "trading and costs.",
        "momentum",
        {},
        lambda m, tf: {
            "kind": "ranking",
            "ranking": {
                "rank_by": "momentum",
                "lookback_months": 6,
                "skip_months": 1,
                "hold": 10,
                "trend_filter": True,
            },
        },
    ),
    Family(
        "ranking_low_vol",
        "Monthly calmest stocks",
        "The low-volatility anomaly: calm stocks have earned about as much as jumpy ones with "
        "far smaller falls, because investors overpay for lottery-like stocks (Baker, Bradley "
        "and Wurgler 2011).",
        "momentum",
        {},
        lambda m, tf: {
            "kind": "ranking",
            "ranking": {
                "rank_by": "low_volatility",
                "lookback_months": 12,
                "skip_months": 0,
                "hold": 10,
                "trend_filter": True,
            },
        },
    ),
    # ------------------------------------------------ shorts (US daily; India: intraday only)
    Family(
        "downtrend_rally_short",
        "Short a spike in a downtrend (US)",
        "The mirror of dip-buying: in a downtrend, short-lived rallies on thin buying tend to "
        "fade. US only, because Indian daily trades can't be short.",
        "reversion",
        {"rsi_len": (2, 3), "spike": (90, 95)},
        lambda m, tf: visual(
            None,
            None,
            short=all_of(downtrend(), cmp(ind("rsi", period="$rsi_len"), "above", num("$spike"))),
            exit_short=cmp(ind("rsi", period="$rsi_len"), "below", num(30)),
            stop_loss=stop("atr", 3),
            max_bars=10,
        ),
        markets=("US",),
    ),
    # ------------------------------------------------ hourly, with the daily trend
    Family(
        "hourly_breakout_daily_trend",
        "Hourly breakout with the daily trend",
        "Shorter candles give more trades; reading the daily chart keeps only breakouts in the "
        "direction of the bigger trend, which removes most false alarms (multiple timeframes).",
        "breakout",
        {"entry_len": (20, 40), "trail": (2.5, 3.5)},
        lambda m, tf: visual(
            all_of(
                cmp(price(chart="1d"), "above", ind("sma", period=50, chart="1d")),
                cmp(price(), "above", ind("donchian", "upper", offset=1, period="$entry_len")),
            ),
            cmp(price(), "below", ind("donchian", "lower", offset=1, period="$entry_len")),
            stop_loss=stop("atr", 2),
            trailing=stop("atr", "$trail"),
        ),
        timeframes=("1h",),
    ),
    Family(
        "hourly_dip_daily_trend",
        "Hourly RSI dip with the daily trend",
        "Dip-buying on hourly candles inside a daily uptrend: the same liquidity reason as daily "
        "dips, with more chances and shorter holds.",
        "reversion",
        {"rsi_len": (2, 4), "dip": (10, 20)},
        lambda m, tf: visual(
            all_of(
                cmp(price(chart="1d"), "above", ind("sma", period=50, chart="1d")),
                cmp(ind("rsi", period="$rsi_len"), "below", num("$dip")),
            ),
            cmp(ind("rsi", period="$rsi_len"), "above", num(65)),
            stop_loss=stop("atr", 3),
            max_bars=14,
        ),
        timeframes=("1h",),
    ),
    # ------------------------------------------------ intraday (15- and 5-minute)
    Family(
        "opening_range_breakout",
        "Opening range breakout on volume",
        "The first minutes set the day's battle lines; a break of the opening range on heavy "
        "volume is often followed through as overnight orders and news get absorbed (Zarattini "
        "and Aziz 2023).",
        "intraday",
        {"minutes": (15, 30), "rvol": (1.5, 2.0)},
        lambda m, tf: visual(
            all_of(
                window(_session(m)[0], _session(m)[1]),
                cmp(price(), "crosses_above", ind("opening_range", "high", minutes="$minutes")),
                cmp(ind("rvol", period=20), "at_least", num("$rvol")),
            ),
            cmp(price(), "below", ind("vwap")),
            stop_loss=stop("atr", 2),
            exit_time=_session(m)[2],
        ),
        timeframes=("15m", "5m"),
    ),
    Family(
        "vwap_reclaim",
        "VWAP reclaim in the morning",
        "VWAP is the day's average price paid; funds buy below it and defend it. A stock that "
        "dips under VWAP and closes back above it, in a daily uptrend, is often bought.",
        "intraday",
        # the daily chart is built from the strategy's own candles: 60 days of 5-minute history
        # can't hold a 50-day average, so the trend is short
        {"trend_len": (10, 20)},
        lambda m, tf: visual(
            all_of(
                window(_session(m)[0], _session(m)[1]),
                cmp(price(chart="1d"), "above", ind("sma", period="$trend_len", chart="1d")),
                cmp(price(), "crosses_above", ind("vwap")),
            ),
            cmp(price(), "below", ind("vwap")),
            stop_loss=stop("atr", 2),
            take_profit=stop("atr", 3),
            exit_time=_session(m)[2],
        ),
        timeframes=("15m", "5m"),
    ),
    Family(
        "intraday_dip_above_vwap",
        "Intraday RSI dip above VWAP",
        "Within a strong day (price above VWAP) a quick RSI(2) washout is usually bought back by "
        "the same buyers that made the day strong.",
        "intraday",
        {"dip": (5, 10, 20)},
        lambda m, tf: visual(
            all_of(
                cmp(price(), "above", ind("vwap")),
                cmp(ind("rsi", period=2), "below", num("$dip")),
                window(_session(m)[0], "14:30" if m == "IN" else "15:00"),
            ),
            cmp(ind("rsi", period=2), "above", num(70)),
            stop_loss=stop("atr", 2),
            max_bars=12,
            exit_time=_session(m)[2],
        ),
        timeframes=("15m", "5m"),
    ),
    # ------------------------------------------------ round 2 (sprint 2026-11, from its report)
    # The first round's lesson on the user's data: in India nearly every daily family failed
    # only one rule, matching simply holding its own stocks (exam Sharpe ratio 1.49 against
    # 0.9–1.2), while the families that stay invested for months (crossovers, Supertrend,
    # slowed MACD) passed. Dip buying lost money in calm sideways markets in India. Every
    # intraday family lost to costs. So round 2 trades less, holds longer, and buys dips
    # only where the regime map says they paid.
    Family(
        "trend_hold_long",
        "Hold while above the long average and six-month momentum is positive",
        "Time-series momentum held for months: in when the stock is above its long average and "
        "up over six or twelve months, out only when it falls below the average. Few trades, so "
        "India's 0.1% delivery tax each way barely matters, and the strategy stays invested "
        "through the long rises that beat the dip buyers in round 1 (Moskowitz, Ooi, Pedersen "
        "2012; Faber 2007).",
        "trend",
        {"avg": (150, 200), "roc_len": (126, 252)},
        lambda m, tf: visual(
            all_of(
                cmp(price(), "above", ind("sma", period="$avg")),
                cmp(ind("roc", period="$roc_len"), "above", num(0)),
            ),
            cmp(price(), "below", ind("sma", period="$avg")),
            stop_loss=stop("atr", 4),
        ),
        labels={"avg": "Long average", "roc_len": "Momentum length"},
    ),
    Family(
        "trend_dip_stacked",
        "RSI(2) dips only in a stacked, rising trend",
        "Round 1's dips paid in rising markets and lost in calm sideways ones (India: −0.18% a "
        "trade). Requiring the 50-candle average above the 200 and rising over a month keeps "
        "only the dips that are noise inside a real trend, where the liquidity provider is paid.",
        "reversion",
        {"dip": (5, 10), "hold": (5, 10)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(ind("sma", period=50), "above", ind("sma", period=200)),
                cmp(ind("sma", period=50), "above", ind("sma", period=50, offset=20)),
                cmp(ind("rsi", period=2), "below", num("$dip")),
            ),
            cmp(ind("rsi", period=2), "above", num(70)),
            stop_loss=stop("atr", 3),
            max_bars="$hold",
        ),
        labels={"dip": "RSI(2) below", "hold": "Most candles held"},
    ),
    Family(
        "dip_when_volatile",
        "Uptrend dips when volatility is high",
        "Liquidity providers earn most when volatility is high and few are willing to buy "
        "(Nagel 2012, 'Evaporating liquidity'). Round 1's dips earned most in volatile up and "
        "sideways regimes and nothing in calm ones, so buy only when the stock's ATR is a large "
        "share of its price.",
        "reversion",
        {"natr_min": (2.0, 3.0), "dip": (5, 10)},
        lambda m, tf: visual(
            all_of(
                uptrend(),
                cmp(ind("natr", period=14), "above", num("$natr_min")),
                cmp(ind("rsi", period=2), "below", num("$dip")),
            ),
            cmp(ind("rsi", period=2), "above", num(70)),
            stop_loss=stop("atr", 3),
            max_bars=10,
        ),
        labels={"natr_min": "ATR at least (% of price)", "dip": "RSI(2) below"},
    ),
    Family(
        "leader_dip_52w",
        "Short dips in stocks near their 52-week high",
        "Investors anchor on the 52-week high and are slow to push a stock through it, so stocks "
        "near it keep outperforming (George and Hwang 2004). A short dip in such a leader is a "
        "cheap entry into the strongest stocks rather than a falling knife.",
        "reversion",
        {"near": (1.1, 1.2), "dip": (5, 10)},
        lambda m, tf: visual(
            all_of(
                cmp(price(times="$near"), "above", ind("high_52w")),
                cmp(ind("rsi", period=2), "below", num("$dip")),
            ),
            cmp(ind("rsi", period=2), "above", num(70)),
            stop_loss=stop("atr", 3),
            max_bars=10,
        ),
        labels={"near": "Close × this above the 52-week high", "dip": "RSI(2) below"},
    ),
    Family(
        "breakout_hold_trend",
        "52-week high breakout held until the trend ends",
        "Round 1's breakouts were cut short by trailing stops and lost to holding the stocks. "
        "Buy a new 52-week high and hold until the price closes under its 100- or 200-candle "
        "average: momentum runs for months, and fewer exits mean lower costs.",
        "momentum",
        {"exit_avg": (100, 200), "stop_atr": (3.0, 5.0)},
        lambda m, tf: visual(
            cmp(price(), "above", ind("high_52w", offset=1)),
            cmp(price(), "below", ind("sma", period="$exit_avg")),
            stop_loss=stop("atr", "$stop_atr"),
        ),
        labels={"exit_avg": "Exit below average", "stop_atr": "Stop (ATR)"},
    ),
]

BY_KEY = {f.key: f for f in FAMILIES}


def pick(keys: Sequence[str] | None) -> list[Family]:
    if not keys or list(keys) == ["all"]:
        return list(FAMILIES)
    missing = [k for k in keys if k not in BY_KEY]
    if missing:
        raise KeyError(f"No family called: {', '.join(missing)}")
    return [BY_KEY[k] for k in keys]
