import { describe, expect, it } from "vitest";
import { bucketEquity, defaultView, yRange } from "./equityView";

const IST = "Asia/Kolkata";
const H = 3_600_000;
// 3 Nov 2026 09:15 IST = 03:45 UTC
const D0 = Date.UTC(2026, 10, 3, 3, 45);

describe("Money over time views (D-207)", () => {
  const pts = [0, 0.25, 1, 1.5, 24, 25, 24 * 30].map((h, i) => ({ ts: D0 + h * H, equity: 1_000_000 + i }));

  it("keeps the last point of each hour, day and month in the market's time zone", () => {
    expect(bucketEquity(pts, "hours", IST).map((p) => p.equity)).toEqual([1_000_001, 1_000_003, 1_000_004, 1_000_005, 1_000_006]);
    expect(bucketEquity(pts, "days", IST).map((p) => p.equity)).toEqual([1_000_003, 1_000_005, 1_000_006]);
    expect(bucketEquity(pts, "months", IST).map((p) => p.equity)).toEqual([1_000_005, 1_000_006]);
  });

  it("shows hours for a young desk and days once it has a week of history", () => {
    expect(defaultView(pts.slice(0, 4), IST)).toBe("hours");
    const week = Array.from({ length: 6 }, (_, d) => ({ ts: D0 + d * 24 * H, equity: 1 }));
    expect(defaultView(week, IST)).toBe("days");
    // the hours view keeps only the last five trading days
    expect(bucketEquity(week, "hours", IST)).toHaveLength(5);
  });

  it("keeps a flat line readable instead of a huge empty band", () => {
    const r = yRange([1_000_000, 1_000_000], 1_000_000);
    expect(r.max - r.min).toBeLessThan(10_000);
    expect(r.min).toBeLessThan(1_000_000);
    expect(r.max).toBeGreaterThan(1_000_000);
  });
});
