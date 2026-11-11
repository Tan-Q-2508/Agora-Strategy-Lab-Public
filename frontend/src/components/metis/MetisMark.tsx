import { cn } from "../../lib/utils";

/**
 * Metis's emblem: Kairos's ring, closed this time (Metis thinks between the moments), with a
 * four-pointed spark inside: an idea. Drawn in currentColor plus the accent for both themes.
 */
export function MetisMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-5", className)} role={title ? "img" : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.7" />
      <path d="M12 6.6 13.35 10.65 17.4 12 13.35 13.35 12 17.4 10.65 13.35 6.6 12 10.65 10.65Z" fill="var(--accent)" />
    </svg>
  );
}
