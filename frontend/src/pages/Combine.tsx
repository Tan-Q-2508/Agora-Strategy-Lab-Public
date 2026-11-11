import { Combine as CombineIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { JobProgress } from "../components/JobProgress";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Pill } from "../components/ui/pill";
import { ScrollBox } from "../components/ui/scroll-box";
import { Segmented } from "../components/ui/segmented";
import { postJson, toEnvelope, type MarketCode, type StrategySummary } from "../lib/api";
import { formatDate, formatSignedMoney, MARKET_CURRENCY, MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useJob, useJobId } from "../lib/useJob";

type Mode = "all" | "any" | "veto" | "vote";

const MODES: { value: Mode; label: string; text: string }[] = [
  { value: "all", label: "All agree", text: "Trades only when every strategy says yes, within five candles of each other." },
  { value: "any", label: "Any one", text: "Trades when any strategy says yes." },
  { value: "veto", label: "Veto", text: "The first strategy trades, unless another has just said to get out." },
  { value: "vote", label: "Vote", text: "Trades when at least two of them say yes." },
];

interface Part { trades: number; win_rate: number | null; net: number }
interface Side { name?: string; study: Part; exam: Part }
interface TradeRow { symbol: string; side: string; entry_ts: number; net: number; return_pct: number }
export interface CombineResult {
  held_up: boolean;
  verdict: string;
  checks: { ok: boolean; text: string }[];
  alone: Side[];
  combined: Side;
  tries: number;
  definition: Record<string, unknown>;
  changes: {
    removed: TradeRow[];
    added: TradeRow[];
    removed_n: number;
    removed_net: number;
    removed_losers: number;
    added_n: number;
    added_net: number;
    added_winners: number;
  };
}

function rate(p: Part): string {
  return p.win_rate === null ? "—" : `${Math.round(p.win_rate * 100)}%`;
}

function Line({ name, s, market, strong }: { name: string; s: Side; market: MarketCode; strong?: boolean }) {
  const cur = MARKET_CURRENCY[market];
  const cell = "px-3 py-2.5 text-right tabular-nums";
  return (
    <tr className="border-b border-hairline last:border-0">
      <td className={`py-2.5 pr-3 pl-5 ${strong ? "font-semibold" : ""}`}>{name}</td>
      <td className={cell}>{s.study.trades}</td>
      <td className={cell}>{rate(s.study)}</td>
      <td className={cell}><Change value={s.study.net} text={formatSignedMoney(s.study.net, cur, 0)} /></td>
      <td className={cell}>{s.exam.trades}</td>
      <td className={cell}>{rate(s.exam)}</td>
      <td className={`${cell} pr-5`}><Change value={s.exam.net} text={formatSignedMoney(s.exam.net, cur, 0)} /></td>
    </tr>
  );
}

function Trades({ title, rows, market }: { title: string; rows: TradeRow[]; market: MarketCode }) {
  const cur = MARKET_CURRENCY[market];
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      {rows.length === 0 ? <p className="m-0 px-5 pb-5 text-small text-fg-muted">None.</p> : (
        <ScrollBox size="sm">
          <table className="w-full border-collapse text-[14px]">
            <tbody>
              {rows.map((t) => (
                <tr key={`${t.symbol}-${t.entry_ts}`} className="border-b border-hairline last:border-0">
                  <td className="py-2 pr-3 pl-5 font-semibold">{t.symbol}</td>
                  <td className="px-3 py-2 text-small text-fg-muted">{formatDate(t.entry_ts, MARKET_TZ[market])}</td>
                  <td className="py-2 pr-5 pl-3 text-right"><Change value={t.net} text={formatSignedMoney(t.net, cur, 0)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollBox>
      )}
    </Card>
  );
}

function Results({ r, market, names }: { r: CombineResult; market: MarketCode; names: string[] }) {
  const navigate = useNavigate();
  const cur = MARKET_CURRENCY[market];
  const c = r.changes;
  async function save() {
    try {
      const out = await postJson<{ id: number }>("/strategies", { name: `Combined: ${names.join(" + ")}`.slice(0, 120), description: "Made with the strategy combiner.", definition: r.definition });
      toast.success("Saved. You can backtest it or paper trade it like any strategy.");
      navigate(`/strategies/${out.id}`);
    } catch (err) {
      toast.error(toEnvelope(err).message);
    }
  }
  return (
    <>
      <Card className="gap-2 p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="m-0 flex items-center gap-2 font-semibold">
            <Pill tone={r.held_up ? "profit" : "warning"}>{r.held_up ? "Held up" : "Didn't hold up"}</Pill>
            {r.verdict}
          </p>
          <Button onClick={() => void save()}>Save as a strategy</Button>
        </div>
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-small text-fg-muted">
          {r.checks.map((x) => <li key={x.text}>{x.ok ? "✓" : "✗"} {x.text}</li>)}
          <li>This strategy has now been tried {r.tries} times; the luck check gets stricter with every try.</li>
        </ul>
      </Card>
      <Card>
        <CardHeader><CardTitle>Against each strategy alone</CardTitle></CardHeader>
        <table className="w-full border-collapse text-[14px]">
          <thead className="text-right text-small text-fg-muted">
            <tr className="border-b border-border">
              <th className="py-2.5 pr-3 pl-5 text-left font-medium">Strategy</th>
              <th className="px-3 font-medium">Study trades</th><th className="px-3 font-medium">Won</th><th className="px-3 font-medium">After costs</th>
              <th className="px-3 font-medium">Exam trades</th><th className="px-3 font-medium">Won</th><th className="px-3 pr-5 font-medium">After costs</th>
            </tr>
          </thead>
          <tbody>
            {r.alone.map((s) => <Line key={s.name} name={s.name ?? ""} s={s} market={market} />)}
            <Line name="Combined" s={r.combined} market={market} strong />
          </tbody>
        </table>
      </Card>
      <div className="grid grid-cols-2 gap-5">
        <Trades title={`Removed ${c.removed_n} trades (${c.removed_losers} were losers, net ${formatSignedMoney(c.removed_net, cur, 0)})`} rows={c.removed} market={market} />
        <Trades title={`Added ${c.added_n} trades (${c.added_winners} were winners, net ${formatSignedMoney(c.added_net, cur, 0)})`} rows={c.added} market={market} />
      </div>
    </>
  );
}

export default function Combine() {
  const list = useApi<{ strategies: StrategySummary[] }>("/strategies?archived=false");
  const [picked, setPicked] = useState<number[]>([]);
  const [mode, setMode] = useState<Mode>("all");
  const [jobId, setJobId] = useJobId("strategy_combine");
  const [result, setResult] = useState<CombineResult | null>(null);
  const { job, cancel } = useJob<CombineResult>(jobId, (j) => {
    if (j.status === "done" && j.result) setResult(j.result);
  });
  const usable = useMemo(() => (list.status === "ready" ? list.data.strategies.filter((s) => (s.kind === "visual" || s.kind === "code") && s.version_id !== null) : []), [list]);
  const first = usable.find((s) => s.version_id === picked[0]);
  const fits = (s: StrategySummary) => !first || (s.market === first.market && s.timeframe === first.timeframe);
  const busy = job?.status === "running" || job?.status === "queued";
  const names = picked.map((v) => usable.find((s) => s.version_id === v)?.name ?? "");

  async function test() {
    setResult(null);
    try {
      const res = await postJson<{ job_id: string }>("/metis/combine", { version_ids: picked, mode });
      setJobId(res.job_id);
    } catch (err) {
      const env = toEnvelope(err);
      toast.error(env.message, { description: env.action });
    }
  }

  return (
    <>
      <PageHeader title="Combine strategies" subtitle="Pick strategies and how they work together, then see which trades that removes and adds. Same tests as everything else: unseen years, costs and the luck check." />
      {list.status === "loading" && <LoadingRows rows={4} />}
      {list.status === "error" && <ErrorState error={list.error} onRetry={list.reload} />}
      {list.status === "ready" && usable.length < 2 && (
        <Card className="justify-center py-4"><EmptyState icon={CombineIcon} title="Not enough strategies" body="You need at least two strategies made of rules or code." /></Card>
      )}
      {usable.length >= 2 && (
        <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-5">
          <Card>
            <CardHeader><CardTitle>Strategies ({picked.length} picked; the first leads)</CardTitle></CardHeader>
            <ScrollBox size="md" label="Strategies">
              <ul className="m-0 list-none p-0">
                {usable.map((s) => {
                  const v = s.version_id as number;
                  const on = picked.includes(v);
                  return (
                    <li key={s.id} className="border-b border-hairline last:border-0">
                      <label className={`flex items-center gap-3 px-5 py-2.5 ${fits(s) ? "" : "opacity-40"}`}>
                        <input type="checkbox" className="size-4 accent-[var(--accent-strong)]" disabled={!on && (!fits(s) || picked.length >= 5)} checked={on} onChange={(e) => setPicked((p) => (e.target.checked ? [...p, v] : p.filter((x) => x !== v)))} />
                        <span className="flex-1">{s.name}</span>
                        <span className="text-small text-fg-subtle">{s.market === "IN" ? "India" : "US"} · {s.timeframe ? TIMEFRAME_LABEL[s.timeframe] : ""}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </ScrollBox>
          </Card>
          <Card>
            <CardHeader><CardTitle>How they work together</CardTitle></CardHeader>
            <CardBody className="flex flex-col gap-3">
              <Segmented label="How they combine" value={mode} onChange={setMode} options={MODES.map((m) => ({ value: m.value, label: m.label }))} />
              <p className="m-0 text-small text-fg-muted">{MODES.find((m) => m.value === mode)?.text}</p>
              <p className="m-0 text-small text-fg-muted">To share money between strategies instead, use Portfolio.</p>
              <Button variant="primary" disabled={picked.length < 2 || busy} onClick={() => void test()}>{busy ? "Testing…" : "Test together"}</Button>
            </CardBody>
          </Card>
        </div>
      )}
      {job && busy && <JobProgress job={job} onCancel={cancel} />}
      {job?.status === "failed" && <p className="m-0 text-small text-loss">{job.message}</p>}
      {result && first && <Results r={result} market={first.market} names={names} />}
    </>
  );
}
