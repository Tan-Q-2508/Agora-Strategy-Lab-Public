/** Checks of strategy revisions (Phase 16): the look-ahead check (D-88) and forward checks on
 * new candles (D-90). */

export type CheckVerdict = "clean" | "lookahead" | "history" | "no_data" | "waiting" | "holding" | "slipping" | "failed";

export interface LookaheadResult {
  verdict: CheckVerdict;
  title: string;
  text: string;
  notes: string[];
  symbols: string[];
  signals: number;
  version: number;
  start: number;
  end: number;
  lookahead: { slices: number; signals_checked: number; indicators_checked: number; findings: { symbol: string; ts: number; kind: string; text: string }[]; leaky_indicators: string[] };
  history: { extra_candles: number | null; signals_compared: number; findings: { symbol: string; ts: number; text: string }[]; unsettled: { indicator: string; max_change_pct: number }[] };
}

export interface ForwardResult {
  verdict: CheckVerdict;
  title: string;
  text: string;
  subject: "revision" | "new_strategy" | "sleeve";
  name: string;
  since: number;
  sessions: number;
  trades: number;
  numbers: { label: string; value: string }[];
  can_undo: boolean;
  undo_label?: string;
}

export interface CheckRow<R = LookaheadResult | ForwardResult> {
  id: number;
  kind: "lookahead" | "forward";
  created_at: number;
  strategy_id: number;
  strategy_name?: string;
  version_id: number;
  version: number | null;
  baseline_version_id: number | null;
  sleeve_id: number | null;
  portfolio_id: number | null;
  verdict: CheckVerdict;
  title: string;
  result: R;
  action: string;
}

export const VERDICT_TONE: Record<CheckVerdict, "profit" | "loss" | "warning" | "neutral" | "info"> = {
  clean: "profit",
  holding: "profit",
  lookahead: "loss",
  failed: "loss",
  history: "warning",
  slipping: "warning",
  waiting: "neutral",
  no_data: "neutral",
};

export const VERDICT_WORDS: Record<CheckVerdict, string> = {
  clean: "Passed",
  lookahead: "Look-ahead found",
  history: "Depends on history",
  no_data: "No prices",
  waiting: "Waiting for candles",
  holding: "Holding up",
  slipping: "Slipping",
  failed: "Stopped holding up",
};
