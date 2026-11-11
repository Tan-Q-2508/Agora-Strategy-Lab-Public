/** Who a strategy or run belongs to, for the tabs on Paper, Strategies and Backtests (the user,
 * 2026-11-06: "for grouping I meant tabs"; Kairos's desk strategies out of "your strategies"). */
export type Owner = "you" | "metis" | "kairos";

export function ownerOf(name: string, kind?: string | null): Owner {
  if (kind === "kairos" || name.startsWith("Kairos")) return "kairos";
  if (name.startsWith("Metis")) return "metis";
  return "you";
}
