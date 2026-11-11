import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const row = (symbol: string, name: string, group: string, change: number) => ({
  symbol, name, group, market: "IN", value: 24000, as_of: 1_760_000_000_000,
  change_pct: change, change_1m_pct: 2.1, change_1y_pct: -5.4, ytd_pct: 3.3, spark: [23000, 23500, 24000],
});

const BODY = {
  market: "IN",
  groups: [
    { key: "broad", indices: [row("NIFTY50", "Nifty 50", "broad", -0.4)] },
    { key: "sector", indices: [row("NIFTYIT", "Nifty IT", "sector", -1.9), row("NIFTYBANK", "Nifty Bank", "sector", 1.2)] },
    { key: "gauge", indices: [row("INDIAVIX", "India VIX (expected volatility)", "gauge", 6.0)] },
  ],
};

describe("Indices", () => {
  it("shows the market, its sectors sorted by today's move, and the gauges", async () => {
    mockBackend({ "/api/indices*": BODY });
    renderAt(<App />, "/indices");
    expect(await screen.findByRole("heading", { name: "Indices" })).toBeInTheDocument();
    expect(screen.getByText("Nifty 50")).toBeInTheDocument();
    const sectors = screen.getByText("Sectors").closest("section, div")!.parentElement!;
    const names = within(sectors).getAllByText(/^Nifty (Bank|IT)$/).map((e) => e.textContent);
    expect(names).toEqual(["Nifty Bank", "Nifty IT"]); // +1.2% first, −1.9% after
    expect(screen.getByText("India VIX (expected volatility)")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /Indices/ })).toHaveAttribute("href", "/indices");
  });
});
