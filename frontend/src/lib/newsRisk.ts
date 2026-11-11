/** The news risk gauge's words and colours, shared by the News screen and Home. */
import type { GuardMode, RiskName } from "./kairos";

export const RISK_TONE: Record<RiskName, "profit" | "info" | "warning" | "loss"> = {
  calm: "profit",
  watchful: "info",
  elevated: "warning",
  severe: "loss",
};
export const RISK_WORD: Record<RiskName, string> = { calm: "Calm", watchful: "Watchful", elevated: "Elevated", severe: "Severe" };
export const RISK_BAR: Record<RiskName, string> = { calm: "bg-profit", watchful: "bg-info", elevated: "bg-warning", severe: "bg-loss" };

/** What the desk does at this level, in the guard's mode (mirrors backend/kairos/news_guard.py). */
export function guardWords(level: number, mode: GuardMode): string {
  if (mode === "off") return "The news guard is off: Kairos's desk trades on prices only.";
  const protective = mode === "protective";
  // D-211: news is caution, never a stop; sectors the news helps are where Kairos looks first
  if (level >= 75) return protective ? "Still trading: half size where the news hurts, readier where it helps; longs sold if the market falls with it." : "Still trading, at half size where the news hurts.";
  if (level >= 50) return protective ? "Still trading: half size where the news hurts, readier where it helps; losing longs cut once prices confirm." : "Still trading, at half size where the news hurts.";
  return "Trading normally; readier to buy where the news helps a sector.";
}
