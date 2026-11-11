import { Loader2 } from "lucide-react";
import type { Job } from "../../lib/api";
import { formatCountdown } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { Popover } from "../ui/popover";
import { Progress } from "../ui/progress";
import { ScrollBox } from "../ui/scroll-box";

/**
 * Everything Agora is doing in the background, on every screen (the user's request 2026-10-24,
 * D-107): jobs keep running when a screen is left, and this shows them so nothing seems to
 * vanish. Hidden when nothing runs.
 */
export function Activity() {
  const jobs = useApi<{ jobs: Job[] }>("/jobs?active=true", 3_000);
  const list = jobs.status === "ready" ? (jobs.data.jobs ?? []) : [];
  if (list.length === 0) return null;
  return (
    <Popover
      align="end"
      trigger={
        <button
          type="button"
          aria-label={`${list.length} task${list.length === 1 ? "" : "s"} running`}
          className="flex h-8 items-center gap-1.5 rounded-full bg-accent-soft px-3 text-small font-medium text-accent-soft-fg hover:brightness-95"
        >
          <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          {list.length === 1 ? "Working…" : `${list.length} tasks running`}
        </button>
      }
    >
      <p className="m-0 mb-3 text-small font-semibold">Running in the background</p>
      <ScrollBox size="md">
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {list.map((j) => (
            <li key={j.job_id} className="flex flex-col gap-1">
              <div className="flex justify-between gap-2 text-small">
                <span className="truncate font-medium">{j.title}</span>
                <span className="shrink-0 tabular-nums text-fg-muted">
                  {Math.round(j.pct)}%{j.eta_s ? ` · about ${formatCountdown(j.eta_s)} left` : ""}
                </span>
              </div>
              <Progress value={j.pct} label={j.title} />
              <p className="m-0 truncate text-tiny text-fg-subtle">{j.message}</p>
            </li>
          ))}
        </ul>
      </ScrollBox>
      <p className="m-0 mt-3 text-tiny text-fg-subtle">These keep going when you switch screens. They stop only when Agora closes.</p>
    </Popover>
  );
}
