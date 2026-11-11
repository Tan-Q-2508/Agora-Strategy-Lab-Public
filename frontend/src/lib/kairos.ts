/** What the backend's chart reading (`/api/analysis/chart`) returns (docs/KAIROS.md §3, §5). */

export type Bias = "bullish" | "bearish" | "neutral";

export interface Pt {
  ts: number;
  value: number;
  label?: string;
}

export interface SignalStats {
  n: number;
  hit_rate: number;
  avg_return_pct?: number;
  base_rate?: number;
  horizon?: number;
}

export interface Zone {
  low: number;
  high: number;
  center: number;
  role: "support" | "resistance" | "testing";
  strength: number;
  touches: number;
  flipped: boolean;
  from_ts: number;
  label: string;
}

export interface TrendLineInfo {
  kind: "support" | "resistance";
  from: Pt;
  to: Pt;
  touches: number;
  broken: boolean;
  broken_ts: number | null;
  value_now: number;
  label: string;
}

export interface PatternInfo {
  key: string;
  name: string;
  bias: Bias;
  status: "forming" | "confirmed" | "target" | "failed";
  confidence: number;
  provisional: boolean;
  points: Pt[];
  upper: { from: Pt; to: Pt } | null;
  lower: { from: Pt; to: Pt } | null;
  trigger: number;
  target: number;
  stop: number;
  start_ts: number;
  event_ts: number | null;
  resolved_ts: number | null;
  volume_confirmed: boolean;
  explanation: string;
  stats: SignalStats | null;
}

export interface CandleInfo {
  ts: number;
  key: string;
  name: string;
  bias: Bias;
  meaning: string;
  high: number;
  low: number;
  stats: SignalStats | null;
}

export interface DivergenceInfo {
  kind: string;
  label: string;
  bullish: boolean;
  strong: boolean;
  from: Pt;
  to: Pt;
  rsi_from: number;
  rsi_to: number;
  known_ts: number;
  stats: SignalStats | null;
}

export interface Idea {
  direction: "long" | "short";
  action: string;
  entry: number;
  wait: "now" | "breakout" | "pullback";
  stop: number;
  target: number;
  reward_risk: number;
  risk_pct: number;
  quality: "good" | "fair" | "poor";
  text: string;
}

export interface ChartReport {
  symbol: string;
  name: string;
  market: "IN" | "US";
  timeframe: string;
  as_of: number;
  close: number;
  change_pct: number;
  atr: number;
  score: number;
  bias: Bias;
  confidence: "low" | "medium" | "high";
  components: Record<string, number>;
  trend: {
    score: number;
    regime: string;
    structure: number;
    adx: number | null;
    sma200: number | null;
    atr_pct: number;
    volatility: string;
  };
  momentum: { score: number; rsi: number; rsi_state: string; macd_above_signal: boolean; notes: string[] };
  volume: { has_volume: boolean; rvol: number | null; accumulation_days: number; distribution_days: number; cmf: number; notes: string[] };
  zones: Zone[];
  lines: TrendLineInfo[];
  channel: string | null;
  patterns: PatternInfo[];
  candles: CandleInfo[];
  divergences: DivergenceInfo[];
  fibonacci: { up: boolean; from: Pt; to: Pt; levels: { ratio: number; price: number; label: string }[]; nearest: string | null } | null;
  idea: Idea | null;
  invalidation: string | null;
  headline: string;
  summary: string[];
  future: number[];
}

export interface ForecastPoint {
  ts: number;
  p10: number;
  p25: number;
  median: number;
  p75: number;
  p90: number;
}

export interface PredictedCandle {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  p10: number;
  p90: number;
  direction: -1 | 0 | 1;
}

export interface PredictionCheck {
  ts: number;
  actual: { open: number; high: number; low: number; close: number };
  predicted?: { open: number; high: number; low: number; close: number };
  direction_right?: boolean;
  inside80?: boolean;
  p10?: number;
  p90?: number;
}

/** Kairos's last prediction for this stock next to the candles that formed (KAIROS §17). */
export interface PreviousPrediction {
  kind: "live" | "re-created";
  made_at: number;
  origin: number;
  formed: number;
  horizon: number;
  complete: boolean;
  candles: PredictionCheck[];
  predicted: PredictedCandle[];
  direction_hits?: number;
  direction_scored?: number;
  inside80?: number;
  predicted_change_pct?: number | null;
  actual_change_pct?: number;
  end_error_pct?: number | null;
  text?: string;
}

export interface ForecastInfo {
  horizon: number;
  origin: number;
  path: ForecastPoint[];
  up_probability: number;
  median_change_pct: number;
  range80_pct: [number, number];
  weights: Record<string, number>;
  track: {
    tests: number;
    direction_hits: number;
    direction_rate: number;
    skill_pct: number;
    band80: number;
    band50: number;
  } | null;
  text: string;
  verdict: string;
  edge: boolean;
  peers: number;
  /** Forecasts Kairos showed for this stock and later checked against what happened. */
  live?: { n: number; direction_hits: number; inside80: number; pending: number } | null;
  candles?: PredictedCandle[];
  previous?: PreviousPrediction | null;
  calibration?: { width: number; bias: number; tests: number; live: number; coverage: number | null; text: string; checked?: number };
  analyst?: { beta: number; score: number; news_tilt: number } | null;
  news?: { stock?: string; risk?: number; tilt?: number; widen_pct?: number } | null;
}

/** One timeframe's trend and momentum, and the verdict over all of them (D-97). */
export interface TimeframeReading {
  timeframe: string;
  label: string;
  candles: number;
  trend: number;
  regime: string;
  momentum: number;
  rsi: number;
  above_sma50: boolean | null;
  above_sma200: boolean | null;
  direction: -1 | 0 | 1;
}
export interface Timeframes {
  chart: string;
  timeframes: TimeframeReading[];
  score: number;
  verdict: "aligned_up" | "aligned_down" | "pullback_in_uptrend" | "bounce_in_downtrend" | "sideways" | "mixed" | "unknown";
  headline: string;
  text: string;
  long_ok: boolean;
  short_ok: boolean;
}

export interface ChartReading {
  instrument: { id: number; symbol: string; name: string; market: "IN" | "US" };
  timeframe: string;
  report: ChartReport;
  timeframes?: Timeframes | null;
  /** Set while Kairos studies this market's history for the first time (KAIROS §8.1). */
  training_job?: string | null;
  forecast: ForecastInfo | null;
  disclaimer: string;
  computed_ms: number;
}

export type KairosLayer = "levels" | "lines" | "patterns" | "candles" | "forecast" | "predicted" | "lastPrediction" | "fibonacci" | "idea";

export const DEFAULT_LAYERS: Record<KairosLayer, boolean> = {
  levels: true,
  lines: true,
  patterns: true,
  candles: true,
  forecast: true,
  predicted: true,
  lastPrediction: true,
  fibonacci: false,
  idea: false,
};

export const LAYER_LABEL: Record<KairosLayer, string> = {
  levels: "Support & resistance",
  lines: "Trendlines",
  patterns: "Chart patterns",
  candles: "Candlesticks",
  forecast: "Forecast range",
  predicted: "Predicted candles",
  lastPrediction: "Last prediction vs what happened",
  fibonacci: "Fibonacci",
  idea: "Trade idea",
};

export interface NewsItem {
  id: number;
  title: string;
  summary: string;
  link: string;
  publisher: string;
  source?: string;
  published_at: number;
  sentiment: number;
  tone: "positive" | "negative" | "neutral";
  symbols: string[];
  topics?: string[];
  topic_labels?: string[];
  group?: string | null;
  severity?: number;
  impact?: number;
  scope?: "IN" | "US" | "WORLD";
  sectors?: Record<string, number>;
}

export type RiskName = "calm" | "watchful" | "elevated" | "severe";

export interface RiskDriver {
  title: string;
  link?: string | null;
  publisher?: string | null;
  published_at: number;
  topic: string | null;
  topic_label: string;
  severity: number;
  impact: number;
  sources: number;
  weight: number;
}

export interface NewsRisk {
  market: "IN" | "US" | "WORLD";
  level: number;
  name: RiskName;
  text: string;
  score: number;
  drivers: RiskDriver[];
  headlines: number;
  as_of: number;
}

export interface StockAlert {
  state: "critical" | "negative" | "positive" | "quiet";
  score: number;
  count: number;
  headline: string | null;
  flag?: string;
}

export interface NewsResponse {
  enabled: boolean;
  refreshing: boolean;
  sources: string[];
  items: NewsItem[];
  mood?: { score: number; count: number; tone: "positive" | "negative" | "neutral" | "quiet" };
  alert?: StockAlert;
  risk?: NewsRisk;
}

export type GuardMode = "protective" | "cautious" | "off";

export interface LiveNews {
  enabled: boolean;
  refreshing: boolean;
  sources: string[];
  items: NewsItem[];
  risk: Record<"IN" | "US" | "WORLD", NewsRisk>;
  guard: GuardMode;
  groups: string[];
  topics: { key: string; label: string; group: string }[];
  as_of: number;
}
