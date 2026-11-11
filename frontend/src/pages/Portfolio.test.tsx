import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { PortfolioDetail } from "../lib/portfolio";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const OPP = {
  id: 4, market: "IN" as const, strategy_id: 3, version_id: 8, name: "RSI dip buyer", symbols: ["HDFCBANK", "ICICIBANK"], overrides: {},
  source: "scanner" as const, status: "open" as const, score: 1.1, evidence: "On unseen years: 14 trades, won 64%, made ₹21,300 after costs (1.8× won to lost); 84% chance it isn't luck.",
  found_at: 1_760_000_000_000, checked_at: 1_760_000_000_000,
};

const DETAIL: PortfolioDetail = {
  id: 1, name: "India portfolio", market: "IN", budget: 100_000, risk: "balanced", status: "draft", manage: true,
  created_at: 1_760_000_000_000, updated_at: 1_760_000_000_000, sleeves_planned: 2, backtest_return: 0.21, paper_started_at: null,
  cash: 100_000,
  plan: {
    market: "IN", budget: 100_000, risk: "balanced", cash: 14_000, invested: 86_000, method: "inverse volatility",
    sleeves: [
      { key: "a", name: "RSI dip buyer", strategy_id: 3, version_id: 8, symbols: ["HDFCBANK", "ICICIBANK"], weight: 0.5, capital: 50_000, score: 1, sharpe: 1.3, luck: 0.84, volatility: 0.09, opportunity_id: 4,
        reasons: ["Held up on unseen years: Sharpe 1.30, 14 trades, won 64%, made ₹21,300 after costs.", "Luck check: 84% chance it isn't luck."] },
      { key: "b", name: "Trend rider", strategy_id: 5, version_id: 9, symbols: ["TCS"], weight: 0.36, capital: 36_000, score: 0.8, sharpe: 1.0, luck: 0.8, volatility: 0.12, opportunity_id: null,
        reasons: ["Held up on unseen years: Sharpe 1.00."] },
    ],
    left_out: [{ name: "Copycat", reason: "Left out: it moves with “RSI dip buyer” (correlation 0.91), which is already in and scored higher." }],
    estimate: { volatility: 0.08, sharpe: 1.2, diversification: 1.31 },
    overlaps: [], notes: ["Weighted by inverse volatility on study-year returns."], made_at: 1_760_000_000_000,
  },
  backtest: {
    start: 1_600_000_000_000, end: 1_760_000_000_000, budget: 100_000, final: 121_000,
    metrics: { total_return: 0.21, max_drawdown: -0.08, sharpe: 1.1 },
    curve: [[1_600_000_000_000, 100_000], [1_760_000_000_000, 121_000]], benchmark: [[1_600_000_000_000, 100_000], [1_760_000_000_000, 115_000]],
    sleeves: [{ name: "RSI dip buyer", capital: 50_000, final: 61_000, moved: 0, made: 11_000, trades: 30 }],
    rebalances: 12, moved: 4_000, honesty: "These sleeves were chosen because they held up in these years, so this backtest flatters the portfolio.",
  },
  sleeves: [], moves: [{ id: 1, ts: 1_760_000_000_000, kind: "plan", text: "Planned 2 sleeves for ₹1.00 lakh." }],
  opportunities: [OPP],
};

describe("Portfolio", () => {
  it("starts from a budget and plans a portfolio", async () => {
    const spy = mockBackend({
      "/api/portfolios": { portfolios: [] },
      "/api/opportunities": { opportunities: [] },
      "POST /api/portfolios": { portfolio: { ...DETAIL, plan: {}, backtest: {} }, job_id: "portfolio_plan-1" },
      "/api/portfolios/1": { portfolio: DETAIL },
      "/api/jobs/portfolio_plan-1": { job_id: "portfolio_plan-1", kind: "portfolio_plan", title: "Planning", status: "done", pct: 100, eta_s: 0, message: "Done.", result: {}, error: null },
    });
    renderAt(<App />, "/portfolio");
    expect(await screen.findByText("No portfolio yet")).toBeInTheDocument();
    const [newButton] = screen.getAllByRole("button", { name: "New portfolio" });
    if (!newButton) throw new Error("no New portfolio button");
    fireEvent.click(newButton);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Careful" }));
    expect(await within(dialog).findByText(/20% kept in cash/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Plan it" }));
    await waitFor(() =>
      expect(spy.mock.calls.some(([url, init]) => String(url).endsWith("/api/portfolios") && (init as RequestInit | undefined)?.method === "POST" && String((init as RequestInit).body).includes('"risk":"careful"'))).toBe(true),
    );
    expect(await screen.findByRole("heading", { name: "India portfolio", level: 1 })).toBeInTheDocument();
  });

  it("shows the plan with its reasons, the backtest's honesty note and the opportunities", async () => {
    const spy = mockBackend({
      "/api/portfolios/1": { portfolio: DETAIL },
      "POST /api/portfolios/1/paper/start": { portfolio: { ...DETAIL, status: "paper" } },
      "POST /api/opportunities/4/dismiss": { opportunity: { ...OPP, status: "dismissed" } },
    });
    renderAt(<App />, "/portfolio/1");
    const sleeve = await screen.findByRole("listitem", { name: "Sleeve RSI dip buyer" });
    expect(within(sleeve).getByText(/Luck check: 84% chance/)).toBeInTheDocument();
    expect(within(sleeve).getByText("₹50,000")).toBeInTheDocument();
    expect(screen.getByText(/Left out \(1\) and why/)).toBeInTheDocument();
    expect(screen.getByText(/flatters the portfolio/)).toBeInTheDocument();
    expect(screen.getByText(/the AI never sets a weight/)).toBeInTheDocument();
    const opp = screen.getByRole("listitem", { name: "RSI dip buyer on HDFCBANK, ICICIBANK" });
    expect(within(opp).getByText(/84% chance it isn't luck/)).toBeInTheDocument();
    fireEvent.click(within(opp).getByRole("button", { name: "Dismiss" }));
    fireEvent.click(screen.getByRole("button", { name: "Paper trade it" }));
    await waitFor(() => expect(spy.mock.calls.some(([url, init]) => String(url).endsWith("/api/portfolios/1/paper/start") && (init as RequestInit | undefined)?.method === "POST")).toBe(true));
    expect(spy.mock.calls.some(([url]) => String(url).endsWith("/api/opportunities/4/dismiss"))).toBe(true);
  });

  it("is in the sidebar", async () => {
    mockBackend({ "/api/portfolios": { portfolios: [] }, "/api/opportunities": { opportunities: [] } });
    renderAt(<App />, "/");
    expect(await screen.findByRole("link", { name: "Portfolio" })).toHaveAttribute("href", "/portfolio");
  });
});
