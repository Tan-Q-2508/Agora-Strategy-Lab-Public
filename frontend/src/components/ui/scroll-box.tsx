import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const HEIGHT = {
  xs: "max-h-[200px]",
  sm: "max-h-[280px]",
  md: "max-h-[380px]",
  lg: "max-h-[480px]",
  xl: "max-h-[600px]",
  // a page's main list: the rest of the window below the page's header
  page: "max-h-[calc(100vh-260px)] min-h-[320px]",
} as const;

/**
 * A fixed-height box whose extra content scrolls inside it (D-212: the user, 2026-11-06, "in
 * all the pages of Agora all containers must be a fixed size, and extra length must be scrolled
 * inside that container"). Tables keep their header row in view while they scroll.
 */
export function ScrollBox({
  size = "md",
  label,
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { size?: keyof typeof HEIGHT; label?: string }) {
  return (
    <div
      tabIndex={0}
      role={label ? "region" : undefined}
      aria-label={label}
      className={cn(
        "scroll-box min-h-0 overflow-y-auto",
        "[&_thead_th]:sticky [&_thead_th]:top-0 [&_thead_th]:z-[1] [&_thead_th]:bg-surface",
        HEIGHT[size],
        className,
      )}
      {...rest}
    />
  );
}
