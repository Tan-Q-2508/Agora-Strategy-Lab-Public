import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { ThemeProvider } from "./lib/theme";

export const HEALTH = {
  app: "agora", status: "ok", version: "0.1.0", db_ok: true, data_sources: [], ai: { state: "not_checked" }, server_time: 0,
};
export const MARKETS = {
  markets: [
    { market: "IN", name: "India", is_open: true, next_change: 0, next_change_display: "Closes 15:30 IST", seconds_to_change: 3 * 3600 + 57 * 60, approximate: true },
    { market: "US", name: "US", is_open: false, next_change: 0, next_change_display: "Opens 09:30 ET", seconds_to_change: 7 * 3600, approximate: true },
  ],
  server_time: 0,
};
export const SETTINGS = {
  values: { theme: "light", "ai.enabled": true, "ai.model": "qwen3.5:4b", "ai.base_url": "http://localhost:11434", "default_capital.IN": 1000000, "default_capital.US": 100000, intraday_square_off_time: "15:20", volume_cap_pct: 5, onboarding_done: true, markets: ["IN", "US"] },
  meta: { theme: { default: "light", description: "Light or dark colors for the whole app." }, volume_cap_pct: { default: 5, description: "Largest order allowed." } },
};

const IN_ROWS = ["RELIANCE", "TCS"].map((symbol, i) => ({
  instrument_id: i + 1, symbol, name: `${symbol} Ltd`, market: "IN", type: "equity", first: null, last: null, bars: 0, gaps: 0, stale: false, source: null, status: "empty",
}));
export const EMPTY_COVERAGE = { timeframe: "1d", rows: IN_ROWS, totals: { symbols: 2, ok: 0, empty: 2, stale: 0, gaps: 0 }, last_update: null, data_mode: "real" };
export const INSTRUMENTS = {
  instruments: [
    { id: 1, market: "IN", symbol: "RELIANCE", yahoo_symbol: "RELIANCE.NS", name: "Reliance Industries", type: "equity" },
    { id: 2, market: "US", symbol: "SPY", yahoo_symbol: "SPY", name: "SPDR S&P 500", type: "etf" },
  ],
};
export const AI_READY = {
  enabled: true, state: "ready", version: "0.12.0", model: "qwen3.5:4b", num_ctx: 32768, auto_ctx: true,
  models: [{ name: "qwen3.5:4b", size_gb: 3.2 }],
  recommended: [
    { name: "qwen3.5:4b", label: "Qwen 3.5 (4B)", note: "Recommended." },
    { name: "gemma4:e4b", label: "Gemma 4 (E4B)", note: "Larger." },
  ],
  warning: null,
  runs_on: null,
};

/** A streamed AI reply, as /api/ai/explain sends it (Server-Sent Events). */
export function sseResponse(events: Record<string, unknown>[]): () => Response {
  return () =>
    new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""), {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
}

const RISK = (market: string, level: number, name: string, title: string) => ({
  market, level, name, text: `${name} news.`, score: 1, headlines: 40, as_of: 1_760_000_000_000,
  drivers: [{ title, link: "https://example.invalid/a", publisher: "BBC News", published_at: 1_760_000_000_000, topic: "conflict", topic_label: "War & conflict", severity: 4, impact: -0.7, sources: 3, weight: 1.2 }],
});
export const NEWS_LIVE = {
  enabled: true,
  refreshing: false,
  sources: ["BBC News · World", "GDELT · World geopolitics", "RBI · Press releases"],
  items: [
    { id: 1, title: "Oil jumps as tensions escalate near the Strait of Hormuz", summary: "", link: "https://example.invalid/1", publisher: "BBC News", source: "bbc_world", published_at: 1_760_000_000_000, sentiment: -0.4, tone: "negative", symbols: [], topics: ["conflict", "energy"], topic_labels: ["War & conflict", "Oil & energy"], group: "Geopolitics", severity: 4, impact: -0.7, scope: "WORLD", sectors: { Energy: 1, Airlines: -1 } },
    { id: 2, title: "RBI keeps the repo rate unchanged", summary: "", link: "https://example.invalid/2", publisher: "RBI", source: "rbi_press", published_at: 1_759_990_000_000, sentiment: 0, tone: "neutral", symbols: [], topics: ["central_bank"], topic_labels: ["Central banks & rates"], group: "Economy", severity: 1, impact: 0.2, scope: "IN", sectors: {} },
    { id: 3, title: "Infosys wins a large deal", summary: "", link: "https://example.invalid/3", publisher: "Mint", source: "mint_markets", published_at: 1_759_980_000_000, sentiment: 0.6, tone: "positive", symbols: ["INFY"], topics: ["corporate"], topic_labels: ["Company news"], group: "Companies", severity: 1, impact: 0.4, scope: "IN", sectors: {} },
  ],
  risk: {
    IN: RISK("IN", 54, "elevated", "Oil jumps as tensions escalate near the Strait of Hormuz"),
    US: RISK("US", 31, "watchful", "Oil jumps as tensions escalate near the Strait of Hormuz"),
    WORLD: RISK("WORLD", 38, "watchful", "Oil jumps as tensions escalate near the Strait of Hormuz"),
  },
  guard: "protective",
  groups: ["Geopolitics", "Economy", "Markets", "Companies"],
  topics: [{ key: "conflict", label: "War & conflict", group: "Geopolitics" }],
  as_of: 1_760_000_000_000,
};

export const SOURCES = { sources: [{ source: "yahoo", label: "Yahoo Finance", state: "ok", until: null, last_error: null }], recent: [], server_time: 0 };

export type Routes = Record<string, unknown>;

/** Mock the backend: GET returns the matching fixture; PUT /settings echoes. Returns the spy. */
export const AUTOPILOT = {
  on: true,
  running: true,
  doing: "",
  last_round: 1_760_000_000_000,
  desks: [{ id: 7, market: "IN", state: "running", name: "Kairos desk · India", auto: true }],
  prices: { IN: { have: 120, want: 230 } },
  metis: { on: true, ai_ready: false, why: "Ollama isn't running." },
  last: {},
};

export function mockBackend(overrides: Routes = {}) {
  const routes: Routes = {
    "/api/health": HEALTH,
    "/api/markets/status": MARKETS,
    "/api/settings": SETTINGS,
    "/api/data/coverage*": EMPTY_COVERAGE,
    "/api/data/sources*": SOURCES,
    "/api/instruments*": INSTRUMENTS,
    "/api/strategies*": { strategies: [] },
    "/api/backtests*": { backtests: [] },
    "/api/templates": { templates: [] },
    "/api/indicators": { indicators: [], price_fields: [] },
    "POST /api/strategies/validate": { ok: false, issues: [], definition: null },
    "/api/paper/sessions": { sessions: [], mode: "live" },
    "/api/paper/accounts": { accounts: [] },
    "/api/ai/status*": AI_READY,
    "/api/news/live*": NEWS_LIVE,
    "/api/autopilot": AUTOPILOT,
    "/api/jobs?*": { jobs: [] },
    ...overrides,
  };
  const spy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const exact = routes[`${method} ${url}`];
    if (typeof exact === "function") return (exact as () => Response)();
    if (method !== "GET" && exact !== undefined) {
      return new Response(JSON.stringify(exact), { status: 200 });
    }
    if (method === "PUT") return new Response(JSON.stringify(SETTINGS), { status: 200 });
    // Exact match first, then the longest "prefix*" route.
    let body = routes[url];
    if (body === undefined) {
      const key = Object.keys(routes)
        .filter((k) => k.endsWith("*") && url.startsWith(k.slice(0, -1)))
        .sort((a, b) => b.length - a.length)[0];
      if (key) body = routes[key];
    }
    if (body instanceof Error) throw body;
    if (typeof body === "function") return (body as () => Response)();
    if (body === undefined) return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "Missing", action: "", detail: url } }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", spy);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  FakeWebSocket.instances = [];
  return spy;
}

/** Stands in for the live push channel: tests call `FakeWebSocket.push(type, data)`. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
    setTimeout(() => this.onopen?.(), 0);
  }
  send() {}
  close() {
    this.onclose?.();
  }
  static push(type: string, data: Record<string, unknown>) {
    for (const ws of FakeWebSocket.instances) ws.onmessage?.({ data: JSON.stringify({ type, data }) });
  }
}

export function renderAt(ui: ReactElement, path = "/") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </ThemeProvider>,
  );
}
