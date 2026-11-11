/** Metis, Kairos's AI researcher (docs/METIS.md): the shapes `/api/metis` returns. */
import type { MarketCode } from "./api";

export interface MetisPart {
  trades: number;
  wins: number;
  win_rate: number | null;
  net: number;
  gross: number;
  charges: number;
  profit_factor: number | null;
}

export interface MetisIdea {
  id: number;
  round_id: number;
  created_at: number;
  kind: "filter" | "tweak" | "new_strategy" | "simplify" | "universe";
  title: string;
  why: string;
  market: MarketCode | null;
  strategy_id: number | null;
  strategy_version_id: number | null;
  status: "held_up" | "saved" | "rejected" | "untestable";
  verdict: string;
  result: {
    start?: number;
    end?: number;
    split?: number;
    symbols?: string[];
    baseline?: { study: MetisPart; exam: MetisPart } | null;
    candidate?: { study: MetisPart; exam: MetisPart };
    checks?: { ok: boolean; text: string }[];
    /** The luck check (D-82): the deflated Sharpe ratio over the ideas already tried. */
    luck?: { dsr: number; psr?: number; tries: number; days: number } | null;
    /** The overfitting check (D-89): probability of backtest overfitting over all the tries. */
    overfit?: { pbo: number | null; tries: number; text: string } | null;
    /** A "new" strategy that was really one you have (D-79). */
    family?: { strategy_id: number; name: string; version_id: number; why: string } | null;
  };
  /** Who thought of it: the AI model, or the expert's playbook in code (METIS §14). */
  origin?: "ai" | "playbook";
  saved_strategy_id: number | null;
  saved_version_id: number | null;
  run_id: number | null;
}

export interface MetisRound {
  id: number;
  started_at: number;
  finished_at: number | null;
  status: "running" | "done" | "failed" | "skipped";
  trigger: "auto" | "user";
  focus: string;
  model: string;
  noticed: string;
  note: string;
  ideas: number;
  kept: number;
  thinking: string;
  direction?: Direction;
  /** The trade autopsy's findings per strategy (D-109). */
  autopsy?: { strategy: string; lines: string[] }[];
}

/** The research agenda's four directions (METIS §13, D-83). */
export type Direction = "improve_live" | "improve" | "discover" | "opportunities";

export const DIRECTION_LABEL: Record<Direction, string> = {
  improve_live: "Improving what you're paper trading",
  improve: "Improving your strategies",
  discover: "Discovering new strategies",
  opportunities: "Finding new stocks for what works",
};

export interface MetisStatus {
  on: boolean;
  state: "off" | "waiting_ai" | "waiting" | "scheduled" | "working" | "playbook";
  doing: string;
  waiting: string;
  /** Why Metis is working from its playbook (the AI helper isn't available). */
  ai_note?: string;
  direction?: Direction | null;
  ai_ready: boolean;
  thread: boolean;
  last_round_at: number | null;
  next_round_at: number | null;
  every_minutes: number;
  apply: boolean;
  focus: string;
  totals: { rounds: number; ideas: number; tested: number; held_up: number; saved: number };
  rounds: MetisRound[];
  ideas: MetisIdea[];
}

export const KIND_LABEL: Record<MetisIdea["kind"], string> = {
  filter: "Filter",
  tweak: "Settings change",
  new_strategy: "New strategy",
  simplify: "Simpler rules",
  universe: "Different stocks",
};

export const STATUS_LABEL: Record<MetisIdea["status"], { label: string; tone: "profit" | "accent" | "neutral" | "warning" }> = {
  saved: { label: "Held up · saved", tone: "profit" },
  held_up: { label: "Held up", tone: "accent" },
  rejected: { label: "Didn't hold up", tone: "neutral" },
  untestable: { label: "Couldn't test", tone: "warning" },
};

/** One plain line for what Metis is doing or waiting for. */
export function stateLine(s: MetisStatus, now = Date.now()): string {
  if (s.state === "working") return s.doing || "Researching…";
  if (s.state === "off") return "Switched off. Metis only researches when you click Research now.";
  if (s.state === "waiting_ai" || s.state === "waiting") return s.waiting;
  if (s.state === "playbook" && !s.next_round_at) return "Working from its playbook until the AI helper is ready.";
  if (s.next_round_at) {
    const mins = Math.max(0, Math.round((s.next_round_at - now) / 60_000));
    return mins <= 0 ? "Starting its next round any moment." : `Next round in about ${mins} minute${mins === 1 ? "" : "s"}; it researches every ${s.every_minutes} minutes while Agora is open.`;
  }
  return `It researches every ${s.every_minutes} minutes while Agora is open.`;
}

export interface LibraryArea {
  key: string;
  title: string;
  sections: string[];
}
