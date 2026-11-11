import { AlertTriangle, CheckCircle2, Database, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { JobProgress } from "../components/JobProgress";
import { PageHeader } from "../components/PageHeader";
import { WholeMarket } from "../components/WholeMarket";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Dot } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import {
  deleteJson,
  postJson,
  qs,
  toEnvelope,
  type CoverageResponse,
  type CoverageRow,
  type FetchLogRow,
  type Instrument,
  type MarketCode,
  type RefreshResult,
  type SourceInfo,
  type Timeframe,
} from "../lib/api";
import { formatAgo, formatCount, formatDate, MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useJob, useJobId } from "../lib/useJob";
import { cn } from "../lib/utils";
import { ScrollBox } from "../components/ui/scroll-box";

const TIMEFRAMES: Timeframe[] = ["1d", "1h", "15m", "5m", "1m"];

const STATUS: Record<CoverageRow["status"], { label: string; tone: "profit" | "warning" | "loss" | "neutral" }> = {
  ok: { label: "Up to date", tone: "profit" },
  gaps: { label: "Has gaps", tone: "warning" },
  stale: { label: "Needs update", tone: "warning" },
  empty: { label: "Not downloaded", tone: "neutral" },
};

function Summary({ data }: { data: CoverageResponse }) {
  const t = data.totals;
  const tiles = [
    { label: "Stocks", value: t.symbols, hint: "the whole data set" },
    { label: "Up to date", value: t.ok, hint: "nothing missing" },
    { label: "Need attention", value: t.gaps + t.stale, hint: "gaps or old prices" },
    { label: "Not downloaded", value: t.empty, hint: "no prices yet" },
  ];
  return (
    <div className="grid grid-cols-4 gap-5">
      {tiles.map((x) => (
        <Card key={x.label} className="gap-1 p-5">
          <p className="m-0 text-small text-fg-muted">{x.label}</p>
          <p className="m-0 text-title font-bold tabular-nums">{x.value}</p>
          <p className="m-0 text-tiny text-fg-subtle">{x.hint}</p>
        </Card>
      ))}
    </div>
  );
}

function CoverageTable({
  rows,
  timeframe,
  onRefresh,
  onRemove,
}: {
  rows: CoverageRow[];
  timeframe: Timeframe;
  onRefresh: (row: CoverageRow) => void;
  onRemove: (row: CoverageRow) => void;
}) {
  const intraday = timeframe !== "1d";
  return (
    <div className="max-h-[520px] overflow-auto">
      <table className="w-full border-collapse text-[14px]">
        <thead className="sticky top-0 z-10 bg-surface text-left text-small text-fg-muted">
          <tr className="border-b border-border">
            <th className="py-2.5 pr-3 pl-5 font-medium">Stock</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-3 py-2.5 font-medium">From</th>
            <th className="px-3 py-2.5 font-medium">To</th>
            <th className="px-3 py-2.5 text-right font-medium">{intraday ? "Days" : "Candles"}</th>
            {!intraday && <th className="px-3 py-2.5 text-right font-medium">Gaps</th>}
            <th className="px-3 py-2.5 font-medium">Source</th>
            <th className="py-2.5 pr-5 pl-3 text-right font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const st = STATUS[r.status];
            const tz = MARKET_TZ[r.market];
            const removable = r.market === "US" && r.symbol !== "SPY";
            return (
              <tr key={r.instrument_id} className="border-b border-hairline last:border-0 hover:bg-surface-2/60">
                <td className="py-2.5 pr-3 pl-5">
                  <div className="flex flex-col">
                    <span className="font-semibold">{r.symbol}</span>
                    <span className="max-w-[200px] truncate text-small text-fg-muted">{r.name}</span>
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <span className="inline-flex items-center gap-2 text-small whitespace-nowrap">
                    <Dot tone={st.tone} />
                    {st.label}
                  </span>
                </td>
                <td className="px-3 py-2.5 tabular-nums text-fg-muted">{r.first ? formatDate(r.first, tz) : "—"}</td>
                <td className="px-3 py-2.5 tabular-nums text-fg-muted">{r.last ? formatDate(r.last, tz) : "—"}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{intraday ? (r.days ?? 0) : formatCount(r.bars)}</td>
                {!intraday && <td className={cn("px-3 py-2.5 text-right tabular-nums", r.gaps > 0 && "text-warning")}>{r.gaps}</td>}
                <td className="px-3 py-2.5 text-small text-fg-muted">{r.source ?? "—"}</td>
                <td className="py-2.5 pr-5 pl-3">
                  <div className="flex justify-end gap-1">
                    <Button size="icon-sm" variant="ghost" aria-label={`Refresh ${r.symbol}`} title="Refresh this stock" onClick={() => onRefresh(r)}>
                      <RefreshCw aria-hidden="true" />
                    </Button>
                    {removable && (
                      <Button size="icon-sm" variant="ghost" aria-label={`Remove ${r.symbol}`} title="Remove from your list" onClick={() => onRemove(r)}>
                        <Trash2 aria-hidden="true" />
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AddTicker({ onAdded }: { onAdded: (jobId: string) => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await postJson<{ instrument: Instrument; job_id: string }>("/instruments", { symbol: value.trim() });
      toast.success(`${res.instrument.symbol} added. Downloading its prices…`);
      setValue("");
      onAdded(res.job_id);
    } catch (err) {
      const env = toEnvelope(err);
      setError(`${env.message} ${env.action}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <label htmlFor="add-ticker" className="sr-only">
          US ticker to add
        </label>
        <input
          id="add-ticker"
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          placeholder="Add a US ticker, e.g. NFLX"
          maxLength={12}
          className="h-9 w-56 rounded-control border border-border bg-surface px-3 text-[14px] placeholder:text-fg-subtle"
        />
        <Button size="sm" type="submit" disabled={busy || !value.trim()}>
          <Plus aria-hidden="true" />
          {busy ? "Checking…" : "Add"}
        </Button>
      </div>
      {error && <p className="m-0 text-small text-loss">{error}</p>}
    </form>
  );
}

function Sources() {
  const s = useApi<{ sources: SourceInfo[]; recent: FetchLogRow[]; server_time: number }>("/data/sources?limit=12", 15_000);
  if (s.status !== "ready") return <LoadingRows rows={2} />;
  return (
    <div className="flex flex-col gap-4">
      <ScrollBox size="md">
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {s.data.sources.map((src) => (
            <li key={src.source} className="flex items-center justify-between gap-3 text-[14px]">
              <span className="flex items-center gap-2">
                <Dot tone={src.state === "ok" ? "profit" : "warning"} live={src.state === "ok"} />
                {src.label}
              </span>
              <span className="text-small text-fg-muted">
                {src.state === "ok" ? "Working" : src.until ? `Resting until ${new Date(src.until).toLocaleTimeString()}` : "Not answering"}
              </span>
            </li>
          ))}
        </ul>
      </ScrollBox>
      <details className="text-small">
        <summary className="cursor-pointer text-fg-muted">Recent downloads</summary>
        <ScrollBox size="sm">
          <ul className="m-0 mt-2 flex list-none flex-col gap-1 p-0">
            {s.data.recent.length === 0 && <li className="text-fg-subtle">Nothing downloaded yet.</li>}
            {s.data.recent.map((r, i) => (
              <li key={i} className="flex justify-between gap-2 tabular-nums">
                <span className="truncate">
                  {r.symbol ?? "—"} · {r.timeframe} · {r.source}
                </span>
                <span className={cn(r.status === "ok" ? "text-fg-muted" : r.status === "fallback" ? "text-info" : "text-warning")}>
                  {r.status === "ok" ? `${r.rows} candles` : r.status === "fallback" ? `backup source, ${r.rows}` : r.status.replace("_", " ")} ·{" "}
                  {formatAgo(r.at, s.data.server_time)}
                </span>
              </li>
            ))}
          </ul>
        </ScrollBox>
      </details>
    </div>
  );
}

export default function Data() {
  const [market, setMarket] = useState<MarketCode>("IN");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [jobId, setJobId] = useJobId("data_refresh");
  const cov = useApi<CoverageResponse>(`/data/coverage${qs({ market, timeframe })}`);
  const { job, cancel } = useJob<RefreshResult>(jobId, (j) => {
    cov.reload();
    if (j.status === "done" && j.result) {
      const failed = j.result.failed.length;
      if (failed) toast.warning(`${failed} download${failed === 1 ? "" : "s"} didn't finish. Try again in a few minutes.`);
      else toast.success("Prices are up to date.");
      if (j.result.fallback_used) toast.info("Yahoo didn't answer for some stocks, so Agora used a backup source.");
    }
  });
  const busy = job?.status === "running" || job?.status === "queued";

  async function refresh(body: Record<string, unknown>) {
    try {
      const res = await postJson<{ job_id: string }>("/data/refresh", body);
      setJobId(res.job_id);
    } catch (err) {
      const env = toEnvelope(err);
      toast.error(env.message, { description: env.action });
    }
  }

  async function remove(row: CoverageRow) {
    try {
      await deleteJson(`/instruments/${row.instrument_id}`);
      toast.success(`${row.symbol} removed. Its saved prices are kept.`);
      cov.reload();
    } catch (err) {
      const env = toEnvelope(err);
      toast.error(env.message, { description: env.action });
    }
  }

  const lastUpdate = cov.status === "ready" && cov.data.last_update ? formatAgo(cov.data.last_update) : null;
  // only stocks with something wrong (the user, 2026-11-06): the totals above cover the rest
  const rows = useMemo(() => (cov.status === "ready" ? cov.data.rows.filter((r) => r.status !== "ok") : []), [cov]);

  return (
    <>
      <PageHeader
        title="Data"
        subtitle="Which prices Agora has saved, how fresh they are, and any gaps. Refresh now updates every stock that has saved prices, not only the list below."
        actions={
          <Button variant="primary" disabled={busy} onClick={() => refresh({ market, timeframes: [timeframe], scope: "saved" })}>
            <RefreshCw aria-hidden="true" className={cn(busy && "animate-spin")} />
            {busy ? "Downloading…" : "Refresh now"}
          </Button>
        }
      />
      <WholeMarket />
      {cov.status === "ready" && cov.data.data_mode === "fake" && (
        <div className="flex items-center gap-3 rounded-card bg-info-soft px-4 py-3 text-small text-info-soft-fg">
          <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
          Agora is using practice prices (synthetic data), not real market data.
        </div>
      )}
      {job && (
        <Card className="p-5">
          <JobProgress job={job} onCancel={cancel} />
        </Card>
      )}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            label="Market"
            value={market}
            onChange={setMarket}
            options={[
              { value: "IN", label: "India" },
              { value: "US", label: "US" },
            ]}
          />
          <Segmented label="Timeframe" value={timeframe} onChange={setTimeframe} options={TIMEFRAMES.map((t) => ({ value: t, label: TIMEFRAME_LABEL[t] }))} />
        </div>
        {lastUpdate && <span className="text-small text-fg-muted">Last download {lastUpdate}</span>}
      </div>
      {cov.status === "loading" && <LoadingRows rows={6} />}
      {cov.status === "error" && <ErrorState error={cov.error} onRetry={cov.reload} />}
      {cov.status === "ready" && (
        <>
          <Summary data={cov.data} />
          <div className="grid grid-cols-[minmax(0,1fr)_320px] items-start gap-5">
            <Card>
              <CardHeader>
                <CardTitle>
                  Stocks with warnings · {TIMEFRAME_LABEL[timeframe]}
                </CardTitle>
                {market === "US" && <AddTicker onAdded={(id) => (setJobId(id), cov.reload())} />}
              </CardHeader>
              {cov.data.totals.empty === cov.data.totals.symbols ? (
                <EmptyState
                  icon={Database}
                  title="No prices downloaded yet"
                  body={
                    timeframe === "1d"
                      ? "Download about ten years of daily prices for these stocks. It takes a few minutes the first time."
                      : "Yahoo keeps only recent intraday prices. Download them now, and Agora will keep saving more each day while it's open."
                  }
                  action={
                    <Button variant="primary" disabled={busy} onClick={() => refresh({ market, timeframes: [timeframe], scope: "saved" })}>
                      Download prices
                    </Button>
                  }
                />
              ) : rows.length === 0 ? (
                <EmptyState icon={CheckCircle2} title="Nothing to fix" body="Every stock is up to date on this timeframe." />
              ) : (
                <CoverageTable rows={rows} timeframe={timeframe} onRefresh={(r) => refresh({ instrument_ids: [r.instrument_id], timeframes: [timeframe] })} onRemove={remove} />
              )}
            </Card>
            <div className="flex flex-col gap-5">
              <Card>
                <CardHeader>
                  <CardTitle>Data sources</CardTitle>
                </CardHeader>
                <CardBody>
                  <Sources />
                </CardBody>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Good to know</CardTitle>
                </CardHeader>
                <CardBody className="flex flex-col gap-2 text-small text-fg-muted">
                  <p className="m-0 flex gap-2">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-profit" aria-hidden="true" />
                    Agora only downloads what's missing, so refreshing is quick.
                  </p>
                  <p className="m-0 flex gap-2">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-profit" aria-hidden="true" />
                    If Yahoo is busy, Agora waits and tries a backup source (NSE for India, Stooq for the US).
                  </p>
                  <p className="m-0 flex gap-2">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-profit" aria-hidden="true" />
                    Gaps can be real: days a stock didn't trade, or before it was listed.
                  </p>
                </CardBody>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
