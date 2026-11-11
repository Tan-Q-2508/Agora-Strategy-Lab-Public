/** Types for watchlists, sectors, the world desk and the autopilot (SPEC §18, D-94 to D-99). */
import type { MarketCode } from "./api";

export type ListKind = "custom" | "ready" | "kairos" | "metis";
export type ListCategory = "custom" | "index" | "sector" | "size" | "factor" | "theme" | "etf" | "ai";

export interface WatchlistSummary {
  id: number;
  name: string;
  market: MarketCode;
  kind: ListKind;
  category: ListCategory;
  key: string | null;
  description: string;
  reason: string;
  count: number;
  editable: boolean;
  live: boolean;
  created_at: number;
  updated_at: number;
}

export interface WatchlistItem {
  instrument_id: number;
  symbol: string;
  name: string;
  type: string;
  sector: string;
  industry: string;
  size: string;
  tags: string[];
  note: string;
  last: number | null;
  change_pct: number | null;
}

export interface WatchlistDetail extends WatchlistSummary {
  items: WatchlistItem[];
  with_prices: number;
}

export interface SectorReading {
  name: string;
  members: number;
  returns: Record<"1w" | "1m" | "3m" | "6m", number | null>;
  rs_ratio: number | null;
  rs_momentum: number | null;
  quadrant: "leading" | "weakening" | "lagging" | "improving" | "unknown";
  breadth: { members: number; above50: number; above200: number; new_highs: number };
  month_z: number | null;
  volume_ratio: number | null;
  state: "boom" | "strong" | "neutral" | "weak" | "slump";
  score: number;
  leaders: { symbol: string; instrument_id: number; "1m": number }[];
  laggards: { symbol: string; instrument_id: number; "1m": number }[];
  sentence: string;
}

export interface SectorOverview {
  market: MarketCode;
  as_of: number | null;
  sectors: SectorReading[];
  industries: SectorReading[];
  booms: string[];
  slumps: string[];
  stocks: number;
  sentence: string;
}

export interface WorldEffect {
  target: string;
  label: string;
  value: number;
  map: number;
  measured: { n: number; mean_pct: number; hit_rate: number | null } | null;
}

export interface WorldDriver {
  scenario: string;
  title: string;
  calming: boolean;
  strength: number;
  weight: number;
  chain: string[];
  effects: WorldEffect[];
  headlines: { title: string; publisher: string; published_at: number; link: string; calming: boolean }[];
  event_id: number | null;
}

export interface WorldStock {
  instrument_id: number;
  symbol: string;
  name: string;
  tilt: number;
  vs_market: number;
  why: string[];
}

export interface WorldView {
  market: MarketCode;
  tilt: number;
  sectors: Record<string, number>;
  tags: Record<string, number>;
  drivers: WorldDriver[];
  helped: WorldStock[];
  hurt: WorldStock[];
  sentence: string;
}

export interface MoveCause {
  key: string;
  kind: "world" | "news" | "company" | "contagion";
  title: string;
  score: number;
  headline: { title: string; publisher: string; published_at: number; link: string } | null;
  sources: number;
  chain: string[];
  clues: string[];
  against: string[];
}

export interface Move {
  id: number;
  market: MarketCode;
  target: string;
  timeframe: string;
  start_ts: number;
  end_ts: number;
  move_pct: number;
  z: number;
  verdict: "news" | "world" | "contagion" | "unclear";
  text: string;
  created_at: number;
  causes: MoveCause[];
  confidence: "high" | "medium" | "low";
  headlines_read: number;
}

export interface WorldEventRow {
  id: number;
  scenario: string;
  kind: string;
  title: string;
  first_seen: number;
  last_seen: number;
  strength: number;
  status: "active" | "fading" | "measured";
  headlines: { title: string; publisher: string; link: string }[];
}

export interface WorldResponse {
  IN: WorldView;
  US: WorldView;
  events: WorldEventRow[];
  moves: Move[];
}

export interface Lesson {
  scenario: string;
  title: string;
  market: MarketCode;
  target: string;
  n: number;
  mean_pct: number;
  map: number | null;
  agrees: boolean | null;
}

export interface AutopilotStatus {
  on: boolean;
  running: boolean;
  doing: string;
  last_round: number | null;
  desks: { id: number; market: MarketCode; state: string; name: string; auto: boolean }[];
  prices: Partial<Record<MarketCode, { have: number; want: number }>>;
  metis: { on: boolean; ai_ready: boolean; why: string };
}

export const STATE_TONE: Record<SectorReading["state"], "profit" | "loss" | "warning" | "neutral" | "info"> = {
  boom: "profit",
  strong: "info",
  neutral: "neutral",
  weak: "warning",
  slump: "loss",
};
export const STATE_WORD: Record<SectorReading["state"], string> = {
  boom: "Booming",
  strong: "Leading",
  neutral: "Steady",
  weak: "Lagging",
  slump: "Slumping",
};
export const CATEGORY_WORD: Record<ListCategory, string> = {
  custom: "Your lists",
  ai: "Made by Kairos and Metis",
  index: "Indices",
  sector: "Sectors",
  size: "Large, mid and small caps",
  factor: "Factor lists (how quant funds pick)",
  theme: "Themes",
  etf: "ETFs",
};
export const CATEGORY_ORDER: ListCategory[] = ["custom", "ai", "index", "sector", "size", "factor", "theme", "etf"];
