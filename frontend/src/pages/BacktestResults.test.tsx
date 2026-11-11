import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const RUN = {
  id: 4, name: null, status: "done", progress: 100, starred: false, created_at: 0, finished_at: 1, strategy_id: 7, strategy_name: "My MA",
  version: 3, strategy_version_id: 9, mode: "single", market: "IN", timeframe: "1d", symbols: ["RELIANCE", "TCS"], start: 1_600_000_000_000,
  end: 1_700_000_000_000, capital: 1_000_000, headline: {}, error: null, parent_run_id: null, overrides: {}, params: {},
  metrics: {
    total_return: 0.42, cagr: 0.073, max_drawdown: 0.18, sharpe: 1.21, win_rate: 0.54, trades: 37, vs_benchmark: -0.19,
    final_equity: 1_420_000, charges_total: 12_345, charges_by_type: { stt: 9000, gst: 3345 }, monthly_returns: { "2021-01": 0.02 },
    per_symbol: [{ symbol: "RELIANCE", trades: 20, win_rate: 0.5, net_pnl: 300000, charges: 6000, open_at_end: 0 }],
    benchmark: { total_return: 0.61, cagr: 0.1, max_drawdown: 0.3 },
  },
  warnings: [{ level: "warn", code: "survivorship", title: "Uses today's Nifty 50 list (survivorship bias)", text: "Stocks that left the index aren't included." }],
  summary: "This strategy made 42% over 5 years (7.3% a year), less than simply holding the Nifty 50 (61%). Its worst drop was 18%.",
  error_detail: null, repro: null, job: null,
};

describe("Backtest results", () => {
  it("reads top to bottom: headline cards, summary, honesty panel", async () => {
    mockBackend({
      "/api/backtests/4": RUN,
      "/api/backtests/4/equity": { points: [{ ts: 1_600_000_000_000, equity: 1e6, cash: 1e6, exposure: 0, drawdown: 0 }], benchmark: [], capital: 1e6 },
      "/api/backtests/4/trades*": { trades: [], total: 0, next_cursor: null },
    });
    renderAt(<App />, "/backtests/4");
    expect(await screen.findByText(RUN.summary)).toBeInTheDocument();
    expect(screen.getByText("+42.0%")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
    expect(screen.getByText("vs Nifty 50")).toBeInTheDocument();
    expect(screen.getByText("Uses today's Nifty 50 list (survivorship bias)")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Trades" })).toBeInTheDocument();
  });

  it("explains a failed run in plain English", async () => {
    mockBackend({ "/api/backtests/5": { ...RUN, id: 5, status: "failed", metrics: null, error: "Your strategy code stopped: Line 2: ZeroDivisionError." } });
    renderAt(<App />, "/backtests/5");
    expect(await screen.findByText("Your strategy code stopped: Line 2: ZeroDivisionError.")).toBeInTheDocument();
  });
});
