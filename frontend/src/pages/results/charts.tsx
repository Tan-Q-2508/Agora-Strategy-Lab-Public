import { useCallback } from "react";
import { EChart, type OptionBuilder } from "../../components/charts/EChart";
import { alpha } from "../../components/charts/tokens";
import type { EquityResponse, MarketCode, TradeRow } from "../../lib/api";
import { formatCompactMoney, formatDate, formatMoney, formatPercent, MARKET_CURRENCY, MARKET_TZ } from "../../lib/format";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function EquityChart({ data, market, benchmarkName }: { data: EquityResponse; market: MarketCode; benchmarkName: string }) {
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  const build: OptionBuilder = useCallback(
    (t) => ({
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: unknown) => formatMoney(Number(v), cur, 0),
        axisPointer: { type: "line", lineStyle: { color: t.fgSubtle } },
      },
      legend: { top: 0, right: 0, textStyle: { color: t.fgMuted }, data: ["Your strategy", benchmarkName] },
      grid: { top: 32, left: 8, right: 12, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { formatter: (v: number) => formatDate(v, tz).replace(/^\d+ /, "") } },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => formatCompactMoney(v, cur) } },
      dataZoom: [{ type: "inside" }],
      series: [
        {
          name: "Your strategy",
          type: "line",
          showSymbol: false,
          lineStyle: { width: 2, color: t.accent },
          itemStyle: { color: t.accent },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: alpha(t.accent, 0.22) }, { offset: 1, color: alpha(t.accent, 0) }] } },
          data: data.points.map((p) => [p.ts, p.equity]),
        },
        {
          name: benchmarkName,
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.5, color: t.benchmark, type: "dashed" },
          itemStyle: { color: t.benchmark },
          data: data.benchmark.map((p) => [p.ts, p.value]),
        },
      ],
    }),
    [data, cur, tz, benchmarkName],
  );
  return <EChart build={build} height={320} caption={`Your strategy's money over time vs simply holding the ${benchmarkName}. Drag or scroll to zoom.`} ariaLabel="Equity curve compared with the benchmark" />;
}

export function DrawdownChart({ data, market }: { data: EquityResponse; market: MarketCode }) {
  const tz = MARKET_TZ[market];
  const build: OptionBuilder = useCallback(
    (t) => ({
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => formatPercent(Number(v)) },
      xAxis: { type: "time", axisLabel: { formatter: (v: number) => formatDate(v, tz).replace(/^\d+ /, "") } },
      yAxis: { type: "value", max: 0, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%` } },
      series: [
        {
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.5, color: t.loss },
          areaStyle: { color: alpha(t.loss, 0.18) },
          data: data.points.map((p) => [p.ts, p.drawdown]),
        },
      ],
    }),
    [data, tz],
  );
  return <EChart build={build} height={200} caption="How far below its previous high the account was at each point (the 'underwater' chart)." ariaLabel="Drawdown over time" />;
}

export function MonthlyHeatmap({ monthly }: { monthly: Record<string, number> }) {
  const years = [...new Set(Object.keys(monthly).map((k) => k.slice(0, 4)))].sort();
  const build: OptionBuilder = useCallback(
    (t) => {
      const cells = Object.entries(monthly).map(([k, v]) => [Number(k.slice(5, 7)) - 1, years.indexOf(k.slice(0, 4)), Number((v * 100).toFixed(2))]);
      const maxAbs = Math.max(1, ...cells.map((c) => Math.abs(c[2] ?? 0)));
      return {
        tooltip: { formatter: (p: { value: number[] }) => `${MONTHS[p.value[0] ?? 0]} ${years[p.value[1] ?? 0]}: ${formatPercent((p.value[2] ?? 0) / 100)}` },
        grid: { top: 8, left: 8, right: 8, bottom: 8, containLabel: true },
        xAxis: { type: "category", data: MONTHS, splitArea: { show: false } },
        yAxis: { type: "category", data: years, inverse: true },
        visualMap: { min: -maxAbs, max: maxAbs, show: false, inRange: { color: [t.loss, t.surface, t.profit] } },
        series: [
          {
            type: "heatmap",
            data: cells,
            label: { show: true, color: t.fg, fontSize: 10, formatter: (p: { value: number[] }) => `${(p.value[2] ?? 0) > 0 ? "+" : ""}${(p.value[2] ?? 0).toFixed(1)}` },
            itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
          },
        ],
      };
    },
    [monthly, years],
  );
  return <EChart build={build} height={Math.max(140, 36 * years.length + 40)} caption="Each month's return. Green months made money, red months lost it; the numbers are percentages." ariaLabel="Monthly returns heatmap" />;
}

export function PnlDistribution({ trades }: { trades: TradeRow[] }) {
  const build: OptionBuilder = useCallback(
    (t) => {
      const rets = trades.filter((x) => x.exit_reason !== "end_of_test").map((x) => x.return_pct);
      const lo = Math.floor(Math.min(0, ...rets));
      const hi = Math.ceil(Math.max(0, ...rets));
      const width = Math.max(0.5, (hi - lo) / 24);
      const bins: { x: number; n: number }[] = [];
      for (let x = lo; x < hi; x += width) bins.push({ x, n: 0 });
      for (const r of rets) {
        const b = bins[Math.min(bins.length - 1, Math.floor((r - lo) / width))];
        if (b) b.n += 1;
      }
      return {
        tooltip: { formatter: (p: { dataIndex: number }) => { const b = bins[p.dataIndex]; return b ? `${b.x.toFixed(1)}% to ${(b.x + width).toFixed(1)}%: ${b.n} trades` : ""; } },
        xAxis: { type: "category", data: bins.map((b) => `${b.x.toFixed(0)}%`) },
        yAxis: { type: "value", minInterval: 1 },
        series: [{ type: "bar", data: bins.map((b) => ({ value: b.n, itemStyle: { color: b.x + width / 2 >= 0 ? t.profit : t.loss, borderRadius: [3, 3, 0, 0] } })), barCategoryGap: "12%" }],
      };
    },
    [trades],
  );
  return <EChart build={build} height={220} caption="How many trades ended at each return after charges. Bars right of zero are winners." ariaLabel="Distribution of trade returns" />;
}

const CHARGE_LABELS: Record<string, string> = {
  brokerage: "Brokerage",
  commission: "Commission",
  stt: "STT",
  exchange_txn: "Exchange charge",
  sebi_fee: "SEBI fee",
  stamp_duty: "Stamp duty",
  gst: "GST",
  dp_charge: "DP charge",
  sec_fee: "SEC fee",
  finra_taf: "FINRA fee",
};

export function ChargesDonut({ byType, market }: { byType: Record<string, number>; market: MarketCode }) {
  const cur = MARKET_CURRENCY[market];
  const build: OptionBuilder = useCallback(
    (t) => ({
      color: [t.accent, t.info, t.warning, t.profit, t.benchmark, t.loss, alpha(t.accent, 0.5), alpha(t.info, 0.5)],
      tooltip: { trigger: "item", formatter: (p: { name: string; value: number; percent: number }) => `${p.name}: ${formatMoney(p.value, cur)} (${p.percent.toFixed(0)}%)` },
      legend: { orient: "vertical", right: 0, top: "middle", textStyle: { color: t.fgMuted, fontSize: 11 } },
      series: [
        {
          type: "pie",
          radius: ["52%", "78%"],
          center: ["32%", "50%"],
          itemStyle: { borderColor: t.surface, borderWidth: 2 },
          label: { show: false },
          data: Object.entries(byType)
            .filter(([, v]) => v > 0)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ name: CHARGE_LABELS[k] ?? k, value: Number(v.toFixed(2)) })),
        },
      ],
    }),
    [byType, cur],
  );
  return <EChart build={build} height={220} caption="Where the charges went. Taxes and fees are paid even on losing trades." ariaLabel="Charges by type" />;
}
