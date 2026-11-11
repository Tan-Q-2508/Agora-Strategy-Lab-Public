/**
 * "Money over time" by hours, days or months (the user, 2026-11-06, D-207: "if the stock market
 * is closed how will I know the trend of history"). Each view keeps the money at the end of each
 * hour, trading day or month, in the market's own time zone.
 */
export type EquityView = "hours" | "days" | "months";

export interface EquityPoint {
  ts: number;
  equity: number;
}

/** The hours view shows the last few trading days; days and months show everything. */
export const HOURS_DAYS = 5;

const fmt = new Map<string, Intl.DateTimeFormat>();

function parts(ms: number, timeZone: string): { y: string; m: string; d: string; h: string } {
  let f = fmt.get(timeZone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23" });
    fmt.set(timeZone, f);
  }
  const out: Record<string, string> = {};
  for (const p of f.formatToParts(ms)) out[p.type] = p.value;
  return { y: out.year ?? "", m: out.month ?? "", d: out.day ?? "", h: out.hour ?? "" };
}

function key(ms: number, view: EquityView, timeZone: string): string {
  const p = parts(ms, timeZone);
  if (view === "months") return `${p.y}-${p.m}`;
  if (view === "days") return `${p.y}-${p.m}-${p.d}`;
  return `${p.y}-${p.m}-${p.d} ${p.h}`;
}

/** The last point in each hour, day or month (points must be in time order). */
export function bucketEquity<P extends EquityPoint>(points: P[], view: EquityView, timeZone: string): P[] {
  const out: P[] = [];
  let last = "";
  for (const p of points) {
    const k = key(p.ts, view, timeZone);
    if (k === last) out[out.length - 1] = p;
    else out.push(p);
    last = k;
  }
  if (view !== "hours") return out;
  const days: string[] = [];
  for (let i = out.length - 1; i >= 0; i--) {
    const d = key(out[i]!.ts, "days", timeZone);
    if (days[days.length - 1] !== d) days.push(d);
    if (days.length > HOURS_DAYS) return out.slice(i + 1);
  }
  return out;
}

/** How many distinct trading days the points cover. */
export function daysCovered(points: EquityPoint[], timeZone: string): number {
  return new Set(points.map((p) => key(p.ts, "days", timeZone))).size;
}

/** Days once there's a week of history, hours before that. */
export function defaultView(points: EquityPoint[], timeZone: string): EquityView {
  return daysCovered(points, timeZone) >= HOURS_DAYS ? "days" : "hours";
}

/** A y-axis range that shows small moves instead of a flat line in a huge band. */
export function yRange(values: number[], capital: number): { min: number; max: number } {
  const lo = Math.min(...values, capital);
  const hi = Math.max(...values, capital);
  const pad = Math.max((hi - lo) * 0.12, Math.abs(capital) * 0.002, 1);
  return { min: lo - pad, max: hi + pad };
}
