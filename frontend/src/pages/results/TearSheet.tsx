import { useCallback, type ReactNode } from "react";
import { EChart, type OptionBuilder } from "../../components/charts/EChart";
import { alpha } from "../../components/charts/tokens";
import { LoadingRows } from "../../components/states";
import { Card, CardBody, CardHeader, CardTitle } from "../../components/ui/card";
import { Tooltip } from "../../components/ui/tooltip";
import { formatDate, formatPercent } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { cn } from "../../lib/utils";
import { ScrollBox } from "../../components/ui/scroll-box";

/** The tear sheet of one backtest (D-89), as the backend saves it. */
export interface TearSheetData {
  days: number;
  empty?: boolean;
  text?: string;
  sharpe: { value: number; band: { p5: number; p50: number; p95: number }; psr: number; dsr: number | null; trials: number; min_track_record_days: number | null; have_days: number };
  outcomes: { return_p5?: number; return_p50?: number; return_p95?: number; drop_p50?: number; drop_p95?: number };
  trade_order: { trades: number; history: number; p50: number; p95: number; worst: number; losing_streak_p95?: number };
  rolling: { window: number; points: [string, number][]; share_positive: number | null };
  underwater: { periods: { peak: string; trough: string; recovered: string | null; depth: number; days_falling: number; days_recovering: number | null }[]; time_underwater: number };
  risk: { var_95: number; cvar_95: number; tail_ratio: number; best_day: number; worst_day: number; best_month: number | null; worst_month: number | null; positive_months: number | null; skew: number; kurtosis: number };
  years: { year: string; return: number }[];
  summary: string[];
}

const day = (d: string) => formatDate(Date.parse(`${d}T00:00:00Z`));
const pct = (x: number | null | undefined, digits = 1) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`);

/** Loads the tear sheet when an older run didn't save one. */
export function TearSheet({ runId, saved }: { runId: number; saved?: TearSheetData }) {
  const fetched = useApi<TearSheetData>(saved ? null : `/backtests/${runId}/tearsheet`);
  const got = saved ?? (fetched.status === "ready" ? fetched.data : undefined);
  // an answer without the expected parts is treated as "not available" rather than crashing
  const data = got && (got.empty || (got.sharpe && Array.isArray(got.summary))) ? got : undefined;
  return (
    <Card>
      <CardHeader>
        <CardTitle>How much could be luck</CardTitle>
        <span className="text-tiny text-fg-subtle">Tear sheet · worked out from the daily results</span>
      </CardHeader>
      <CardBody>
        {data ? (
          <Sheet s={data} />
        ) : fetched.status === "error" ? (
          <p className="m-0 text-small text-fg-muted">{fetched.error.message}</p>
        ) : got ? (
          <p className="m-0 text-small text-fg-muted">The tear sheet isn't available for this backtest.</p>
        ) : (
          <LoadingRows rows={4} />
        )}
      </CardBody>
    </Card>
  );
}

function Sheet({ s }: { s: TearSheetData }) {
  if (s.empty) return <p className="m-0 text-small text-fg-muted">{s.text ?? "Too short a backtest for a tear sheet."}</p>;
  return (
    <div className="flex flex-col gap-5">
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-[14px]">
        {s.summary.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
      <div className="grid grid-cols-3 gap-4">
        <SharpeTile s={s} />
        <Tile title="Other histories it could have had" tip="The daily results reshuffled in blocks, 400 times (a block bootstrap): the same kind of days, in other orders.">
          <Row label="Yearly return, bad case" value={pct(s.outcomes.return_p5)} tone={(s.outcomes.return_p5 ?? 0) < 0 ? "loss" : undefined} />
          <Row label="Yearly return, typical" value={pct(s.outcomes.return_p50)} />
          <Row label="Yearly return, good case" value={pct(s.outcomes.return_p95)} />
          <Row label="Worst drop, typical" value={pct(s.outcomes.drop_p50)} />
          <Row label="Worst drop, bad case" value={pct(s.outcomes.drop_p95)} tone="loss" />
        </Tile>
        <Tile title="The same trades, other orders" tip="The finished trades shuffled into 1,000 random orders: the same profit, but other drops along the way.">
          {s.trade_order.trades >= 5 ? (
            <>
              <Row label="Worst drop in history" value={`${s.trade_order.history.toFixed(1)}%`} />
              <Row label="Worst drop, typical order" value={`${s.trade_order.p50.toFixed(1)}%`} />
              <Row label="Worst drop, 1 in 20 orders" value={`${s.trade_order.p95.toFixed(1)}%`} tone="loss" />
              <Row label="Losing trades in a row to expect" value={String(s.trade_order.losing_streak_p95 ?? "—")} />
            </>
          ) : (
            <p className="m-0 text-small text-fg-muted">Too few finished trades to shuffle.</p>
          )}
        </Tile>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_340px] items-start gap-5">
        <div className="flex flex-col gap-2">
          <p className="m-0 text-small font-semibold">Six-month Sharpe ratio over time</p>
          <RollingChart s={s} />
        </div>
        <div className="flex flex-col gap-2">
          <p className="m-0 text-small font-semibold">Each year</p>
          <YearsChart s={s} />
        </div>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_340px] items-start gap-5">
        <Underwater s={s} />
        <Tile title="Risk numbers" tip="From the daily results. A 'bad day' is the worst 5% of days.">
          <Row label="A bad day loses at least" value={pct(s.risk.var_95, 2)} />
          <Row label="The worst 5% of days lose on average" value={pct(s.risk.cvar_95, 2)} />
          <Row label="Best · worst day" value={`${pct(s.risk.best_day)} · ${pct(s.risk.worst_day)}`} />
          <Row label="Best · worst month" value={`${pct(s.risk.best_month)} · ${pct(s.risk.worst_month)}`} />
          <Row label="Months that made money" value={pct(s.risk.positive_months, 0)} />
          <Row label="Good days vs bad days (tail ratio)" value={s.risk.tail_ratio.toFixed(2)} />
          <Row label="Lopsidedness (skew) · fat tails (kurtosis)" value={`${s.risk.skew.toFixed(2)} · ${s.risk.kurtosis.toFixed(1)}`} />
        </Tile>
      </div>
    </div>
  );
}

function Tile({ title, tip, children }: { title: string; tip: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-tile border border-hairline p-4">
      <Tooltip content={tip}>
        <p className="m-0 w-fit cursor-help text-small font-semibold underline decoration-dotted decoration-fg-subtle/50 underline-offset-4" tabIndex={0}>
          {title}
        </p>
      </Tooltip>
      <dl className="m-0 flex flex-col gap-1.5 text-small">{children}</dl>
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "loss" | "profit" }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-fg-muted">{label}</dt>
      <dd className={cn("m-0 tabular-nums font-semibold", tone === "loss" && "text-loss", tone === "profit" && "text-profit")}>{value}</dd>
    </div>
  );
}

/** The Sharpe ratio with its 90% range drawn as a band on a scale that includes zero. */
function SharpeTile({ s }: { s: TearSheetData }) {
  const { value, band, psr, dsr, trials, min_track_record_days: mtr, have_days: have } = s.sharpe;
  const lo = Math.min(0, band.p5, value) - 0.25;
  const hi = Math.max(0, band.p95, value) + 0.25;
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <Tile title="Sharpe ratio and its range" tip="The range comes from reshuffling the daily results; the chance is the probabilistic Sharpe ratio (it allows for lopsided and fat-tailed days).">
      <div className="relative my-2 h-7" role="img" aria-label={`Sharpe ratio ${value.toFixed(2)}, 90% range ${band.p5.toFixed(2)} to ${band.p95.toFixed(2)}`}>
        <div className="absolute inset-x-0 top-3 h-1 rounded-full bg-surface-2" />
        <div className="absolute top-2 h-3 rounded-full bg-accent/25" style={{ left: x(band.p5), width: `calc(${x(band.p95)} - ${x(band.p5)})` }} />
        <div className="absolute top-0.5 h-6 w-px bg-fg-subtle" style={{ left: x(0) }} title="zero" />
        <div className="absolute top-1 size-5 -translate-x-1/2 rounded-full border-2 border-surface bg-accent shadow" style={{ left: x(value) }} />
      </div>
      <Row label="Sharpe ratio" value={value.toFixed(2)} />
      <Row label="90% range" value={`${band.p5.toFixed(2)} to ${band.p95.toFixed(2)}`} />
      <Row label="Chance it is really above zero" value={pct(psr, 0)} tone={psr >= 0.95 ? "profit" : psr < 0.5 ? "loss" : undefined} />
      {dsr !== null && <Row label={`Luck check (best of ${trials} settings)`} value={pct(dsr, 0)} tone={dsr >= 0.5 ? "profit" : "loss"} />}
      <Row label="Days needed to be 95% sure" value={mtr === null ? "never" : `${mtr.toLocaleString("en-GB")} (has ${have.toLocaleString("en-GB")})`} />
    </Tile>
  );
}

function RollingChart({ s }: { s: TearSheetData }) {
  const build: OptionBuilder = useCallback(
    (t) => ({
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => Number(v).toFixed(2) },
      xAxis: { type: "time", axisLabel: { formatter: (v: number) => formatDate(v).replace(/^\d+ /, "") } },
      yAxis: { type: "value", scale: true },
      series: [
        {
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.5, color: t.accent },
          areaStyle: { color: alpha(t.accent, 0.12), origin: 0 },
          data: s.rolling.points.map(([d, v]) => [Date.parse(`${d}T00:00:00Z`), v]),
          markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: t.fgSubtle, type: "dashed" }, data: [{ yAxis: 0 }] },
        },
      ],
    }),
    [s],
  );
  if (!s.rolling.points.length) return <p className="m-0 text-small text-fg-muted">Needs more than six months of results.</p>;
  return <EChart build={build} height={200} caption={`The Sharpe ratio of each ${s.rolling.window}-day window. A steady line above zero is a steady edge; one bump means one lucky stretch.`} ariaLabel="Rolling six-month Sharpe ratio" />;
}

function YearsChart({ s }: { s: TearSheetData }) {
  const build: OptionBuilder = useCallback(
    (t) => ({
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => formatPercent(Number(v) / 100) },
      xAxis: { type: "category", data: s.years.map((y) => y.year) },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${v}%` } },
      series: [{ type: "bar", data: s.years.map((y) => ({ value: Number((y.return * 100).toFixed(2)), itemStyle: { color: y.return >= 0 ? t.profit : t.loss, borderRadius: 3 } })) }],
    }),
    [s],
  );
  return <EChart build={build} height={200} caption="The return of each calendar year (the first and last may be part-years)." ariaLabel="Return of each year" />;
}

function Underwater({ s }: { s: TearSheetData }) {
  const periods = s.underwater.periods;
  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-small font-semibold">
        The deepest falls <span className="font-normal text-fg-muted">· {pct(s.underwater.time_underwater, 0)} of days were below an earlier high</span>
      </p>
      {periods.length === 0 ? (
        <p className="m-0 text-small text-fg-muted">It never fell below a high.</p>
      ) : (
        <ScrollBox size="lg">
          <table className="w-full border-collapse text-[14px]">
            <thead className="text-left text-small text-fg-muted">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Fell from</th>
                <th className="px-3 py-2 font-medium">Lowest</th>
                <th className="px-3 py-2 font-medium">Back to the high</th>
                <th className="px-3 py-2 text-right font-medium">Fall</th>
                <th className="py-2 pl-3 text-right font-medium">Days down · to recover</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p, i) => (
                <tr key={i} className="border-b border-hairline last:border-0">
                  <td className="py-2 pr-3 text-small tabular-nums">{day(p.peak)}</td>
                  <td className="px-3 py-2 text-small tabular-nums">{day(p.trough)}</td>
                  <td className="px-3 py-2 text-small tabular-nums">{p.recovered ? day(p.recovered) : <span className="text-warning">not yet</span>}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-loss">−{pct(p.depth)}</td>
                  <td className="py-2 pl-3 text-right text-small tabular-nums">
                    {p.days_falling} · {p.days_recovering ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollBox>
      )}
    </div>
  );
}
