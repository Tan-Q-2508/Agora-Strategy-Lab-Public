import { cn } from "../../lib/utils";

/** Profit/loss text: always arrow + sign + color, never color alone (DESIGN_BRIEF §3). */
export function Change({ value, text, className }: { value: number; text: string; className?: string }) {
  const up = value > 0;
  const down = value < 0;
  return (
    <span className={cn("font-semibold whitespace-nowrap", up && "text-profit", down && "text-loss", !up && !down && "text-fg-muted", className)}>
      <span aria-hidden="true">{up ? "▲ " : down ? "▼ " : ""}</span>
      <span className="sr-only">{up ? "up " : down ? "down " : ""}</span>
      {text}
    </span>
  );
}
