import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { mockBackend, renderAt } from "./test-utils";

vi.mock("lightweight-charts", () => import("./test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("./test-mocks/echarts-core"));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("app shell", () => {
  it("shows every main screen in the sidebar", async () => {
    mockBackend();
    renderAt(<App />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const label of ["Home", "Strategies", "Backtests", "Compare", "Paper trading", "Charts", "Data", "Settings"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("shows Kairos and Metis working on their own on Home", async () => {
    mockBackend();
    renderAt(<App />, "/");
    expect(await screen.findByText("Kairos and Metis")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Kairos desk · India" })).toHaveAttribute("href", "/paper/desk/7");
    expect(screen.getByText("started on its own")).toBeInTheDocument();
    expect(screen.getByText("working from its playbook until Ollama is ready")).toBeInTheDocument();
    expect(screen.getByText(/India: prices for 120 of 230 stocks so far/)).toBeInTheDocument();
  });

  it("shows live market status in the top bar and on Home", async () => {
    mockBackend();
    renderAt(<App />);
    expect(await screen.findByText(/closes in 3h 57m/)).toBeInTheDocument();
    expect(screen.getByText("Closes 15:30 IST · in 3h 57m")).toBeInTheDocument();
    expect(screen.getByText("Closed")).toBeInTheDocument();
  });

  it("explains in plain English when the backend is down", async () => {
    mockBackend({ "/api/markets/status": new TypeError("Failed to fetch") });
    renderAt(<App />);
    expect(await screen.findByText("Agora isn't running.")).toBeInTheDocument();
    expect(screen.getByText("Market hours unavailable")).toBeInTheDocument();
  });

  it("collapses the sidebar and remembers it", async () => {
    mockBackend();
    renderAt(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    expect(localStorage.getItem("agora.sidebar.collapsed")).toBe("1");
  });

  it("opens the command palette with Ctrl+K and navigates", async () => {
    mockBackend();
    renderAt(<App />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByText("Strategies"));
    expect(await screen.findByRole("heading", { name: "Strategies" })).toBeInTheDocument();
  });

  it("shows a friendly page for unknown links", async () => {
    mockBackend();
    renderAt(<App />, "/nope");
    expect(await screen.findByText("That page doesn't exist")).toBeInTheDocument();
  });

  it.each([
    ["/strategies", "No strategies yet"],
    ["/strategies/new", "Add a buy rule"],
    ["/backtests", "No backtests yet"],
    ["/compare", "Nothing to compare yet"],
    ["/paper", "No paper trading sessions"],
    ["/data", "No prices downloaded yet"],
  ])("%s has a real empty state", async (path, text) => {
    mockBackend();
    renderAt(<App />, path);
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("renders the onboarding tour without the shell", async () => {
    mockBackend();
    renderAt(<App />, "/welcome");
    expect(await screen.findByText("Welcome to your strategy lab")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("charts a stock's real prices once one is picked", async () => {
    const bars = [0, 1, 2].map((i) => ({ ts: 1_700_000_000_000 + i * 86_400_000, open: 10, high: 11, low: 9, close: 10.5, volume: 100, source: "yahoo" }));
    mockBackend({ "/api/candles*": { instrument: { id: 1, market: "IN", symbol: "RELIANCE" }, timeframe: "1d", adjusted: true, bars, note: null } });
    renderAt(<App />, "/charts");
    expect(await screen.findByText("Choose a stock to see its chart")).toBeInTheDocument();
    const select = await screen.findByRole("combobox", { name: "Stock" });
    await waitFor(() => expect(select).not.toBeDisabled());
    fireEvent.focus(select);
    fireEvent.change(select, { target: { value: "RELI" } });
    fireEvent.mouseDown(await screen.findByRole("option", { name: /RELIANCE/ }));
    expect(await screen.findByRole("img", { name: "Candlestick chart of RELIANCE" })).toBeInTheDocument();
  });

  it("sends first-time users to the setup tour", async () => {
    mockBackend({ "/api/settings": { values: { theme: "light", onboarding_done: false }, meta: {} } });
    renderAt(<App />);
    expect(await screen.findByText("Welcome to your strategy lab")).toBeInTheDocument();
  });
});

describe("theme", () => {
  it("defaults to light and saves a new choice to settings", async () => {
    const spy = mockBackend();
    renderAt(<App />, "/settings");
    await screen.findByText("Appearance");
    expect(document.documentElement.dataset.theme).toBe("light");
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
    const put = spy.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(put?.[1]?.body).toBe(JSON.stringify({ theme: "dark" }));
    expect(localStorage.getItem("agora.theme")).toBe("dark");
  });

  it("follows the saved server setting", async () => {
    mockBackend({ "/api/settings": { values: { theme: "dark" }, meta: {} } });
    renderAt(<App />);
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
  });

  it("lists every default with its explanation", async () => {
    mockBackend();
    renderAt(<App />, "/settings");
    expect(await screen.findByText("Largest order (% of volume)")).toBeInTheDocument();
    expect(screen.getByText("₹10 L")).toBeInTheDocument();
    expect(screen.getByText("15:20 IST")).toBeInTheDocument();
  });
});

describe("keyboard and palette", () => {
  it("shows shortcuts with ? and jumps with g then a letter", async () => {
    mockBackend();
    renderAt(<App />);
    await screen.findByText(/closes in 3h 57m/);
    fireEvent.keyDown(window, { key: "?" });
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "b" });
    expect(await screen.findByRole("heading", { name: "Backtests" })).toBeInTheDocument();
  });

  it("offers actions and your own strategies in the palette", async () => {
    mockBackend({
      "/api/strategies*": { strategies: [{ id: 7, name: "My MA", description: "", kind: "visual", market: "IN", created_at: 0, updated_at: 0, archived: false, template_key: null, version: 1, version_id: 9, timeframe: "1d", last_backtest: null }] },
    });
    renderAt(<App />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Describe a strategy to the AI helper")).toBeInTheDocument();
    expect(within(dialog).getByText("Start paper trading")).toBeInTheDocument();
    expect(await within(dialog).findByText("My MA")).toBeInTheDocument();
  });

  it("onboarding ends by running a real starter backtest", async () => {
    const spy = mockBackend({
      "/api/templates": { templates: [{ key: "ma_crossover", name: "Moving-average crossover", summary: "Buy on the cross up.", description: "", idea: "", timeframe: "1d" }] },
      "POST /api/settings": {},
      "POST /api/data/refresh": { job_id: "refresh-1" },
      "/api/jobs/refresh-1": { id: "refresh-1", kind: "refresh", title: "Download", status: "done", pct: 100, message: "Done", eta_s: null, error: null, result: { symbols: 50, fetched: 1000, failed: [], fallback_used: false }, created_at: 0 },
      "POST /api/strategies": { strategy: { id: 3 }, version: { id: 11 } },
      "POST /api/backtests": { run_id: 21, job_id: "backtest-21" },
      "/api/jobs/backtest-21": { id: "backtest-21", kind: "backtest", title: "Backtest", status: "done", pct: 100, message: "Backtest finished.", eta_s: null, error: null, result: null, created_at: 0 },
    });
    renderAt(<App />, "/welcome");
    fireEvent.click(await screen.findByRole("button", { name: /Download prices/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Next/ }));
    const runBtn = await screen.findByRole("button", { name: "Run backtest" });
    await waitFor(() => expect(runBtn).toBeEnabled());
    fireEvent.click(runBtn);
    expect(await screen.findByRole("button", { name: /See the results/ })).toBeInTheDocument();
    const post = spy.mock.calls.find(([url, init]) => String(url) === "/api/backtests" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ strategy_version_id: 11, mode: "single" });
  });
});
