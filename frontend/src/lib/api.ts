/** Thin wrapper around the backend API. Every failure becomes a plain-English ApiError. */

export interface ErrorEnvelope {
  code: string;
  message: string;
  action: string;
  detail: string;
}

export class ApiError extends Error {
  readonly envelope: ErrorEnvelope;

  constructor(envelope: ErrorEnvelope) {
    super(envelope.message);
    this.envelope = envelope;
  }
}

export interface Health {
  app: string;
  status: "ok" | "degraded";
  version: string;
  db_ok: boolean;
  data_sources: { source: string; state: string; until: number | null }[];
  ai: { state: string; models?: string[] };
  server_time: number;
}

export interface MarketStatus {
  market: "IN" | "US";
  name: string;
  is_open: boolean;
  next_change: number;
  next_change_display: string;
  seconds_to_change: number;
  approximate: boolean;
}

export interface SettingsResponse {
  values: Record<string, unknown>;
  meta: Record<string, { default: unknown; description: string }>;
}

const OFFLINE: ErrorEnvelope = {
  code: "BACKEND_UNREACHABLE",
  message: "Agora isn't running.",
  action: "Double-click Start Agora again.",
  detail: "",
};

export function toEnvelope(err: unknown): ErrorEnvelope {
  if (err instanceof ApiError) return err.envelope;
  return {
    code: "UNKNOWN",
    message: "Something went wrong.",
    action: "Try again.",
    detail: String(err),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch (err) {
    throw new ApiError({ ...OFFLINE, detail: String(err) });
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const env = (body as { error?: ErrorEnvelope } | null)?.error;
    throw new ApiError(
      env ?? {
        code: `HTTP_${response.status}`,
        message: "Agora couldn't complete that request.",
        action: "Try again.",
        detail: `HTTP ${response.status}`,
      },
    );
  }
  return body as T;
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function putJson<T>(path: string, data: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function postJson<T>(path: string, data: unknown = {}): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function patchJson<T>(path: string, data: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deleteJson<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

/** Build "?a=1&b=2" from defined values only. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

// ---------------------------------------------------------------- data

export type MarketCode = "IN" | "US";
export type Timeframe = "1d" | "1h" | "15m" | "5m" | "1m";

export interface Instrument {
  id: number;
  market: MarketCode;
  symbol: string;
  yahoo_symbol: string;
  name: string;
  type: "equity" | "etf" | "index";
}

export interface CoverageRow {
  instrument_id: number;
  symbol: string;
  name: string;
  market: MarketCode;
  type: string;
  first: number | null;
  last: number | null;
  bars: number;
  gaps: number;
  stale: boolean;
  source: string | null;
  status: "ok" | "gaps" | "stale" | "empty";
  days?: number;
}

export interface CoverageResponse {
  timeframe: Timeframe;
  rows: CoverageRow[];
  totals: { symbols: number; ok: number; empty: number; stale: number; gaps: number };
  last_update: number | null;
  data_mode: "real" | "fake";
}

export interface SourceInfo {
  source: string;
  label: string;
  state: "ok" | "cooling_down" | "down";
  until: number | null;
  last_error: string | null;
}

export interface FetchLogRow {
  source: string;
  symbol: string | null;
  timeframe: string | null;
  status: "ok" | "empty" | "rate_limited" | "error" | "fallback";
  rows: number;
  message: string;
  at: number;
  duration_ms: number;
}

export interface Job<R = unknown> {
  job_id: string;
  kind: string;
  title: string;
  key?: string | null;
  created_at?: number;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  pct: number;
  eta_s: number | null;
  message: string;
  result: R | null;
  error: ErrorEnvelope | null;
}

export interface RefreshResult {
  symbols: number;
  fetched: number;
  failed: { symbol: string; timeframe: string; problem: string }[];
  fallback_used: boolean;
}

export interface CandleRow {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: string;
}

export interface CandlesResponse {
  instrument: Instrument;
  timeframe: Timeframe;
  adjusted: boolean;
  bars: CandleRow[];
  note: string | null;
}

// ---------------------------------------------------------------- strategies & backtests

export interface StrategySummary {
  id: number;
  name: string;
  description: string;
  kind: "visual" | "code" | "kairos" | "ranking" | "combined";
  market: MarketCode;
  created_at: number;
  updated_at: number;
  archived: boolean;
  template_key: string | null;
  version: number | null;
  version_id: number | null;
  timeframe: Timeframe | null;
  /** Who made the current revision, and when (docs/REVISIONS.md). */
  version_author?: "user" | "ai_draft" | "kairos" | "metis" | null;
  version_at?: number | null;
  last_backtest: { run_id: number; total_return: number | null; max_drawdown: number | null; trades: number | null; created_at: number; points: number[] } | null;
}

export interface SavedVersion<D = unknown> {
  id: number;
  strategy_id: number;
  version: number;
  definition: D;
  content_hash: string;
  created_at: number;
  note: string;
  created_by: "user" | "ai_draft" | "kairos" | "metis";
  /** Revision control (docs/REVISIONS.md): who, from which revision, what changed and why. */
  author_label?: string;
  parent_version_id?: number | null;
  changes?: string[];
  evidence?: { verdict?: string; test?: string } & Record<string, unknown>;
  source?: string;
}

export interface TemplateInfo {
  key: string;
  name: string;
  summary: string;
  description: string;
  idea: string;
  timeframe: Timeframe;
  /** "ranking": compares the stocks each month (D-91); otherwise rules on each chart. */
  kind?: "visual" | "ranking";
}

export interface Headline {
  total_return: number | null;
  cagr: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  win_rate: number | null;
  trades: number | null;
  vs_benchmark: number | null;
  final_equity: number | null;
}

export interface BacktestBrief {
  id: number;
  name: string | null;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  starred: boolean;
  created_at: number;
  finished_at: number | null;
  strategy_id: number;
  strategy_name: string;
  version: number;
  strategy_version_id: number;
  mode: "single" | "oos" | "sweep" | "walk_forward";
  market: MarketCode;
  timeframe: Timeframe;
  symbols: string[];
  start: number;
  end: number;
  capital: number;
  headline: Headline;
  error: string | null;
  parent_run_id: number | null;
  overrides: Record<string, number>;
}

export interface Warning {
  level: "info" | "warn";
  code: string;
  title: string;
  text: string;
}

export type Metrics = Record<string, unknown> & {
  total_return?: number;
  cagr?: number | null;
  max_drawdown?: number;
  sharpe?: number | null;
  monthly_returns?: Record<string, number>;
  per_symbol?: { symbol: string; trades: number; win_rate: number | null; net_pnl: number; charges: number; open_at_end: number }[];
  charges_by_type?: Record<string, number>;
  benchmark?: { total_return: number | null; cagr: number | null; max_drawdown: number };
};

export interface BacktestDetail extends BacktestBrief {
  params: Record<string, unknown>;
  metrics: Metrics | null;
  warnings: Warning[];
  summary: string | null;
  error_detail: string | null;
  repro: Record<string, unknown> | null;
  job: Job | null;
}

export interface EquityResponse {
  points: { ts: number; equity: number; cash: number; exposure: number; drawdown: number }[];
  benchmark: { ts: number; value: number }[];
  capital: number;
}

export interface TradeRow {
  id: number;
  symbol: string;
  side: "long" | "short";
  qty: number;
  entry_ts: number;
  entry_price: number;
  exit_ts: number | null;
  exit_price: number | null;
  gross_pnl: number;
  charges: number;
  net_pnl: number;
  return_pct: number;
  bars_held: number;
  entry_reason: string;
  exit_reason: string | null;
}

export interface CostProfiles {
  brokerage: { id: number; market: MarketCode; name: string; rules: Record<string, unknown>; is_default: boolean }[];
  slippage: { id: number; market: MarketCode; name: string; bps: number; is_default: boolean }[];
}

// ---------------------------------------------------------------- paper trading

export type PaperState = "starting" | "running" | "paused_data" | "paused_user" | "stopped";

export interface PaperAccount {
  id: number;
  name: string;
  market: MarketCode;
  starting_capital: number;
  brokerage_profile_id: number;
  slippage_bps: number;
  created_at: number;
}

export interface Freshness {
  level: "green" | "amber" | "red" | "closed";
  text: string;
  delay_s: number;
  last_bar_ts?: number | null;
  delayed?: boolean;
}

export interface PaperPosition {
  instrument_id: number;
  symbol: string;
  side: "long" | "short";
  qty: number;
  entry_price: number;
  entry_ts: number;
  last_price: number | null;
  unrealized: number | null;
  unrealized_pct: number | null;
  stop: number | null;
  target: number | null;
  /** D-210: the stop follows the price; trail_on when it has moved past the first stop. */
  trailing?: boolean;
  trail_on?: boolean;
  /** D-210: where part of the trade is sold (the stop then moves to the entry). */
  partial_at?: number | null;
  reason: string;
}

export interface PaperSessionSummary {
  id: number;
  name: string;
  kind?: "visual" | "code" | "kairos" | "ranking";
  strategy_id: number;
  strategy_version_id: number;
  version: number;
  market: MarketCode;
  timeframe: Timeframe;
  product: string;
  symbols: string[];
  universe: "symbols" | "all";
  account: PaperAccount;
  state: PaperState;
  mode: "live" | "replay";
  started_at: number;
  stopped_at: number | null;
  last_bar_ts: number | null;
  equity: number;
  total_return: number;
  first_capital?: number;
  moved?: number;
  day_pnl: number;
  open_positions: number;
  trades: number;
  freshness: Freshness | null;
  problem: string | null;
  now: number | null;
  gaps: { from: number; to: number }[];
}

export interface PaperFillRow {
  id: number;
  ts: number;
  symbol: string;
  instrument_id: number;
  side: "buy" | "sell";
  type: string;
  qty: number;
  price: number;
  charges: number;
  reason: string;
}

export interface PaperTradeRow {
  id: number;
  symbol: string;
  instrument_id: number;
  side: "long" | "short";
  qty: number;
  entry_ts: number;
  entry_price: number;
  exit_ts: number | null;
  exit_price: number | null;
  net_pnl: number;
  return_pct: number;
  charges: number;
  entry_reason: string;
  exit_reason: string | null;
}

export interface PaperEventRow {
  id: number;
  ts: number;
  level: "info" | "warn" | "error";
  kind: string;
  message_plain: string;
}

/** A paper strategy's whole record (D-209); every number but `trades` is missing with no trades. */
export interface PaperStats {
  trades: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
  net_pnl?: number;
  charges?: number;
  avg_pnl?: number;
  avg_win?: number | null;
  avg_loss?: number | null;
  profit_factor?: number | null;
  biggest_win?: number | null;
  biggest_win_pct?: number | null;
  biggest_loss?: number | null;
  biggest_loss_pct?: number | null;
  avg_return_pct?: number;
  median_return_pct?: number | null;
  top10_return_pct?: number | null;
  bottom10_return_pct?: number | null;
  avg_bars_held?: number;
  best_streak?: number;
  worst_streak?: number;
  longs?: number;
  shorts?: number;
  exits?: Record<string, number>;
  first_ts?: number;
  last_ts?: number;
}

export interface PaperSessionDetail extends PaperSessionSummary {
  stats?: PaperStats;
  runs?: number;
  positions: PaperPosition[];
  equity_curve: { ts: number; equity: number; cash: number }[];
  fills: PaperFillRow[];
  rejected: { id: number; ts: number; symbol: string; side: string; reason: string }[];
  closed_trades: PaperTradeRow[];
  events: PaperEventRow[];
  instruments: { id: number; symbol: string }[];
}

export interface PaperTick {
  session_id: number;
  state: PaperState;
  equity: number | null;
  cash: number | null;
  day_pnl: number;
  positions: PaperPosition[];
  freshness: Freshness;
  problem: string | null;
  now: number;
}

export interface VsBacktest {
  ready: boolean;
  message?: string;
  days?: number;
  live?: { total_return: number; final_equity: number; trades: number; win_rate: number | null; net_pnl: number };
  backtest?: { total_return: number; final_equity: number; trades: number; win_rate: number | null; net_pnl: number };
  matched_trades?: number;
  only_backtest?: { symbol: string; entry_ts: number; side: string }[];
  only_live?: { symbol: string; entry_ts: number; side: string }[];
  series?: { label: string; points: { ts: number; value: number }[] }[];
  reasons?: string[];
}
