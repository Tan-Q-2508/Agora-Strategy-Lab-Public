import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

/** Shimmering placeholder with the exact size of the content it stands in for (no layout shift). */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "animate-shimmer rounded-control bg-[linear-gradient(90deg,var(--surface-2)_0%,var(--hairline)_50%,var(--surface-2)_100%)] bg-[length:800px_100%]",
        className,
      )}
      {...props}
    />
  );
}
