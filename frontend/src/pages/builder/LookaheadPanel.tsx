import { Eye, Play } from "lucide-react";
import { toast } from "sonner";
import { JobProgress } from "../../components/JobProgress";
import { Button } from "../../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Pill } from "../../components/ui/pill";
import { postJson, toEnvelope } from "../../lib/api";
import { VERDICT_TONE, VERDICT_WORDS, type CheckRow, type LookaheadResult } from "../../lib/checks";
import { formatDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";
import { ScrollBox } from "../../components/ui/scroll-box";

/** The look-ahead check (D-88): proves the rules only use candles that had closed, and that
 * they don't depend on how much history is loaded. One click; runs in the background. */
export function LookaheadPanel({ strategyId, version, ensureSaved }: { strategyId: number; version: number | null; ensureSaved: () => Promise<boolean> }) {
  const checks = useApi<{ checks: CheckRow<LookaheadResult>[] }>(`/strategies/${strategyId}/checks?kind=lookahead&limit=5`);
  const [jobId, setJobId] = useJobId("lookahead", `strategy:${strategyId}`);
  const { job, cancel } = useJob<CheckRow<LookaheadResult>>(jobId, (j) => {
    if (j.status === "done") checks.reload();
  });
  const running = job !== null && (job.status === "queued" || job.status === "running");
  const latest = checks.status === "ready" ? (checks.data.checks ?? [])[0] : undefined;
  const current = latest && latest.version === version ? latest : undefined;

  async function start() {
    if (!(await ensureSaved())) return;
    try {
      const r = await postJson<{ job_id: string }>(`/strategies/${strategyId}/lookahead`, {});
      setJobId(r.job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Look-ahead check</CardTitle>
        {current && <Pill tone={VERDICT_TONE[current.verdict]} className="h-6 px-2 text-tiny">{VERDICT_WORDS[current.verdict]}</Pill>}
      </CardHeader>
      <CardBody className="flex flex-col gap-3" aria-live="polite">
        {job && (running || job.status === "failed") ? (
          <JobProgress job={job} onCancel={cancel} />
        ) : current ? (
          <Result row={current} />
        ) : (
          <p className="m-0 text-small text-fg-muted">
            Proves the rules only use candles that had already closed: Agora runs them on growing slices of history with the later candles hidden, and again with more older history, and compares every signal. About a minute.
            {latest && latest.version !== null && <> The last check was of version {latest.version}.</>}
          </p>
        )}
        {!running && (
          <Button size="sm" onClick={() => void start()} className="w-fit">
            {current ? <Eye aria-hidden="true" /> : <Play aria-hidden="true" />}
            {current ? "Check again" : "Run the check"}
          </Button>
        )}
      </CardBody>
    </Card>
  );
}

function Result({ row }: { row: CheckRow<LookaheadResult> }) {
  const r = row.result;
  const findings = [...r.lookahead.findings, ...r.history.findings];
  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-[14px] font-semibold">{r.title}</p>
      <p className="m-0 text-small text-fg-muted">{r.text}</p>
      {findings.length > 0 && (
        <ScrollBox size="sm">
          <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-small">
            {findings.slice(0, 5).map((f, i) => (
              <li key={i}>{f.text}</li>
            ))}
          </ul>
        </ScrollBox>
      )}
      {r.notes.map((n, i) => (
        <p key={i} className="m-0 text-tiny text-fg-subtle">
          {n}
        </p>
      ))}
      <details className="text-tiny text-fg-subtle">
        <summary className="cursor-pointer">Details</summary>
        <p className="m-0 mt-1">
          Version {r.version}, checked {formatDate(row.created_at)} on {r.symbols.join(", ") || "no stocks"}: {r.lookahead.slices} slices, {r.lookahead.signals_checked} signals and {r.lookahead.indicators_checked} indicator lines compared with later candles hidden
          {r.history.extra_candles !== null ? `; ${r.history.signals_compared} signals compared with ${r.history.extra_candles} more older candles` : ""}.
        </p>
      </details>
    </div>
  );
}
