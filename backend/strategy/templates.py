"""Starter strategies (SPEC §5.2; Phase 10.4): 28 classic ideas from around the world.

Each template is a visual Strategy Definition with named parameters (so it can be swept),
written for India; ``template_definition`` adapts it to the US (trade type, exit times).
Descriptions are plain English and honest about what each idea assumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.strategy.definition import VisualDefinition


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    summary: str
    description: str
    idea: str  # the market behaviour the strategy bets on
    timeframe: str
    body: dict[str, Any]  # definition without market/product/universe

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "summary": self.summary,
            "description": self.description,
            "idea": self.idea,
            "timeframe": self.timeframe,
        }


def _param(
    name: str, label: str, default: float, lo: float, hi: float, typ: str = "int"
) -> dict[str, Any]:
    return {"name": name, "label": label, "type": typ, "default": default, "min": lo, "max": hi}


def _ind(
    name: str, offset: int = 0, output: str | None = None, times: Any = 1.0, **params: Any
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": "indicator",
        "name": name,
        "params": params,
        "offset": offset,
        "times": times,
    }
    if output:
        d["output"] = output
    return d


CLOSE = {"kind": "price", "field": "close"}


def _num(v: Any) -> dict[str, Any]:
    return {"kind": "number", "value": v}


def _cmp(left: dict[str, Any], op: str, right: dict[str, Any]) -> dict[str, Any]:
    return {"type": "compare", "left": left, "op": op, "right": right}


TEMPLATES: dict[str, Template] = {}


def _add(t: Template) -> None:
    TEMPLATES[t.key] = t


_add(
    Template(
        "ma_crossover",
        "Moving-average crossover",
        "Buy when the fast average crosses above the slow one; sell when it crosses back.",
        "Follows trends: it buys after prices have started rising and sells after they start "
        "falling, so it catches big moves but gives back some profit at each turn.",
        "Prices that start trending tend to keep going.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("fast", "Fast average (candles)", 20, 5, 100),
                _param("slow", "Slow average (candles)", 50, 20, 300),
            ],
            "entry": {
                "long": _cmp(
                    _ind("sma", period="$fast"), "crosses_above", _ind("sma", period="$slow")
                )
            },
            "exit": {
                "long": _cmp(
                    _ind("sma", period="$fast"), "crosses_below", _ind("sma", period="$slow")
                )
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)
_add(
    Template(
        "rsi_mean_reversion",
        "RSI mean reversion",
        "Buy oversold dips in an uptrend (RSI below 30, price above its 200-day average).",
        "Buys short, sharp drops in stocks that are still in a long uptrend, and sells once "
        "the bounce is overdone (RSI above 70) or after a set number of days.",
        "Sharp drops inside a long uptrend usually bounce back.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("rsi_len", "RSI length", 14, 2, 50),
                _param("oversold", "Oversold level", 30, 5, 45),
                _param("overbought", "Overbought level", 70, 55, 95),
                _param("hold", "Most days to hold", 20, 2, 100),
            ],
            "entry": {
                "long": {
                    "type": "all",
                    "conditions": [
                        _cmp(_ind("rsi", period="$rsi_len"), "crosses_below", _num("$oversold")),
                        _cmp(CLOSE, "above", _ind("sma", period=200)),
                    ],
                }
            },
            "exit": {
                "long": _cmp(_ind("rsi", period="$rsi_len"), "crosses_above", _num("$overbought")),
                "stop_loss": {"kind": "percent", "value": 8},
                "max_bars": "$hold",
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)
_add(
    Template(
        "bollinger_reversion",
        "Bollinger Band reversion",
        "Buy when the price closes below the lower band; sell when it gets back to the middle.",
        "Treats an unusually low close (two standard deviations below the 20-day average) as "
        "a stretch that tends to snap back toward the average.",
        "Unusual moves away from the average tend to reverse.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("length", "Band length (candles)", 20, 5, 100),
                _param("width", "Band width (std devs)", 2.0, 1.0, 4.0, "float"),
            ],
            "entry": {
                "long": _cmp(
                    CLOSE,
                    "crosses_below",
                    _ind("bollinger", output="lower", period="$length", mult="$width"),
                )
            },
            "exit": {
                "long": _cmp(
                    CLOSE,
                    "crosses_above",
                    _ind("bollinger", output="middle", period="$length", mult="$width"),
                ),
                "stop_loss": {"kind": "percent", "value": 6},
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)
_add(
    Template(
        "donchian_breakout",
        "Donchian breakout",
        "Buy when the price breaks above its 20-day high; sell when it breaks below its 10-day low.",
        "The classic “turtle” idea: join a move once it breaks out of its recent range, and "
        "step aside when it falls back through a shorter range.",
        "Breakouts from a range often start a new trend.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("entry_len", "Breakout length (candles)", 20, 5, 100),
                _param("exit_len", "Exit length (candles)", 10, 3, 60),
            ],
            "entry": {
                "long": _cmp(
                    CLOSE,
                    "crosses_above",
                    _ind("donchian", offset=1, output="upper", period="$entry_len"),
                )
            },
            "exit": {
                "long": _cmp(
                    CLOSE,
                    "crosses_below",
                    _ind("donchian", offset=1, output="lower", period="$exit_len"),
                )
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)
_add(
    Template(
        "supertrend",
        "Supertrend trend-follow",
        "Buy when Supertrend turns up; sell when it turns down.",
        "Supertrend trails the price by a multiple of its typical daily range (ATR); a close "
        "through that line flips the trend.",
        "Trends persist until the price breaks a volatility-based trailing line.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("atr_len", "ATR length", 10, 3, 50),
                _param("mult", "ATR multiple", 3.0, 1.0, 6.0, "float"),
            ],
            "entry": {
                "long": _cmp(
                    _ind("supertrend", output="direction", period="$atr_len", mult="$mult"),
                    "crosses_above",
                    _num(0),
                )
            },
            "exit": {
                "long": _cmp(
                    _ind("supertrend", output="direction", period="$atr_len", mult="$mult"),
                    "crosses_below",
                    _num(0),
                )
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)
_add(
    Template(
        "opening_range_breakout",
        "Opening range breakout (intraday)",
        "Trade a break of the first 15 minutes' high or low; always closed before the end of the day.",
        "Uses 5-minute candles. After the first 15 minutes, buys a break above that range or "
        "short-sells a break below it, with a small stop-loss and target, and exits every "
        "trade before the close.",
        "The first minutes set the day's direction; a break of that range tends to run.",
        "5m",
        {
            "timeframe": "5m",
            "parameters": [
                _param("range_min", "Opening range (minutes)", 15, 5, 60),
                _param("stop_pct", "Stop-loss (%)", 1.0, 0.2, 5.0, "float"),
                _param("target_pct", "Take-profit (%)", 2.0, 0.2, 10.0, "float"),
            ],
            "entry": {
                "long": {
                    "type": "all",
                    "conditions": [
                        {"type": "time", "after": "09:30", "before": "14:30"},
                        _cmp(
                            CLOSE,
                            "crosses_above",
                            _ind("opening_range", output="high", minutes="$range_min"),
                        ),
                    ],
                },
                "short": {
                    "type": "all",
                    "conditions": [
                        {"type": "time", "after": "09:30", "before": "14:30"},
                        _cmp(
                            CLOSE,
                            "crosses_below",
                            _ind("opening_range", output="low", minutes="$range_min"),
                        ),
                    ],
                },
            },
            "exit": {
                "stop_loss": {"kind": "percent", "value": "$stop_pct"},
                "take_profit": {"kind": "percent", "value": "$target_pct"},
                "exit_time": "15:10",
            },
            "sizing": {"kind": "percent_equity", "value": 20},
            "limits": {"max_open_positions": 3},
        },
    )
)
_add(
    Template(
        "macd_momentum",
        "MACD momentum",
        "Buy when the MACD line crosses above its signal line while above zero; sell on the cross back.",
        "Looks for momentum picking up inside an existing uptrend (MACD above zero), and "
        "leaves when momentum fades.",
        "Accelerating momentum tends to continue for a while.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("fast", "Fast length", 12, 3, 50),
                _param("slow", "Slow length", 26, 10, 100),
                _param("signal", "Signal length", 9, 3, 30),
            ],
            "entry": {
                "long": {
                    "type": "all",
                    "conditions": [
                        _cmp(
                            _ind(
                                "macd", output="macd", fast="$fast", slow="$slow", signal="$signal"
                            ),
                            "crosses_above",
                            _ind(
                                "macd",
                                output="signal",
                                fast="$fast",
                                slow="$slow",
                                signal="$signal",
                            ),
                        ),
                        _cmp(
                            _ind(
                                "macd", output="macd", fast="$fast", slow="$slow", signal="$signal"
                            ),
                            "above",
                            _num(0),
                        ),
                    ],
                }
            },
            "exit": {
                "long": _cmp(
                    _ind("macd", output="macd", fast="$fast", slow="$slow", signal="$signal"),
                    "crosses_below",
                    _ind("macd", output="signal", fast="$fast", slow="$slow", signal="$signal"),
                ),
                "stop_loss": {"kind": "atr", "value": 3, "atr_period": 14},
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)
_add(
    Template(
        "high_52w_momentum",
        "52-week-high momentum",
        "Buy stocks trading within 2% of their 52-week high; exit below the 50-day average.",
        "Stocks near their yearly high often keep making new highs. A trailing stop protects "
        "gains, and a drop below the 50-day average ends the trade.",
        "Strength attracts more buying; leaders keep leading.",
        "1d",
        {
            "timeframe": "1d",
            "parameters": [
                _param("near_factor", "Close ÷ 52-week high, at least", 0.98, 0.8, 1.0, "float"),
                _param("exit_avg", "Exit average (candles)", 50, 10, 200),
                _param("trail_pct", "Trailing stop (%)", 10.0, 2.0, 30.0, "float"),
            ],
            "entry": {
                "long": _cmp(CLOSE, "at_least", _ind("high_52w", times="$near_factor")),
            },
            "exit": {
                "long": _cmp(CLOSE, "crosses_below", _ind("sma", period="$exit_avg")),
                "trailing_stop": {"kind": "percent", "value": "$trail_pct"},
            },
            "sizing": {"kind": "percent_equity", "value": 10},
        },
    )
)


# ---------------------------------------------------------------- Phase 10.4: the world's classics


def _simple(
    key: str,
    name: str,
    summary: str,
    description: str,
    idea: str,
    parameters: list[dict[str, Any]],
    entry: dict[str, Any],
    exit_: dict[str, Any],
    *,
    timeframe: str = "1d",
    sizing: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> None:
    body: dict[str, Any] = {
        "timeframe": timeframe,
        "parameters": parameters,
        "entry": {"long": entry},
        "exit": exit_,
        "sizing": sizing or {"kind": "percent_equity", "value": 10},
    }
    if limits:
        body["limits"] = limits
    _add(Template(key, name, summary, description, idea, timeframe, body))


def _all(*conds: dict[str, Any]) -> dict[str, Any]:
    return {"type": "all", "conditions": list(conds)}


UPTREND = _cmp(CLOSE, "above", _ind("sma", period=200))

_simple(
    "turtle",
    "Turtle trading (System 2)",
    "Buy a break of the 55-day high; exit at the 20-day low; stop 2 ATRs; risk 1% per trade.",
    "The rules Richard Dennis taught his 'Turtles' in 1983: buy when the price makes a new "
    "55-day high, risk 1% of the account with a stop two ATRs away, and leave when the price "
    "falls to a 20-day low. Many small losses, a few huge trends.",
    "Big trends start with new highs, and a fixed risk per trade survives the false starts.",
    [
        _param("entry_len", "Breakout length (candles)", 55, 20, 120),
        _param("exit_len", "Exit length (candles)", 20, 5, 60),
        _param("stop_atr", "Stop (ATRs)", 2.0, 1.0, 4.0, "float"),
    ],
    _cmp(CLOSE, "crosses_above", _ind("donchian", offset=1, output="upper", period="$entry_len")),
    {
        "long": _cmp(
            CLOSE, "crosses_below", _ind("donchian", offset=1, output="lower", period="$exit_len")
        ),
        "stop_loss": {"kind": "atr", "value": "$stop_atr", "atr_period": 20},
    },
    sizing={"kind": "risk_percent", "value": 1},
)
_simple(
    "golden_cross",
    "Golden cross (50/200)",
    "Buy when the 50-day average crosses above the 200-day; sell on the death cross.",
    "The most-quoted long-term signal on Wall Street and Dalal Street. Slow and late by "
    "design: it misses the first part of a move but keeps you in long trends and out of "
    "long declines.",
    "Long-term trends last long enough to profit from even a late entry.",
    [
        _param("fast", "Fast average (candles)", 50, 20, 100),
        _param("slow", "Slow average (candles)", 200, 100, 300),
    ],
    _cmp(_ind("sma", period="$fast"), "crosses_above", _ind("sma", period="$slow")),
    {"long": _cmp(_ind("sma", period="$fast"), "crosses_below", _ind("sma", period="$slow"))},
)
_simple(
    "connors_rsi2",
    "Connors RSI(2) pullback",
    "In an uptrend, buy when the 2-day RSI drops below 10; sell when the close rises above its 5-day average.",
    "Larry Connors' short-term mean-reversion rule: a two-day RSI under 10 is an extreme "
    "dip, and in a stock above its 200-day average such dips usually bounce within days.",
    "Short, sharp pullbacks in long uptrends snap back.",
    [
        _param("rsi_len", "RSI length", 2, 2, 5),
        _param("level", "Oversold level", 10, 2, 30),
        _param("exit_avg", "Exit average (candles)", 5, 3, 20),
    ],
    _all(_cmp(_ind("rsi", period="$rsi_len"), "crosses_below", _num("$level")), UPTREND),
    {
        "long": _cmp(CLOSE, "crosses_above", _ind("sma", period="$exit_avg")),
        "stop_loss": {"kind": "percent", "value": 8},
        "max_bars": 10,
    },
)
_simple(
    "triple_screen",
    "Triple screen (Elder)",
    "Trade with the long trend (price above a slow EMA); buy when the stochastic turns up from oversold.",
    "Alexander Elder's three screens: the long trend picks the direction (here: price above "
    "a 130-day EMA, about a 26-week EMA), an oscillator finds the pullback (stochastic up "
    "through 20), and a stop limits the damage.",
    "Buying pullbacks in the direction of the bigger trend gives better entries.",
    [
        _param("trend_len", "Trend EMA (candles)", 130, 50, 250),
        _param("k_len", "Stochastic length", 14, 5, 30),
        _param("oversold", "Oversold level", 20, 5, 40),
    ],
    _all(
        _cmp(CLOSE, "above", _ind("ema", period="$trend_len")),
        _cmp(_ind("stochastic", output="k", k="$k_len"), "crosses_above", _num("$oversold")),
    ),
    {
        "long": _cmp(_ind("stochastic", output="k", k="$k_len"), "crosses_below", _num(80)),
        "stop_loss": {"kind": "atr", "value": 2, "atr_period": 14},
        "max_bars": 30,
    },
)
_simple(
    "squeeze_breakout",
    "Squeeze breakout (TTM)",
    "After a volatility squeeze (Bollinger inside Keltner), buy a close above the upper band.",
    "John Carter's squeeze: when the Bollinger Bands contract inside the Keltner Channel, "
    "the market is coiled. The first close above the upper band often starts a sharp move. "
    "Exit when the price falls back below the 20-day EMA.",
    "Quiet markets lead to violent ones; trade the release.",
    [
        _param("length", "Length (candles)", 20, 10, 50),
        _param("width", "Band width (std devs)", 2.0, 1.0, 3.0, "float"),
    ],
    _all(
        _cmp(
            _ind("squeeze", offset=1, output="on", period="$length", bb="$width"),
            "at_least",
            _num(1),
        ),
        _cmp(
            CLOSE,
            "crosses_above",
            _ind("bollinger", output="upper", period="$length", mult="$width"),
        ),
    ),
    {
        "long": _cmp(CLOSE, "crosses_below", _ind("ema", period="$length")),
        "stop_loss": {"kind": "atr", "value": 2, "atr_period": 14},
    },
)
_simple(
    "ichimoku_cloud",
    "Ichimoku cloud breakout",
    "Buy when the conversion line crosses above the base line with the price above the cloud.",
    "The Japanese all-in-one system (Goichi Hosoda): price above both cloud spans means an "
    "uptrend; the fast line crossing the base line times the entry. Exit when the price "
    "closes back below the base line.",
    "Trends above the cloud continue; the cloud acts as support.",
    [
        _param("conversion", "Conversion length", 9, 5, 20),
        _param("base", "Base length", 26, 10, 60),
    ],
    _all(
        _cmp(
            _ind("ichimoku", output="conversion", conversion="$conversion", base="$base"),
            "crosses_above",
            _ind("ichimoku", output="base", conversion="$conversion", base="$base"),
        ),
        _cmp(
            CLOSE,
            "above",
            _ind("ichimoku", output="span_a", conversion="$conversion", base="$base"),
        ),
        _cmp(
            CLOSE,
            "above",
            _ind("ichimoku", output="span_b", conversion="$conversion", base="$base"),
        ),
    ),
    {
        "long": _cmp(
            CLOSE,
            "crosses_below",
            _ind("ichimoku", output="base", conversion="$conversion", base="$base"),
        ),
        "stop_loss": {"kind": "percent", "value": 10},
    },
)
_simple(
    "psar_trend",
    "Parabolic SAR trend",
    "Buy when the price crosses above the SAR dots; sell when it crosses back below.",
    "Welles Wilder's stop-and-reverse system: the dots trail the price and speed up as the "
    "trend matures, so the exit tightens automatically. It whipsaws in sideways markets.",
    "A trend continues until the price breaks an accelerating trailing stop.",
    [
        _param("step", "Step", 0.02, 0.005, 0.1, "float"),
        _param("maximum", "Maximum step", 0.2, 0.05, 0.5, "float"),
    ],
    _cmp(CLOSE, "crosses_above", _ind("psar", start="$step", step="$step", maximum="$maximum")),
    {
        "long": _cmp(
            CLOSE, "crosses_below", _ind("psar", start="$step", step="$step", maximum="$maximum")
        )
    },
)
_simple(
    "keltner_breakout",
    "Keltner channel breakout",
    "Buy a close above the upper Keltner band; sell when the price returns to the middle line.",
    "Chester Keltner's channel, in Linda Raschke's ATR form: a close beyond two ATRs above "
    "the 20-day EMA is a volatility breakout; a return to the EMA ends it.",
    "Moves strong enough to leave the volatility channel tend to continue.",
    [
        _param("length", "EMA length", 20, 10, 50),
        _param("mult", "ATR multiple", 2.0, 1.0, 3.5, "float"),
    ],
    _cmp(CLOSE, "crosses_above", _ind("keltner", output="upper", period="$length", mult="$mult")),
    {
        "long": _cmp(
            CLOSE, "crosses_below", _ind("keltner", output="middle", period="$length", mult="$mult")
        )
    },
)
_simple(
    "adx_trend",
    "ADX trend (Wilder)",
    "Buy when +DI crosses above −DI while ADX shows a real trend (above 25); sell on the cross back.",
    "Welles Wilder's directional system: the DI lines say who is winning, ADX says whether "
    "there is a trend at all. Only trading when ADX is above 25 skips most sideways chop.",
    "Strong trends, once confirmed, keep going.",
    [
        _param("length", "DI length", 14, 7, 30),
        _param("min_adx", "Minimum ADX", 25, 15, 40),
    ],
    _all(
        _cmp(
            _ind("adx", output="plus_di", period="$length"),
            "crosses_above",
            _ind("adx", output="minus_di", period="$length"),
        ),
        _cmp(_ind("adx", output="adx", period="$length"), "above", _num("$min_adx")),
    ),
    {
        "long": _cmp(
            _ind("adx", output="plus_di", period="$length"),
            "crosses_below",
            _ind("adx", output="minus_di", period="$length"),
        ),
        "stop_loss": {"kind": "atr", "value": 3, "atr_period": 14},
    },
)
_simple(
    "williams_r_pullback",
    "Williams %R pullback",
    "In an uptrend, buy when %R climbs back above −80; sell when it reaches −20 or after 15 days.",
    "Larry Williams' %R shows where the close sits in the recent range. Leaving the oversold "
    "zone in a stock above its 200-day average marks the end of a pullback.",
    "Pullbacks in uptrends end when buyers return to the top of the range.",
    [
        _param("length", "%R length", 14, 5, 30),
        _param("oversold", "Oversold level", -80, -95, -60),
    ],
    _all(_cmp(_ind("williams_r", period="$length"), "crosses_above", _num("$oversold")), UPTREND),
    {
        "long": _cmp(_ind("williams_r", period="$length"), "crosses_above", _num(-20)),
        "stop_loss": {"kind": "percent", "value": 7},
        "max_bars": 15,
    },
)
_simple(
    "cci_swing",
    "CCI swing",
    "Buy when CCI climbs back above −100; sell when it reaches +100.",
    "Donald Lambert's commodity channel index measures how far the price is from its "
    "average. A climb back above −100 after a drop below it is a swing low; +100 is a "
    "stretched high to take profits.",
    "Prices swing around their average; extremes revert.",
    [
        _param("length", "CCI length", 20, 10, 50),
        _param("low", "Buy level", -100, -200, -50),
        _param("high", "Sell level", 100, 50, 200),
    ],
    _cmp(_ind("cci", period="$length"), "crosses_above", _num("$low")),
    {
        "long": _cmp(_ind("cci", period="$length"), "crosses_above", _num("$high")),
        "stop_loss": {"kind": "atr", "value": 3, "atr_period": 14},
        "max_bars": 30,
    },
)
_simple(
    "heikin_ashi_trend",
    "Heikin-Ashi trend",
    "Buy when Heikin-Ashi candles turn up (HA close above HA open); sell when they turn down.",
    "Heikin-Ashi ('average bar' in Japanese) smooths candles so a trend shows as a run of one "
    "colour. Trading only the colour changes keeps you in the run and filters single-day noise.",
    "Smoothed candles show the real trend; trade its turns.",
    [_param("stop_pct", "Stop-loss (%)", 8.0, 2.0, 20.0, "float")],
    _cmp(_ind("heikin_ashi", output="close"), "crosses_above", _ind("heikin_ashi", output="open")),
    {
        "long": _cmp(
            _ind("heikin_ashi", output="close"), "crosses_below", _ind("heikin_ashi", output="open")
        ),
        "stop_loss": {"kind": "percent", "value": "$stop_pct"},
    },
)
_simple(
    "vwap_pullback",
    "VWAP reclaim (intraday)",
    "Buy when the price climbs back above the day's VWAP; leave below it or before the close.",
    "Uses 5-minute candles. VWAP is where the day's average buyer stands; a reclaim of it "
    "after the first half hour says buyers are back in control. A small stop and target "
    "limit each trade, and every trade is closed before the end of the day.",
    "Institutions benchmark to VWAP; above it, buyers are winning the day.",
    [
        _param("stop_pct", "Stop-loss (%)", 0.7, 0.2, 3.0, "float"),
        _param("target_pct", "Take-profit (%)", 1.4, 0.3, 6.0, "float"),
    ],
    _all(
        {"type": "time", "after": "09:45", "before": "14:30"},
        _cmp(CLOSE, "crosses_above", _ind("vwap")),
    ),
    {
        "long": _cmp(CLOSE, "crosses_below", _ind("vwap")),
        "stop_loss": {"kind": "percent", "value": "$stop_pct"},
        "take_profit": {"kind": "percent", "value": "$target_pct"},
        "exit_time": "15:10",
    },
    timeframe="5m",
    sizing={"kind": "percent_equity", "value": 20},
    limits={"max_open_positions": 3},
)
_simple(
    "aroon_trend",
    "Aroon trend",
    "Buy when Aroon up crosses above Aroon down and is above 70; sell on the cross back.",
    "Tushar Chande's Aroon counts how recently the highest high and lowest low happened. A "
    "fresh high with an old low is the start of an uptrend.",
    "New highs that keep coming mean a trend is under way.",
    [_param("length", "Aroon length", 25, 10, 60)],
    _all(
        _cmp(
            _ind("aroon", output="up", period="$length"),
            "crosses_above",
            _ind("aroon", output="down", period="$length"),
        ),
        _cmp(_ind("aroon", output="up", period="$length"), "above", _num(70)),
    ),
    {
        "long": _cmp(
            _ind("aroon", output="up", period="$length"),
            "crosses_below",
            _ind("aroon", output="down", period="$length"),
        ),
        "stop_loss": {"kind": "atr", "value": 3, "atr_period": 14},
    },
)
_simple(
    "mfi_reversion",
    "Money-flow oversold bounce",
    "In an uptrend, buy when the money flow index climbs back above 20; sell above 80.",
    "Gene Quong and Avrum Soudack's MFI is a volume-weighted RSI. Selling pressure that dries "
    "up (MFI leaving the oversold zone) in a long uptrend often marks a low.",
    "When heavy selling stops in a strong stock, it bounces.",
    [
        _param("length", "MFI length", 14, 5, 30),
        _param("oversold", "Oversold level", 20, 5, 40),
    ],
    _all(_cmp(_ind("mfi", period="$length"), "crosses_above", _num("$oversold")), UPTREND),
    {
        "long": _cmp(_ind("mfi", period="$length"), "crosses_above", _num(80)),
        "stop_loss": {"kind": "percent", "value": 8},
        "max_bars": 20,
    },
)
_simple(
    "coppock_turn",
    "Coppock curve turn",
    "Buy when the Coppock curve crosses above zero; sell when it crosses back below.",
    "Edwin Coppock's 1962 long-term momentum curve, designed for buying after big declines. "
    "On daily candles it is a slow momentum filter.",
    "After a long decline, a lasting turn in momentum marks the next bull phase.",
    [
        _param("long", "Long ROC", 14, 5, 60),
        _param("short", "Short ROC", 11, 3, 40),
        _param("smooth", "Smoothing (WMA)", 10, 3, 40),
    ],
    _cmp(_ind("coppock", long="$long", short="$short", period="$smooth"), "crosses_above", _num(0)),
    {
        "long": _cmp(
            _ind("coppock", long="$long", short="$short", period="$smooth"),
            "crosses_below",
            _num(0),
        ),
        "stop_loss": {"kind": "percent", "value": 12},
    },
)
_simple(
    "vortex_cross",
    "Vortex crossover",
    "Buy when VI+ crosses above VI−; sell when it crosses back below.",
    "Etienne Botes and Douglas Siepman's vortex indicator (2010) compares upward and "
    "downward movement; their crossings mark trend starts.",
    "When upward movement starts to dominate, a trend begins.",
    [_param("length", "Length (candles)", 14, 7, 40)],
    _cmp(
        _ind("vortex", output="plus", period="$length"),
        "crosses_above",
        _ind("vortex", output="minus", period="$length"),
    ),
    {
        "long": _cmp(
            _ind("vortex", output="plus", period="$length"),
            "crosses_below",
            _ind("vortex", output="minus", period="$length"),
        ),
        "stop_loss": {"kind": "atr", "value": 3, "atr_period": 14},
    },
)
_simple(
    "triple_ma",
    "Triple moving average (4-9-18)",
    "Buy when the 4-day EMA crosses above the 9-day with the 9-day above the 18-day; sell when the 4-day falls below the 18-day.",
    "A popular futures-desk system: three averages in order (fast above medium above slow) "
    "confirm a trend; the fastest crossing the slowest ends it.",
    "Averages stacked in order mean a trend at every speed.",
    [
        _param("fast", "Fast EMA", 4, 2, 10),
        _param("mid", "Middle EMA", 9, 5, 20),
        _param("slow", "Slow EMA", 18, 10, 50),
    ],
    _all(
        _cmp(_ind("ema", period="$fast"), "crosses_above", _ind("ema", period="$mid")),
        _cmp(_ind("ema", period="$mid"), "above", _ind("ema", period="$slow")),
    ),
    {"long": _cmp(_ind("ema", period="$fast"), "crosses_below", _ind("ema", period="$slow"))},
)
_simple(
    "fisher_reversal",
    "Fisher transform reversal",
    "Buy when the Fisher transform crosses above its trigger while below −1; sell when it crosses back below.",
    "John Ehlers' Fisher transform turns prices into a near-normal distribution, so extreme "
    "readings stand out. A turn up from a deep low is an early reversal signal.",
    "Statistically extreme lows tend to reverse.",
    [
        _param("length", "Length (candles)", 9, 5, 30),
        _param("depth", "Must be below", -1.0, -3.0, 0.0, "float"),
    ],
    _all(
        _cmp(
            _ind("fisher", output="value", period="$length"),
            "crosses_above",
            _ind("fisher", output="trigger", period="$length"),
        ),
        _cmp(_ind("fisher", output="value", period="$length"), "below", _num("$depth")),
    ),
    {
        "long": _cmp(
            _ind("fisher", output="value", period="$length"),
            "crosses_below",
            _ind("fisher", output="trigger", period="$length"),
        ),
        "stop_loss": {"kind": "atr", "value": 2.5, "atr_period": 14},
        "max_bars": 20,
    },
)
_simple(
    "schaff_cycle",
    "Schaff trend cycle",
    "Buy when the Schaff trend cycle crosses up through 25; sell when it crosses down through 75.",
    "Doug Schaff's cycle runs MACD through a double stochastic, making it faster than MACD "
    "at catching trend turns.",
    "Momentum cycles: catch the up-leg early, leave as it tops.",
    [
        _param("cycle", "Cycle length", 10, 5, 30),
        _param("low", "Buy level", 25, 5, 40),
        _param("high", "Sell level", 75, 60, 95),
    ],
    _cmp(_ind("stc", cycle="$cycle"), "crosses_above", _num("$low")),
    {
        "long": _cmp(_ind("stc", cycle="$cycle"), "crosses_below", _num("$high")),
        "stop_loss": {"kind": "atr", "value": 3, "atr_period": 14},
    },
)


# Templates whose idea needs daily candles (a 52-week high, monthly swings, a weekly screen):
# they aren't tried on other timeframes (D-118).
DAILY_ONLY = {"high_52w_momentum", "coppock_turn", "triple_screen", "golden_cross"}
SHORT_TERM = ("15m", "5m", "1m")  # India: closed the same day (intraday product)


def timeframes_for(key: str) -> tuple[str, ...]:
    """The timeframes a template makes sense on: its own, plus the others when it's a pattern
    that works on any chart (D-118)."""
    t = TEMPLATES[key]
    if t.timeframe != "1d":
        return tuple(dict.fromkeys((t.timeframe, "15m", "5m", "1m")))
    if key in DAILY_ONLY:
        return ("1d",)
    return ("1d", "1h", "15m", "5m", "1m")


def template_definition(
    key: str, market: str, symbols: list[str] | None = None, timeframe: str | None = None
) -> VisualDefinition:
    """The template as a full definition for ``market`` (whole universe unless symbols).

    ``timeframe`` runs a template on another chart (D-118): the same rules on hourly or
    minute candles. In India, 15-, 5- and 1-minute versions are intraday trades (closed by the
    day's square-off); hourly versions hold overnight like daily ones."""
    t = TEMPLATES[key]
    body: dict[str, Any] = _deep_copy(t.body)
    tf = timeframe or t.timeframe
    if tf != t.timeframe:
        body["timeframe"] = tf
        if tf in SHORT_TERM and t.timeframe == "1d":
            body.setdefault("exit", {})["exit_time"] = "15:10"
    if market == "IN":
        body["product"] = "intraday" if tf in SHORT_TERM else "delivery"
    else:
        body["product"] = "cash"
        if tf in SHORT_TERM and "exit_time" in body.get("exit", {}):
            # New York's session: 09:30–16:00 instead of 09:15–15:30
            body["exit"]["exit_time"] = "15:45"
            for side in ("long", "short"):
                rule = body["entry"].get(side)
                if rule and rule.get("type") == "all" and rule["conditions"][0]["type"] == "time":
                    rule["conditions"][0] = {"type": "time", "after": "09:45", "before": "15:00"}
    body["market"] = market
    body["universe"] = (
        {"kind": "symbols", "symbols": symbols} if symbols else {"kind": "all", "symbols": []}
    )
    body["kind"] = "visual"
    return VisualDefinition.model_validate(body)


def _deep_copy(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _deep_copy(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_deep_copy(v) for v in x]
    return x


def catalog() -> list[dict[str, Any]]:
    return [t.public() for t in TEMPLATES.values()]
