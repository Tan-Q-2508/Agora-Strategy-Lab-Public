import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { mockBackend } from "../../test-utils";
import { ResultCard } from "./cards";
import { TradeCheckNote, TradeReview } from "./TradeReview";

vi.mock("lightweight-charts", () => import("../../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../../test-mocks/echarts-core"));

const REVIEW = {
  trades: 120,
  headline: "Costs ate 63% of the profit before costs (₹19,415 of ₹30,850).",
  lines: ["Costs ate 63% of the profit before costs (₹19,415 of ₹30,850). Fewer trades that aim for bigger moves would keep more of it.", "13 of 27 trades taken when the market was trending (Choppiness (14) below 46.7) lost (won 52%, against 65% overall)."],
  advice: ["Kairos found 1 filter that held up on unseen trades. Click Improve with Kairos to test it as a new version."],
  money: { gross: 30850, charges: 19415, net: 11435, cost_share: 0.63, avg_gross: 257, avg_charges: 162, trades_per_month: 1.4, level: "warn" },
  wins: { win_rate: 0.65, payoff: 0.6, breakeven_win_rate: 0.64, expectancy: 95, best3_share: 0.8, net_without_best3: -9046, longest_losing_streak: 4 },
  exits: { by_reason: [{ reason: "stop", label: "Stop-loss", count: 30, win_rate: 0, avg_net: -6000 }], lines: [] },
  failure_reasons: [],
  filters: {
    note: "Tested on the last 48 trades, which the filters never saw while being chosen.",
    rules: [{ key: "chop", text: "Skip signals that come when the market is trending (Choppiness (14) below 43.9).", held_up: true, test: { before: { trades: 33, win_rate: 0.667, net: 2833 }, after: { trades: 31, win_rate: 0.71, net: 15236 } } }],
  },
  losers: [{ symbol: "INFY", side: "long", entry_ts: 1_552_621_500_000, net: -6533, return_pct: -6.28, exit_reason: "Stop-loss", why: ["price was against its 50-candle trend (-6.6%): trades like that won 58%"] }],
};

describe("Kairos's trade review", () => {
  it("shows costs, win rate, filters that held up and the worst losers", async () => {
    mockBackend({ "/api/kairos/review/backtest/7": { review: REVIEW } });
    render(
      <MemoryRouter>
        <TradeReview kind="backtest" refId={7} market="IN" strategyId={3} canImprove />
      </MemoryRouter>,
    );
    expect(await screen.findByText("63% of profit")).toBeInTheDocument();
    expect(screen.getByText("needs 64% to break even")).toBeInTheDocument();
    expect(screen.getByText("Held up")).toBeInTheDocument();
    expect(screen.getByText(/against its 50-candle trend/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Improve with Kairos/ })).toBeInTheDocument();
  });

  it("offers a review when there is none yet", async () => {
    mockBackend({ "/api/kairos/review/paper/4": { review: null } });
    render(
      <MemoryRouter>
        <TradeReview kind="paper" refId={4} market="US" />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Review with Kairos/ }));
  });

  it("says when the trade check is still proving itself", () => {
    render(<TradeCheckNote tc={{ mode: "strict", checked: 206, skipped: 0, skipped_followed: 0, skipped_would_have_won: 0, skipped_would_have_lost: 0, proven: false, judged: 12, top_reasons: [] }} />);
    expect(screen.getByText(/skipped 0 of 206 signals/)).toBeInTheDocument();
    expect(screen.getByText(/hasn't yet proven/)).toBeInTheDocument();
  });

  it("draws an options strategy card with its payoff", () => {
    const grid = Array.from({ length: 61 }, (_, i) => 60 + i * 1.33);
    render(
      <MemoryRouter>
        <ResultCard
          card={{
            type: "options",
            title: "Iron condor · TCS",
            market: "IN",
            spot: 100,
            days: 30,
            vol: 0.2,
            legs: [{ label: "Sell 95 put", premium: 1.1 }],
            net: -2,
            max_profit: 2,
            max_loss: 8,
            breakevens: [88, 112],
            pop: 0.71,
            grid,
            at_expiry: grid.map((x) => (Math.abs(x - 100) < 10 ? 2 : -8)),
            today: grid.map(() => 0),
            lot: 1,
          }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("71% chance of profit")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Profit or loss at expiry/ })).toBeInTheDocument();
    expect(screen.getByText("Collects")).toBeInTheDocument();
  });
});
