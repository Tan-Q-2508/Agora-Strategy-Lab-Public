/**
 * Talking to Kairos: the conversation state for the chat panel on every screen.
 *
 * A reply streams as Server-Sent Events (backend/kairos/agent.py): steps appear as Kairos
 * runs its tools, words as it writes. When a step says "go to this screen" and the user
 * lets Kairos follow (Settings → kairos.follow), the app navigates there.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { deleteJson, getJson, toEnvelope, type ErrorEnvelope, type SettingsResponse } from "./api";
import { useApi } from "./useApi";

export type StepStatus = "running" | "done" | "error";

export interface Card {
  type: string;
  link?: string;
  [key: string]: unknown;
}

export interface Step {
  id: string;
  tool: string;
  status: StepStatus;
  label: string;
  detail?: string;
  pct?: number;
  message?: string;
  card?: Card | null;
  ui?: { navigate?: string } | null;
}

export interface Turn {
  key: string;
  role: "user" | "assistant";
  text: string;
  steps: Step[];
  streaming?: boolean;
  thinking?: boolean;
  unchecked?: string[];
  mode?: string;
  error?: ErrorEnvelope;
  notice?: string;
}

export interface ThreadInfo {
  id: number;
  title: string;
  updated_at: number;
}

export interface KairosStatus {
  mode: "ai" | "basic" | "practice";
  ai_state: string;
  model: string;
  suggestions: string[];
  footer: string;
}

interface SavedMessage {
  id: number;
  role: "user" | "assistant" | "step";
  content: string;
  payload: { steps?: Step[]; unchecked?: string[]; mode?: string };
}

type KairosEvent =
  | { type: "thread"; thread_id: number }
  | { type: "thinking" }
  | ({ type: "step" } & Step)
  | { type: "text"; delta: string }
  | { type: "text_reset" }
  | { type: "notice"; text: string }
  | { type: "done"; message_id: number; thread_id: number; mode: string; unchecked: string[]; footer: string }
  | { type: "error"; message: string; action: string };

interface KairosApi {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  turns: Turn[];
  busy: boolean;
  threadId: number | null;
  threads: ThreadInfo[];
  status: KairosStatus | null;
  send: (text: string) => void;
  ask: (text: string) => void; // open the panel and send
  stop: () => void;
  newThread: () => void;
  openThread: (id: number) => void;
  deleteThread: (id: number) => void;
}

const Ctx = createContext<KairosApi | null>(null);

/** Where the user is, so "this chart" and "this backtest" mean something to Kairos. */
function pageContext(pathname: string, search: string): Record<string, string> {
  const q = new URLSearchParams(search);
  const page: Record<string, string> = { screen: pathname };
  for (const k of ["symbol", "market", "tf"]) {
    const v = q.get(k);
    if (v) page[k === "tf" ? "timeframe" : k] = v;
  }
  const m = /^\/(backtests|paper|strategies)\/(\d+)/.exec(pathname);
  if (m?.[1] && m[2]) page[{ backtests: "backtest_id", paper: "paper_session_id", strategies: "strategy_id" }[m[1]] ?? "id"] = m[2];
  return page;
}

async function stream(body: unknown, onEvent: (e: KairosEvent) => void, signal: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/kairos/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal.aborted) return;
    onEvent({ type: "error", message: "Agora isn't answering.", action: "Make sure Agora is still open, then try again." });
    void err;
    return;
  }
  if (!res.ok || !res.body) {
    let env = { message: "Kairos couldn't answer.", action: "Try again." };
    try {
      const data = (await res.json()) as { error?: ErrorEnvelope };
      if (data.error) env = data.error;
    } catch {
      /* keep the default */
    }
    onEvent({ type: "error", ...env });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut = buffer.indexOf("\n\n");
      while (cut >= 0) {
        const chunk = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        cut = buffer.indexOf("\n\n");
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) onEvent(JSON.parse(line.slice(6)) as KairosEvent);
      }
    }
  } catch (err) {
    if (!signal.aborted) onEvent({ type: "error", ...toEnvelope(err) });
  }
}

let keySeq = 0;
const nextKey = () => `t${++keySeq}`;

export function KairosProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState<number | null>(null);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const abort = useRef<AbortController | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const settings = useApi<SettingsResponse>("/settings");
  const follow = settings.status !== "ready" || settings.data.values["kairos.follow"] !== false;
  const enabled = settings.status !== "ready" || settings.data.values["kairos.enabled"] !== false;
  const statusApi = useApi<KairosStatus>(open ? "/kairos/status" : null);
  const status = statusApi.status === "ready" ? statusApi.data : null;

  const refreshThreads = useCallback(() => {
    getJson<{ threads: ThreadInfo[] }>("/kairos/threads")
      .then((r) => setThreads(r.threads))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (open) refreshThreads();
  }, [open, refreshThreads]);

  const update = useCallback((fn: (t: Turn) => Turn) => {
    setTurns((all) => {
      const last = all.at(-1);
      if (!last || last.role !== "assistant") return all;
      return [...all.slice(0, -1), fn(last)];
    });
  }, []);

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setTurns((all) => [...all, { key: nextKey(), role: "user", text: message, steps: [] }, { key: nextKey(), role: "assistant", text: "", steps: [], streaming: true }]);
      setBusy(true);
      const ctrl = new AbortController();
      abort.current = ctrl;
      const page = pageContext(location.pathname, location.search);
      void stream(
        { message, thread_id: threadId, page },
        (e) => {
          switch (e.type) {
            case "thread":
              setThreadId(e.thread_id);
              break;
            case "thinking":
              update((t) => ({ ...t, thinking: true }));
              break;
            case "step": {
              const { type: _type, ...step } = e;
              void _type;
              update((t) => {
                const i = t.steps.findIndex((s) => s.id === step.id);
                const steps = i >= 0 ? t.steps.map((s, k) => (k === i ? { ...s, ...step } : s)) : [...t.steps, step];
                return { ...t, steps, thinking: false };
              });
              if (step.status === "done" && step.ui?.navigate && follow) navigate(step.ui.navigate);
              break;
            }
            case "text":
              update((t) => ({ ...t, text: t.text + e.delta, thinking: false }));
              break;
            case "text_reset":
              update((t) => ({ ...t, text: "" }));
              break;
            case "notice":
              update((t) => ({ ...t, notice: e.text }));
              break;
            case "error":
              update((t) => ({ ...t, error: { code: "KAIROS", message: e.message, action: e.action, detail: "" } }));
              break;
            case "done":
              update((t) => ({ ...t, streaming: false, thinking: false, unchecked: e.unchecked, mode: e.mode }));
              break;
          }
        },
        ctrl.signal,
      ).finally(() => {
        setBusy(false);
        update((t) => ({ ...t, streaming: false, thinking: false }));
        refreshThreads();
      });
    },
    [busy, threadId, location.pathname, location.search, update, follow, navigate, refreshThreads],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    setBusy(false);
    update((t) => ({ ...t, streaming: false, thinking: false, notice: "Stopped. Anything already started (a backtest, a session) keeps running on its own screen." }));
  }, [update]);

  const newThread = useCallback(() => {
    abort.current?.abort();
    setThreadId(null);
    setTurns([]);
    setBusy(false);
  }, []);

  const openThread = useCallback((id: number) => {
    abort.current?.abort();
    setBusy(false);
    getJson<{ messages: SavedMessage[] }>(`/kairos/threads/${id}`)
      .then((r) => {
        setThreadId(id);
        setTurns(
          r.messages
            .filter((m) => m.role !== "step")
            .map((m) => ({ key: nextKey(), role: m.role as "user" | "assistant", text: m.content, steps: m.payload.steps ?? [], unchecked: m.payload.unchecked, mode: m.payload.mode })),
        );
      })
      .catch(() => undefined);
  }, []);

  const deleteThread = useCallback(
    (id: number) => {
      void deleteJson(`/kairos/threads/${id}`).then(() => {
        if (id === threadId) newThread();
        refreshThreads();
      });
    },
    [threadId, newThread, refreshThreads],
  );

  const ask = useCallback(
    (text: string) => {
      setOpen(true);
      send(text);
    },
    [send],
  );
  const toggle = useCallback(() => setOpen((o) => !o), []);

  // Ctrl/Cmd+J opens and closes Kairos from anywhere.
  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);

  const value = useMemo<KairosApi>(
    () => ({ open, setOpen, toggle, turns, busy, threadId, threads, status, send, ask, stop, newThread, openThread, deleteThread }),
    [open, toggle, turns, busy, threadId, threads, status, send, ask, stop, newThread, openThread, deleteThread],
  );
  // Switched off in Settings → Kairos: every entry point (top bar, palette, chart toggle) hides.
  return <Ctx.Provider value={enabled ? value : null}>{children}</Ctx.Provider>;
}

/** Kairos from any component; a harmless stand-in outside the app shell (tests, onboarding). */
export function useKairos(): KairosApi | null {
  return useContext(Ctx);
}
