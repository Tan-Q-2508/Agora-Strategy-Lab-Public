import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const TEMPLATES = {
  templates: [
    { key: "ma_crossover", name: "Moving-average crossover", summary: "Buy on the cross up.", description: "Follows trends.", idea: "Trends persist.", timeframe: "1d" },
  ],
};
const STRATEGY = {
  id: 7, name: "My MA", description: "Trend follower", kind: "visual", market: "IN", created_at: 0, updated_at: 0, archived: false,
  template_key: "ma_crossover", version: 3, version_id: 9, timeframe: "1d",
  last_backtest: { run_id: 4, total_return: 0.42, max_drawdown: 0.18, trades: 31, created_at: Date.now() - 3600_000, points: [100, 104, 103, 110, 142] },
};

describe("Strategies library", () => {
  it("shows saved strategies with their last backtest and the templates", async () => {
    mockBackend({ "/api/strategies*": { strategies: [STRATEGY] }, "/api/templates": TEMPLATES });
    renderAt(<App />, "/strategies");
    expect(await screen.findByText("My MA")).toBeInTheDocument();
    expect(screen.getByText("+42.0%")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Equity curve of the last backtest/ })).toBeInTheDocument();
    expect(screen.getByText("Moving-average crossover")).toBeInTheDocument();
  });

  it("creates a strategy from a template in the chosen market", async () => {
    const spy = mockBackend({ "/api/strategies*": { strategies: [] }, "/api/templates": TEMPLATES, "POST /api/strategies": { strategy: { id: 12 } } });
    renderAt(<App />, "/strategies");
    fireEvent.click(await screen.findByRole("button", { name: "Use this" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("radio", { name: "US" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create strategy" }));
    await vi.waitFor(() => {
      const post = spy.mock.calls.find(([url, init]) => String(url) === "/api/strategies" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ name: "Moving-average crossover", market: "US", template_key: "ma_crossover" });
    });
  });
});
