import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { EMPTY_COVERAGE, mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));

afterEach(() => vi.unstubAllGlobals());

const FULL = {
  ...EMPTY_COVERAGE,
  rows: [
    { ...EMPTY_COVERAGE.rows[0], first: 1_451_619_900_000, last: 1_767_150_000_000, bars: 2480, status: "ok", source: "yahoo" },
    { ...EMPTY_COVERAGE.rows[1], first: 1_451_619_900_000, last: 1_767_150_000_000, bars: 2477, gaps: 3, status: "gaps", source: "yahoo" },
  ],
  totals: { symbols: 2, ok: 1, empty: 0, stale: 0, gaps: 1 },
  last_update: Date.now() - 120_000,
};

describe("Data screen", () => {
  it("shows coverage with plain status words", async () => {
    mockBackend({ "/api/data/coverage*": FULL });
    renderAt(<App />, "/data");
    expect(await screen.findByText("Has gaps")).toBeInTheDocument();
    expect(screen.getAllByText("Up to date")).toHaveLength(1); // the tile: the table lists only problems
    expect(screen.getByText("Last download 2 min ago")).toBeInTheDocument();
  });

  it("starts a download and shows its progress", async () => {
    const job = { job_id: "data_refresh-1", kind: "data_refresh", title: "Downloading prices for 51 stocks", status: "running", pct: 40, eta_s: 30, message: "Downloading TCS (daily)…", result: null, error: null };
    mockBackend({ "POST /api/data/refresh": { job_id: "data_refresh-1" }, "/api/jobs/data_refresh-1": job });
    renderAt(<App />, "/data");
    fireEvent.click(await screen.findByRole("button", { name: "Download prices" }));
    expect(await screen.findByText("Downloading TCS (daily)…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40"));
  });

  it("finds a download again after leaving the screen, and shows it in the top bar", async () => {
    const job = { job_id: "data_refresh-7", kind: "data_refresh", title: "Downloading prices for 798 stocks", status: "running", pct: 12, eta_s: 600, message: "Downloading INFY (daily)…", result: null, error: null };
    mockBackend({
      "/api/data/coverage*": FULL,
      "/api/jobs?kind=data_refresh&active=true": { jobs: [job] },
      "/api/jobs?active=true": { jobs: [job] },
      "/api/jobs/data_refresh-7": job,
    });
    renderAt(<App />, "/data");
    expect(await screen.findByText("Downloading INFY (daily)…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Downloading…/ })).toBeDisabled();
    expect(await screen.findByRole("button", { name: "1 task running" })).toBeInTheDocument();
  });
});
