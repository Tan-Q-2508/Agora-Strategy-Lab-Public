/** Kairos's trade check (KAIROS §16): the choices and what each means, in one place. */
export type TradeCheckMode = "off" | "learn" | "balanced" | "strict";

export const TRADE_CHECK_OPTIONS: { value: TradeCheckMode; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "learn", label: "Learn only" },
  { value: "balanced", label: "Balanced" },
  { value: "strict", label: "Strict" },
];

export const TRADE_CHECK_HINT: Record<TradeCheckMode, string> = {
  off: "Every signal is traded exactly as the rules say.",
  learn: "Every signal is traded; Kairos learns which ones lose after costs.",
  balanced: "Kairos skips signals that look clearly worse than this strategy's usual trade, once it has proven it can tell them apart.",
  strict: "Kairos takes only signals with a good chance of winning: a higher win rate with fewer trades, once it has proven itself.",
};
