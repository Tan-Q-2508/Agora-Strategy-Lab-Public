import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const ACTIONS = {
  summary: [{ kind: "metis_round", n: 3, ok: 2, failed: 1, wrong: 0, cut_off: 0, running: 0, last_at: 1 }],
  actions: [
    { id: 1, started_at: Date.now(), ms: 2100, kind: "metis_round", what: "Metis research round", who: "metis", why: "auto", status: "failed", output: "The AI stopped", correct: null, correct_why: "", detail: {} },
  ],
};

describe("Logs", () => {
  it("lists what happened and how it came out", async () => {
    mockBackend({ "/api/actions*": ACTIONS });
    renderAt(<App />, "/logs");
    expect(await screen.findByText("Metis research round")).toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("The AI stopped")).toBeInTheDocument();
    expect(screen.getByText("2.1 s")).toBeInTheDocument();
  });
});
