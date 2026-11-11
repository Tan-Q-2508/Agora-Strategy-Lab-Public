import type { Band, ChartDrawings, ChartMarker, GhostCandle, Level, Path } from "../components/charts/drawings";
import { alpha, type ChartTokens } from "../components/charts/tokens";
import type { Bias, ChartReading, KairosLayer } from "./kairos";

const s = (ms: number) => Math.round(ms / 1000);

function biasColor(b: Bias, t: ChartTokens): string {
  return b === "bullish" ? t.profit : b === "bearish" ? t.loss : t.info;
}

function short(v: number): string {
  return v >= 1000 ? v.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : v.toFixed(2);
}

const STATUS_MARK: Record<string, string> = { forming: "forming", confirmed: "confirmed", target: "target reached", failed: "failed" };

/** Kairos's chart reading as shapes for the price chart, honouring the layer switches. */
export function kairosDrawings(r: ChartReading, layers: Record<KairosLayer, boolean>, t: ChartTokens): ChartDrawings {
  const rep = r.report;
  const future = rep.future.map(s);
  const end = future.at(-1) ?? s(rep.as_of);
  const now = s(rep.as_of);
  const bands: Band[] = [];
  const paths: Path[] = [];
  const levels: Level[] = [];
  const markers: ChartMarker[] = [];
  const candles: GhostCandle[] = [];
  let autoscale: { min: number; max: number } | null = null;

  if (layers.levels) {
    for (const [i, z] of rep.zones.entries()) {
      const base = z.role === "support" ? t.profit : z.role === "resistance" ? t.loss : t.accent;
      const a = 0.06 + 0.1 * (z.strength / 100);
      const word = z.role === "support" ? "Support" : z.role === "resistance" ? "Resistance" : "Testing";
      bands.push({
        id: `zone-${i}`,
        upper: [{ time: s(z.from_ts), value: z.high }, { time: end, value: z.high }],
        lower: [{ time: s(z.from_ts), value: z.low }, { time: end, value: z.low }],
        fill: alpha(base, a),
        stroke: alpha(base, 0.45),
        dashed: true,
      });
      levels.push({ id: `zone-${i}-axis`, price: z.center, color: base, title: `${word[0]} ×${z.touches}`, axisOnly: true });
    }
  }

  if (layers.lines) {
    // The three strongest lines are enough to read a chart; the panel lists the rest.
    for (const [i, ln] of rep.lines.slice(0, 3).entries()) {
      const color = ln.kind === "support" ? t.profit : t.loss;
      paths.push({
        id: `line-${i}`,
        points: [{ time: s(ln.from.ts), value: ln.from.value }, { time: s(ln.to.ts), value: ln.to.value }],
        color: alpha(color, ln.broken ? 0.55 : 0.9),
        width: 1.5,
        dashed: ln.broken,
        label: ln.broken ? `${ln.kind} line broken` : undefined,
      });
    }
  }

  if (layers.patterns) {
    // Draw the two most important live patterns; failed ones are only described in the panel.
    const drawn = rep.patterns.filter((p) => p.status !== "failed").slice(0, 2);
    for (const [i, p] of drawn.entries()) {
      const color = biasColor(p.bias, t);
      const faded = p.status === "failed";
      paths.push({
        id: `pat-${i}`,
        points: p.points.map((q) => ({ time: s(q.ts), value: q.value })),
        color: alpha(color, faded ? 0.5 : 0.95),
        width: 2,
        dots: true,
        pointLabels: p.points.map((q) => q.label || undefined),
        label: `${p.name} · ${STATUS_MARK[p.status] ?? p.status}`,
        labelAt: "start",
      });
      for (const [k, bound] of [p.upper, p.lower].entries()) {
        if (!bound) continue;
        paths.push({
          id: `pat-${i}-b${k}`,
          points: [{ time: s(bound.from.ts), value: bound.from.value }, { time: s(bound.to.ts), value: bound.to.value }],
          color: alpha(color, 0.7),
          width: 1.25,
          dashed: true,
        });
      }
      if (i === 0 && (p.status === "forming" || p.status === "confirmed") && p.target) {
        paths.push({
          id: `pat-${i}-target`,
          points: [{ time: now, value: p.target }, { time: end, value: p.target }],
          color: alpha(color, 0.85),
          width: 1.25,
          dotted: true,
          label: `Target ${short(p.target)}`,
        });
      }
    }
    for (const [i, d] of rep.divergences.entries()) {
      const color = d.bullish ? t.profit : t.loss;
      paths.push({
        id: `div-${i}`,
        points: [{ time: s(d.from.ts), value: d.from.value }, { time: s(d.to.ts), value: d.to.value }],
        color,
        width: 1.5,
        dotted: true,
        label: d.label,
        labelAt: "mid",
      });
    }
  }

  if (layers.candles) {
    const recent = rep.candles.filter((c) => c.bias !== "neutral").slice(-5);
    for (const c of recent) {
      markers.push({
        time: s(c.ts),
        position: c.bias === "bullish" ? "belowBar" : "aboveBar",
        color: biasColor(c.bias, t),
        shape: "circle",
        text: c.name,
      });
    }
  }

  const fc = r.forecast;
  if (layers.forecast && fc && fc.path.length > 1) {
    const pts = fc.path.map((p) => ({ ...p, time: s(p.ts) }));
    bands.push({
      id: "fc80",
      upper: pts.map((p) => ({ time: p.time, value: p.p90 })),
      lower: pts.map((p) => ({ time: p.time, value: p.p10 })),
      fill: alpha(t.accent, 0.1),
      stroke: alpha(t.accent, 0.35),
      dashed: true,
    });
    bands.push({
      id: "fc50",
      upper: pts.map((p) => ({ time: p.time, value: p.p75 })),
      lower: pts.map((p) => ({ time: p.time, value: p.p25 })),
      fill: alpha(t.accent, 0.16),
    });
    const lastPt = pts.at(-1);
    // With the predicted candles drawn, the middle line steps back so it doesn't cover them.
    const ghosts = layers.predicted && Boolean(fc.candles?.length);
    paths.push({
      id: "fc-median",
      points: pts.map((p) => ({ time: p.time, value: p.median })),
      color: ghosts ? alpha(t.accent, 0.45) : t.accent,
      width: ghosts ? 1.25 : 2,
      dashed: true,
      label: lastPt && !ghosts ? `Likely ${short(lastPt.median)}` : undefined,
    });
    autoscale = {
      min: Math.min(...pts.map((p) => p.p10)),
      max: Math.max(...pts.map((p) => p.p90)),
    };
  }

  if (layers.predicted && fc?.candles?.length) {
    // Kairos's most likely next candles: tinted, dashed, so they never pass for real ones.
    for (const k of fc.candles) {
      const color = k.direction > 0 ? t.profit : k.direction < 0 ? t.loss : t.fgMuted;
      candles.push({ time: s(k.ts), open: k.open, high: k.high, low: k.low, close: k.close, color: alpha(color, 0.85), fill: alpha(color, 0.22), dashed: true });
    }
    const lo = Math.min(...fc.candles.map((k) => k.low));
    const hi = Math.max(...fc.candles.map((k) => k.high));
    autoscale = autoscale ? { min: Math.min(autoscale.min, lo), max: Math.max(autoscale.max, hi) } : { min: lo, max: hi };
  }

  const prev = fc?.previous;
  if (layers.lastPrediction && prev && prev.candles.length) {
    // The last prediction outlined over the candles that actually formed.
    for (const row of prev.candles) {
      if (!row.predicted) continue;
      candles.push({ time: s(row.ts), ...row.predicted, color: alpha(t.info, 0.9), dashed: true });
    }
    const first = prev.candles[0];
    const last = prev.candles.at(-1);
    if (first && last && first.p10 !== undefined && last.p90 !== undefined) {
      const pts = prev.candles.filter((r) => r.p10 !== undefined && r.p90 !== undefined);
      bands.push({
        id: "prev80",
        upper: [{ time: s(prev.made_at), value: prev.origin }, ...pts.map((r) => ({ time: s(r.ts), value: r.p90 as number }))],
        lower: [{ time: s(prev.made_at), value: prev.origin }, ...pts.map((r) => ({ time: s(r.ts), value: r.p10 as number }))],
        fill: alpha(t.info, 0.06),
        stroke: alpha(t.info, 0.3),
        dashed: true,
      });
    }
    markers.push({
      time: s(prev.made_at),
      position: "aboveBar",
      color: t.info,
      shape: "square",
      text: "Prediction",
    });
  }

  if (layers.fibonacci && rep.fibonacci) {
    for (const lv of rep.fibonacci.levels) {
      levels.push({ id: `fib-${lv.label}`, price: lv.price, color: alpha(t.info, 0.7), title: `Fib ${lv.label}`, dashed: true });
    }
  }

  if (layers.idea && rep.idea && rep.idea.quality !== "poor") {
    const idea = rep.idea;
    levels.push({ id: "entry", price: idea.entry, color: t.accent, title: "Entry", dashed: true });
    levels.push({ id: "stop", price: idea.stop, color: t.loss, title: "Stop", dashed: true });
    levels.push({ id: "target", price: idea.target, color: t.profit, title: "Target", dashed: true });
  }

  // Close enough that the predicted candles read as candles, far enough to show the patterns.
  const focus = layers.predicted && fc?.candles?.length ? (rep.timeframe === "1d" ? 70 : 110) : rep.timeframe === "1d" ? 100 : 150;
  return { bands, candles, paths, levels, markers, future, autoscale, focus, font: t.fontSans, textColor: t.fgMuted };
}
