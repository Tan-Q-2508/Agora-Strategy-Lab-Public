import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Card } from "../components/ui/card";
import { Pill } from "../components/ui/pill";
import { ScrollBox } from "../components/ui/scroll-box";
import { formatAgo, formatCount } from "../lib/format";
import { useApi } from "../lib/useApi";

export interface ActionRow {
  id: number;
  started_at: number;
  ms: number | null;
  kind: string;
  what: string;
  who: string;
  why: string;
  status: string;
  output: string;
  correct: boolean | null;
  correct_why: string;
  detail: Record<string, unknown>;
}

interface KindRow {
  kind: string;
  n: number;
  ok: number;
  failed: number;
  wrong: number;
  cut_off: number;
  running: number;
  last_at: number;
}

interface ActionsResponse {
  actions: ActionRow[];
  summary: KindRow[];
}

const TONE: Record<string, "profit" | "loss" | "warning" | "neutral"> = {
  ok: "profit",
  failed: "loss",
  wrong: "loss",
  cut_off: "warning",
  running: "neutral",
  skipped: "neutral",
};

const WORD: Record<string, string> = {
  ok: "Done",
  failed: "Failed",
  wrong: "Wrong",
  cut_off: "Cut off",
  running: "Running",
  skipped: "Skipped",
};

/** Plain names for the kinds of work, for the filter. */
function kindWord(kind: string): string {
  const word = kind.replace(/_/g, " ");
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function took(ms: number | null): string {
  if (ms === null) return "";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60_000)} min`;
}

function Row({ a }: { a: ActionRow }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <>
      <tr className="cursor-pointer border-t border-border hover:bg-surface-sunken" onClick={() => setOpen(!open)}>
        <td className="py-2 pr-2 pl-4 align-top text-fg-muted">
          <Chevron size={14} aria-hidden="true" />
        </td>
        <td className="px-2 py-2 align-top whitespace-nowrap text-small text-fg-muted">{formatAgo(a.started_at)}</td>
        <td className="px-2 py-2 align-top text-small text-fg-muted">{kindWord(a.kind)}</td>
        <td className="px-2 py-2 align-top">{a.what}</td>
        <td className="max-w-[420px] truncate px-2 py-2 align-top text-small text-fg-muted">{a.output}</td>
        <td className="px-2 py-2 align-top">
          <Pill tone={TONE[a.status] ?? "neutral"}>{WORD[a.status] ?? a.status}</Pill>
        </td>
        <td className="py-2 pr-4 pl-2 text-right align-top whitespace-nowrap text-small text-fg-muted">{took(a.ms)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="bg-surface-sunken px-10 py-3 text-small">
            <dl className="m-0 grid grid-cols-[110px_1fr] gap-x-3 gap-y-1">
              <dt className="text-fg-muted">Started by</dt>
              <dd className="m-0">{a.who}</dd>
              {a.why && (
                <>
                  <dt className="text-fg-muted">Why</dt>
                  <dd className="m-0">{a.why}</dd>
                </>
              )}
              <dt className="text-fg-muted">What came out</dt>
              <dd className="m-0 whitespace-pre-wrap">{a.output || "Nothing was recorded."}</dd>
              <dt className="text-fg-muted">Was it right?</dt>
              <dd className="m-0">{a.correct === null ? "Not checked" : a.correct ? "Yes" : "No"}{a.correct_why ? `: ${a.correct_why}` : ""}</dd>
              <dt className="text-fg-muted">When</dt>
              <dd className="m-0">{new Date(a.started_at).toLocaleString()}</dd>
              {Object.keys(a.detail).length > 0 && (
                <>
                  <dt className="text-fg-muted">Details</dt>
                  <dd className="m-0 font-mono text-[12px] break-all">{JSON.stringify(a.detail)}</dd>
                </>
              )}
            </dl>
          </td>
        </tr>
      )}
    </>
  );
}

export default function Logs() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [hours, setHours] = useState(24);
  const path = useMemo(() => {
    const p = new URLSearchParams({ q, kind, status, hours: String(hours), limit: "300" });
    return `/actions?${p.toString()}`;
  }, [q, kind, status, hours]);
  const state = useApi<ActionsResponse>(path, 30_000);
  const control = "h-9 rounded-md border border-border bg-surface px-3 text-small";
  return (
    <>
      <PageHeader title="Logs" subtitle="Everything Agora did: who started it, why, what came out, and whether that was right." />
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label="Search the log" className={`${control} w-[260px]`} placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Kind of work" className={control} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds of work</option>
          {state.status === "ready" && state.data.summary.map((k) => <option key={k.kind} value={k.kind}>{kindWord(k.kind)} ({formatCount(k.n)})</option>)}
        </select>
        <select aria-label="Outcome" className={control} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any outcome</option>
          {Object.entries(WORD).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select aria-label="How far back" className={control} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={1}>Last hour</option>
          <option value={24}>Last day</option>
          <option value={168}>Last week</option>
          <option value={2160}>Last 90 days</option>
        </select>
      </div>
      <Card className="overflow-hidden p-0">
        {state.status === "loading" && <LoadingRows />}
        {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
        {state.status === "ready" && state.data.actions.length === 0 && (
          <EmptyState icon={ScrollText} title="Nothing here" body="No work matches. Try a longer time or clear the search." />
        )}
        {state.status === "ready" && state.data.actions.length > 0 && (
          <ScrollBox size="page" label="The log">
            <table className="w-full border-collapse text-[14px]">
              <thead className="text-left text-small text-fg-muted">
                <tr>
                  <th className="w-8" aria-label="Open" />
                  <th className="px-2 py-2.5 font-medium">When</th>
                  <th className="px-2 py-2.5 font-medium">Kind</th>
                  <th className="px-2 py-2.5 font-medium">What</th>
                  <th className="px-2 py-2.5 font-medium">What came out</th>
                  <th className="px-2 py-2.5 font-medium">Outcome</th>
                  <th className="py-2.5 pr-4 pl-2 text-right font-medium">Took</th>
                </tr>
              </thead>
              <tbody>{state.data.actions.map((a) => <Row key={a.id} a={a} />)}</tbody>
            </table>
          </ScrollBox>
        )}
      </Card>
    </>
  );
}
