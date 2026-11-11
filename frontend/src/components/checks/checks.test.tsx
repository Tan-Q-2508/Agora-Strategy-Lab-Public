import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LookaheadPanel } from "../../pages/builder/LookaheadPanel";
import { RankingRulesPanel } from "../../pages/builder/RankingRulesPanel";
import { TearSheet, type TearSheetData } from "../../pages/results/TearSheet";
import type { RankingDefinition } from "../../lib/strategy";
import { mockBackend, renderAt } from "../../test-utils";
import { TooltipProvider } from "../ui/tooltip";
import { ForwardChecks } from "./ForwardChecks";

vi.mock("echarts/core", () => import("../../test-mocks/echarts-core"));

afterEach(() => vi.unstubAllGlobals());

const LOOKAHEAD = {
  id: 7, kind: "lookahead", created_at: 1_760_000_000_000, strategy_id: 3, version_id: 30, version: 2, baseline_version_id: null, sleeve_id: null, portfolio_id: null,
  verdict: "lookahead", title: "Look-ahead found: the rules used candles that hadn't closed yet.", action: "",
  result: {
    verdict: "lookahead", title: "Look-ahead found: the rules used candles that hadn't closed yet.", text: "When later candles were hidden the rules behaved differently.", notes: [], symbols: ["RELIANCE"], signals: 12, version: 2, start: 0, end: 0,
    lookahead: { slices: 20, signals_checked: 80, indicators_checked: 40, leaky_indicators: ["SMA (20)"], findings: [{ symbol: "RELIANCE", ts: 0, kind: "signal", text: "RELIANCE, 5 Mar 2024: with later candles visible the rules bought; with them hidden they did nothing." }] },
    history: { extra_candles: 250, signals_compared: 12, findings: [], unsettled: [] },
  },
};

describe("Checks", () => {
  it("shows the look-ahead check of this version and can run it again", async () => {
    const spy = mockBackend({ "/api/strategies/3/checks*": { checks: [LOOKAHEAD] }, "POST /api/strategies/3/lookahead": { job_id: "lookahead-1" }, "/api/jobs/lookahead-1": { job_id: "lookahead-1", kind: "lookahead", title: "Look-ahead check", status: "running", pct: 40, eta_s: null, message: "Checking RELIANCE…", result: null, error: null } });
    renderAt(<LookaheadPanel strategyId={3} version={2} ensureSaved={async () => true} />);
    expect(await screen.findByText("Look-ahead found")).toBeInTheDocument();
    expect(screen.getByText(/with them hidden they did nothing/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Check again/ }));
    expect(await screen.findByText("Checking RELIANCE…")).toBeInTheDocument();
    expect(spy.mock.calls.some(([u, i]) => String(u).endsWith("/api/strategies/3/lookahead") && (i as RequestInit | undefined)?.method === "POST")).toBe(true);
  });

  it("lists forward checks with Undo for what stopped holding up", async () => {
    const check = {
      ...LOOKAHEAD, id: 9, kind: "forward", verdict: "failed", title: "Version 5 stopped holding up.", baseline_version_id: 40, version: 5,
      result: { verdict: "failed", title: "Version 5 stopped holding up.", text: "On the 46 trading days since it was saved it made ₹3,200 less than version 4.", subject: "revision", name: "RSI dip: version 5", since: 1_755_000_000_000, sessions: 46, trades: 14, numbers: [{ label: "Version 5 made", value: "−₹1,000" }], can_undo: true, undo_label: "Put version 4 back" },
    };
    const item = { subject: "revision", name: "RSI dip: version 5", strategy_id: 3, version_id: 50, sleeve_id: null, portfolio_id: null, since: 1_755_000_000_000, days_since: 60, check };
    const spy = mockBackend({
      "/api/checks/forward": { items: [item, { ...item, name: "Breakout: version 2", version_id: 60, check: null, days_since: 9 }], auto_undo: false },
      "POST /api/checks/9/undo": { check: { ...check, action: "Version 4's rules were put back by you as version 6." } },
    });
    renderAt(<ForwardChecks subject="revision" title="Do saved improvements still hold up?" intro="Re-tested on new candles." />);
    expect(await screen.findByText("Stopped holding up")).toBeInTheDocument();
    expect(screen.getByText("Saved 9 days ago. The first re-test needs about a month of new candles.")).toBeInTheDocument();
    expect(screen.getByText(/Undoing is up to you/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Put version 4 back/ }));
    await waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).endsWith("/api/checks/9/undo"))).toBe(true));
  });

  it("draws the tear sheet from a run's saved numbers", () => {
    const sheet: TearSheetData = {
      days: 900,
      sharpe: { value: 1.2, band: { p5: 0.4, p50: 1.2, p95: 2.0 }, psr: 0.97, dsr: 0.41, trials: 12, min_track_record_days: 640, have_days: 900 },
      outcomes: { return_p5: -0.05, return_p50: 0.12, return_p95: 0.3, drop_p50: 0.14, drop_p95: 0.27 },
      trade_order: { trades: 60, history: 12.1, p50: 14.2, p95: 22.5, worst: 30.1, losing_streak_p95: 7 },
      rolling: { window: 126, points: [["2024-01-02", 0.8], ["2024-02-01", 1.1]], share_positive: 0.82 },
      underwater: { periods: [{ peak: "2024-03-01", trough: "2024-04-10", recovered: null, depth: 0.12, days_falling: 40, days_recovering: null }], time_underwater: 0.61 },
      risk: { var_95: 0.018, cvar_95: 0.026, tail_ratio: 1.1, best_day: 0.04, worst_day: -0.05, best_month: 0.09, worst_month: -0.08, positive_months: 0.6, skew: -0.2, kurtosis: 4.1 },
      years: [{ year: "2024", return: 0.11 }],
      summary: ["Sharpe ratio 1.20; anywhere from 0.40 to 2.00 is plausible (90% range)."],
    };
    renderAt(
      <TooltipProvider>
        <TearSheet runId={4} saved={sheet} />
      </TooltipProvider>,
    );
    expect(screen.getByText(/anywhere from 0.40 to 2.00/)).toBeInTheDocument();
    expect(screen.getByText("Luck check (best of 12 settings)")).toBeInTheDocument();
    expect(screen.getByText("41%")).toBeInTheDocument();
    expect(screen.getByText("not yet")).toBeInTheDocument();
    expect(screen.getByText("22.5%")).toBeInTheDocument();
  });

  it("edits a ranking and keeps its trade size in step with the stocks held", () => {
    const start: RankingDefinition = {
      schema_version: 1, kind: "ranking", market: "IN", universe: { kind: "all", symbols: [] }, timeframe: "1d", product: "delivery",
      sizing: { kind: "percent_equity", value: 9.5 }, limits: { max_open_positions: 20, max_per_symbol: 1, max_daily_loss_pct: null }, parameters: [],
      ranking: { rank_by: "momentum", lookback_months: 12, skip_months: 1, hold: 10, trend_filter: true },
    };
    let latest = start;
    function Harness() {
      const [d, setD] = useState(start);
      return <RankingRulesPanel d={d} issues={[]} onChange={(n) => ((latest = n), setD(n))} />;
    }
    renderAt(<Harness />);
    expect(screen.getByText("Each month, rank the stocks by 12-month rise (leaving out the latest 1 month) and hold the top 10 that actually rose, in equal shares.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Stocks held"), { target: { value: "5" } });
    fireEvent.blur(screen.getByLabelText("Stocks held"));
    expect(latest.ranking.hold).toBe(5);
    expect(latest.sizing.value).toBe(19);
    expect(latest.limits.max_open_positions).toBe(10);
    fireEvent.click(screen.getByRole("radio", { name: "Low volatility" }));
    expect(screen.getByText(/rank the stocks by calmness over 6 months/)).toBeInTheDocument();
  });
});
