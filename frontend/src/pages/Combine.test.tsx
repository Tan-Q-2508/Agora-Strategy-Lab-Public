import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const S = { kind: "visual", market: "IN", timeframe: "1d", archived: false, description: "", created_at: 0, updated_at: 0, template_key: null, version: 1 };

describe("Combine strategies", () => {
  it("lists strategies and the ways to combine them", async () => {
    mockBackend({ "/api/strategies*": { strategies: [{ ...S, id: 1, name: "Crossover", version_id: 11 }, { ...S, id: 2, name: "Volume push", version_id: 12 }] } });
    renderAt(<App />, "/strategies/combine");
    expect(await screen.findByText("Crossover")).toBeInTheDocument();
    expect(screen.getByText("Volume push")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "All agree" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test together" })).toBeDisabled();
  });
});
