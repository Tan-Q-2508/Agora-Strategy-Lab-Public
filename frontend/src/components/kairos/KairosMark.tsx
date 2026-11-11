import { cn } from "../../lib/utils";

/**
 * Kairos's emblem: the candle from the Agora mark inside a ring (the market's cycle) that
 * opens just before one o'clock, the decisive moment. Drawn in currentColor plus the accent
 * so it works in both themes.
 */
export function KairosMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-5", className)} role={title ? "img" : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.7" strokeLinecap="round" strokeDasharray="45.5 7.9" transform="rotate(-62 12 12)" />
      <path d="M12 7.2v9.8" stroke="var(--accent)" strokeWidth="1.7" strokeLinecap="round" />
      <rect x="10.2" y="9.45" width="3.6" height="5.1" rx="0.85" fill="var(--accent)" />
    </svg>
  );
}
