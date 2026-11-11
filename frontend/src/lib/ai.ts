/** The optional AI helper: status and streamed explanations (Server-Sent Events). */
import { toEnvelope, type ErrorEnvelope } from "./api";

export type AIState = "ready" | "model_missing" | "not_running" | "not_installed" | "disabled" | "error";

export interface AIStatus {
  enabled: boolean;
  state: AIState;
  version: string | null;
  model: string;
  /** The reading size in use now (on Automatic, the size that fit the graphics card). */
  num_ctx: number;
  /** True when the reading size is Automatic. */
  auto_ctx: boolean;
  models: { name: string; size_gb: number }[];
  recommended: { name: string; label: string; note: string }[];
  warning: string | null;
  /** Where the loaded model runs; null until Ollama loads it for a first question. */
  runs_on: { where: "gpu" | "partly" | "cpu"; gpu_percent: number; text: string; fix?: string } | null;
}

export type ExplainKind = "backtest" | "trade" | "metric" | "paper_day";

export interface ExplainHandlers {
  onText: (text: string) => void;
  onDone: (info: { unverified: string[]; note: string }) => void;
  onError: (err: ErrorEnvelope) => void;
}

/** POST /api/ai/explain and feed each streamed piece to the handlers. Abort with `signal`. */
export async function streamExplain(
  body: { kind: ExplainKind; id?: number; question?: string },
  h: ExplainHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/ai/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) return;
    h.onError({ ...toEnvelope(err), message: "Agora isn't answering.", action: "Make sure Agora is still open, then try again." });
    return;
  }
  if (!res.ok || !res.body) {
    let env: ErrorEnvelope = { code: "AI_FAILED", message: "The AI helper didn't answer.", action: "Try again.", detail: String(res.status) };
    try {
      const data = (await res.json()) as { error?: ErrorEnvelope };
      if (data.error) env = data.error;
    } catch {
      /* keep the default */
    }
    h.onError(env);
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
        if (!line) continue;
        const ev = JSON.parse(line.slice(6)) as { type: string; text?: string; unverified?: string[]; note?: string; message?: string; action?: string; detail?: string };
        if (ev.type === "text" && ev.text) h.onText(ev.text);
        else if (ev.type === "done") h.onDone({ unverified: ev.unverified ?? [], note: ev.note ?? "" });
        else if (ev.type === "error") h.onError({ code: "AI_FAILED", message: ev.message ?? "The AI helper stopped.", action: ev.action ?? "Try again.", detail: ev.detail ?? "" });
      }
    }
  } catch (err) {
    if (!signal?.aborted) h.onError(toEnvelope(err));
  }
}
