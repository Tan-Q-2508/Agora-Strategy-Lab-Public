import { motion } from "framer-motion";
import type { RiskName } from "../../lib/kairos";
import { RISK_BAR } from "../../lib/newsRisk";
import { cn } from "../../lib/utils";

/** A 0–100 meter with the four zones (calm, watchful, elevated, severe) marked. */
export function RiskMeter({ level, name }: { level: number; name: RiskName }) {
  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-surface-2" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level)} aria-label="News risk">
      {[25, 50, 75].map((x) => (
        <span key={x} aria-hidden="true" className="absolute top-0 z-10 h-full w-px bg-surface" style={{ left: `${x}%` }} />
      ))}
      <motion.span
        className={cn("absolute left-0 top-0 h-full rounded-full", RISK_BAR[name])}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(2, Math.min(100, level))}%` }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      />
    </div>
  );
}
