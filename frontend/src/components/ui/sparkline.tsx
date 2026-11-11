import { cn } from "../../lib/utils";

/** A tiny line chart (no axes) for cards; colour follows the sign of the change. */
export function Sparkline({ points, className, label }: { points: number[]; className?: string; label: string }) {
  if (points.length < 2) return <div className={cn("h-10", className)} aria-hidden="true" />;
  const w = 120;
  const h = 36;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const xy = points.map((v, i) => [(i / (points.length - 1)) * w, h - 2 - ((v - min) / span) * (h - 4)] as const);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const up = (points.at(-1) ?? 0) >= (points[0] ?? 0);
  const colour = up ? "var(--profit)" : "var(--loss)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cn("h-10 w-full", className)} role="img" aria-label={label}>
      <path d={`${d} L${w},${h} L0,${h} Z`} fill={colour} opacity={0.08} />
      <path d={d} fill="none" stroke={colour} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
