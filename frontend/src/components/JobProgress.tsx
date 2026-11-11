import { X } from "lucide-react";
import type { Job } from "../lib/api";
import { formatCountdown } from "../lib/format";
import { cn } from "../lib/utils";
import { ErrorState } from "./states";
import { Button } from "./ui/button";
import { Progress } from "./ui/progress";

/** A running job: title, plain-English status line, progress bar, time left and Cancel. */
export function JobProgress({ job, onCancel, className }: { job: Job; onCancel?: () => void; className?: string }) {
  if (job.status === "failed" && job.error) return <ErrorState error={job.error} className={className} />;
  const running = job.status === "running" || job.status === "queued";
  return (
    <div className={cn("flex flex-col gap-2.5", className)} aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <p className="m-0 truncate text-[14px] font-semibold">{job.title}</p>
          <p className="m-0 truncate text-small text-fg-muted">{job.message}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-small tabular-nums text-fg-muted">
            {Math.round(job.pct)}%{running && job.eta_s ? ` · about ${formatCountdown(job.eta_s)} left` : ""}
          </span>
          {running && onCancel && (
            <Button size="sm" variant="ghost" onClick={onCancel}>
              <X aria-hidden="true" />
              Cancel
            </Button>
          )}
        </div>
      </div>
      <Progress value={job.pct} label={job.title} />
    </div>
  );
}
