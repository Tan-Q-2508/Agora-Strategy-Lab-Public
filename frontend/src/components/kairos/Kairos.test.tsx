import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../../App";
import { mockBackend, renderAt, SETTINGS, sseResponse } from "../../test-utils";

vi.mock("lightweight-charts", () => import("../../test-mocks/lightweight-charts"));
vi.mock("echarts/core", () => import("../../test-mocks/echarts-core"));

afterEach(() => vi.unstubAllGlobals());

const STATUS = { mode: "ai", ai_state: "ready", model: "qwen3.5:4b", suggestions: ["Analyse RELIANCE"], footer: "Kairos is a research tool, not financial advice. Paper money only." };

const CHART_CARD = {
  type: "chart",
  symbol: "RELIANCE",
  name: "Reliance Industries",
  market: "IN",
  timeframe: "1d",
  bias: "bearish",
  score: -23,
  confidence: "low",
  headline: "Downtrend · rectangle forming",
  lines: ["RELIANCE is in a downtrend (trend score −57)."],
  forecast: "Over the next 10 trading days, RELIANCE will most likely be between ₹1,235.52 and ₹1,446.73.",
  idea: null,
  link: "/charts?symbol=RELIANCE&market=IN&tf=1d&kairos=1",
};

function reply(follow = true) {
  return sseResponse([
    { type: "thread", thread_id: 7 },
    { type: "thinking" },
    { type: "step", id: "s1", tool: "analyze_chart", status: "running", label: "Reading RELIANCE's chart…" },
    { type: "step", id: "s1", tool: "analyze_chart", status: "done", label: "Read RELIANCE's 1d chart", detail: "Bearish · score −23", card: CHART_CARD, ui: follow ? { navigate: CHART_CARD.link } : null },
    { type: "text", delta: "RELIANCE is in a **downtrend**. " },
    { type: "text", delta: "Not financial advice." },
    { type: "done", message_id: 3, thread_id: 7, mode: "ai", unchecked: ["1,999"], footer: STATUS.footer },
  ]);
}

describe("Kairos chat panel", () => {
  it("opens from the top bar, streams steps, a card and the reply", async () => {
    const spy = mockBackend({
      "/api/kairos/status": STATUS,
      "/api/kairos/threads": { threads: [] },
      "POST /api/kairos/chat": reply(false),
    });
    renderAt(<App />, "/");
    fireEvent.click(await screen.findByRole("button", { name: /Kairos/ }));
    const panel = await screen.findByRole("complementary", { name: /Kairos, your trading agent/ });
    expect(await within(panel).findByText("What should we look at?")).toBeInTheDocument();
    expect(within(panel).getByText("AI")).toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText("Message Kairos"), { target: { value: "analyse reliance" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Send" }));
    expect(await within(panel).findByText("Read RELIANCE's 1d chart")).toBeInTheDocument();
    expect(within(panel).getByText("Downtrend · rectangle forming")).toBeInTheDocument();
    expect(within(panel).getByText("downtrend")).toHaveClass("font-semibold");
    expect(within(panel).getByText(/Couldn't check these numbers/)).toHaveTextContent("1,999");
    const call = spy.mock.calls.find(([url]) => String(url) === "/api/kairos/chat");
    const body = JSON.parse(String(call?.[1]?.body)) as { message: string; thread_id: number | null; page: { screen: string } };
    expect(body).toMatchObject({ message: "analyse reliance", thread_id: null, page: { screen: "/" } });
  });

  it("follows Kairos to the screen it talks about", async () => {
    mockBackend({
      "/api/kairos/status": STATUS,
      "/api/kairos/threads": { threads: [] },
      "POST /api/kairos/chat": reply(true),
      "/api/candles*": { instrument: {}, timeframe: "1d", adjusted: true, bars: [], note: null },
    });
    renderAt(<App />, "/");
    fireEvent.click(await screen.findByRole("button", { name: /Kairos/ }));
    const panel = await screen.findByRole("complementary", { name: /Kairos, your trading agent/ });
    fireEvent.click(await within(panel).findByText("Analyse RELIANCE"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Charts", level: 1 })).toBeInTheDocument());
  });

  it("stays put when following is switched off", async () => {
    mockBackend({
      "/api/settings": { ...SETTINGS, values: { ...SETTINGS.values, "kairos.follow": false } },
      "/api/kairos/status": STATUS,
      "/api/kairos/threads": { threads: [] },
      "POST /api/kairos/chat": reply(true),
    });
    renderAt(<App />, "/");
    fireEvent.click(await screen.findByRole("button", { name: /Kairos/ }));
    const panel = await screen.findByRole("complementary", { name: /Kairos, your trading agent/ });
    fireEvent.click(await within(panel).findByText("Analyse RELIANCE"));
    expect(await within(panel).findByText("Read RELIANCE's 1d chart")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Charts", level: 1 })).not.toBeInTheDocument();
  });

  it("reopens a past conversation with its steps", async () => {
    mockBackend({
      "/api/kairos/status": STATUS,
      "/api/kairos/threads": { threads: [{ id: 7, title: "analyse reliance", created_at: 0, updated_at: 0 }] },
      "/api/kairos/threads/7": {
        id: 7,
        messages: [
          { id: 1, role: "user", content: "analyse reliance", payload: {}, created_at: 0 },
          { id: 2, role: "assistant", content: "It's in a downtrend.", payload: { steps: [{ id: "s1", tool: "analyze_chart", status: "done", label: "Read RELIANCE's 1d chart", card: CHART_CARD }] }, created_at: 0 },
        ],
      },
    });
    renderAt(<App />, "/");
    fireEvent.click(await screen.findByRole("button", { name: /Kairos/ }));
    const panel = await screen.findByRole("complementary", { name: /Kairos, your trading agent/ });
    fireEvent.click(within(panel).getByRole("button", { name: "Past conversations" }));
    fireEvent.click(await within(panel).findByText("analyse reliance"));
    expect(await within(panel).findByText("It's in a downtrend.")).toBeInTheDocument();
    expect(within(panel).getByText("Read RELIANCE's 1d chart")).toBeInTheDocument();
  });

  it("opens with Ctrl+J", async () => {
    mockBackend({ "/api/kairos/status": STATUS, "/api/kairos/threads": { threads: [] } });
    renderAt(<App />, "/");
    await screen.findByRole("button", { name: /Kairos/ });
    fireEvent.keyDown(window, { key: "j", ctrlKey: true });
    expect(await screen.findByRole("complementary", { name: /Kairos, your trading agent/ })).toBeInTheDocument();
  });

  it("disappears when switched off in Settings", async () => {
    mockBackend({ "/api/settings": { ...SETTINGS, values: { ...SETTINGS.values, "kairos.enabled": false } } });
    renderAt(<App />, "/");
    await screen.findByRole("button", { name: /Search or jump to/ }).catch(() => undefined);
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Kairos$/ })).not.toBeInTheDocument());
    fireEvent.keyDown(window, { key: "j", ctrlKey: true });
    expect(screen.queryByRole("complementary", { name: /Kairos, your trading agent/ })).not.toBeInTheDocument();
  });
});
