import { FlaskConical, Star } from "lucide-react";
import { ScrollBox } from "../components/ui/scroll-box";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Dot } from "../components/ui/pill";
import { Segmented } from "../components/ui/segmented";
import type { BacktestBrief } from "../lib/api";
import { formatAgo, formatDate, formatPercent, MARKET_TZ, TIMEFRAME_LABEL } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ownerOf, type Owner } from "../lib/owner";
import { Tabs } from "../components/ui/tabs";
import { cn } from "../lib/utils";

const STATUS = {
  queued: { label: "Waiting", tone: "neutral" as const },
  running: { label: "Running", tone: "warning" as const },
  done: { label: "Finished", tone: "profit" as const },
  failed: { label: "Failed", tone: "loss" as const },
  cancelled: { label: "Cancelled", tone: "neutral" as const },
};
const MODE = { single: "", oos: "In/out of sample", sweep: "Sweep", walk_forward: "Walk-forward" } as const;

const OWNERS: { value: Owner; label: string }[] = [
  { value: "you", label: "Yours" },
  { value: "metis", label: "Metis" },
  { value: "kairos", label: "Kairos" },
];

export default function Backtests() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"all" | "starred">("all");
  const s = useApi<{ backtests: BacktestBrief[] }>(`/backtests?limit=200${filter === "starred" ? "&starred=true" : ""}`, 5000);
  const [picked, setPicked] = useState<number[]>([]);
  const [owner, setOwner] = useState<Owner>("you");

  return (
    <>
      <PageHeader
        title="Backtests"
        subtitle="Test a strategy on years of past prices, with realistic Indian and US charges."
        actions={
          <>
            <Segmented label="Show" value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "starred", label: "Starred" }]} />
            {picked.length >= 2 && (
              <Button onClick={() => navigate(`/compare?runs=${picked.join(",")}`)}>Compare {picked.length}</Button>
            )}
            <Button variant="primary" asChild>
              <Link to="/backtests/new">Run a backtest</Link>
            </Button>
          </>
        }
      />
      {s.status === "loading" && <LoadingRows rows={5} />}
      {s.status === "error" && <ErrorState error={s.error} onRetry={s.reload} />}
      {s.status === "ready" && s.data.backtests.length === 0 && (
        <Card className="min-h-[360px] justify-center">
          <EmptyState
            icon={FlaskConical}
            title={filter === "starred" ? "No starred backtests" : "No backtests yet"}
            body="Pick a strategy and a date range. Results show the return, the worst drop, charges paid and how much to trust them."
            action={
              <Button variant="soft" asChild>
                <Link to="/strategies">Choose a strategy</Link>
              </Button>
            }
          />
        </Card>
      )}
      {s.status === "ready" && s.data.backtests.length > 0 && (
        <Card className="overflow-hidden p-0">
          <Tabs
            label="Whose backtests"
            value={owner}
            onValueChange={(v) => setOwner(v as Owner)}
            tabs={OWNERS.map((o) => ({
              value: o.value,
              label: (
                <>
                  {o.label}{" "}
                  <span className="text-small font-normal text-fg-subtle">
                    {s.data.backtests.filter((b) => ownerOf(b.strategy_name) === o.value).length}
                  </span>
                </>
              ),
              content: null,
            }))}
          />
          <ScrollBox size="page" label="Backtests">
            <table className="w-full border-collapse text-[14px]">
              <thead className="text-left text-small text-fg-muted">
                <tr className="border-b border-border">
                  <th className="py-3 pr-2 pl-5 font-medium">
                    <span className="sr-only">Select to compare</span>
                  </th>
                  <th className="px-3 py-3 font-medium">Strategy</th>
                  <th className="px-3 py-3 font-medium">Period</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 text-right font-medium">Total return</th>
                  <th className="px-3 py-3 text-right font-medium">Worst drop</th>
                  <th className="px-3 py-3 text-right font-medium">Trades</th>
                  <th className="py-3 pr-5 pl-3 text-right font-medium">Run</th>
                </tr>
              </thead>
              <tbody>
                {s.data.backtests.filter((b) => ownerOf(b.strategy_name) === owner).map((b) => {
                  const st = STATUS[b.status];
                  const tz = MARKET_TZ[b.market];
                  return (
                    <tr key={b.id} className="cursor-pointer border-b border-hairline last:border-0 hover:bg-surface-2/60" onClick={() => navigate(`/backtests/${b.id}`)}>
                      <td className="py-3 pr-2 pl-5" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={`Select backtest ${b.id} to compare`}
                          disabled={b.status !== "done" || (!picked.includes(b.id) && picked.length >= 4)}
                          checked={picked.includes(b.id)}
                          onChange={(e) => setPicked((p) => (e.target.checked ? [...p, b.id] : p.filter((x) => x !== b.id)))}
                          className="size-4 accent-[var(--accent-strong)]"
                        />
                      </td>
                      <td className="px-3 py-3">
                        <Link to={`/backtests/${b.id}`} className="font-semibold text-fg no-underline" onClick={(e) => e.stopPropagation()}>
                          {b.starred && <Star className="mr-1 inline size-3.5 fill-accent text-accent" aria-label="Starred" />}
                          {b.name ?? b.strategy_name} <span className="font-normal text-fg-subtle">v{b.version}</span>
                        </Link>
                        <div className="text-tiny text-fg-subtle">
                          {b.market === "IN" ? "India" : "US"} · {TIMEFRAME_LABEL[b.timeframe]} · {b.symbols.length} stock{b.symbols.length === 1 ? "" : "s"}
                          {MODE[b.mode] ? ` · ${MODE[b.mode]}` : ""}
                          {b.symbols.length >= 30 ? " · today's list, flattered" : ""}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-small tabular-nums text-fg-muted">
                        {formatDate(b.start, tz)} – {formatDate(b.end - 1, tz)}
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex items-center gap-2 text-small whitespace-nowrap">
                          <Dot tone={st.tone} live={b.status === "running"} />
                          {st.label}
                          {b.status === "running" && ` ${Math.round(b.progress)}%`}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {b.headline.total_return != null ? <Change value={b.headline.total_return} text={formatPercent(b.headline.total_return)} /> : "—"}
                      </td>
                      <td className={cn("px-3 py-3 text-right tabular-nums")}>{b.headline.max_drawdown != null ? `${(b.headline.max_drawdown * 100).toFixed(1)}%` : "—"}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{b.headline.trades ?? "—"}</td>
                      <td className="py-3 pr-5 pl-3 text-right text-small text-fg-subtle">{formatAgo(b.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </ScrollBox>
        </Card>
      )}
    </>
  );
}
