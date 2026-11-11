/**
 * Deterministic example data for previews (Charts screen, theme preview) until real
 * prices arrive in Phase 2. Always labelled "Example" in the UI.
 */
import type { Candle, Overlay, TradeMarker } from "../components/charts/PriceChart";

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function gauss(r: () => number): number {
  const u = Math.max(r(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

export function exampleCandles(count = 130, seed = 7): Candle[] {
  const r = rng(seed);
  const out: Candle[] = [];
  let price = 1240;
  let t = Date.UTC(2025, 5, 2, 3, 45) / 1000; // 09:15 IST
  for (let i = 0; i < count; i++) {
    const open = price * (1 + gauss(r) * 0.004);
    const close = open * (1 + gauss(r) * 0.014 + 0.0006);
    const high = Math.max(open, close) * (1 + Math.abs(gauss(r)) * 0.006);
    const low = Math.min(open, close) * (1 - Math.abs(gauss(r)) * 0.006);
    out.push({ time: t, open: round(open), high: round(high), low: round(low), close: round(close), volume: Math.round(4e6 * (0.6 + r())) });
    price = close;
    t += 86400 * ((i + 1) % 5 === 0 ? 3 : 1); // skip weekends
  }
  return out;
}

function round(n: number): number {
  return Math.round(n * 20) / 20; // ₹0.05 tick
}

export function sma(candles: Candle[], n: number): Overlay["points"] {
  const pts: Overlay["points"] = [];
  let sum = 0;
  candles.forEach((c, i) => {
    sum += c.close;
    const prev = candles[i - n];
    if (prev) sum -= prev.close;
    if (i >= n - 1) pts.push({ time: c.time, value: Math.round((sum / n) * 100) / 100 });
  });
  return pts;
}

export function exampleMarkers(candles: Candle[]): TradeMarker[] {
  const pick = [18, 47, 76, 104];
  return pick.flatMap((i, k) => {
    const c = candles[i];
    return c ? [{ time: c.time, kind: k % 2 === 0 ? ("buy" as const) : ("sell" as const) }] : [];
  });
}

export function exampleEquity(points = 72, seed = 3): { months: string[]; strategy: number[]; benchmark: number[] } {
  const r = rng(seed);
  const months: string[] = [];
  const strategy: number[] = [];
  const benchmark: number[] = [];
  let s = 1_000_000;
  let b = 1_000_000;
  for (let i = 0; i < points; i++) {
    const d = new Date(Date.UTC(2020, i, 1));
    months.push(d.toLocaleString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" }));
    s *= 1 + 0.005 + gauss(r) * 0.03;
    b *= 1 + 0.0066 + gauss(r) * 0.045;
    strategy.push(Math.round(s));
    benchmark.push(Math.round(b));
  }
  return { months, strategy, benchmark };
}
