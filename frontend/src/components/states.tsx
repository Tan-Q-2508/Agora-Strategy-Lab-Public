import type { LucideIcon } from "lucide-react";
import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";
import type { ErrorEnvelope } from "../lib/api";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Skeleton } from "./ui/skeleton";

/** Every empty panel says what belongs here and offers one clear next action. */
export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  body: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-10 text-center", className)}>
      <span className="flex size-12 items-center justify-center rounded-full bg-accent-soft text-accent-strong">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="flex max-w-sm flex-col gap-1">
        <p className="m-0 text-[16px] font-semibold">{title}</p>
        <p className="m-0 text-small text-fg-muted">{body}</p>
      </div>
      {action}
    </div>
  );
}

/** Plain-English error + what to do; technical detail stays behind "Details". */
export function ErrorState({ error, onRetry, className }: { error: ErrorEnvelope; onRetry?: () => void; className?: string }) {
  return (
    <div role="alert" className={cn("flex flex-col gap-3 rounded-card bg-warning-soft p-4 text-warning-soft-fg", className)}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div className="flex flex-col gap-0.5">
          <p className="m-0 text-[14px] font-semibold">{error.message}</p>
          <p className="m-0 text-small">{error.action}</p>
        </div>
        {onRetry && (
          <Button size="sm" className="ml-auto" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
      {error.detail && (
        <details className="text-small">
          <summary className="cursor-pointer">Details</summary>
          <code className="mt-2 block font-mono text-tiny whitespace-pre-wrap">{error.detail}</code>
        </details>
      )}
    </div>
  );
}

/** Skeleton rows sized like the content that will replace them. */
export function LoadingRows({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-11 w-full" />
      ))}
    </div>
  );
}
