import { Columns2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { EChart, type OptionBuilder } from "../components/charts/EChart";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Button } from "../components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Select } from "../components/ui/input";
import { postJson, toEnvelope, type BacktestBrief, type ErrorEnvelope } from "../lib/api";
import { formatDate, formatPercent } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ScrollBox } from "../components/ui/scroll-box";

interface CompareResponse {
  series: { run_id: number; label: string; points: { ts: number; value: number }[] }[];
  metrics: ({ run_id: number; label: string; market: "IN" | "US" } & Record<string, number | null | string>)[];
}

const ROWS: [string, string, "spct" | "pct" | "ratio" | "count"][] = [
  ["total_return", "Total return", "spct"],
  ["cagr", "Yearly return", "spct"],
  ["max_drawdown", "Worst drop", "pct"],
  ["sharpe", "Sharpe ratio", "ratio"],
  ["sortino", "Sortino ratio", "ratio"],
  ["win_rate", "Win rate", "pct"],
  ["profit_factor", "Profit factor", "ratio"],
  ["trades", "Trades", "count"],
];

function cell(v: number | null | string, kind: string) {
  if (v === null || typeof v === "string") return "—";
  if (kind === "spct") return <Change value={v} text={formatPercent(v)} />;
  if (kind === "pct") return `${(v * 100).toFixed(1)}%`;
  if (kind === "ratio") return v.toFixed(2);
  return String(v);
}

export default function Compare() {
  const [search, setSearch] = useSearchParams();
  const ids = (search.get("runs") ?? "").split(",").map(Number).filter(Boolean).slice(0, 4);
  const runs = useApi<{ backtests: BacktestBrief[] }>("/backtests?limit=200");
  const [state, setState] = useState<{ key: string; data?: CompareResponse; error?: ErrorEnvelope } | null>(null);
  const key = ids.join(",");

  useEffect(() => {
    if (!ids.length) return;
    let alive = true;
    postJson<CompareResponse>("/backtests/compare", { run_ids: ids })
      .then((data) => alive && setState({ key, data }))
      .catch((err: unknown) => alive && setState({ key, error: toEnvelope(err) }));
    return () => {
      alive = false;
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = state?.key === key ? state.data : undefined;
  const build: OptionBuilder = useCallback(
    (t) => ({
      color: [t.accent, t.info, t.profit, t.warning],
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => Number(v).toFixed(1) },
      legend: { top: 0, textStyle: { color: t.fgMuted } },
      grid: { top: 36, left: 8, right: 12, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { formatter: (v: number) => formatDate(v).replace(/^\d+ /, "") } },
      yAxis: { type: "value", scale: true },
      dataZoom: [{ type: "inside" }],
      series: (data?.series ?? []).map((s) => ({ name: s.label, type: "line", showSymbol: false, lineStyle: { width: 2 }, data: s.points.map((p) => [p.ts, p.value]) })),
    }),
    [data],
  );
  const done = runs.status === "ready" ? runs.data.backtests.filter((b) => b.status === "done") : [];
  const setIds = (next: number[]) => setSearch(next.length ? { runs: next.join(",") } : {});

  return (
    <>
      <PageHeader title="Compare" subtitle="Overlay up to four backtests to see which held up best." />
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          {ids.map((id) => {
            const b = done.find((x) => x.id === id);
            return (
              <span key={id} className="inline-flex h-9 items-center gap-2 rounded-full border border-border bg-surface-2 pr-1 pl-3 text-small font-semibold">
                {b ? `${b.strategy_name} v${b.version} (#${id})` : `#${id}`}
                <button type="button" aria-label={`Remove backtest ${id}`} onClick={() => setIds(ids.filter((x) => x !== id))} className="rounded-full px-2 py-1 text-fg-muted hover:bg-surface">
                  ×
                </button>
              </span>
            );
          })}
          {ids.length < 4 && (
            <Select aria-label="Add a backtest" value="" onChange={(e) => setIds([...ids, Number(e.target.value)])} className="h-9 w-[320px] text-small">
              <option value="">Add a finished backtest…</option>
              {done
                .filter((b) => !ids.includes(b.id))
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    #{b.id} {b.strategy_name} v{b.version} · {b.headline.total_return != null ? formatPercent(b.headline.total_return) : ""}{b.symbols.length >= 30 ? " (today's list, flattered)" : ""}
                  </option>
                ))}
            </Select>
          )}
        </div>
      </Card>
      {!ids.length ? (
        <Card className="min-h-[360px] justify-center">
          <EmptyState
            icon={Columns2}
            title="Nothing to compare yet"
            body="Pick two to four finished backtests above, or tick them on the Backtests screen."
            action={
              <Button variant="soft" asChild>
                <Link to="/backtests">Go to backtests</Link>
              </Button>
            }
          />
        </Card>
      ) : state?.error ? (
        <ErrorState error={state.error} />
      ) : !data ? (
        <LoadingRows rows={5} />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Growth of 100</CardTitle>
            </CardHeader>
            <CardBody>
              <EChart build={build} height={360} caption="Each backtest starts at 100, so different starting amounts compare fairly." ariaLabel="Equity curves of the compared backtests" />
            </CardBody>
          </Card>
          <Card>
            <ScrollBox size="lg">
              <table className="w-full border-collapse text-[14px]">
                <thead className="text-left text-small text-fg-muted">
                  <tr className="border-b border-border">
                    <th className="py-3 pl-5 font-medium">Measure</th>
                    {data.metrics.map((m) => (
                      <th key={m.run_id} className="px-3 py-3 text-right font-medium">
                        {m.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map(([k, label, kind]) => (
                    <tr key={k} className="border-b border-hairline last:border-0">
                      <td className="py-2.5 pl-5 text-fg-muted">{label}</td>
                      {data.metrics.map((m) => (
                        <td key={m.run_id} className="px-3 py-2.5 text-right tabular-nums">
                          {cell(m[k] ?? null, kind)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollBox>
          </Card>
        </>
      )}
    </>
  );
}
