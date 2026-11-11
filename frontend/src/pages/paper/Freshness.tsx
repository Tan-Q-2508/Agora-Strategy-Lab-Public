import { Dot, Pill } from "../../components/ui/pill";
import { Tooltip } from "../../components/ui/tooltip";
import type { Freshness } from "../../lib/api";

const TONE = { green: "profit", amber: "warning", red: "loss", closed: "neutral" } as const;
const PILL = { green: "profit", amber: "warning", red: "loss", closed: "neutral" } as const;

/** Data freshness: how old the latest price is (SPEC §7.2). Always visible on live screens. */
export function FreshnessBadge({ f, compact = false }: { f: Freshness | null; compact?: boolean }) {
  if (!f) return null;
  const live = f.level !== "closed";
  return (
    <Tooltip content="Data freshness: how old the latest price is. Green is up to date, amber a little late, red not arriving.">
      <Pill tone={PILL[f.level]} className={compact ? "h-7 px-2.5 text-tiny" : undefined} tabIndex={0}>
        <Dot tone={TONE[f.level]} live={live} />
        <span>{f.text}</span>
      </Pill>
    </Tooltip>
  );
}
