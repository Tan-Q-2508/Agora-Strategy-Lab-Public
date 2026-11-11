/**
 * Indices (D-174): every Indian and US index Agora follows, in three groups: the market as a
 * whole and by size, its sectors (sorted by today's move, so money flowing in or out shows at a
 * glance), and its gauges (volatility, currency, rates). The user asked for this on 2026-11-05.
 */
import { motion } from "framer-motion";
import { Gauge } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingRows } from "../components/states";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/card";
import { Change } from "../components/ui/change";
import { Segmented } from "../components/ui/segmented";
import type { MarketCode } from "../lib/api";
import { formatAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ScrollBox } from "../components/ui/scroll-box";

export interface IndexRow {
  symbol: string;
  name: string;
  group: "broad" | "sector" | "gauge";
  market: MarketCode;
  value: number | null;
  as_of?: number;
  change_pct?: number | null;
  change_1m_pct?: number | null;
  change_1y_pct?: number | null;
  ytd_pct?: number | null;
  spark?: number[];
}

export interface IndicesResponse {
  market: MarketCode;
  groups: { key: "broad" | "sector" | "gauge"; indices: IndexRow[] }[];
}

const MARKETS: { value: MarketCode; label: string }[] = [
  { value: "IN", label: "India" },
  { value: "US", label: "US" },
];

const GROUP_TITLE: Record<string, { title: string; hint: string }> = {
  broad: { title: "The market", hint: "The whole market and its large, mid and small companies." },
  sector: { title: "Sectors", hint: "Sorted by today's move: where money is going in and out." },
  gauge: { title: "Gauges", hint: "Fear (volatility), the currency and interest rates." },
};

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function value(v: number): string {
  return v.toLocaleString(undefined, { maximumFractionDigits: v < 100 ? 2 : 0 });
}

function Spark({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const span = hi - lo || 1;
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * 100).toFixed(1)},${(28 - ((p - lo) / span) * 26).toFixed(1)}`)
    .join(" ");
  const up = points[points.length - 1]! >= points[0]!;
  return (
    <svg viewBox="0 0 100 30" className="h-7 w-24" aria-hidden="true" preserveAspectRatio="none">
      <path d={d} fill="none" strokeWidth={1.6} className={up ? "stroke-profit" : "stroke-loss"} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Cell({ v }: { v: number | null | undefined }) {
  return v === null || v === undefined ? <span className="text-fg-subtle">—</span> : <Change value={v} text={pct(v)} />;
}

function IndexTable({ rows }: { rows: IndexRow[] }) {
  return (
    <ScrollBox size="xl" className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-small">
        <thead>
          <tr className="text-left text-tiny text-fg-subtle">
            <th className="py-2 pr-3 font-medium">Index</th>
            <th className="py-2 pr-3 text-right font-medium">Value</th>
            <th className="py-2 pr-3 text-right font-medium">Today</th>
            <th className="py-2 pr-3 text-right font-medium">1 month</th>
            <th className="py-2 pr-3 text-right font-medium">This year</th>
            <th className="py-2 pr-3 text-right font-medium">1 year</th>
            <th className="py-2 font-medium">3 months</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="border-t border-hairline">
              <td className="py-2 pr-3">
                <span className="font-semibold">{r.name}</span>
                {r.as_of ? <span className="ml-2 text-tiny text-fg-subtle">{formatAgo(r.as_of)}</span> : null}
              </td>
              <td className="py-2 pr-3 text-right tabular-nums">{r.value === null ? <span className="text-fg-subtle">no prices yet</span> : value(r.value)}</td>
              <td className="py-2 pr-3 text-right tabular-nums"><Cell v={r.change_pct} /></td>
              <td className="py-2 pr-3 text-right tabular-nums"><Cell v={r.change_1m_pct} /></td>
              <td className="py-2 pr-3 text-right tabular-nums"><Cell v={r.ytd_pct} /></td>
              <td className="py-2 pr-3 text-right tabular-nums"><Cell v={r.change_1y_pct} /></td>
              <td className="py-2">{r.spark ? <Spark points={r.spark} /> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollBox>
  );
}

export default function Indices() {
  const [market, setMarket] = useState<MarketCode>("IN");
  const res = useApi<IndicesResponse>(`/indices?market=${market}&refresh=true`, 60_000);
  return (
    <>
      <PageHeader title="Indices" subtitle="Every Indian and US index Agora follows: the whole market, its sectors and its gauges." />
      <Segmented value={market} onChange={(v) => setMarket(v as MarketCode)} options={MARKETS} label="Market" />
      {res.status === "error" ? (
        <ErrorState error={res.error} onRetry={res.reload} />
      ) : res.status === "loading" ? (
        <LoadingRows rows={8} />
      ) : res.data.groups.every((g) => g.indices.length === 0) ? (
        <EmptyState icon={Gauge} title="No indices yet" body="Agora is downloading them; this page fills in within a minute." />
      ) : (
        res.data.groups.map((g) => {
          const rows = g.key === "sector" ? [...g.indices].sort((a, b) => (b.change_pct ?? -1e9) - (a.change_pct ?? -1e9)) : g.indices;
          const meta = GROUP_TITLE[g.key]!;
          return (
            <motion.div key={g.key} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
              <Card>
                <CardHeader>
                  <CardTitle>{meta.title}</CardTitle>
                  <p className="m-0 text-small text-fg-muted">{meta.hint}</p>
                </CardHeader>
                <CardBody>
                  <IndexTable rows={rows} />
                </CardBody>
              </Card>
            </motion.div>
          );
        })
      )}
    </>
  );
}
