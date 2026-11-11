/** Portfolios and opportunities (docs/PORTFOLIO.md): the shapes `/api/portfolios` returns. */
import type { MarketCode } from "./api";

export type Risk = "careful" | "balanced" | "bold";

export const RISK_LABEL: Record<Risk, { label: string; hint: string }> = {
  careful: { label: "Careful", hint: "20% kept in cash, at most 30% in one sleeve, aiming at 10% volatility a year." },
  balanced: { label: "Balanced", hint: "10% kept in cash, at most 40% in one sleeve, aiming at 15% volatility a year." },
  bold: { label: "Bold", hint: "5% kept in cash, at most 50% in one sleeve, aiming at 22% volatility a year." },
};

export interface PlanSleeve {
  key: string;
  name: string;
  strategy_id: number;
  version_id: number;
  symbols: string[];
  weight: number;
  capital: number;
  score: number;
  sharpe: number;
  luck: number;
  volatility: number;
  reasons: string[];
  opportunity_id: number | null;
}

export interface Plan {
  market: MarketCode;
  budget: number;
  risk: Risk;
  sleeves: PlanSleeve[];
  left_out: { name: string; reason: string }[];
  cash: number;
  invested: number;
  method: string;
  estimate: { volatility?: number; return?: number; sharpe?: number; diversification?: number };
  overlaps: string[];
  notes: string[];
  made_at?: number;
}

export interface PortfolioBacktest {
  empty?: boolean;
  start: number;
  end: number;
  budget: number;
  final: number;
  metrics: { total_return?: number | null; cagr?: number | null; max_drawdown?: number | null; sharpe?: number | null; benchmark_return?: number | null };
  curve: [number, number][];
  benchmark: [number, number][];
  sleeves: { name: string; capital: number; final: number; moved: number; made: number; trades: number }[];
  rebalances: number;
  moved: number;
  honesty: string;
  made_at?: number;
}

export interface LiveSleeve {
  id: number;
  strategy_id: number;
  symbols: string[];
  weight: number;
  capital: number;
  status: "planned" | "active" | "winding_down" | "retired";
  session_id: number | null;
  reasons: string[];
  equity: number | null;
  pnl: number | null;
  open_trades: number;
}

export interface Opportunity {
  id: number;
  market: MarketCode;
  strategy_id: number;
  version_id: number;
  name: string;
  symbols: string[];
  overrides: Record<string, number>;
  source: "scanner" | "metis" | "kairos_research" | "user";
  status: "open" | "in_portfolio" | "dismissed" | "stale";
  score: number;
  evidence: string;
  found_at: number;
  checked_at: number;
}

/** How the money is spread (D-91): the best of your strategies, or a monthly ranking. */
export type Method = "mix" | "momentum" | "low_volatility";
export const METHOD_LABEL: Record<Method, { label: string; hint: string }> = {
  mix: { label: "Best strategies", hint: "Split across your strategies and stocks that held up on years they weren't chosen on (the allocator)." },
  momentum: { label: "Momentum", hint: "Each month, hold the index's 10 strongest risers of the past year, in equal shares." },
  low_volatility: { label: "Low volatility", hint: "Each month, hold the index's 10 calmest stocks that are in an uptrend, in equal shares." },
};

export interface PortfolioSummary {
  id: number;
  name: string;
  market: MarketCode;
  budget: number;
  risk: Risk;
  method?: Method;
  status: "draft" | "paper" | "stopped" | "archived";
  manage: boolean;
  created_at: number;
  updated_at: number;
  sleeves_planned: number;
  backtest_return: number | null;
  paper_started_at: number | null;
  live?: { equity: number; cash: number; invested: number; pnl: number; return: number };
}

export interface PortfolioDetail extends PortfolioSummary {
  plan: Plan | Record<string, never>;
  backtest: PortfolioBacktest | Record<string, never>;
  sleeves: LiveSleeve[];
  moves: { id: number; ts: number; kind: string; text: string }[];
  cash: number;
  opportunities: Opportunity[];
}

export const STATUS_WORDS: Record<PortfolioSummary["status"], { label: string; tone: "profit" | "neutral" | "accent" | "warning" }> = {
  draft: { label: "Planned", tone: "neutral" },
  paper: { label: "Paper trading", tone: "profit" },
  stopped: { label: "Stopped", tone: "neutral" },
  archived: { label: "Archived", tone: "neutral" },
};

export const SOURCE_WORDS: Record<Opportunity["source"], string> = {
  scanner: "Found by the scanner",
  metis: "Found by Metis",
  kairos_research: "From Kairos's research",
  user: "Added by you",
};

export function hasPlan(p: PortfolioDetail): p is PortfolioDetail & { plan: Plan } {
  return Array.isArray((p.plan as Plan).sleeves);
}

export function hasBacktest(p: PortfolioDetail): p is PortfolioDetail & { backtest: PortfolioBacktest } {
  return Array.isArray((p.backtest as PortfolioBacktest).curve);
}
