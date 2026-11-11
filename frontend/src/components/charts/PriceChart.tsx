import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesType,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "../../lib/theme";
import { cn } from "../../lib/utils";
import { DrawingsPrimitive, type ChartDrawings } from "./drawings";
import { alpha, readChartTokens } from "./tokens";

export interface Candle {
  time: number; // bar open, UTC seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface TradeMarker {
  time: number;
  kind: "buy" | "sell";
  text?: string;
}

export interface Overlay {
  id: string;
  label: string;
  color?: "accent" | "info" | "benchmark" | "warning";
  points: { time: number; value: number }[];
}

export interface PriceChartProps {
  candles: Candle[];
  markers?: TradeMarker[];
  overlays?: Overlay[];
  drawings?: ChartDrawings | null; // shapes drawn onto the chart (Kairos)
  timeZone: string; // the market's zone, e.g. "Asia/Kolkata"
  intraday?: boolean;
  initialFrom?: number; // open zoomed to candles from here (UTC seconds); the rest is a scroll away
  height?: number;
  caption: string;
  ariaLabel: string;
  className?: string;
}

interface Legend {
  o: number;
  h: number;
  l: number;
  c: number;
}

function fmtTime(seconds: number, timeZone: string, intraday: boolean): string {
  const opts: Intl.DateTimeFormatOptions = intraday
    ? { hour: "2-digit", minute: "2-digit", hour12: false, timeZone }
    : { day: "numeric", month: "short", timeZone };
  return new Intl.DateTimeFormat("en-GB", opts).format(new Date(seconds * 1000));
}

/** Run a clean-up step that may find its chart already removed (React runs both effects'
 * clean-ups when the candles change). */
function safe(fn: () => void) {
  try {
    fn();
  } catch {
    /* the chart is already gone */
  }
}

/**
 * TradingView Lightweight Charts, themed from tokens: candles, volume, trade markers,
 * indicator overlays, Kairos drawings and a floating OHLC legend that follows the crosshair.
 * The chart is built once per set of candles; overlays, markers and drawings are layered on
 * separately so switching them on and off keeps the user's zoom.
 */
export function PriceChart({
  candles,
  markers = [],
  overlays = [],
  drawings = null,
  timeZone,
  intraday = false,
  initialFrom,
  height = 360,
  caption,
  ariaLabel,
  className,
}: PriceChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const hadDrawings = useRef(false);
  const [api, setApi] = useState<{ chart: IChartApi; series: ISeriesApi<"Candlestick"> } | null>(null);
  const { resolved } = useTheme();
  const last = candles.at(-1);
  const [legend, setLegend] = useState<Legend | null>(last ? { o: last.open, h: last.high, l: last.low, c: last.close } : null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const t = readChartTokens();
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: t.fgSubtle,
        fontFamily: t.fontSans,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: t.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false,
        timeVisible: intraday,
        tickMarkFormatter: (time: Time) => fmtTime(time as number, timeZone, intraday),
      },
      localization: { timeFormatter: (time: Time) => fmtTime(time as number, timeZone, intraday) },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: t.fgSubtle, labelBackgroundColor: t.fg },
        horzLine: { color: t.fgSubtle, labelBackgroundColor: t.fg },
      },
    });
    chartRef.current = chart;
    hadDrawings.current = false; // a new chart: zoom to Kairos's view again when it draws

    const series = chart.addSeries(CandlestickSeries, {
      upColor: t.profit,
      downColor: t.loss,
      borderVisible: false,
      wickUpColor: t.profit,
      wickDownColor: t.loss,
    });
    series.setData(candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    // Keep candles clear of the volume bars at the bottom.
    series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });

    if (candles.some((c) => c.volume !== undefined)) {
      const volume = chart.addSeries(HistogramSeries, { priceScaleId: "", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volume.setData(
        candles.map((c) => ({
          time: c.time as UTCTimestamp,
          value: c.volume ?? 0,
          color: alpha(c.close >= c.open ? t.profit : t.loss, 0.28),
        })),
      );
    }

    const from = initialFrom === undefined ? 0 : candles.findIndex((c) => c.time >= initialFrom);
    if (from > 0) chart.timeScale().setVisibleLogicalRange({ from: Math.min(from, Math.max(0, candles.length - 30)), to: candles.length + 2 });
    else chart.timeScale().fitContent();
    const onMove = (p: MouseEventParams<Time>) => {
      const d = p.seriesData.get(series) as { open: number; high: number; low: number; close: number } | undefined;
      if (d && "open" in d) setLegend({ o: d.open, h: d.high, l: d.low, c: d.close });
    };
    chart.subscribeCrosshairMove(onMove);
    setApi({ chart, series });
    return () => {
      setApi(null);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the opening zoom only applies when the chart is built
  }, [candles, timeZone, intraday, resolved]);

  // Overlays, markers and drawings, layered onto the chart built above.
  useEffect(() => {
    // Skip a stale chart: when the chart is rebuilt this effect first runs with the old one.
    if (!api || api.chart !== chartRef.current) return;
    const { chart, series } = api;
    const t = readChartTokens();
    const added: ISeriesApi<SeriesType>[] = [];
    const palette = { accent: t.accent, info: t.info, benchmark: t.benchmark, warning: t.warning };
    for (const o of overlays) {
      const line = chart.addSeries(LineSeries, {
        color: palette[o.color ?? "accent"],
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData(o.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      added.push(line);
    }
    const lastTime = candles.at(-1)?.time ?? 0;
    const future = (drawings?.future ?? []).filter((x) => x > lastTime);
    if (future.length) {
      // Empty candle slots to the right of today, so lines and forecasts have room.
      const slots = chart.addSeries(LineSeries, { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
      slots.setData(future.map((x) => ({ time: x as UTCTimestamp })));
      added.push(slots);
    }
    const items: SeriesMarker<Time>[] = [
      ...markers.map((m) => ({
        time: m.time as UTCTimestamp,
        position: (m.kind === "buy" ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
        shape: (m.kind === "buy" ? "arrowUp" : "arrowDown") as "arrowUp" | "arrowDown",
        color: m.kind === "buy" ? t.profit : t.loss,
        text: m.text ?? "",
      })),
      ...(drawings?.markers ?? []).map((m) => ({ ...m, time: m.time as UTCTimestamp })),
    ].sort((a, b) => (a.time as number) - (b.time as number));
    const markerApi = items.length ? createSeriesMarkers(series, items) : null;
    const prim = drawings ? new DrawingsPrimitive(drawings) : null;
    if (prim) series.attachPrimitive(prim);
    const levels = (drawings?.levels ?? []).map((l) =>
      series.createPriceLine({
        price: l.price,
        color: l.color,
        lineWidth: 1,
        lineStyle: l.dashed ? 2 : 0,
        lineVisible: !l.axisOnly,
        axisLabelVisible: true,
        title: l.title,
      }),
    );
    if (drawings && !hadDrawings.current) {
      // Zoom to the recent stretch Kairos is talking about, with room for the forecast.
      const n = candles.length;
      const focus = drawings.focus ?? n;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - focus), to: n + future.length + 2 });
    }
    hadDrawings.current = Boolean(drawings);
    return () => {
      // When the whole chart is going away it's already removed: touching it would
      // schedule a repaint of a disposed chart.
      if (chartRef.current !== chart) return;
      safe(() => levels.forEach((l) => series.removePriceLine(l)));
      safe(() => prim && series.detachPrimitive(prim));
      safe(() => markerApi?.detach());
      safe(() => added.forEach((x) => chart.removeSeries(x)));
    };
  }, [api, candles, overlays, markers, drawings]);

  return (
    <figure className={cn("m-0 flex flex-col gap-2", className)}>
      <div className="relative" style={{ height }}>
        {legend && (
          <div className="pointer-events-none absolute top-1 left-1 z-10 flex gap-3 rounded-control bg-surface/85 px-2 py-1 text-tiny text-fg-muted backdrop-blur-sm">
            <span>O {legend.o.toFixed(2)}</span>
            <span>H {legend.h.toFixed(2)}</span>
            <span>L {legend.l.toFixed(2)}</span>
            <span>
              C <b className="font-semibold text-fg">{legend.c.toFixed(2)}</b>
            </span>
          </div>
        )}
        <div ref={ref} role="img" aria-label={ariaLabel} className="absolute inset-0" />
      </div>
      <figcaption className="text-small text-fg-muted">{caption}</figcaption>
    </figure>
  );
}
