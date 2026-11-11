import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ChartTokens } from "../components/charts/tokens";
import { DEFAULT_LAYERS, type ChartReading, type ForecastInfo } from "../lib/kairos";
import { kairosDrawings } from "../lib/kairosDrawings";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));

afterEach(() => vi.unstubAllGlobals());

const DAY = 86_400_000;
const T0 = 1_767_225_600_000;
const BARS = Array.from({ length: 60 }, (_, i) => ({ ts: T0 + i * DAY, open: 100 + i, high: 101.5 + i, low: 99.5 + i, close: 101 + i, volume: 1000, source: "fake" }));

export const READING: ChartReading = {
  instrument: { id: 1, symbol: "RELIANCE", name: "Reliance Industries", market: "IN" },
  timeframe: "1d",
  disclaimer: "Kairos is a research tool, not financial advice. Paper money only.",
  computed_ms: 12,
  report: {
    symbol: "RELIANCE",
    name: "Reliance Industries",
    market: "IN",
    timeframe: "1d",
    as_of: T0 + 59 * DAY,
    close: 160,
    change_pct: 0.6,
    atr: 2,
    score: 52,
    bias: "bullish",
    confidence: "high",
    components: { trend: 0.8 },
    trend: { score: 75, regime: "strong uptrend", structure: 1, adx: 40, sma200: null, atr_pct: 1.2, volatility: "normal" },
    momentum: { score: 0.5, rsi: 64, rsi_state: "strong", macd_above_signal: true, notes: [] },
    volume: { has_volume: true, rvol: 1.1, accumulation_days: 4, distribution_days: 1, cmf: 0.1, notes: [] },
    zones: [{ low: 150, high: 151, center: 150.5, role: "support", strength: 70, touches: 3, flipped: false, from_ts: T0 + 10 * DAY, label: "Support ₹150.50 (3 touches)" }],
    lines: [{ kind: "support", from: { ts: T0 + 5 * DAY, value: 104 }, to: { ts: T0 + 64 * DAY, value: 166 }, touches: 3, broken: false, broken_ts: null, value_now: 161, label: "Rising support line (3 touches)" }],
    channel: null,
    patterns: [
      {
        key: "bull_flag", name: "Bull flag", bias: "bullish", status: "confirmed", confidence: 0.77, provisional: false,
        points: [{ ts: T0 + 40 * DAY, value: 140, label: "Pole" }, { ts: T0 + 50 * DAY, value: 152, label: "Flag" }],
        upper: { from: { ts: T0 + 51 * DAY, value: 152 }, to: { ts: T0 + 59 * DAY, value: 150 } },
        lower: { from: { ts: T0 + 51 * DAY, value: 148 }, to: { ts: T0 + 59 * DAY, value: 146 } },
        trigger: 151, target: 163, stop: 146, start_ts: T0 + 40 * DAY, event_ts: T0 + 57 * DAY, resolved_ts: null,
        volume_confirmed: true, explanation: "Bull flag: a sharp rise (the pole) and a small drift lower. It broke up on strong volume at ₹151.00.",
        stats: { n: 412, hit_rate: 0.58, base_rate: 0.52 },
      },
    ],
    candles: [{ ts: T0 + 59 * DAY, key: "hammer", name: "Hammer", bias: "bullish", meaning: "A long lower wick after a fall.", high: 161, low: 158, stats: null }],
    divergences: [],
    fibonacci: null,
    idea: { direction: "long", action: "Buy", entry: 160, wait: "now", stop: 154, target: 172, reward_risk: 2, risk_pct: 3.75, quality: "good", text: "Buy near ₹160.00, stop ₹154.00, target ₹172.00 (reward 2.0× the risk). An educational idea, not advice." },
    invalidation: "A close below ₹154.00 would cancel this view.",
    headline: "Strong uptrend · bull flag confirmed",
    summary: ["RELIANCE is in a strong uptrend (trend score +75).", "Overall: bullish (score +52 of 100, high confidence)."],
    future: Array.from({ length: 15 }, (_, i) => T0 + (60 + i) * DAY),
  },
  forecast: {
    horizon: 10,
    origin: 160,
    path: [
      { ts: T0 + 59 * DAY, p10: 160, p25: 160, median: 160, p75: 160, p90: 160 },
      { ts: T0 + 60 * DAY, p10: 150, p25: 155, median: 161, p75: 166, p90: 171 },
    ],
    up_probability: 0.56,
    median_change_pct: 0.6,
    range80_pct: [-6, 7],
    weights: { analogues: 0.5, volatility: 0.4, trend: 0.1 },
    track: { tests: 49, direction_hits: 27, direction_rate: 0.55, skill_pct: 1, band80: 0.8, band50: 0.5 },
    text: "Over the next 10 trading days, RELIANCE will most likely be between ₹150.00 and ₹171.00.",
    verdict: "Tested 49 times on RELIANCE: the direction was right 27 times (55%), no better than a coin flip, so read this as a range, not a prediction.",
    edge: false,
    peers: 4,
  },
};

const TOKENS: ChartTokens = {
  fg: "#111111", fgMuted: "#222222", fgSubtle: "#333333", surface: "#ffffff", border: "#eeeeee", grid: "#eeeeee",
  accent: "#e8692c", accentSoft: "#fdf0e8", benchmark: "#888888", profit: "#1f7a4d", loss: "#b42318", warning: "#b45309", info: "#2563eb", fontSans: "Inter",
};

describe("Charts screen with Kairos", () => {
  it("opens a linked chart with Kairos on and shows its reading", async () => {
    mockBackend({
      "/api/candles*": { instrument: {}, timeframe: "1d", adjusted: true, bars: BARS, note: null },
      "/api/analysis/chart*": READING,
      "/api/news*": {
        enabled: true,
        refreshing: false,
        sources: ["Google News"],
        items: [{ id: 1, title: "Reliance shares surge after strong results", summary: "", link: "https://example.invalid/1", publisher: "Example Wire", published_at: Date.now() - 3_600_000, sentiment: 0.7, tone: "positive", symbols: ["RELIANCE"] }],
        mood: { score: 0.7, count: 1, tone: "positive" },
      },
    });
    renderAt(<App />, "/charts?symbol=RELIANCE&market=IN&kairos=1");
    expect(await screen.findByText("Kairos reads RELIANCE")).toBeInTheDocument();
    expect(screen.getAllByText("Bullish")[0]).toHaveClass("text-profit");
    expect(screen.getByText("Bull flag")).toBeInTheDocument();
    expect(screen.getByText(/worked 58% of 412 times/)).toBeInTheDocument();
    expect(screen.getByText(/no better than a coin flip/)).toBeInTheDocument();
    expect(screen.getByText(READING.disclaimer)).toBeInTheDocument();
    expect(await screen.findByText("Reliance shares surge after strong results")).toBeInTheDocument();
    expect(screen.getByText(/Mostly good news/)).toBeInTheDocument();
    // switching Kairos off removes the panel
    fireEvent.click(screen.getByRole("button", { name: /Kairos on/ }));
    expect(screen.queryByText("Kairos reads RELIANCE")).not.toBeInTheDocument();
  });

  it("explains in plain English when there aren't enough prices", async () => {
    mockBackend({
      "/api/candles*": { instrument: {}, timeframe: "1d", adjusted: true, bars: BARS, note: null },
      "/api/analysis/chart*": () =>
        new Response(JSON.stringify({ error: { code: "NOT_ENOUGH_PRICES", message: "Kairos needs more prices to read this chart.", action: "Open the Data screen.", detail: "" } }), { status: 409 }),
    });
    renderAt(<App />, "/charts?symbol=RELIANCE&kairos=1");
    expect(await screen.findByText("Kairos needs more prices to read this chart.")).toBeInTheDocument();
  });
});

describe("Kairos drawings", () => {
  it("turns a reading into zones, lines, patterns, markers and a forecast cone", () => {
    const d = kairosDrawings(READING, DEFAULT_LAYERS, TOKENS);
    expect(d.bands.map((b) => b.id)).toEqual(["zone-0", "fc80", "fc50"]);
    expect(d.bands[0]?.fill).toContain("rgba(31, 122, 77");
    expect(d.paths.map((p) => p.id)).toEqual(["line-0", "pat-0", "pat-0-b0", "pat-0-b1", "pat-0-target", "fc-median"]);
    expect(d.markers).toHaveLength(1);
    expect(d.future).toHaveLength(15);
    expect(d.autoscale).toEqual({ min: 150, max: 171 });
    expect(d.levels.map((l) => l.title)).toEqual(["S ×3"]);
  });

  it("honours the layer switches", () => {
    const d = kairosDrawings(READING, { ...DEFAULT_LAYERS, levels: false, forecast: false, idea: true }, TOKENS);
    expect(d.bands).toEqual([]);
    expect(d.levels.map((l) => l.title)).toEqual(["Entry", "Stop", "Target"]);
    expect(d.autoscale).toBeNull();
  });
});

describe("Kairos's predicted candles (KAIROS §17)", () => {
  const candles = [
    { ts: T0 + 60 * DAY, open: 160, high: 163, low: 158, close: 162, p10: 152, p90: 170, direction: 1 as const },
    { ts: T0 + 61 * DAY, open: 162, high: 164, low: 159, close: 161, p10: 150, p90: 172, direction: -1 as const },
  ];
  const previous = {
    kind: "live" as const,
    made_at: T0 + 50 * DAY,
    origin: 150,
    formed: 2,
    horizon: 10,
    complete: false,
    predicted: candles,
    candles: [
      { ts: T0 + 51 * DAY, actual: { open: 150, high: 153, low: 149, close: 152 }, predicted: { open: 150, high: 152, low: 149, close: 151 }, direction_right: true, inside80: true, p10: 145, p90: 156 },
      { ts: T0 + 52 * DAY, actual: { open: 152, high: 154, low: 148, close: 149 }, predicted: { open: 151, high: 153, low: 150, close: 152 }, direction_right: false, inside80: true, p10: 144, p90: 158 },
    ],
    direction_hits: 1,
    direction_scored: 2,
    inside80: 2,
    predicted_change_pct: 1.3,
    actual_change_pct: -0.7,
    end_error_pct: -2,
    text: "2 of 10 predicted candles have formed; the close stayed inside the 8-in-10 range on 2 of 2.",
  };
  const reading: ChartReading = { ...READING, forecast: { ...(READING.forecast as ForecastInfo), candles, previous } };

  it("draws the next candles tinted and dashed, and the last prediction as outlines", () => {
    const d = kairosDrawings(reading, DEFAULT_LAYERS, TOKENS);
    const ghosts = d.candles ?? [];
    expect(ghosts).toHaveLength(4);
    expect(ghosts.slice(0, 2).every((c) => c.fill && c.dashed)).toBe(true);
    expect(ghosts.slice(2).every((c) => !c.fill)).toBe(true);
    expect(d.bands.map((b) => b.id)).toContain("prev80");
    expect(d.markers.some((m) => m.text === "Prediction")).toBe(true);
    expect(d.autoscale?.max).toBeGreaterThanOrEqual(171);
    const off = kairosDrawings(reading, { ...DEFAULT_LAYERS, predicted: false, lastPrediction: false }, TOKENS);
    expect(off.candles).toEqual([]);
  });

  it("shows the prediction and how the last one did in the panel", async () => {
    mockBackend({
      "/api/candles*": { instrument: {}, timeframe: "1d", adjusted: true, bars: BARS, note: null },
      "/api/analysis/chart*": reading,
      "/api/news*": { enabled: false, refreshing: false, sources: [], items: [], mood: null },
    });
    renderAt(<App />, "/charts?symbol=RELIANCE&market=IN&kairos=1");
    expect(await screen.findByText("Predicted candles")).toBeInTheDocument();
    expect(screen.getByText(/1 rising, 1 falling, 0 flat/)).toBeInTheDocument();
    expect(screen.getByText(/Kairos's prediction from/)).toBeInTheDocument();
    expect(screen.getByText(previous.text)).toBeInTheDocument();
  });
});

describe("Charts timeframes and history", () => {
  it("offers 1-minute candles and asks for all the history there is", async () => {
    const spy = mockBackend({
      "/api/candles*": { instrument: {}, timeframe: "1m", adjusted: true, bars: BARS, note: null },
    });
    renderAt(<App />, "/charts?symbol=RELIANCE&market=IN&tf=1m");
    expect(await screen.findByRole("radio", { name: "1 minute" })).toBeInTheDocument();
    await screen.findByText(/RELIANCE · 1 minute/);
    const urls = spy.mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith("/api/candles"));
    expect(urls.some((u) => u.includes("timeframe=1m") && u.includes("full=true") && !u.includes("start="))).toBe(true);
  });
});
