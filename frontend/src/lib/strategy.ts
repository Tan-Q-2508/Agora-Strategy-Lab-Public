/**
 * Strategy Definition types (mirror backend/strategy/definition.py) and helpers that turn
 * rules into plain-English text for the block builder.
 */
import type { MarketCode, Timeframe } from "./api";

export type Num = number | string; // a number or "$parameter"
export type PriceField = "open" | "high" | "low" | "close" | "volume" | "hl2" | "typical";

/** A bigger timeframe of the same stock, read on its last finished candle (D-97). */
export type BiggerTf = "1mo" | "1w" | "1d" | "1h" | "15m" | "5m";
export const BIGGER: Record<string, BiggerTf[]> = {
  "1d": ["1w", "1mo"],
  "1h": ["1d", "1w"],
  "15m": ["1h", "1d"],
  "5m": ["15m", "1h", "1d"],
  "1m": ["5m", "15m", "1h"],
};
export const CHART_WORDS: Record<BiggerTf, string> = {
  "1mo": "monthly",
  "1w": "weekly",
  "1d": "daily",
  "1h": "hourly",
  "15m": "15-minute",
  "5m": "5-minute",
};

export interface PriceOperand {
  kind: "price";
  field: PriceField;
  offset?: number;
  times?: Num;
  chart?: BiggerTf | null;
}
export interface IndicatorOperand {
  kind: "indicator";
  name: string;
  params: Record<string, Num>;
  output?: string | null;
  source?: PriceField | null;
  offset?: number;
  times?: Num;
  chart?: BiggerTf | null;
}
export interface NumberOperand {
  kind: "number";
  value: Num;
}
export type Operand = PriceOperand | IndicatorOperand | NumberOperand;

export type CompareOp = "above" | "below" | "at_least" | "at_most" | "crosses_above" | "crosses_below";
export interface Compare {
  type: "compare";
  left: Operand;
  op: CompareOp;
  right: Operand;
}
export interface Between {
  type: "between";
  value: Operand;
  lower: Operand;
  upper: Operand;
}
export interface AllOf {
  type: "all";
  conditions: Condition[];
}
export interface AnyOf {
  type: "any";
  conditions: Condition[];
}
export interface NotOf {
  type: "not";
  condition: Condition;
}
export interface TimeWindow {
  type: "time";
  after?: string | null;
  before?: string | null;
}
export interface PositionCheck {
  type: "position";
  check: "bars_held_at_least" | "profit_pct_at_least" | "loss_pct_at_least";
  value: Num;
}
export type Condition = Compare | Between | AllOf | AnyOf | NotOf | TimeWindow | PositionCheck;

export interface StopSpec {
  kind: "percent" | "atr";
  value: Num;
  atr_period?: number;
}
/** Partial exits (D-125): sell part of the trade at each step, let the rest run. */
export interface ScaleStepSpec {
  kind: "r" | "percent" | "atr";
  value: Num;
  sell_pct: Num;
}
export interface ScaleOutSpec {
  steps: ScaleStepSpec[];
  breakeven: boolean;
}
export interface ParameterDef {
  name: string;
  label: string;
  type: "int" | "float";
  default: number;
  min: number;
  max: number;
  step?: number | null;
}
export type Product = "intraday" | "delivery" | "cash";
export type SizingKind = "percent_equity" | "fixed_qty" | "fixed_amount" | "risk_percent";

interface Common {
  schema_version: 1;
  market: MarketCode;
  universe: { kind: "symbols" | "all"; symbols: string[] };
  timeframe: Timeframe;
  product: Product;
  sizing: { kind: SizingKind; value: Num };
  limits: { max_open_positions: number; max_per_symbol: 1; max_daily_loss_pct: number | null };
  parameters: ParameterDef[];
}
export interface VisualDefinition extends Common {
  kind: "visual";
  entry: { long: Condition | null; short: Condition | null };
  exit: {
    long: Condition | null;
    short: Condition | null;
    stop_loss: StopSpec | null;
    take_profit: StopSpec | null;
    trailing_stop: StopSpec | null;
    scale_out?: ScaleOutSpec | null;
    max_bars: Num | null;
    exit_time: string | null;
  };
}
export interface CodeDefinition extends Common {
  kind: "code";
  code: string;
}
export interface KairosSettings {
  entry_score: Num;
  exit_score: Num;
  stop_atr: Num;
  target_r: Num;
  trail_atr: Num | null;
  partial_r?: Num | null;
  partial_pct?: Num;
  max_bars: Num | null;
  allow_short: boolean;
}
/** The Kairos brain as a strategy (docs/KAIROS.md §9). */
export interface KairosDefinition extends Common {
  kind: "kairos";
  kairos: KairosSettings;
  weights: Record<string, number>;
  trained_at: number | null;
}
/** How a ranking strategy picks its stocks each month (D-91). */
export interface RankingSettings {
  rank_by: "momentum" | "low_volatility";
  lookback_months: number;
  skip_months: number;
  hold: number;
  trend_filter: boolean;
}
/** A cross-sectional strategy: each month, rank the index and hold the top few (D-91). */
export interface RankingDefinition extends Common {
  kind: "ranking";
  ranking: RankingSettings;
}
export type Definition = VisualDefinition | CodeDefinition | KairosDefinition | RankingDefinition;

/** The ranking rules in one plain sentence (mirrors backend/strategy/ranking.py `describe`). */
export function describeRanking(r: RankingSettings): string {
  const how =
    r.rank_by === "momentum"
      ? `${r.lookback_months}-month rise${r.skip_months ? ` (leaving out the latest ${r.skip_months} month${r.skip_months === 1 ? "" : "s"})` : ""}`
      : `calmness over ${r.lookback_months} months`;
  const filter = r.trend_filter ? (r.rank_by === "momentum" ? " that actually rose" : " above their 200-day average") : "";
  return `Each month, rank the stocks by ${how} and hold the top ${r.hold}${filter}, in equal shares.`;
}

export interface Issue {
  path: (string | number)[];
  where: string;
  message: string;
  hint: string;
  severity: "error" | "warning";
}

export interface IndicatorParam {
  name: string;
  label: string;
  default: number;
  min: number;
  max: number;
  type: "int" | "float";
}
export interface IndicatorInfo {
  key: string;
  label: string;
  description: string;
  params: IndicatorParam[];
  outputs: { key: string; label: string }[];
  overlay: boolean;
  uses_source: boolean;
  default_source: PriceField;
  intraday_only: boolean;
  group?: string;
}

// ---------------------------------------------------------------- defaults

export function defaultProduct(market: MarketCode, timeframe: Timeframe): Product {
  if (market === "US") return "cash";
  return timeframe === "1d" ? "delivery" : "intraday";
}

export function blankVisual(market: MarketCode): VisualDefinition {
  return {
    schema_version: 1,
    kind: "visual",
    market,
    universe: { kind: "symbols", symbols: market === "IN" ? ["RELIANCE"] : ["SPY"] },
    timeframe: "1d",
    product: defaultProduct(market, "1d"),
    sizing: { kind: "percent_equity", value: 10 },
    limits: { max_open_positions: 5, max_per_symbol: 1, max_daily_loss_pct: null },
    parameters: [],
    entry: { long: null, short: null },
    exit: { long: null, short: null, stop_loss: null, take_profit: null, trailing_stop: null, max_bars: null, exit_time: null },
  };
}

export const STARTER_CODE = `def on_bar(ctx):
    """Runs once per closed candle for each stock."""
    rsi = ctx.ind.rsi(ctx.close, 14)
    if not ctx.position and rsi[-1] < 30:
        ctx.buy(size=ctx.size.percent_equity(10), stop_loss=ctx.stop.percent(5))
    elif ctx.position and rsi[-1] > 70:
        ctx.sell_all("RSI back above 70")
`;

export function blankCode(market: MarketCode): CodeDefinition {
  const v = blankVisual(market);
  return {
    schema_version: 1,
    kind: "code",
    market,
    universe: v.universe,
    timeframe: v.timeframe,
    product: v.product,
    sizing: v.sizing,
    limits: v.limits,
    parameters: [],
    code: STARTER_CODE,
  };
}

export function defaultCompare(): Compare {
  return {
    type: "compare",
    left: { kind: "indicator", name: "rsi", params: { period: 14 } },
    op: "crosses_below",
    right: { kind: "number", value: 30 },
  };
}

// ---------------------------------------------------------------- words

export const OP_WORDS: Record<CompareOp, string> = {
  above: "is above",
  below: "is below",
  at_least: "is at least",
  at_most: "is at most",
  crosses_above: "crosses above",
  crosses_below: "crosses below",
};

export const FIELD_WORDS: Record<PriceField, string> = {
  open: "Open",
  high: "High",
  low: "Low",
  close: "Close",
  volume: "Volume",
  hl2: "Mid-price (H+L)/2",
  typical: "Typical price",
};

export const SHORT_NAMES: Record<string, string> = {
  sma: "SMA",
  ema: "EMA",
  wma: "WMA",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "Bollinger",
  atr: "ATR",
  adx: "ADX",
  stochastic: "Stochastic",
  cci: "CCI",
  vwap: "VWAP",
  supertrend: "Supertrend",
  donchian: "Donchian",
  keltner: "Keltner",
  obv: "OBV",
  roc: "ROC",
  highest: "Highest",
  lowest: "Lowest",
  high_52w: "52-week high",
  low_52w: "52-week low",
  prev_day: "Previous day",
  opening_range: "Opening range",
};

export function numText(v: Num | undefined | null, params?: ParameterDef[]): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "string") {
    if (!v.startsWith("$")) return v;
    const p = params?.find((x) => x.name === v.slice(1));
    // a parameter shows by its label, minus any "(unit)" note so blocks stay short
    return p ? p.label.replace(/\s*\([^)]*\)\s*$/, "") : v.slice(1).replace(/_/g, " ");
  }
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4)));
}

function suffix(o: { offset?: number; times?: Num; chart?: BiggerTf | null }, params?: ParameterDef[]): string {
  let s = "";
  if (o.chart) s += ` on the ${CHART_WORDS[o.chart]} chart`;
  if (o.times !== undefined && o.times !== 1 && o.times !== "1") s += ` × ${numText(o.times, params)}`;
  if (o.offset) s += o.offset === 1 ? " (1 candle ago)" : ` (${o.offset} candles ago)`;
  return s;
}

export function operandText(o: Operand, catalog?: Record<string, IndicatorInfo>, params?: ParameterDef[]): string {
  if (o.kind === "number") return numText(o.value, params);
  if (o.kind === "price") return FIELD_WORDS[o.field] + suffix(o, params);
  const info = catalog?.[o.name];
  const name = SHORT_NAMES[o.name] ?? info?.label ?? o.name;
  const args = info ? info.params.map((p) => numText(o.params[p.name] ?? p.default, params)) : Object.values(o.params).map((v) => numText(v, params));
  let text = args.length ? `${name}(${args.join(", ")})` : name;
  if (info && info.outputs.length > 1) {
    const out = info.outputs.find((x) => x.key === (o.output ?? info.outputs[0]?.key));
    if (out) text += ` ${out.label.toLowerCase()}`;
  }
  if (o.source && o.source !== (info?.default_source ?? "close")) text += ` of ${FIELD_WORDS[o.source].toLowerCase()}`;
  return text + suffix(o, params);
}

export function conditionText(c: Condition, catalog?: Record<string, IndicatorInfo>): string {
  switch (c.type) {
    case "compare":
      return `${operandText(c.left, catalog)} ${OP_WORDS[c.op]} ${operandText(c.right, catalog)}`;
    case "between":
      return `${operandText(c.value, catalog)} is between ${operandText(c.lower, catalog)} and ${operandText(c.upper, catalog)}`;
    case "all":
      return c.conditions.map((x) => conditionText(x, catalog)).join(" AND ");
    case "any":
      return c.conditions.map((x) => conditionText(x, catalog)).join(" OR ");
    case "not":
      return `NOT (${conditionText(c.condition, catalog)})`;
    case "time":
      return `time is ${c.after ? `after ${c.after}` : ""}${c.after && c.before ? " and " : ""}${c.before ? `before ${c.before}` : ""}`;
    case "position":
      return {
        bars_held_at_least: `in the trade for at least ${numText(c.value)} candles`,
        profit_pct_at_least: `profit is at least ${numText(c.value)}%`,
        loss_pct_at_least: `loss is at least ${numText(c.value)}%`,
      }[c.check];
  }
}

/** True when `issuePath` points inside the block at `blockPath`. */
export function pathWithin(issuePath: (string | number)[], blockPath: (string | number)[]): boolean {
  return blockPath.every((p, i) => issuePath[i] === p);
}

export const PRODUCT_WORDS: Record<Product, string> = {
  intraday: "Intraday (same day)",
  delivery: "Delivery (hold for days)",
  cash: "Cash (US)",
};

export const SIZING_WORDS: Record<SizingKind, { label: string; unit: string; hint: string }> = {
  percent_equity: { label: "% of your money", unit: "%", hint: "Each trade uses this share of the account's current value." },
  fixed_amount: { label: "Fixed amount", unit: "", hint: "Each trade buys about this much money's worth." },
  fixed_qty: { label: "Fixed number of shares", unit: "shares", hint: "Each trade buys exactly this many shares." },
  risk_percent: { label: "Risk % per trade", unit: "%", hint: "Sizes each trade so hitting the stop-loss loses this share of the account." },
};
