import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { FakeWebSocket, mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const ACCOUNT = { id: 2, name: "Paper account 1", market: "IN", starting_capital: 1_000_000, brokerage_profile_id: 1, slippage_bps: 5, created_at: 0 };
const SUMMARY = {
  id: 5, name: "Bands", strategy_id: 7, strategy_version_id: 9, version: 3, market: "IN", timeframe: "1d", product: "delivery",
  symbols: ["RELIANCE"], universe: "symbols", account: ACCOUNT, state: "running", mode: "replay", started_at: 1_750_000_000_000,
  stopped_at: null, last_bar_ts: 1_760_000_000_000, equity: 1_012_345, total_return: 1.2345, day_pnl: 2_500, open_positions: 1, trades: 4,
  freshness: { level: "green", text: "Up to date · last candle 15:30 IST", delay_s: 0 }, problem: null, now: 1_760_000_000_000, gaps: [],
};
const POSITION = {
  instrument_id: 1, symbol: "RELIANCE", side: "long", qty: 10, entry_price: 1400, entry_ts: 1_759_000_000_000, last_price: 1450,
  unrealized: 500, unrealized_pct: 3.57, stop: 1330, target: null, reason: "Buy rule",
};
const DETAIL = {
  ...SUMMARY,
  positions: [POSITION],
  equity_curve: [
    { ts: 1_758_000_000_000, equity: 1_000_000, cash: 1_000_000 },
    { ts: 1_760_000_000_000, equity: 1_012_345, cash: 998_000 },
  ],
  fills: [{ id: 1, ts: 1_759_000_000_000, symbol: "RELIANCE", instrument_id: 1, side: "buy", type: "market", qty: 10, price: 1400, charges: 12.5, reason: "Buy rule" }],
  rejected: [],
  closed_trades: [],
  events: [{ id: 1, ts: 1_750_000_000_000, level: "info", kind: "started", message_plain: "Paper trading started with 1 stock(s)." }],
  instruments: [{ id: 1, symbol: "RELIANCE" }],
};

describe("Paper trading", () => {
  it("lists sessions with their live numbers", async () => {
    mockBackend({ "/api/paper/sessions": { sessions: [SUMMARY], mode: "replay" } });
    renderAt(<App />, "/paper");
    expect(await screen.findByText("Bands")).toBeInTheDocument();
    expect(screen.getByText("Practice replay")).toBeInTheDocument();
    expect(screen.getByText("+1.23%")).toBeInTheDocument();
    expect(screen.getByText("Up to date · last candle 15:30 IST")).toBeInTheDocument();
  });

  it("groups sessions by who runs them and market, with stopped ones folded and clearable", async () => {
    const spy = mockBackend({
      "/api/paper/sessions": {
        sessions: [
          { ...SUMMARY, id: 11, name: "Kairos desk · 1 hour", kind: "kairos", timeframe: "1h" },
          { ...SUMMARY, id: 12, name: "Kairos desk · 1 day", kind: "kairos" },
          { ...SUMMARY, id: 13, name: "Metis · dip buyer", market: "US" },
          { ...SUMMARY, id: 14, name: "Old desk run", kind: "kairos", state: "stopped" },
        ],
        mode: "live",
      },
      "POST /api/paper/sessions/clear-stopped": { hidden: 1 },
    });
    renderAt(<App />, "/paper");
    const panel = await screen.findByRole("tabpanel");
    // daily desk first, then the hourly one
    expect(within(panel).getAllByText(/Kairos desk ·/).map((e) => e.textContent)).toEqual(["Kairos desk · 1 day", "Kairos desk · 1 hour"]);
    expect(screen.getByRole("tab", { name: /Metis USA/ })).toBeInTheDocument();
    expect(screen.queryByText("Old desk run")).not.toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("tab", { name: /Stopped/ }));
    expect(await screen.findByText("Old desk run")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear stopped" }));
    await waitFor(() => expect(spy.mock.calls.some(([url, init]) => String(url) === "/api/paper/sessions/clear-stopped" && init?.method === "POST")).toBe(true));
  });

  it("starts a session with a new paper account", async () => {
    const spy = mockBackend({
      "/api/strategies*": {
        strategies: [{ id: 7, name: "Bands", description: "", kind: "visual", market: "IN", created_at: 0, updated_at: 0, archived: false, template_key: null, version: 3, version_id: 9, timeframe: "1d", last_backtest: null }],
      },
      "POST /api/paper/sessions": { session_id: 5 },
      "/api/paper/sessions/5": { session: DETAIL },
      "/api/paper/sessions/5/vs-backtest*": { ready: false, message: "The comparison appears after 5 trading days (1 so far)." },
      "/api/paper/sessions/5/candles*": { bars: [], markers: [] },
    });
    renderAt(<App />, "/paper?start=7");
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByLabelText("Strategy")).toHaveValue("7"));
    fireEvent.change(within(dialog).getByLabelText("Starting money"), { target: { value: "500000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start paper trading" }));
    await waitFor(() => {
      const post = spy.mock.calls.find(([url, init]) => String(url) === "/api/paper/sessions" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ strategy_version_id: 9, account: { market: "IN", name: "", starting_capital: 500000 }, trade_check: "off" });
    });
    // the live screen is loaded on demand, which can take a moment under load
    expect(await screen.findByRole("heading", { name: "Bands" }, { timeout: 5000 })).toBeInTheDocument();
  });

  it("updates the live screen from pushed ticks and can pause", async () => {
    const spy = mockBackend({
      "/api/paper/sessions/5": { session: DETAIL },
      "/api/paper/sessions/5/vs-backtest*": { ready: false, message: "The comparison appears after 5 trading days (1 so far)." },
      "/api/paper/sessions/5/candles*": { bars: [], markers: [] },
      "POST /api/paper/sessions/5/pause": { session: { ...DETAIL, state: "paused_user" } },
    });
    renderAt(<App />, "/paper/5");
    expect(await screen.findByRole("heading", { name: "Bands" }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("RELIANCE");
    expect(screen.getByRole("list", { name: "Recent fills" })).toHaveTextContent("Bought 10 RELIANCE at ₹1,400.00");
    expect(screen.getByText("The comparison appears after 5 trading days (1 so far).")).toBeInTheDocument();
    await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
    act(() => {
      FakeWebSocket.push("paper.tick", {
        session_id: 5, state: "running", equity: 1_020_000, cash: 998_000, day_pnl: -1500,
        positions: [{ ...POSITION, last_price: 1460, unrealized: 600 }],
        freshness: { level: "amber", text: "Waiting for the 15:30 IST candle", delay_s: 200 }, problem: null, now: 1_760_000_100_000,
      });
    });
    expect(await screen.findByText("Waiting for the 15:30 IST candle")).toBeInTheDocument();
    expect(screen.getByText("Today").closest("section, div")?.parentElement).toHaveTextContent("−₹1,500");
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(spy.mock.calls.some(([url, init]) => String(url) === "/api/paper/sessions/5/pause" && init?.method === "POST")).toBe(true));
  });
});
