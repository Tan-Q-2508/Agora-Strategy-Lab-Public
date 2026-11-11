import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const LEARNED = {
  market: "IN",
  timeframe: "1d",
  trained: { at: 1_760_000_000_000, candles: 125_000, samples: 12_000, base_rate: 0.53, horizon: 10 },
  best: [{ key: "pattern:bull_flag:up", label: "Bull flag breakout", family: "chart pattern", direction: 1, n: 412, hit_rate: 0.58, base_rate: 0.53, paper_n: 0, paper_wins: 0, edge: 0.048, weight: 1.96, text: "Bull flag breakout on Indian stocks: rose 10 days later 58% of 412 times (any day: 53%)." }],
  worst: [{ key: "candle:hammer", label: "Hammer", family: "candlestick", direction: 1, n: 300, hit_rate: 0.49, base_rate: 0.53, paper_n: 0, paper_wins: 0, edge: -0.035, weight: 0.3, text: "Hammer on Indian stocks: rose 10 days later 49% of 300 times (any day: 53%)." }],
  paper_trades: 0,
  signals: 40,
  exits: { plan: "stop 1.5 ATR, target 3.5× the risk, trailing stop 2 ATR, no partial sale", chosen: true, why: "chosen from its record: +0.21R a trade over 900 past trades, against +0.12R for the settings" },
};
const ACCOUNT = { id: 2, name: "Kairos desk (India)", market: "IN", starting_capital: 1_000_000, brokerage_profile_id: 1, slippage_bps: 5, created_at: 0 };
const DESK = {
  id: 8, kind: "kairos", name: "Kairos desk · India", strategy_id: 3, strategy_version_id: 4, version: 1, market: "IN", timeframe: "1d", product: "delivery",
  symbols: ["TCS", "INFY"], universe: "symbols", account: ACCOUNT, state: "running", mode: "replay", started_at: 1_750_000_000_000, stopped_at: null,
  last_bar_ts: 1_760_000_000_000, equity: 1_004_000, total_return: 0.4, day_pnl: 0, open_positions: 0, trades: 1, freshness: null, problem: null, now: 1_760_000_000_000, gaps: [],
};
const DETAIL = {
  ...DESK,
  positions: [],
  equity_curve: [],
  fills: [],
  rejected: [],
  closed_trades: [],
  events: [],
  instruments: [{ id: 5, symbol: "TCS" }],
  journal: [
    { id: 2, kind: "review", symbol: "TCS", instrument_id: 5, trade_id: 1, entry_ts: 1, score: null, text: "Closed TCS (long): +3.10% after 6 candles, because it reached its target.", won: true, return_pct: 3.1, at: 1_760_000_000_000 },
    { id: 1, kind: "thesis", symbol: "TCS", instrument_id: 5, trade_id: null, entry_ts: 1, score: 46, text: "Bought 12 TCS at ₹3,400.00. Why: Bull flag breakout (score +46, trend +40).", won: null, return_pct: null, at: 1_759_000_000_000 },
  ],
  learned: LEARNED,
  lessons: [{ id: 1, text: "Bull flag breakout worked 4 of 5 times in my recent paper trades on Indian stocks.", market: "IN", at: 0 }],
};

describe("Kairos desk", () => {
  it("starts a desk on the chosen stocks and shows what Kairos learned", async () => {
    const spy = mockBackend({
      "/api/kairos/desk": { desks: [] },
      "/api/kairos/stats*": LEARNED,
      "/api/kairos/lessons*": { lessons: [] },
      "POST /api/kairos/desk": { job_id: "kairos_desk-1" },
      "/api/jobs/kairos_desk-1": { job_id: "kairos_desk-1", kind: "kairos_desk", title: "Starting the Kairos desk", status: "done", pct: 100, eta_s: 0, message: "Done.", result: { session_id: 8 }, error: null },
      "/api/paper/sessions/8": { session: DETAIL },
      "/api/kairos/desk/8*": DETAIL,
      "/api/paper/sessions/8/vs-backtest*": { ready: false, message: "Soon." },
      "/api/paper/sessions/8/candles*": { bars: [], markers: [] },
    });
    renderAt(<App />, "/paper/desk");
    expect(await screen.findByRole("heading", { name: "Kairos desk", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText(/Bull flag breakout on Indian stocks/)).toBeInTheDocument();
    expect(screen.getByText(/Stop 1.5 ATR, target 3.5× the risk/)).toBeInTheDocument();
    expect(screen.getByText(/Chosen from its record/)).toBeInTheDocument();
    expect(screen.getByText("×2.0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove RELIANCE" }));
    fireEvent.click(screen.getByRole("button", { name: "Start the Kairos desk" }));
    await waitFor(() => {
      const post = spy.mock.calls.find(([url, init]) => String(url) === "/api/kairos/desk" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ market: "IN", symbols: ["TCS", "HDFCBANK", "INFY", "ICICIBANK"] });
    });
    // the desk opens with its diary
    expect(await screen.findByRole("heading", { name: "Kairos's diary" }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/Bought 12 TCS at ₹3,400.00/)).toBeInTheDocument();
    expect(screen.getByText("Review · worked")).toBeInTheDocument();
    expect(screen.getByText(/worked 4 of 5 times in my recent paper trades/)).toBeInTheDocument();
    expect(screen.getByText("Kairos trades this on its own")).toBeInTheDocument();
  });

  it("marks desks in the paper trading list and links to them", async () => {
    mockBackend({ "/api/paper/sessions": { sessions: [DESK], mode: "replay" } });
    renderAt(<App />, "/paper");
    const card = await screen.findByText("Kairos desk · India");
    expect(card.closest("a")).toHaveAttribute("href", "/paper/desk/8");
    expect(screen.getAllByText("Kairos desk").length).toBeGreaterThanOrEqual(1);
  });
});
