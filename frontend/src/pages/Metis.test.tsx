import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { stateLine, type MetisStatus } from "../lib/metis";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const PART = (net: number, trades: number, wr: number) => ({ trades, wins: Math.round(trades * wr), win_rate: wr, net, gross: net + 500, charges: 500, profit_factor: 1.4 });
const STATUS: MetisStatus = {
  on: true,
  state: "scheduled",
  doing: "",
  waiting: "",
  ai_ready: true,
  thread: true,
  last_round_at: 1_760_000_000_000,
  next_round_at: null,
  every_minutes: 20,
  apply: true,
  focus: "",
  totals: { rounds: 1, ideas: 2, tested: 2, held_up: 1, saved: 1 },
  rounds: [
    { id: 1, started_at: 1_760_000_000_000, finished_at: 1_760_000_100_000, status: "done", trigger: "auto", focus: "", model: "qwen3.5:4b", noticed: "Losers clustered in trending markets.", note: "Tested 2 ideas; 1 held up and was saved.", ideas: 2, kept: 1, thinking: "Dip buying works when the market is choppy…" },
  ],
  ideas: [
    {
      id: 2, round_id: 1, created_at: 1_760_000_050_000, kind: "filter", title: "Only buy dips in choppy markets", why: "Losers clustered when choppiness was low.", market: "IN",
      strategy_id: 3, strategy_version_id: 4, status: "saved",
      verdict: "Held up. In the exam years it made ₹37,028 more after costs than the current version.",
      result: { split: 1_690_000_000_000, baseline: { study: PART(65_965, 145, 0.66), exam: PART(13_255, 60, 0.68) }, candidate: { study: PART(70_000, 90, 0.7), exam: PART(50_283, 39, 0.8) }, checks: [] },
      saved_strategy_id: 3, saved_version_id: 9, run_id: 21,
    },
    {
      id: 1, round_id: 1, created_at: 1_760_000_040_000, kind: "tweak", title: "Wider bands", why: "Fewer, deeper dips.", market: "IN",
      strategy_id: 3, strategy_version_id: 4, status: "held_up",
      verdict: "Held up. Made more in the exam years.",
      result: { baseline: { study: PART(1, 10, 0.5), exam: PART(1, 10, 0.5) }, candidate: { study: PART(2, 10, 0.5), exam: PART(3, 10, 0.5) } },
      saved_strategy_id: null, saved_version_id: null, run_id: null,
    },
  ],
};

describe("Metis", () => {
  it("shows the notebook, the numbers on unseen years, how it thought, and saves an idea", async () => {
    const spy = mockBackend({
      "/api/metis": STATUS,
      "POST /api/metis/ideas/1/save": { idea: { ...STATUS.ideas[1], status: "saved" } },
      "PUT /api/settings": { values: {}, meta: {} },
    });
    renderAt(<App />, "/metis");
    expect(await screen.findByRole("heading", { name: "Metis", level: 1 })).toBeInTheDocument();
    const filter = screen.getByRole("article", { name: "Only buy dips in choppy markets" });
    expect(within(filter).getByText("Held up · saved")).toBeInTheDocument();
    expect(within(filter).getByText(/Exam years: Metis never saw these/)).toBeInTheDocument();
    expect(within(filter).getByText(/50,283 · 39 trades · won 80%/)).toBeInTheDocument();
    expect(within(filter).getByRole("link", { name: /See its backtest/ })).toHaveAttribute("href", "/backtests/21");
    expect(screen.getByText("How Metis thought")).toBeInTheDocument();
    expect(screen.getByText(/Tested 2 ideas; 1 held up/)).toBeInTheDocument();
    const tweak = screen.getByRole("article", { name: "Wider bands" });
    fireEvent.click(within(tweak).getByRole("button", { name: "Save it" }));
    await waitFor(() => expect(spy.mock.calls.some(([url, init]) => String(url).endsWith("/api/metis/ideas/1/save") && (init as RequestInit | undefined)?.method === "POST")).toBe(true));
    fireEvent.click(screen.getByRole("radio", { name: "Off" }));
    await waitFor(() =>
      expect(spy.mock.calls.some(([url, init]) => String(url).endsWith("/api/settings") && String((init as RequestInit | undefined)?.body).includes('"metis.enabled":false'))).toBe(true),
    );
  });

  it("keeps working from its playbook when the AI helper is missing", async () => {
    mockBackend({
      "/api/metis": { ...STATUS, ai_ready: false, state: "playbook", ai_note: "Metis needs the AI helper (Ollama) to think.", ideas: [], rounds: [] },
      "/api/metis/library": { total: 117, areas: [{ key: "method", title: "The research method", sections: ["The research loop", "Simple beats clever"] }] },
    });
    renderAt(<App />, "/metis");
    expect(await screen.findByRole("link", { name: "Set up the AI helper" })).toHaveAttribute("href", "/settings?tab=ai");
    expect(screen.getByText(/Metis works from its playbook/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Research now" })).toBeEnabled();
    expect(screen.getByText("No ideas yet")).toBeInTheDocument();
    expect(await screen.findByText("What Metis knows")).toBeInTheDocument();
    expect(screen.getByText(/library of 117 sections/)).toBeInTheDocument();
  });

  it("labels playbook ideas, the luck check, and the round's direction", async () => {
    const [, tweak] = STATUS.ideas;
    if (!tweak) throw new Error("the fixture has two ideas");
    const idea = {
      ...tweak, id: 7, title: "Drop the trending stocks", kind: "universe" as const, origin: "playbook" as const, status: "rejected" as const,
      result: { ...tweak.result, luck: { dsr: 0.31, tries: 12, days: 640 } },
    };
    mockBackend({ "/api/metis": { ...STATUS, ideas: [idea], rounds: [{ ...STATUS.rounds[0], direction: "improve_live", model: "playbook" }] } });
    renderAt(<App />, "/metis");
    const card = await screen.findByRole("article", { name: "Drop the trending stocks" });
    expect(within(card).getByText("Different stocks")).toBeInTheDocument();
    expect(within(card).getByText(/From the playbook/)).toBeInTheDocument();
    expect(within(card).getByText(/Luck check: 31% chance it beats the best of 12 lucky tries/)).toBeInTheDocument();
    expect(screen.getByText("Improving what you're paper trading")).toBeInTheDocument();
  });

  it("describes what Metis is doing in plain words", () => {
    const now = 1_000_000;
    expect(stateLine({ ...STATUS, state: "scheduled", next_round_at: now + 14 * 60_000 }, now)).toMatch(/Next round in about 14 minutes/);
    expect(stateLine({ ...STATUS, state: "working", doing: "Testing idea 2 of 3…" }, now)).toBe("Testing idea 2 of 3…");
    expect(stateLine({ ...STATUS, state: "off" }, now)).toMatch(/Switched off/);
  });
});
