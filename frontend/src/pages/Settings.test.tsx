import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt, SETTINGS } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const DIAG = {
  versions: { agora: "0.1.0", python: "3.12.8", system: "Windows 11", yfinance: "1.7.0", fastapi: "0.115", ollama: null },
  paths: { data: "C:\\Agora\\data", logs: "C:\\Agora\\data\\logs", database_mb: 12.3 },
  data_mode: "real",
  events: [{ ts: 1_760_000_000_000, level: "info", area: "app", message_plain: "Agora 0.1.0 started." }],
  troubleshooting: [{ symptom: "The browser says it can't connect", fix: "Agora isn't running. Double-click Start Agora again." }],
  live_tests: [],
};

describe("Settings", () => {
  it("Diagnostics runs the live checks and lists each result in plain English", async () => {
    mockBackend({
      "/api/diagnostics": DIAG,
      "POST /api/diagnostics/live-test": { job_id: "live-test" },
      "/api/jobs/live-test": {
        id: "live-test", kind: "live_test", title: "Live data checks", status: "done", pct: 100, message: "", eta_s: null, error: null, created_at: 0,
        result: {
          summary: "1 check(s) failed: NSE end-of-day files (India backup).",
          results: [
            { name: "a", label: "Yahoo Finance: daily prices (India and US)", outcome: "passed", detail: "" },
            { name: "b", label: "NSE end-of-day files (India backup)", outcome: "failed", detail: "NSE sent no file" },
          ],
        },
      },
    });
    renderAt(<App />, "/settings?tab=diagnostics");
    expect(await screen.findByText("Agora 0.1.0 started.", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("The browser says it can't connect")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run the checks" }));
    expect(await screen.findByText("1 check(s) failed: NSE end-of-day files (India backup).")).toBeInTheDocument();
    expect(screen.getByText("Not working")).toBeInTheDocument();
    expect(screen.getByText("Working")).toBeInTheDocument();
  });

  it("Costs shows the brokerage profiles in plain words", async () => {
    mockBackend({
      "/api/costs/profiles": {
        brokerage: [{ id: 1, market: "IN", name: "Discount broker (₹20 cap)", rules: { intraday: { percent: 0.03, cap: 20 }, delivery: { flat: 0 } }, is_default: true }],
        slippage: [{ id: 1, market: "IN", name: "Nifty 50 stocks (5 bps)", bps: 5, is_default: true }],
      },
    });
    renderAt(<App />, "/settings?tab=costs");
    expect(await screen.findByText("Intraday: 0.03% of the order, at most ₹20")).toBeInTheDocument();
    expect(screen.getByText("Delivery: Free")).toBeInTheDocument();
  });

  it("Kairos tab saves switches and desk limits, and can study a market again", async () => {
    const values = { ...SETTINGS.values, "kairos.enabled": true, "kairos.think": true, "kairos.follow": true, "news.enabled": true, "kairos.risk_pct": 1, "kairos.max_positions": 5, "kairos.daily_loss_pct": 3, "kairos.entry_score": 40 };
    const meta = { ...SETTINGS.meta, "kairos.risk_pct": { default: 1, description: "How much of the Kairos desk's paper money one trade may lose if its stop is hit (%)." } };
    const spy = mockBackend({
      "/api/settings": { values, meta },
      "/api/kairos/stats*": { market: "IN", timeframe: "1d", trained: { at: 1_760_000_000_000, candles: 125_000, samples: 1, base_rate: 0.53, horizon: 10 }, best: [], worst: [], paper_trades: 0, signals: 0 },
      "POST /api/kairos/train": { job_id: "kairos_train-1" },
      "/api/jobs/kairos_train-1": { job_id: "kairos_train-1", kind: "kairos_train", title: "Kairos is studying Indian 1d history", status: "running", pct: 40, eta_s: null, message: "Studying TCS…", result: null, error: null },
    });
    renderAt(<App />, "/settings?tab=kairos");
    expect(await screen.findByText("How much of the Kairos desk's paper money one trade may lose if its stop is hit (%).")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Risk per trade"), { target: { value: "2" } });
    await waitFor(() => {
      const put = spy.mock.calls.find(([url, init]) => String(url) === "/api/settings" && init?.method === "PUT");
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({ "kairos.risk_pct": 2 });
    });
    expect(screen.getAllByText(/Studied 125,000 candles/).length).toBe(2);
    fireEvent.click(screen.getAllByRole("button", { name: "Study again" })[0]!);
    expect(await screen.findByText("Studying TCS…")).toBeInTheDocument();
  });
});
