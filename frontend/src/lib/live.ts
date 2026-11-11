/**
 * The live push channel (`/ws`). One WebSocket for the whole app, opened when the first
 * screen subscribes; it reconnects with back-off (1 s → 3 s) and tells subscribers when
 * it is back, so they can re-fetch full state (API_CONTRACT → WebSocket).
 */
import { useEffect, useRef, useSyncExternalStore } from "react";

export interface LiveMessage<T = Record<string, unknown>> {
  type: string;
  data: T;
}

type Handler = (msg: LiveMessage) => void;

const handlers = new Set<Handler>();
const reconnectHandlers = new Set<() => void>();
const statusListeners = new Set<() => void>();
let socket: WebSocket | null = null;
let connected = false;
let attempts = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
let bootId: number | null = null;
const MAX_DELAY_MS = 3_000; // Agora runs on this computer: retrying often costs nothing

/** A hello from a restarted Agora: reload, so the open tab runs the new version (D-111). */
export function onHello(id: unknown, reload: () => void = () => window.location.reload()) {
  if (typeof id !== "number") return;
  if (bootId !== null && bootId !== id) {
    reload();
    return;
  }
  bootId = id;
}

function setConnected(v: boolean) {
  if (connected === v) return;
  connected = v;
  statusListeners.forEach((l) => l());
}

function url(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

function connect() {
  if (socket || typeof WebSocket === "undefined") return;
  let ws: WebSocket;
  try {
    ws = new WebSocket(url());
  } catch {
    schedule();
    return;
  }
  socket = ws;
  ws.onopen = () => {
    const wasRetry = attempts > 0;
    attempts = 0;
    setConnected(true);
    if (wasRetry) reconnectHandlers.forEach((h) => h());
  };
  ws.onmessage = (ev: MessageEvent<string>) => {
    try {
      const msg = JSON.parse(ev.data) as LiveMessage;
      if (msg.type === "hello") onHello(msg.data.boot_id);
      handlers.forEach((h) => h(msg));
    } catch {
      /* ignore malformed messages */
    }
  };
  ws.onclose = () => {
    socket = null;
    setConnected(false);
    schedule();
  };
  ws.onerror = () => ws.close();
}

function schedule() {
  if (timer || handlers.size === 0) return;
  const delay = Math.min(MAX_DELAY_MS, 1000 * 2 ** attempts);
  attempts += 1;
  timer = setTimeout(() => {
    timer = null;
    connect();
  }, delay);
}

function release() {
  if (handlers.size > 0) return;
  if (timer) clearTimeout(timer);
  timer = null;
  attempts = 0;
  const s = socket;
  socket = null;
  if (s) {
    s.onclose = null;
    s.close();
  }
  setConnected(false);
}

/** Receive live messages whose type starts with one of `prefixes` (e.g. "paper."). */
export function useLive(prefixes: string[], onMessage: (msg: LiveMessage) => void, onReconnect?: () => void) {
  const cb = useRef(onMessage);
  const rc = useRef(onReconnect);
  useEffect(() => {
    cb.current = onMessage;
    rc.current = onReconnect;
  });
  const key = prefixes.join("|");
  useEffect(() => {
    const list = key.split("|");
    const h: Handler = (msg) => {
      if (list.some((p) => msg.type.startsWith(p))) cb.current(msg);
    };
    const r = () => rc.current?.();
    handlers.add(h);
    reconnectHandlers.add(r);
    connect();
    return () => {
      handlers.delete(h);
      reconnectHandlers.delete(r);
      release();
    };
  }, [key]);
}

/** True while the push channel is connected (screens fall back to polling otherwise). */
export function useLiveConnected(): boolean {
  return useSyncExternalStore(
    (l) => {
      statusListeners.add(l);
      return () => statusListeners.delete(l);
    },
    () => connected,
    () => false,
  );
}
