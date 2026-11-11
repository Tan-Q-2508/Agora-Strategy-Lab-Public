"""The Strategy Definition (SPEC §5.1): the one format every strategy compiles to.

Visual strategies are a tree of plain-English conditions; code strategies carry Python
source for the sandbox. Both share the same settings (market, universe, timeframe,
product, sizing, limits, parameters), so the engine treats them alike.

The models are strict (unknown keys are rejected) and flat enough that a small local AI
model can fill them in from the JSON schema (AI_ASSISTANT §5.4). Numbers may be written as
``"$name"`` to refer to a named parameter, which is how parameter sweeps work.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
PARAM_NAME = r"^[a-z][a-z0-9_]{0,31}$"
REF = re.compile(r"^\$([a-z][a-z0-9_]{0,31})$")

Num = float | str  # a number, or "$parameter_name"
PriceField = Literal["open", "high", "low", "close", "volume", "hl2", "typical"]
# A bigger timeframe of the same stock (D-97): read on its last finished candle.
BiggerTf = Literal["1w", "1mo", "1d", "1h", "15m", "5m"]
CHART_FIELD = Field(
    None,
    description="Read this on a bigger chart of the same stock (e.g. '1w' on a daily "
    "strategy), using its last finished candle. Empty = the strategy's own chart.",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- operands


class PriceOperand(_Strict):
    kind: Literal["price"] = "price"
    field: PriceField = "close"
    offset: int = Field(0, ge=0, le=500, description="Candles ago (0 = the latest closed candle).")
    times: Num = Field(1.0, description="Multiply the value, e.g. 1.02 for 2% above.")
    chart: BiggerTf | None = CHART_FIELD


class IndicatorOperand(_Strict):
    kind: Literal["indicator"] = "indicator"
    name: str = Field(description="Indicator key from the catalog, e.g. 'rsi' or 'sma'.")
    params: dict[str, Num] = Field(default_factory=dict)
    output: str | None = Field(None, description="Which line, e.g. 'upper'. Default: the main one.")
    source: PriceField | None = Field(None, description="Price the indicator is computed on.")
    offset: int = Field(0, ge=0, le=500)
    times: Num = 1.0
    chart: BiggerTf | None = CHART_FIELD


class NumberOperand(_Strict):
    kind: Literal["number"] = "number"
    value: Num


Operand = Annotated[PriceOperand | IndicatorOperand | NumberOperand, Field(discriminator="kind")]


# ---------------------------------------------------------------- conditions

CompareOp = Literal["above", "below", "at_least", "at_most", "crosses_above", "crosses_below"]


class Compare(_Strict):
    type: Literal["compare"] = "compare"
    left: Operand
    op: CompareOp
    right: Operand


class Between(_Strict):
    type: Literal["between"] = "between"
    value: Operand
    lower: Operand
    upper: Operand


class AllOf(_Strict):
    type: Literal["all"] = "all"
    conditions: list[Condition] = Field(min_length=1, max_length=20)


class AnyOf(_Strict):
    type: Literal["any"] = "any"
    conditions: list[Condition] = Field(min_length=1, max_length=20)


class NotOf(_Strict):
    type: Literal["not"] = "not"
    condition: Condition


class TimeWindow(_Strict):
    """True when the candle opens within [after, before) in the market's local time."""

    type: Literal["time"] = "time"
    after: str | None = Field(None, pattern=HHMM)
    before: str | None = Field(None, pattern=HHMM)


class PositionCheck(_Strict):
    """Facts about the open position (only meaningful in exit rules)."""

    type: Literal["position"] = "position"
    check: Literal["bars_held_at_least", "profit_pct_at_least", "loss_pct_at_least"]
    value: Num


Condition = Annotated[
    Compare | Between | AllOf | AnyOf | NotOf | TimeWindow | PositionCheck,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------- rules & settings


class EntryRules(_Strict):
    long: Condition | None = Field(None, description="When to buy.")
    short: Condition | None = Field(None, description="When to short-sell (US, India intraday).")


class StopSpec(_Strict):
    kind: Literal["percent", "atr"]
    value: Num = Field(description="Percent of the entry price, or a multiple of ATR.")
    atr_period: int = Field(14, ge=1, le=200)


class ScaleStepSpec(_Strict):
    kind: Literal["r", "percent", "atr"] = Field(
        "r",
        description='How the profit is measured: "r" = multiples of the stop distance '
        '(needs a stop-loss), "percent" of the entry price, or "atr" (ATR(14)).',
    )
    value: Num = Field(description="How far in profit, e.g. 1 = one R.")
    sell_pct: Num = Field(description="Percent of the starting position sold here (1–99).")


class ScaleOutSpec(_Strict):
    """Partial exits (D-125): book part of the profit and let the rest run."""

    steps: list[ScaleStepSpec] = Field(min_length=1, max_length=3)
    breakeven: bool = Field(
        True, description="After the first partial exit, move the stop to the entry price."
    )


class ExitRules(_Strict):
    long: Condition | None = Field(None, description="When to sell a long position.")
    short: Condition | None = Field(None, description="When to buy back a short position.")
    stop_loss: StopSpec | None = None
    take_profit: StopSpec | None = None
    trailing_stop: StopSpec | None = None
    scale_out: ScaleOutSpec | None = Field(
        None,
        description="Partial exits: e.g. sell 50% at 1R, move the stop to the entry, and let "
        "the rest ride the trailing stop or target.",
    )
    max_bars: Num | None = Field(None, description="Exit after this many candles in a trade.")
    exit_time: str | None = Field(
        None, pattern=HHMM, description="Close intraday trades at this local time."
    )


class Sizing(_Strict):
    kind: Literal["percent_equity", "fixed_qty", "fixed_amount", "risk_percent"] = "percent_equity"
    value: Num = 10.0


class Limits(_Strict):
    max_open_positions: int = Field(5, ge=1, le=100)
    max_per_symbol: Literal[1] = 1
    max_daily_loss_pct: float | None = Field(None, gt=0, le=100)
    # the most of the money one trade may take; without it a tight stop under risk-based sizing
    # can put the whole account in one trade (D-131)
    max_position_pct: float | None = Field(None, gt=0, le=100)
    # the most open trades in one sector (D-168): a desk held six trades on the oil price at once
    max_per_group: int | None = Field(None, ge=1, le=100)


class Universe(_Strict):
    kind: Literal["symbols", "all"] = "symbols"
    symbols: list[str] = Field(default_factory=list, max_length=500)  # a watchlist's limit (D-191)


class ParameterDef(_Strict):
    name: str = Field(pattern=PARAM_NAME)
    label: str = Field(min_length=1, max_length=60)
    type: Literal["int", "float"] = "int"
    default: float
    min: float
    max: float
    step: float | None = None


class _Common(_Strict):
    schema_version: Literal[1] = 1
    market: Literal["IN", "US"]
    universe: Universe = Field(default_factory=Universe)
    timeframe: Literal["1d", "1h", "15m", "5m", "1m"] = "1d"
    product: Literal["intraday", "delivery", "cash"]
    sizing: Sizing = Field(default_factory=Sizing)
    limits: Limits = Field(default_factory=Limits)
    parameters: list[ParameterDef] = Field(default_factory=list, max_length=12)


class VisualDefinition(_Common):
    kind: Literal["visual"] = "visual"
    entry: EntryRules
    exit: ExitRules = Field(default_factory=ExitRules)


class CodeDefinition(_Common):
    kind: Literal["code"] = "code"
    code: str = Field(min_length=1, max_length=50_000)


class KairosSettings(_Strict):
    """How the Kairos brain trades (KAIROS §9). Numbers may be "$parameter" references."""

    entry_score: Num = Field(40.0, description="Enter when the score reaches this (10–90).")
    exit_score: Num = Field(
        20.0, description="Leave when the score turns this far against the trade (0–90)."
    )
    stop_atr: Num = Field(
        2.0, description="Widest stop, in ATRs (a pattern's own stop if tighter)."
    )
    target_r: Num = Field(2.5, description="Target as a multiple of the risk, if no measured move.")
    trail_atr: Num | None = Field(None, description="Optional trailing stop in ATRs.")
    partial_r: Num | None = Field(
        None,
        description="Partial exit (D-125): sell partial_pct of the trade once it is this many "
        "R in profit, then move the stop to the entry price. Empty = off.",
    )
    partial_pct: Num = Field(50.0, description="Percent of the trade sold at partial_r.")
    max_bars: Num | None = Field(30.0, description="Leave after this many candles in a trade.")
    allow_short: bool = Field(True, description="Short-sell where allowed (US, India intraday).")
    bigger_chart: BiggerTf | None = Field(
        None,
        description="Only trade with the trend of this bigger chart (e.g. '1w' for a daily "
        "desk): no buying while it falls, no shorting while it rises (D-97).",
    )
    bigger_charts: list[BiggerTf] | None = Field(
        None,
        description="Read every one of these bigger charts together (D-132): the first works like "
        "bigger_chart; the others say no only when their trend is clearly against the trade.",
    )


class KairosDefinition(_Common):
    """The Kairos brain as a strategy (D-60): it decides from the analyst's signals,
    weighted by how each signal has worked (``weights``, a snapshot from training)."""

    kind: Literal["kairos"] = "kairos"
    sizing: Sizing = Field(default_factory=lambda: Sizing(kind="risk_percent", value=1.0))
    kairos: KairosSettings = Field(default_factory=KairosSettings)
    weights: dict[str, float] = Field(default_factory=dict, max_length=500)
    trained_at: int | None = None


class RankingSettings(_Strict):
    """How a ranking strategy picks its stocks each month (D-91). Plain numbers: a ranking is
    judged as a whole, not swept."""

    rank_by: Literal["momentum", "low_volatility"] = Field(
        "momentum",
        description="Momentum: the biggest risers. Low volatility: the calmest stocks.",
    )
    lookback_months: int = Field(12, ge=1, le=24, description="Months of history to rank on.")
    skip_months: int = Field(
        1, ge=0, le=3, description="Momentum: leave out the latest months (they tend to reverse)."
    )
    hold: int = Field(10, ge=1, le=30, description="How many of the top-ranked stocks to hold.")
    trend_filter: bool = Field(
        True,
        description="Momentum: only stocks that rose over the period. Low volatility: only "
        "stocks above their 200-day average.",
    )


class RankingDefinition(_Common):
    """A cross-sectional strategy (D-91): each month, rank every stock of the universe and hold
    the top few in equal shares. Its sizing and open-trade limit follow from ``hold``."""

    kind: Literal["ranking"] = "ranking"
    timeframe: Literal["1d"] = "1d"
    universe: Universe = Field(default_factory=lambda: Universe(kind="all"))
    ranking: RankingSettings = Field(default_factory=RankingSettings)

    @model_validator(mode="after")
    def _derived(self) -> RankingDefinition:
        # an equal share each (95% invested); room for a rebalance's sells and buys to overlap
        # on one day (the sells fill first at the next open, so the money is there)
        self.sizing = Sizing(kind="percent_equity", value=round(95.0 / self.ranking.hold, 2))
        self.limits = Limits(max_open_positions=min(100, 2 * self.ranking.hold))
        self.parameters = []
        return self


class CombineSettings(_Strict):
    """How several strategies act as one (D-227)."""

    mode: Literal["all", "any", "veto", "vote"] = "all"
    min_votes: int = Field(2, ge=1, le=5)
    window: int = Field(5, ge=0, le=30, description="Candles a member's signal stays good for.")


class CombinedMember(_Strict):
    name: str = Field(max_length=200)
    version_id: int | None = None
    definition: dict[str, Any]


class CombinedDefinition(_Common):
    """Two or more strategies acting as one (D-227): ``backend/strategy/combined.py``."""

    kind: Literal["combined"] = "combined"
    combine: CombineSettings = Field(default_factory=CombineSettings)
    members: list[CombinedMember] = Field(min_length=2, max_length=5)


AnyDefinition = (
    VisualDefinition | CodeDefinition | KairosDefinition | RankingDefinition | CombinedDefinition
)
Definition = Annotated[AnyDefinition, Field(discriminator="kind")]

for _m in (AllOf, AnyOf, NotOf, EntryRules, ExitRules, VisualDefinition):
    _m.model_rebuild()


# ---------------------------------------------------------------- helpers


# Optional fields added after strategies were already saved: left out of the stored JSON while
# empty, so every strategy saved before keeps exactly the same text and hash.
LATER_OPTIONAL = frozenset({"chart", "bigger_chart", "bigger_charts", "max_position_pct"})


def _drop_empty_later(x: Any) -> Any:
    if isinstance(x, dict):
        return {
            k: _drop_empty_later(v) for k, v in x.items() if not (k in LATER_OPTIONAL and v is None)
        }
    if isinstance(x, list):
        return [_drop_empty_later(v) for v in x]
    return x


def canonical_json(defn: AnyDefinition) -> str:
    """Stable JSON (sorted keys, defaults included) so equal strategies hash equally."""
    data = _drop_empty_later(defn.model_dump(mode="json"))
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def content_hash(defn: AnyDefinition) -> str:
    return hashlib.sha256(canonical_json(defn).encode()).hexdigest()


def param_ref(value: Any) -> str | None:
    """The parameter name if ``value`` is a "$name" reference."""
    if isinstance(value, str):
        m = REF.match(value)
        if m:
            return m.group(1)
    return None


def resolve_num(value: Num, params: dict[str, float]) -> float:
    name = param_ref(value)
    if name is not None:
        return float(params[name])
    if isinstance(value, str):
        raise ValueError(f"'{value}' is not a number or a $parameter")
    return float(value)


def json_schema() -> dict[str, Any]:
    """The JSON schema of a visual definition (for the AI helper's structured output)."""
    return VisualDefinition.model_json_schema()
