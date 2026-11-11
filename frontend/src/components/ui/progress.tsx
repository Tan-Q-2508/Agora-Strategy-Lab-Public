import { cn } from "../../lib/utils";

/** A calm progress bar; the fill animates its width (no layout shift). */
export function Progress({ value, label, className }: { value: number; label: string; className?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      className={cn("h-2 w-full overflow-hidden rounded-full bg-surface-2", className)}
    >
      <div className="h-full rounded-full bg-accent transition-[width] duration-300 ease-standard" style={{ width: `${pct}%` }} />
    </div>
  );
}
