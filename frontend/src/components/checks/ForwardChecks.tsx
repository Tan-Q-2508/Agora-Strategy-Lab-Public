import { CalendarClock, RefreshCw, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { postJson, toEnvelope } from "../../lib/api";
import { VERDICT_TONE, VERDICT_WORDS, type CheckRow, type ForwardResult } from "../../lib/checks";
import { formatDate } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useJob, useJobId } from "../../lib/useJob";
import { JobProgress } from "../JobProgress";
import { LoadingRows } from "../states";
import { Button } from "../ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../ui/card";
import { Pill } from "../ui/pill";

export interface ForwardItem {
  subject: "revision" | "sleeve";
  name: string;
  strategy_id: number;
  version_id: number;
  sleeve_id: number | null;
  portfolio_id: number | null;
  since: number | null;
  days_since: number | null;
  check: CheckRow<ForwardResult> | null;
}

/** Forward checks (D-90): what Kairos and Metis saved (or a portfolio's sleeves) re-tested on
 * candles formed after it was saved, with Undo for what stopped holding up. */
export function ForwardChecks({ subject, portfolioId, title, intro }: { subject: "revision" | "sleeve"; portfolioId?: number; title: string; intro: string }) {
  const s = useApi<{ items: ForwardItem[]; auto_undo: boolean }>("/checks/forward");
  const [jobId, setJobId] = useJobId("forward_check");
  const [busy, setBusy] = useState<number | null>(null);
  const { job, cancel } = useJob<{ checked: number }>(jobId, (j) => {
    setJobId(null);
    if (j.status === "done") toast.success(j.result?.checked ? `Re-tested ${j.result.checked} on the newest candles.` : "Nothing has enough new candles to re-test yet.");
    s.reload();
  });
  const items = s.status === "ready" ? (s.data.items ?? []).filter((i) => i.subject === subject && (portfolioId === undefined || i.portfolio_id === portfolioId)) : [];

  async function run() {
    try {
      setJobId((await postJson<{ job_id: string }>("/checks/forward/run")).job_id);
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    }
  }
  async function undo(id: number) {
    setBusy(id);
    try {
      const r = await postJson<{ check: CheckRow<ForwardResult> }>(`/checks/${id}/undo`);
      toast.success(r.check.action);
      s.reload();
    } catch (err) {
      const e = toEnvelope(err);
      toast.error(e.message, { description: e.action });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarClock className="size-4 text-accent" aria-hidden="true" />
          {title}
        </CardTitle>
        {!job && (
          <Button size="sm" variant="ghost" onClick={() => void run()}>
            <RefreshCw aria-hidden="true" />
            Check now
          </Button>
        )}
      </CardHeader>
      <CardBody className="flex flex-col gap-3">
        <p className="m-0 text-small text-fg-muted">{intro}</p>
        {job && <JobProgress job={job} onCancel={cancel} />}
        {s.status === "loading" && <LoadingRows rows={2} />}
        {s.status === "ready" && items.length === 0 && <p className="m-0 text-small text-fg-subtle">Nothing to re-test yet.</p>}
        {items.map((i) => (
          <Item key={`${i.version_id}-${i.sleeve_id ?? ""}-${i.check?.id ?? ""}`} item={i} busy={busy === i.check?.id} onUndo={undo} />
        ))}
        {s.status === "ready" && subject === "revision" && (
          <p className="m-0 text-tiny text-fg-subtle">
            {s.data.auto_undo ? "What stops holding up is put back on its own (as a new version, so nothing is lost)." : "Undoing is up to you (Settings → Kairos)."} Kairos re-tests each one at most once a day while Agora is open.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function Item({ item, busy, onUndo }: { item: ForwardItem; busy: boolean; onUndo: (id: number) => void }) {
  const c = item.check;
  return (
    <div className="flex flex-col gap-1.5 rounded-tile border border-hairline p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={`/strategies/${item.strategy_id}`} className="text-[14px] font-semibold">
          {item.name}
        </Link>
        <Pill tone={c ? VERDICT_TONE[c.verdict] : "neutral"} className="h-6 px-2 text-tiny">
          {c ? VERDICT_WORDS[c.verdict] : "Waiting for candles"}
        </Pill>
      </div>
      {c ? (
        <>
          <p className="m-0 text-small">{c.result.text}</p>
          {c.result.numbers.length > 0 && (
            <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-1 text-tiny">
              {c.result.numbers.map((n) => (
                <div key={n.label} className="flex justify-between gap-2">
                  <dt className="text-fg-muted">{n.label}</dt>
                  <dd className="m-0 tabular-nums font-semibold">{n.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {c.action ? (
            <p className="m-0 text-small font-semibold text-accent-strong">{c.action}</p>
          ) : (
            c.result.can_undo && (
              <Button size="sm" className="w-fit" onClick={() => onUndo(c.id)} disabled={busy}>
                <Undo2 aria-hidden="true" />
                {c.result.undo_label ?? "Undo"}
              </Button>
            )
          )}
          <p className="m-0 text-tiny text-fg-subtle">
            Checked {formatDate(c.created_at)}
            {item.since ? ` on the candles since ${formatDate(item.since)}` : ""}.
          </p>
        </>
      ) : (
        <p className="m-0 text-small text-fg-muted">Saved {item.days_since ?? 0} days ago. The first re-test needs about a month of new candles.</p>
      )}
    </div>
  );
}
