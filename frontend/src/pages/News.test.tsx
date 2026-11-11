import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockBackend, NEWS_LIVE, renderAt } from "../test-utils";

vi.mock("lightweight-charts", () => import("../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../test-mocks/echarts-core"));
afterEach(() => vi.unstubAllGlobals());

describe("News", () => {
  it("shows the three risk gauges, the headlines and what the desk does", async () => {
    mockBackend();
    renderAt(<App />, "/news");
    expect(await screen.findByRole("heading", { name: "News", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("News risk · India")).toBeInTheDocument();
    expect(screen.getByText("News risk · World")).toBeInTheDocument();
    expect(screen.getAllByRole("meter", { name: "News risk" })).toHaveLength(3);
    expect(screen.getByText("54")).toBeInTheDocument();
    expect(screen.getAllByText("Elevated").length).toBeGreaterThanOrEqual(1);
    // the desk's rule at this level, in protective mode
    expect(screen.getAllByText(/Still trading: half size where the news hurts/).length).toBeGreaterThanOrEqual(1);
    const list = screen.getByRole("link", { name: /Infosys wins a large deal/ });
    expect(list).toHaveAttribute("href", "https://example.invalid/3");
    expect(screen.getAllByLabelText("Severity 4 of 5").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("▼ risk-off").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Kairos's news guard")).toBeInTheDocument();
    expect(screen.getByText(/GDELT · World geopolitics/)).toBeInTheDocument();
  });

  it("filters by region, topic, severity and words", async () => {
    const spy = mockBackend();
    renderAt(<App />, "/news");
    await screen.findByText("News risk · India");
    fireEvent.click(screen.getByRole("radio", { name: "World" }));
    fireEvent.click(screen.getByRole("button", { name: "Geopolitics" }));
    fireEvent.click(screen.getByRole("button", { name: "Market-moving only" }));
    fireEvent.change(screen.getByPlaceholderText("Search headlines"), { target: { value: "oil" } });
    await waitFor(() => {
      const urls = spy.mock.calls.map(([u]) => String(u));
      expect(urls.some((u) => u.includes("region=WORLD") && u.includes("group=Geopolitics") && u.includes("min_severity=3") && u.includes("q=oil"))).toBe(true);
    });
  });

  it("refreshes on request", async () => {
    const spy = mockBackend({ "POST /api/news/refresh": { feeds: 20, new: 7, errors: [] } });
    renderAt(<App />, "/news");
    fireEvent.click(await screen.findByRole("button", { name: "Refresh now" }));
    await waitFor(() => {
      const post = spy.mock.calls.find(([u, init]) => String(u) === "/api/news/refresh" && init?.method === "POST");
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ world: true });
    });
    expect(await screen.findByText("7 new headlines.")).toBeInTheDocument();
  });

  it("explains when news is off, and appears on Home and in the sidebar", async () => {
    mockBackend({ "/api/news/live*": { ...NEWS_LIVE, enabled: false } });
    renderAt(<App />, "/news");
    expect(await screen.findByText("Reading news is turned off")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation")).getByRole("link", { name: /News/ })).toHaveAttribute("href", "/news");
  });

  it("shows news risk on Home", async () => {
    mockBackend();
    renderAt(<App />, "/");
    expect(await screen.findByText("News risk")).toBeInTheDocument();
    expect(await screen.findByText("54/100")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open News" })).toHaveAttribute("href", "/news");
  });
});
