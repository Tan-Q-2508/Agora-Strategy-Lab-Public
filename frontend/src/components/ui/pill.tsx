import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const pillVariants = cva(
  "inline-flex h-8 items-center gap-2 rounded-full px-3 text-small whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border border-border bg-surface text-fg",
        profit: "bg-profit-soft text-profit-soft-fg",
        loss: "bg-loss-soft text-loss-soft-fg",
        warning: "bg-warning-soft text-warning-soft-fg",
        info: "bg-info-soft text-info-soft-fg",
        accent: "bg-accent-soft font-semibold text-accent-soft-fg",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface PillProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof pillVariants> {}

export function Pill({ className, tone, ...props }: PillProps) {
  return <span className={cn(pillVariants({ tone }), className)} {...props} />;
}

/** A status dot. `live` pulses gently (stops with reduced motion). */
export function Dot({ tone = "neutral", live = false }: { tone?: "neutral" | "profit" | "loss" | "warning"; live?: boolean }) {
  const color = {
    neutral: "bg-neutral-dot text-neutral-dot",
    profit: "bg-profit text-profit",
    loss: "bg-loss text-loss",
    warning: "bg-warning text-warning",
  }[tone];
  return <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", color, live && "animate-pulse-dot")} />;
}
