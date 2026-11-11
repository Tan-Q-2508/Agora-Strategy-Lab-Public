import { useCallback } from "react";
import { EChart, type OptionBuilder } from "../../components/charts/EChart";
import { alpha } from "../../components/charts/tokens";
import type { MarketCode } from "../../lib/api";
import { formatCompactMoney, formatDate, formatMoney, MARKET_CURRENCY, MARKET_TZ } from "../../lib/format";
import type { Plan, PortfolioBacktest } from "../../lib/portfolio";

/** How the budget is split: one slice per sleeve, plus the cash kept back. */
export function AllocationDonut({ plan }: { plan: Plan }) {
  const cur = MARKET_CURRENCY[plan.market];
  const build: OptionBuilder = useCallback(
    (t) => ({
      color: [t.accent, t.info, t.profit, t.warning, t.benchmark, t.loss, t.fgSubtle],
      tooltip: { trigger: "item", valueFormatter: (v: unknown) => formatMoney(Number(v), cur, 0) },
      xAxis: { show: false },
      yAxis: { show: false },
      series: [
        {
          type: "pie",
          radius: ["58%", "82%"],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 6 },
          label: { show: false },
          data: [
            ...plan.sleeves.map((s) => ({ name: s.name, value: Math.round(s.capital) })),
            { name: "Cash kept back", value: Math.round(plan.cash), itemStyle: { color: alpha(t.fgSubtle, 0.35) } },
          ],
        },
      ],
    }),
    [plan, cur],
  );
  return <EChart build={build} height={220} caption="How the budget is split: each slice is a sleeve (a strategy on its stocks); the grey slice is the cash kept back." ariaLabel="How the portfolio's budget is split" />;
}

/** The portfolio's money over the backtest against simply holding the index. */
export function PortfolioEquity({ bt, market }: { bt: PortfolioBacktest; market: MarketCode }) {
  const cur = MARKET_CURRENCY[market];
  const tz = MARKET_TZ[market];
  const bench = market === "IN" ? "Nifty 50" : "SPY";
  const build: OptionBuilder = useCallback(
    (t) => ({
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => formatMoney(Number(v), cur, 0) },
      legend: { top: 0, right: 0, textStyle: { color: t.fgMuted }, data: ["Portfolio", bench] },
      grid: { top: 32, left: 8, right: 12, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { formatter: (v: number) => formatDate(v, tz).replace(/^\d+ /, "") } },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => formatCompactMoney(v, cur) } },
      dataZoom: [{ type: "inside" }],
      series: [
        {
          name: "Portfolio",
          type: "line",
          showSymbol: false,
          lineStyle: { width: 2, color: t.accent },
          itemStyle: { color: t.accent },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: alpha(t.accent, 0.22) }, { offset: 1, color: alpha(t.accent, 0) }] } },
          data: bt.curve,
        },
        { name: bench, type: "line", showSymbol: false, lineStyle: { width: 1.5, color: t.benchmark, type: "dashed" }, itemStyle: { color: t.benchmark }, data: bt.benchmark },
      ],
    }),
    [bt, cur, tz, bench],
  );
  return <EChart build={build} height={300} caption={`The whole portfolio's money over the backtest vs simply holding the ${bench}. Drag or scroll to zoom.`} ariaLabel="Portfolio equity compared with the benchmark" />;
}
