import { Archive, CheckCircle2, FolderOpen, MinusCircle, PlugZap, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { JobProgress } from "../../components/JobProgress";
import { ErrorState, LoadingRows } from "../../components/states";
import { Button } from "../../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { postJson, toEnvelope, type Health } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";
import { cn } from "../../lib/utils";
import { ScrollBox } from "../../components/ui/scroll-box";

interface DiagnosticsInfo {
  versions: Record<string, string | null>;
  paths: { data: string; logs: string; database_mb: number };
  data_mode: string;
  events: { ts: number; level: string; area: string; message_plain: string }[];
  troubleshooting: { symptom: string; fix: string }[];
}

interface LiveResult {
  results: { name: string; label: string; outcome: "passed" | "failed" | "skipped"; detail: string }[];
  summary: string;
}

const OUTCOME = {
  passed: { icon: CheckCircle2, text: "Working", cls: "text-profit" },
  failed: { icon: XCircle, text: "Not working", cls: "text-loss" },
  skipped: { icon: MinusCircle, text: "Skipped", cls: "text-fg-subtle" },
} as const;

const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Settings → Diagnostics (RUNBOOK §5–6). */
export function DiagnosticsPanel() {
  const info = useApi<DiagnosticsInfo>("/diagnostics");
  const health = useApi<Health>("/health");
  const [jobId, setJobId] = useJobId("live_test");
  const [bundle, setBundle] = useState<string | null>(null);
  const { job } = useJob<LiveResult>(jobId);
  const running = job !== null && (job.status === "running" || job.status === "queued");

  async function call<T>(path: string, body: unknown, ok: (r: T) => void) {
    try {
      ok(await postJson<T>(path, body));
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  if (info.status === "loading") return <LoadingRows rows={5} />;
  if (info.status === "error") return <ErrorState error={info.error} onRetry={info.reload} />;
  const d = info.data;
  const result = job?.status === "done" ? job.result : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_420px] items-start gap-5">
      <div className="flex min-w-0 flex-col gap-5">
        <Card>
          <CardHeader>
            <CardTitle>Live data checks</CardTitle>
            <Button size="sm" onClick={() => void call<{ job_id: string }>("/diagnostics/live-test", {}, (r) => setJobId(r.job_id))} disabled={running}>
              <PlugZap aria-hidden="true" />
              Run the checks
            </Button>
          </CardHeader>
          <CardBody className="flex flex-col gap-3">
            <p className="m-0 text-small text-fg-muted">Asks Yahoo Finance, NSE, Stooq and the AI helper for a little real data to confirm Agora can still read it. Takes about a minute.</p>
            {job && running && <JobProgress job={job} />}
            {result && (
              <>
                <p className="m-0 font-semibold">{result.summary}</p>
                <ScrollBox size="md">
                  <ul className="m-0 flex list-none flex-col p-0">
                    {result.results.map((r) => {
                      const o = OUTCOME[r.outcome];
                      const Icon = o.icon;
                      return (
                        <li key={r.name} className="flex items-start gap-3 border-b border-hairline py-2.5 last:border-0">
                          <Icon className={cn("mt-0.5 size-4 shrink-0", o.cls)} aria-hidden="true" />
                          <div className="flex min-w-0 flex-1 flex-col">
                            <span className="text-[14px]">{r.label}</span>
                            {r.detail && <span className="truncate text-tiny text-fg-subtle">{r.detail}</span>}
                          </div>
                          <span className={cn("text-small", o.cls)}>{o.text}</span>
                        </li>
                      );
                    })}
                  </ul>
                </ScrollBox>
              </>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>If something goes wrong</CardTitle>
          </CardHeader>
          <CardBody>
            <dl className="m-0 flex flex-col">
              {d.troubleshooting.map((t) => (
                <div key={t.symptom} className="grid grid-cols-[240px_1fr] gap-4 border-b border-hairline py-2.5 last:border-0">
                  <dt className="text-[14px] font-semibold">{t.symptom}</dt>
                  <dd className="m-0 text-[14px] text-fg-muted">{t.fix}</dd>
                </div>
              ))}
            </dl>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Recent events</CardTitle>
          </CardHeader>
          <CardBody>
            {d.events.length === 0 ? (
              <p className="m-0 text-small text-fg-muted">Nothing noteworthy yet.</p>
            ) : (
              <ul className="m-0 flex max-h-[320px] list-none flex-col overflow-y-auto p-0">
                {d.events.map((e, i) => (
                  <li key={i} className="flex items-start gap-3 border-b border-hairline py-2 last:border-0">
                    <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", e.level === "error" ? "bg-loss" : e.level === "warn" ? "bg-warning" : "bg-neutral-dot")} aria-hidden="true" />
                    <span className="flex-1 text-[14px]">{e.message_plain}</span>
                    <time className="text-tiny text-fg-subtle tabular-nums">{formatDateTime(e.ts, LOCAL_TZ)}</time>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader>
            <CardTitle>Get help</CardTitle>
          </CardHeader>
          <CardBody className="flex flex-col gap-3">
            <p className="m-0 text-small text-fg-muted">A support bundle collects Agora's logs and settings (no market data, nothing private) into one file you can share in a Claude Code session.</p>
            <Button variant="primary" className="w-fit" onClick={() => void call<{ path: string }>("/diagnostics/support-bundle", {}, (r) => { setBundle(r.path); toast.success("Support bundle created."); })}>
              <Archive aria-hidden="true" />
              Create support bundle
            </Button>
            {bundle && <p className="m-0 text-tiny break-all text-fg-subtle">Saved as {bundle}</p>}
            <Button className="w-fit" onClick={() => void call("/diagnostics/open-folder", { which: "logs" }, () => undefined)}>
              <FolderOpen aria-hidden="true" />
              Open the log folder
            </Button>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>About this copy</CardTitle>
          </CardHeader>
          <CardBody>
            <dl className="m-0 grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-[14px]">
              <dt className="text-fg-muted">Agora</dt>
              <dd className="m-0 font-semibold">{d.versions.agora}</dd>
              <dt className="text-fg-muted">Database</dt>
              <dd className="m-0">{health.status === "ready" && !health.data.db_ok ? "Problem: restart Agora" : `Working · ${d.paths.database_mb} MB`}</dd>
              <dt className="text-fg-muted">Prices</dt>
              <dd className="m-0">{d.data_mode === "fake" ? "Practice prices" : "Real prices"}</dd>
              <dt className="text-fg-muted">Data library</dt>
              <dd className="m-0">yfinance {d.versions.yfinance ?? "?"}</dd>
              <dt className="text-fg-muted">AI helper</dt>
              <dd className="m-0">{d.versions.ollama ? `Ollama ${d.versions.ollama}` : "Not running"}</dd>
              <dt className="text-fg-muted">System</dt>
              <dd className="m-0">
                {d.versions.system} · Python {d.versions.python}
              </dd>
              <dt className="text-fg-muted">Data folder</dt>
              <dd className="m-0 text-small break-all text-fg-muted">{d.paths.data}</dd>
            </dl>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
