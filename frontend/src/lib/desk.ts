/** The Kairos desk and what Kairos learned (`/api/kairos/desk`, `/api/kairos/stats`). */
import type { MarketCode, PaperSessionDetail, Timeframe } from "./api";

export interface LearnedSignal {
  key: string;
  label: string;
  family: string;
  direction: number;
  n: number;
  hit_rate: number | null;
  base_rate: number;
  paper_n: number;
  paper_wins: number;
  edge: number;
  weight: number;
  text: string;
}

export interface Learned {
  market: MarketCode;
  timeframe: Timeframe;
  trained: { at: number; candles: number; samples: number; base_rate: number | null; horizon: number } | null;
  best: LearnedSignal[];
  worst: LearnedSignal[];
  paper_trades: number;
  signals: number;
  /** The exits Kairos trades with and why (D-140); null before it can tell. */
  exits?: { plan: string; chosen: boolean; why: string } | null;
  /** The trade judge (D-145): on only once it proved itself on unseen past trades. */
  judge?: { on: boolean; stand_aside?: boolean; text: string } | null;
}

export interface JournalEntry {
  id: number;
  kind: "thesis" | "review" | "note" | "day";
  symbol: string | null;
  instrument_id: number | null;
  trade_id: number | null;
  entry_ts: number | null;
  score: number | null;
  text: string;
  won: boolean | null;
  return_pct: number | null;
  at: number;
}

export interface Lesson {
  id: number;
  text: string;
  market: MarketCode | null;
  at: number;
}

export interface DeskDetail extends PaperSessionDetail {
  journal: JournalEntry[];
  learned: Learned;
  lessons: Lesson[];
}
