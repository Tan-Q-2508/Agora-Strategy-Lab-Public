import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../../App";
import { AI_READY, mockBackend, renderAt, sseResponse } from "../../test-utils";

vi.mock("lightweight-charts", () => import("../../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const RUN = {
  id: 4, name: null, status: "done", progress: 100, starred: false, created_at: 0, finished_at: 1, strategy_id: 7, strategy_name: "My MA",
  version: 3, strategy_version_id: 9, mode: "single", market: "IN", timeframe: "1d", symbols: ["RELIANCE"], start: 1_600_000_000_000,
  end: 1_700_000_000_000, capital: 1_000_000, headline: {}, error: null, parent_run_id: null, overrides: {}, params: {},
  metrics: { total_return: 0.42, trades: 37, monthly_returns: {}, per_symbol: [], charges_by_type: {} },
  warnings: [], summary: "This strategy made 42%.", error_detail: null, repro: null, job: null,
};
const RESULTS = {
  "/api/backtests/4": RUN,
  "/api/backtests/4/equity": { points: [], benchmark: [], capital: 1e6 },
  "/api/backtests/4/trades*": { trades: [], total: 0, next_cursor: null },
};

describe("AI helper", () => {
  it("streams an explanation of a backtest and flags unchecked numbers", async () => {
    const spy = mockBackend({
      ...RESULTS,
      "POST /api/ai/explain": sseResponse([
        { type: "start", conversation_id: 1 },
        { type: "text", text: "**What worked** It made 37 trades. " },
        { type: "text", text: "It might return 90% next year." },
        { type: "done", unverified: ["90"], note: "AI-generated. Check important numbers." },
      ]),
    });
    renderAt(<App />, "/backtests/4");
    fireEvent.click(await screen.findByRole("button", { name: "Explain this backtest" }, { timeout: 5000 }));
    expect(await screen.findByText("What worked")).toBeInTheDocument();
    expect(screen.getByText(/It made 37 trades/)).toBeInTheDocument();
    expect(await screen.findByText(/These numbers don't appear in your results/)).toHaveTextContent("90");
    expect(screen.getByText("AI-generated. Check important numbers.")).toBeInTheDocument();
    const post = spy.mock.calls.find(([url]) => String(url) === "/api/ai/explain");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ kind: "backtest", id: 4 });
  });

  it("offers setup instead of a dead button when Ollama isn't installed", async () => {
    mockBackend({ ...RESULTS, "/api/ai/status*": { ...AI_READY, state: "not_installed", models: [], version: null } });
    renderAt(<App />, "/backtests/4");
    expect((await screen.findAllByText(/The free AI helper isn't set up/, {}, { timeout: 5000 })).length).toBe(2);
    expect(screen.queryByRole("button", { name: "Explain this backtest" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Set up the AI helper" })[0]).toHaveAttribute("href", "/settings?tab=ai");
  });

  it("Settings: install steps, then a one-click model download", async () => {
    const spy = mockBackend({
      "/api/ai/status*": { ...AI_READY, state: "model_missing", models: [] },
      "POST /api/ai/pull": { job_id: "ai-pull-qwen3.5:4b" },
      "/api/jobs/ai-pull-qwen3.5:4b": { id: "ai-pull-qwen3.5:4b", kind: "ai_pull", title: "Download", status: "running", pct: 40, message: "Downloading qwen3.5:4b: 1.3 of 3.2 GB", eta_s: null, error: null, result: null, created_at: 0 },
    });
    renderAt(<App />, "/settings?tab=ai");
    expect(await screen.findByText("Model not downloaded")).toBeInTheDocument();
    const row = screen.getByText("Qwen 3.5 (4B)").closest("div.flex.items-center") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Download" }));
    expect(await screen.findByText("Downloading qwen3.5:4b: 1.3 of 3.2 GB")).toBeInTheDocument();
    const post = spy.mock.calls.find(([url, init]) => String(url) === "/api/ai/pull" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ model: "qwen3.5:4b" });
  });

  it("Settings: says when the model runs on the processor and how to fix it", async () => {
    mockBackend({
      "/api/ai/status*": {
        ...AI_READY,
        runs_on: { where: "cpu", gpu_percent: 0, text: "The processor, not the graphics card, so answers are several times slower.", fix: "Plug in the charger … Quit Ollama …" },
      },
    });
    renderAt(<App />, "/settings?tab=ai");
    expect(await screen.findByText(/The processor, not the graphics card/)).toBeInTheDocument();
    expect(screen.getByText(/Quit Ollama/)).toBeInTheDocument();
  });

  it("drafts a strategy from an idea and saves it as an AI draft", async () => {
    const definition = {
      schema_version: 1, kind: "visual", market: "IN", universe: { kind: "symbols", symbols: ["RELIANCE"] }, timeframe: "1d", product: "delivery",
      sizing: { kind: "percent_equity", value: 10 }, limits: { max_open_positions: 5, max_per_symbol: 1, max_daily_loss_pct: null }, parameters: [],
      entry: { long: { type: "compare", left: { kind: "indicator", name: "rsi", params: { period: 14 } }, op: "crosses_below", right: { kind: "number", value: 30 } }, short: null },
      exit: { long: null, short: null, stop_loss: { kind: "percent", value: 5 }, take_profit: null, trailing_stop: null, max_bars: null, exit_time: null },
    };
    const spy = mockBackend({
      "/api/indicators": { indicators: [{ key: "rsi", label: "RSI", description: "", params: [{ name: "period", label: "Period", default: 14, min: 2, max: 100, type: "int" }], outputs: [{ key: "value", label: "Value" }], overlay: false, uses_source: true, default_source: "close", intraday_only: false }], price_fields: [] },
      "POST /api/ai/draft-strategy": { ok: true, definition, explanation: "Buys when RSI dips below 30.", unsupported: ["news"], issues: [], attempts: 1, conversation_id: 3, note: "" },
      "POST /api/strategies": { strategy: { id: 12 }, version: { version: 1 } },
    });
    renderAt(<App />, "/strategies/new?kind=ai");
    fireEvent.change(await screen.findByLabelText("Your idea"), { target: { value: "Buy when RSI is oversold" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft the rules" }));
    expect(await screen.findByText("Drafted by the AI helper. Check every rule, then save.")).toBeInTheDocument();
    expect(screen.getByText("Buys when RSI dips below 30.")).toBeInTheDocument();
    expect(screen.getByText(/left out: news/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const post = spy.mock.calls.find(([url, init]) => String(url) === "/api/strategies" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body)).created_by).toBe("ai_draft");
    });
  });
});
