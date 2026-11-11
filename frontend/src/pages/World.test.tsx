import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

const VIEW = {
  market: "IN", tilt: -0.7, sectors: { Energy: 0.1 }, tags: { omc: -1.4 },
  sentence: "War in the Middle East is in the news; it leans against the market.",
  drivers: [
    {
      scenario: "mideast_war", title: "War in the Middle East", calming: false, strength: 14, weight: 0.83,
      chain: ["Fighting near the world's biggest oil producers raises the risk to supply.", "Crude oil, gold, the dollar and volatility rise."],
      effects: [
        { target: "tag:omc", label: "Fuel retailers (India's oil marketing companies)", value: -1.4, map: -2, measured: { n: 6, mean_pct: -1.8, hit_rate: 0.83 } },
        { target: "tag:oil_producer", label: "Oil and gas producers", value: 0.8, map: 1, measured: null },
      ],
      headlines: [{ title: "Iran fires missiles at Israel", publisher: "Reuters", published_at: 1_760_000_000_000, link: "https://example.invalid/w", calming: false }],
      event_id: 1,
    },
  ],
  helped: [{ instrument_id: 1, symbol: "ONGC", name: "ONGC", tilt: 0.1, vs_market: 0.8, why: ["its exposure (oil and gas producers) may gain"] }],
  hurt: [{ instrument_id: 2, symbol: "BPCL", name: "BPCL", tilt: -2.1, vs_market: -1.4, why: ["its exposure (fuel retailers) is hurt"] }],
};
const WORLD = {
  IN: VIEW,
  US: { ...VIEW, market: "US", drivers: [], helped: [], hurt: [], sentence: "No world event in the news is big enough to move this market right now." },
  events: [],
  moves: [
    {
      id: 3, market: "IN", target: "market", timeframe: "1d", start_ts: 1, end_ts: 1_760_000_000_000, move_pct: -2.8, z: -3.6, verdict: "world", created_at: 1,
      text: "the Nifty 50 fell 2.8% on Mon 14 Apr (unusual: 3.6× a normal day). Most likely cause: War in the Middle East.",
      causes: [{ key: "world:mideast_war", kind: "world", title: "War in the Middle East", score: 1.2, headline: { title: "Iran fires missiles at Israel", publisher: "Reuters", published_at: 1, link: "https://example.invalid/w" }, sources: 3, chain: [], clues: ["oil rose 4.2%"], against: [] }],
      confidence: "high", headlines_read: 40,
    },
  ],
};

describe("World", () => {
  it("shows the events, their chain of effects, the stocks they move and why the market fell", async () => {
    mockBackend({ "/api/world*": WORLD, "/api/world/lessons*": { lessons: [{ scenario: "mideast_war", title: "War in the Middle East", market: "IN", target: "tag:omc", n: 6, mean_pct: -1.8, map: -2, agrees: true }] } });
    renderAt(<App />, "/world");
    expect(await screen.findByRole("heading", { name: "World", level: 1 })).toBeInTheDocument();
    expect(screen.getByText(VIEW.sentence)).toBeInTheDocument();
    expect(screen.getByText("Crude oil, gold, the dollar and volatility rise.")).toBeInTheDocument();
    expect(screen.getByText("measured on 6: -1.8%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BPCL" })).toHaveAttribute("href", "/charts?symbol=BPCL&market=IN&kairos=1");
    expect(screen.getByText(/Most likely cause: War in the Middle East/)).toBeInTheDocument();
    expect(screen.getByText("high confidence")).toBeInTheDocument();
    expect(await screen.findByText("What past events actually did")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /World/ })).toHaveAttribute("href", "/world");
  });

  it("says plainly when the world is quiet", async () => {
    mockBackend({ "/api/world*": { ...WORLD, IN: { ...WORLD.US, market: "IN" }, moves: [] }, "/api/world/lessons*": { lessons: [] } });
    renderAt(<App />, "/world");
    expect(await screen.findByText("The world is quiet for this market")).toBeInTheDocument();
    expect(screen.getByText(/No unusual moves yet/)).toBeInTheDocument();
  });
});
