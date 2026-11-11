import type {
  AutoscaleInfo,
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
  UTCTimestamp,
} from "lightweight-charts";

/**
 * Shapes drawn straight onto the price chart (Kairos's levels, lines, patterns and forecast).
 * Times are UTC seconds; prices are in the chart's price units. Generic on purpose: the
 * chart knows nothing about Kairos, it just draws what it's given.
 */
export interface TimePoint {
  time: number;
  value: number;
}

/** A filled area between an upper and a lower edge (same times on both). */
export interface Band {
  id: string;
  upper: TimePoint[];
  lower: TimePoint[];
  fill: string;
  stroke?: string;
  dashed?: boolean;
  label?: string;
  labelColor?: string;
}

/** A polyline (trendline, pattern outline, forecast median …). */
export interface Path {
  id: string;
  points: TimePoint[];
  color: string;
  width?: number;
  dashed?: boolean;
  dotted?: boolean;
  label?: string;
  labelAt?: "start" | "mid" | "end"; // where the label sits (default: just inside the end)
  dots?: boolean; // small circles at each point (pattern turning points)
  pointLabels?: (string | undefined)[];
}

export interface Level {
  id: string;
  price: number;
  color: string;
  title: string;
  dashed?: boolean;
  axisOnly?: boolean; // just a label on the price axis (no line across the chart)
}

export interface ChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "circle" | "arrowUp" | "arrowDown" | "square";
  text: string;
}

/** A candle drawn by the primitive (Kairos's predicted candles; hollow = an old prediction
 * outlined over the candles that actually formed). */
export interface GhostCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  color: string;
  fill?: string; // omit for a hollow outline
  dashed?: boolean;
}

export interface ChartDrawings {
  bands: Band[];
  candles?: GhostCandle[];
  paths: Path[];
  levels: Level[];
  markers: ChartMarker[];
  future: number[]; // empty candle slots to the right of today (for lines and forecasts)
  autoscale?: { min: number; max: number } | null;
  focus?: number; // when first shown, zoom to this many recent candles (plus the future slots)
  font: string;
  textColor: string;
}

type Ctx = CanvasRenderingContext2D;
type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];
type XY = [number, number];

interface Prepared {
  bands: { pts: XY[]; fill: string; stroke?: string; dashed?: boolean; label?: string; labelColor?: string; lx: number; ly: number }[];
  paths: { pts: XY[]; color: string; width: number; dashed?: boolean; dotted?: boolean; label?: string; labelAt: "start" | "mid" | "end"; dots?: boolean; labels: (string | undefined)[] }[];
  candles: { x: number; o: number; h: number; l: number; c: number; w: number; color: string; fill?: string; dashed?: boolean }[];
}

class Renderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly data: Prepared,
    private readonly font: string,
    private readonly textColor: string,
    private readonly layer: "bands" | "paths",
  ) {}

  draw(target: Target): void {
    target.useMediaCoordinateSpace(({ context }) => {
      const ctx = context as Ctx;
      ctx.save();
      ctx.font = `500 11px ${this.font}`;
      if (this.layer === "bands") this.drawBands(ctx);
      else {
        this.drawCandles(ctx);
        this.drawPaths(ctx);
      }
      ctx.restore();
    });
  }

  private drawBands(ctx: Ctx): void {
    for (const b of this.data.bands) {
      if (b.pts.length < 3) continue;
      ctx.beginPath();
      b.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fillStyle = b.fill;
      ctx.fill();
      if (b.stroke) {
        ctx.setLineDash(b.dashed ? [4, 4] : []);
        ctx.strokeStyle = b.stroke;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      if (b.label) {
        ctx.setLineDash([]);
        const w = ctx.measureText(b.label).width;
        ctx.fillStyle = b.labelColor ?? this.textColor;
        ctx.fillText(b.label, b.lx - w - 6, b.ly + 4);
      }
    }
  }

  private drawCandles(ctx: Ctx): void {
    for (const k of this.data.candles) {
      const top = Math.min(k.o, k.c);
      const height = Math.max(1, Math.abs(k.o - k.c));
      ctx.setLineDash(k.dashed ? [3, 2] : []);
      ctx.strokeStyle = k.color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(k.x, k.h);
      ctx.lineTo(k.x, top);
      ctx.moveTo(k.x, top + height);
      ctx.lineTo(k.x, k.l);
      ctx.stroke();
      if (k.fill) {
        ctx.fillStyle = k.fill;
        ctx.fillRect(k.x - k.w / 2, top, k.w, height);
      }
      ctx.strokeRect(k.x - k.w / 2 + 0.5, top + 0.5, Math.max(1, k.w - 1), Math.max(1, height - 1));
    }
    ctx.setLineDash([]);
  }

  /** A small tinted tag, kept inside the plot so it never runs under the price axis. */
  private drawLabel(ctx: Ctx, text: string, pts: XY[], at: "start" | "mid" | "end", color: string): void {
    const first = pts[0];
    const last = pts.at(-1);
    if (!first || !last) return;
    const w = ctx.measureText(text).width;
    let x: number;
    let y: number;
    if (at === "start") {
      x = first[0];
      y = Math.min(...pts.map((q) => q[1])) - 14;
    } else if (at === "mid") {
      x = (first[0] + last[0]) / 2 - w / 2;
      y = (first[1] + last[1]) / 2 + 16; // below the line, clear of pattern names above
    } else {
      x = last[0] - w - 4;
      y = last[1] - 10;
    }
    ctx.globalAlpha = 0.14;
    ctx.fillStyle = color;
    ctx.fillRect(x - 3, y - 9, w + 6, 16);
    ctx.globalAlpha = 1;
    ctx.fillText(text, x, y + 3);
  }

  private drawPaths(ctx: Ctx): void {
    for (const p of this.data.paths) {
      if (p.pts.length < 2 && !p.dots) continue;
      ctx.beginPath();
      p.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.setLineDash(p.dashed ? [6, 4] : p.dotted ? [2, 3] : []);
      ctx.strokeStyle = p.color;
      ctx.lineWidth = p.width;
      ctx.lineJoin = "round";
      ctx.stroke();
      ctx.setLineDash([]);
      if (p.dots) {
        ctx.fillStyle = p.color;
        for (const [x, y] of p.pts) {
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      p.labels.forEach((text, i) => {
        const pt = p.pts[i];
        if (!text || !pt) return;
        const w = ctx.measureText(text).width;
        ctx.fillStyle = p.color;
        ctx.fillText(text, pt[0] - w / 2, pt[1] - 8);
      });
      if (p.label) this.drawLabel(ctx, p.label, p.pts, p.labelAt, p.color);
    }
  }
}

/** One primitive draws everything: bands under the candles, lines and labels above. */
export class DrawingsPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private prepared: Prepared = { bands: [], paths: [], candles: [] };

  constructor(private readonly drawings: ChartDrawings) {}

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>): void {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
    requestUpdate();
  }

  detached(): void {
    this.chart = this.series = this.requestUpdate = null;
  }

  private xy(p: TimePoint): XY | null {
    if (!this.chart || !this.series) return null;
    const x = this.chart.timeScale().timeToCoordinate(p.time as UTCTimestamp);
    const y = this.series.priceToCoordinate(p.value);
    return x === null || y === null ? null : [x, y];
  }

  updateAllViews(): void {
    const bands: Prepared["bands"] = [];
    for (const b of this.drawings.bands) {
      const up = b.upper.map((p) => this.xy(p));
      const lo = b.lower.map((p) => this.xy(p));
      if (up.some((p) => !p) || lo.some((p) => !p)) continue;
      const u = up as XY[];
      const l = lo as XY[];
      const last = u.at(-1);
      const lastLow = l.at(-1);
      if (!last || !lastLow) continue;
      bands.push({
        pts: [...u, ...[...l].reverse()],
        fill: b.fill,
        stroke: b.stroke,
        dashed: b.dashed,
        label: b.label,
        labelColor: b.labelColor,
        lx: last[0],
        ly: (last[1] + lastLow[1]) / 2,
      });
    }
    const paths: Prepared["paths"] = [];
    for (const p of this.drawings.paths) {
      const pts = p.points.map((q) => this.xy(q));
      if (pts.some((q) => !q)) continue;
      paths.push({
        pts: pts as XY[],
        color: p.color,
        width: p.width ?? 1.5,
        dashed: p.dashed,
        dotted: p.dotted,
        label: p.label,
        labelAt: p.labelAt ?? "end",
        dots: p.dots,
        labels: p.pointLabels ?? [],
      });
    }
    const candles: Prepared["candles"] = [];
    if (this.chart && this.series && this.drawings.candles?.length) {
      const spacing = this.chart.timeScale().options().barSpacing;
      const w = Math.max(3, Math.min(14, spacing * 0.62));
      for (const k of this.drawings.candles) {
        const x = this.chart.timeScale().timeToCoordinate(k.time as UTCTimestamp);
        const o = this.series.priceToCoordinate(k.open);
        const h = this.series.priceToCoordinate(k.high);
        const l = this.series.priceToCoordinate(k.low);
        const c = this.series.priceToCoordinate(k.close);
        if (x === null || o === null || h === null || l === null || c === null) continue;
        candles.push({ x, o, h, l, c, w, color: k.color, fill: k.fill, dashed: k.dashed });
      }
    }
    this.prepared = { bands, paths, candles };
  }

  paneViews(): readonly IPrimitivePaneView[] {
    const { font, textColor } = this.drawings;
    return [
      { zOrder: () => "bottom", renderer: () => new Renderer(this.prepared, font, textColor, "bands") },
      { zOrder: () => "top", renderer: () => new Renderer(this.prepared, font, textColor, "paths") },
    ];
  }

  autoscaleInfo(): AutoscaleInfo | null {
    const a = this.drawings.autoscale;
    return a ? { priceRange: { minValue: a.min, maxValue: a.max } } : null;
  }

  redraw(): void {
    this.requestUpdate?.();
  }
}
