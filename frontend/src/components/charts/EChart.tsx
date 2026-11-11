import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { useTheme } from "../../lib/theme";
import { cn } from "../../lib/utils";
import { readChartTokens, type ChartTokens } from "./tokens";

echarts.use([LineChart, BarChart, HeatmapChart, PieChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, DataZoomComponent, MarkLineComponent, CanvasRenderer]);

export type EChartOption = echarts.EChartsCoreOption;

/** Build an option from the live tokens, so the same chart re-themes on light/dark. */
export type OptionBuilder = (t: ChartTokens) => EChartOption;

function baseTheme(t: ChartTokens): EChartOption {
  const axis = {
    axisLine: { lineStyle: { color: t.border } },
    axisTick: { show: false },
    axisLabel: { color: t.fgSubtle, fontSize: 11 },
    splitLine: { lineStyle: { color: t.grid } },
  };
  return {
    color: [t.accent, t.benchmark, t.info, t.warning, t.profit, t.loss],
    textStyle: { fontFamily: t.fontSans, color: t.fgMuted },
    animationDuration: 600,
    animationEasing: "cubicOut",
    grid: { left: 8, right: 12, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg, fontSize: 12 },
      extraCssText: "border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.14);",
    },
    xAxis: axis,
    yAxis: axis,
  };
}

function merge(base: EChartOption, over: EChartOption): EChartOption {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(over)) {
    const b = out[k];
    const isObj = (x: unknown) => typeof x === "object" && x !== null && !Array.isArray(x);
    out[k] = isObj(b) && isObj(v) ? { ...(b as object), ...(v as object) } : Array.isArray(v) && isObj(b) ? v.map((x) => (isObj(x) ? { ...(b as object), ...x } : x)) : v;
  }
  // Long time axes: never let date labels run into each other.
  const axis = out.xAxis as Record<string, unknown> | undefined;
  if (axis && typeof axis === "object" && !Array.isArray(axis) && axis.type === "time") {
    out.xAxis = { ...axis, axisLabel: { hideOverlap: true, ...(axis.axisLabel as object) } };
  }
  return out;
}

/** Apache ECharts for analytics (equity, drawdown, heatmaps, donuts), themed from tokens. */
export function EChart({
  build,
  height = 280,
  caption,
  ariaLabel,
  className,
}: {
  build: OptionBuilder;
  height?: number;
  caption: string;
  ariaLabel: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const t = readChartTokens();
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    chart.setOption({ ...merge(baseTheme(t), build(t)), animation: !reduce });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [build, resolved]);

  return (
    <figure className={cn("m-0 flex flex-col gap-2", className)}>
      <div ref={ref} role="img" aria-label={ariaLabel} style={{ height }} />
      <figcaption className="text-small text-fg-muted">{caption}</figcaption>
    </figure>
  );
}
