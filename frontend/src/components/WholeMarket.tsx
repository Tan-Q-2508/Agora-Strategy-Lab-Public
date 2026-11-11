import type { AutopilotStatus } from "../lib/world";
import { useApi } from "../lib/useApi";
import { cn } from "../lib/utils";

/**
 * How much of the whole market has daily history saved. Agora knows every stock on NSE and
 * the US exchanges (D-102); the starter list is only what the Welcome download fetched.
 */
export function WholeMarket({ className }: { className?: string }) {
  const s = useApi<AutopilotStatus>("/autopilot", 60_000);
  if (s.status !== "ready") return null;
  const parts = Object.entries(s.data.prices).flatMap(([m, p]) =>
    p ? [`${m === "IN" ? "India" : "US"} ${p.have.toLocaleString()} of ${p.want.toLocaleString()}`] : [],
  );
  if (!parts.length) return null;
  const done = Object.values(s.data.prices).every((p) => !p || p.have >= p.want);
  return (
    <p className={cn("m-0 text-small text-fg-muted", className)}>
      Whole market: {parts.join(" · ")} stocks have daily prices
      {done ? "." : s.data.on ? "; the rest download on their own while Agora is open." : ". Switch on “Work on their own” in Settings → Kairos to download the rest."}
    </p>
  );
}
