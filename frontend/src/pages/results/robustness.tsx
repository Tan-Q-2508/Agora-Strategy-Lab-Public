import { useCallback } from "react";
import { EChart, type OptionBuilder } from "../../components/charts/EChart";
import { Change } from "../../components/ui/change";
import type { MarketCode } from "../../lib/api";
import { formatDate, formatPercent, MARKET_TZ } from "../../lib/format";
import { ScrollBox } from "../../components/ui/scroll-box";

interface Part {
  total_return?: number;
  cagr?: number | null;
  max_drawdown?: number;
  sharpe?: number | null;
  trades?: number;
  win_rate?: number | null;
  empty?: boolean;
}

function PartCard({ title, p, note }: { title: string; p: Part; note: string }) {
  if (p.empty) return <div className="rounded-tile border border-hairline p-4 text-small text-fg-muted">{title}: no data.</div>;
  return (
    <div className="flex flex-col gap-2 rounded-tile border border-hairline p-4">
      <p className="m-0 font-semibold">{title}</p>
      <p className="m-0 text-tiny text-fg-subtle">{note}</p>
      <dl className="m-0 grid grid-cols-2 gap-2 text-small">
        <dt className="text-fg-muted">Total return</dt>
        <dd className="m-0 text-right">
          <Change value={p.total_return ?? 0} text={formatPercent(p.total_return ?? 0)} />
        </dd>
        <dt className="text-fg-muted">Worst drop</dt>
        <dd className="m-0 text-right tabular-nums">{p.max_drawdown !== undefined ? `${(p.max_drawdown * 100).toFixed(1)}%` : "—"}</dd>
        <dt className="text-fg-muted">Sharpe</dt>
        <dd className="m-0 text-right tabular-nums">{p.sharpe?.toFixed(2) ?? "—"}</dd>
        <dt className="text-fg-muted">Trades · win rate</dt>
        <dd className="m-0 text-right tabular-nums">
          {p.trades ?? 0} · {p.win_rate != null ? `${Math.round(p.win_rate * 100)}%` : "—"}
        </dd>
      </dl>
    </div>
  );
}

export function PeriodsView({ periods, market }: { periods: { split_ts: number; in_sample: Part; out_of_sample: Part }; market: MarketCode }) {
  const d = formatDate(periods.split_ts, MARKET_TZ[market]);
  return (
    <div className="grid grid-cols-2 gap-4">
      <PartCard title="In-sample (before the split)" p={periods.in_sample} note={`Up to ${d}: the part you'd tune the rules on.`} />
      <PartCard title="Out-of-sample (after the split)" p={periods.out_of_sample} note={`From ${d}: a fairer test of how the rules hold up.`} />
    </div>
  );
}

interface Cell {
  run_id: number;
  overrides: Record<string, number>;
  metrics: Record<string, number | null>;
}

const METRIC_WORDS: Record<string, string> = { sharpe: "Sharpe ratio", total_return: "Total return", cagr: "Yearly return", profit_factor: "Profit factor", calmar: "Calmar ratio" };

interface Pbo {
  pbo: number | null;
  tries: number;
  blocks?: number;
  combinations?: number;
  oos_loss?: number;
  text: string;
}

export function SweepView({ sweep }: { sweep: { params: { name: string; values: number[] }[]; metric: string; cells: Cell[]; best: Record<string, number>; isolated_peak: boolean; pbo?: Pbo } }) {
  const [px, py] = sweep.params;
  const metric = sweep.metric;
  const pct = metric === "total_return" || metric === "cagr";
  const build: OptionBuilder = useCallback(
    (t) => {
      const val = (c: Cell) => {
        const v = c.metrics[metric];
        return v === null || v === undefined ? null : pct ? Number((v * 100).toFixed(2)) : Number(v.toFixed(3));
      };
      if (!py || !px) {
        const x = px?.values ?? [];
        return {
          tooltip: { trigger: "axis" },
          xAxis: { type: "category", data: x.map(String), name: px?.name },
          yAxis: { type: "value", name: METRIC_WORDS[metric] },
          series: [{ type: "bar", data: sweep.cells.map((c) => ({ value: val(c), itemStyle: { color: JSON.stringify(c.overrides) === JSON.stringify(sweep.best) ? t.accent : t.benchmark, borderRadius: [3, 3, 0, 0] } })) }],
        };
      }
      const data = sweep.cells.map((c) => [px.values.indexOf(c.overrides[px.name] ?? NaN), py.values.indexOf(c.overrides[py.name] ?? NaN), val(c)]);
      const nums = data.map((d) => d[2]).filter((v): v is number => typeof v === "number");
      return {
        tooltip: { formatter: (p: { value: (number | null)[] }) => `${px.name} ${px.values[p.value[0] ?? 0]}, ${py.name} ${py.values[p.value[1] ?? 0]}: ${p.value[2] ?? "—"}${pct ? "%" : ""}` },
        grid: { top: 8, left: 8, right: 8, bottom: 24, containLabel: true },
        xAxis: { type: "category", data: px.values.map(String), name: px.name, nameLocation: "middle", nameGap: 26 },
        yAxis: { type: "category", data: py.values.map(String), name: py.name },
        visualMap: { min: Math.min(...nums, 0), max: Math.max(...nums, 0.0001), show: false, inRange: { color: [t.loss, t.surface, t.profit] } },
        series: [{ type: "heatmap", data, label: { show: true, color: t.fg, fontSize: 10 }, itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 } }],
      };
    },
    [sweep, px, py, metric, pct],
  );
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-small">
        Best setting: <b>{Object.entries(sweep.best).map(([k, v]) => `${k} = ${v}`).join(", ")}</b> by {METRIC_WORDS[metric] ?? metric}. The results above are for this setting.
      </p>
      {sweep.isolated_peak && <p className="m-0 rounded-tile bg-warning-soft p-2.5 text-small text-warning-soft-fg">The best setting is a lone peak: its neighbours did much worse. That usually means overfitting.</p>}
      {sweep.pbo && <PboNote pbo={sweep.pbo} />}
      <EChart build={build} height={py ? Math.max(220, 34 * py.values.length + 60) : 240} caption={`${METRIC_WORDS[metric] ?? metric} for every combination tested. A broad area of good results is more trustworthy than one bright cell.`} ariaLabel="Parameter sweep results" />
    </div>
  );
}

export function WalkForwardView({ wf, market }: { wf: { metric: string; windows: { train_start: number; train_end: number; test_start: number; test_end: number; best: Record<string, number>; test_return: number | null }[] }; market: MarketCode }) {
  const tz = MARKET_TZ[market];
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-small text-fg-muted">Each window picks the best setting on its tuning period, then trades it on the next period it has never seen. The equity curve above chains those unseen periods together.</p>
      <ScrollBox size="lg">
        <table className="w-full border-collapse text-[14px]">
          <thead className="text-left text-small text-fg-muted">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Tuned on</th>
              <th className="px-3 py-2 font-medium">Tested on</th>
              <th className="px-3 py-2 font-medium">Chosen setting</th>
              <th className="py-2 pl-3 text-right font-medium">Test return</th>
            </tr>
          </thead>
          <tbody>
            {wf.windows.map((w, i) => (
              <tr key={i} className="border-b border-hairline last:border-0">
                <td className="py-2 pr-3 text-small tabular-nums">
                  {formatDate(w.train_start, tz)} – {formatDate(w.train_end, tz)}
                </td>
                <td className="px-3 py-2 text-small tabular-nums">
                  {formatDate(w.test_start, tz)} – {formatDate(w.test_end, tz)}
                </td>
                <td className="px-3 py-2 text-small">{Object.entries(w.best).map(([k, v]) => `${k} = ${v}`).join(", ")}</td>
                <td className="py-2 pl-3 text-right">{w.test_return !== null ? <Change value={w.test_return} text={formatPercent(w.test_return)} /> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollBox>
    </div>
  );
}

/** The probability of backtest overfitting (CSCV, D-89) as a small gauge with its sentence. */
function PboNote({ pbo }: { pbo: Pbo }) {
  if (pbo.pbo === null) return <p className="m-0 text-small text-fg-muted">{pbo.text}</p>;
  const p = pbo.pbo;
  const tone = p < 0.2 ? "bg-profit" : p < 0.5 ? "bg-accent" : "bg-loss";
  return (
    <div className="flex flex-col gap-2 rounded-tile border border-hairline p-3">
      <div className="flex items-center justify-between gap-3 text-small">
        <span className="font-semibold">Chance the best setting is just the luckiest</span>
        <span className="font-semibold tabular-nums">{Math.round(p * 100)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`Probability of backtest overfitting ${Math.round(p * 100)}%`}>
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(2, p * 100)}%` }} />
      </div>
      <p className="m-0 text-small text-fg-muted">{pbo.text}</p>
      {pbo.oos_loss !== undefined && <p className="m-0 text-tiny text-fg-subtle">The setting picked on one half lost money on the other half in {Math.round(pbo.oos_loss * 100)}% of the {pbo.combinations?.toLocaleString("en-GB")} splits tested.</p>}
    </div>
  );
}
