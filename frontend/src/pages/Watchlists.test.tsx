import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const LIST = (id: number, name: string, category: string, kind = "ready", count = 10) => ({
  id, name, market: "IN", kind, category, key: null, description: `${name} stocks`, reason: kind === "metis" ? "Metals are booming." : "",
  count, editable: kind === "custom", live: category === "factor", created_at: 1_760_000_000_000, updated_at: 1_760_000_000_000,
});
const LISTS = {
  watchlists: [
    LIST(1, "Nifty IT", "index"),
    LIST(2, "Energy (Nifty 500)", "sector", "ready", 19),
    LIST(3, "Mid caps (Nifty Midcap 150)", "size", "ready", 149),
    LIST(4, "Momentum 30 (NSE)", "factor", "ready", 30),
    LIST(5, "Metis · Booming: Metals", "ai", "metis", 5),
    LIST(6, "My banks", "custom", "custom", 2),
  ],
};
const ITEM = (symbol: string, note = "") => ({
  instrument_id: symbol.length, symbol, name: `${symbol} Ltd`, type: "equity", sector: "Materials", industry: "Metals & Mining",
  size: "large", tags: ["metals"], note, last: 150.5, change_pct: 1.2,
});
const SECTORS = {
  market: "IN", as_of: 1_760_000_000_000, stocks: 180, booms: ["Materials"], slumps: [], industries: [],
  sentence: "Booming now: Materials.",
  sectors: [
    {
      name: "Materials", members: 20, returns: { "1w": 2, "1m": 9.4, "3m": 15, "6m": 20 }, rs_ratio: 104, rs_momentum: 102, quadrant: "leading",
      breadth: { members: 20, above50: 85, above200: 70, new_highs: 6 }, month_z: 2.1, volume_ratio: 1.5, state: "boom", score: 80,
      leaders: [], laggards: [], sentence: "Materials is booming.",
    },
  ],
};

describe("Watchlists", () => {
  it("groups ready-made, AI-made and your lists, and shows where money is moving", async () => {
    mockBackend({ "/api/watchlists": LISTS, "/api/sectors*": SECTORS });
    renderAt(<App />, "/watchlists");
    expect(await screen.findByRole("heading", { name: "Watchlists", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("Booming now: Materials.")).toBeInTheDocument();
    expect(screen.getByText("Booming")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Watchlists" });
    for (const g of ["Your lists", "Made by Kairos and Metis", "Indices", "Sectors", "Large, mid and small caps", "Factor lists (how quant funds pick)"]) {
      expect(within(nav).getByText(g)).toBeInTheDocument();
    }
    expect(within(nav).getByRole("link", { name: /Momentum 30 \(NSE\)/ })).toHaveAttribute("href", "/watchlists/4");
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /Watchlists/ })).toHaveAttribute("href", "/watchlists");
  });

  it("shows why Metis made a list, and lets you copy a ready-made one", async () => {
    const spy = mockBackend({
      "/api/watchlists": LISTS,
      "/api/sectors*": SECTORS,
      "/api/watchlists/5": { watchlist: { ...LISTS.watchlists[4], items: [ITEM("TATASTEEL", "+12.0% this month"), ITEM("HINDALCO")], with_prices: 2 } },
      "POST /api/watchlists/5/copy": { watchlist: { ...LIST(9, "My Metis · Booming: Metals", "custom", "custom", 2), items: [], with_prices: 0 } },
    });
    renderAt(<App />, "/watchlists/5");
    expect(await screen.findByText("Metals are booming.")).toBeInTheDocument();
    expect(screen.getByText("Metis made this list:")).toBeInTheDocument();
    expect(screen.getByText("+12.0% this month")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TATASTEEL" })).toHaveAttribute("href", "/charts?symbol=TATASTEEL&market=IN");
    fireEvent.click(screen.getByRole("button", { name: /Copy to my lists/ }));
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u) === "/api/watchlists/5/copy" && i?.method === "POST")).toBe(true));
  });

  it("edits your own list", async () => {
    const spy = mockBackend({
      "/api/watchlists": LISTS,
      "/api/sectors*": SECTORS,
      "/api/watchlists/6": { watchlist: { ...LISTS.watchlists[5], items: [ITEM("HDFCBANK"), ITEM("SBIN")], with_prices: 2 } },
    });
    renderAt(<App />, "/watchlists/6");
    fireEvent.change(await screen.findByLabelText("Add stocks"), { target: { value: "ICICIBANK, AXISBANK" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => {
      const call = spy.mock.calls.find(([u, i]) => String(u) === "/api/watchlists/6" && i?.method === "PATCH");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ add: ["ICICIBANK", "AXISBANK"] });
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove SBIN" }));
    await waitFor(() => {
      const call = spy.mock.calls.filter(([u, i]) => String(u) === "/api/watchlists/6" && i?.method === "PATCH").at(-1);
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ remove: ["SBIN"] });
    });
  });
});
