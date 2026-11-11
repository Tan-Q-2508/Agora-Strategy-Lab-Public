import { motion } from "framer-motion";
import { AlertTriangle, RotateCcw, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { streamExplain, type ExplainKind } from "../../lib/ai";
import type { ErrorEnvelope } from "../../lib/api";
import { duration, ease } from "../../lib/motion";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { AIText } from "./AIText";
import { useAIStatus } from "./useAIStatus";

type Phase = "idle" | "streaming" | "done" | "error";

const SETUP: Record<string, string> = {
  not_installed: "The free AI helper isn't set up. It's optional and runs on your laptop.",
  not_running: "The AI helper (Ollama) isn't running. Start it from your Start menu.",
  model_missing: "The AI model isn't downloaded yet.",
  error: "The AI helper couldn't be checked.",
};

/**
 * One AI explanation: a button, then the reply as it's written, with a Stop button, the
 * "check important numbers" note and any numbers that couldn't be checked against the data.
 * With `ask`, the user types a question first (metric Q&A).
 */
export function AIExplain({
  kind,
  id,
  label,
  ask = false,
  placeholder,
  autoStart = false,
}: {
  kind: ExplainKind;
  id?: number;
  label: string;
  ask?: boolean;
  placeholder?: string;
  autoStart?: boolean;
}) {
  const status = useAIStatus();
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [question, setQuestion] = useState("");
  const [unverified, setUnverified] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<ErrorEnvelope | null>(null);
  const abort = useRef<AbortController | null>(null);
  const started = useRef(false);

  useEffect(() => () => abort.current?.abort(), []);

  function run() {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setText("");
    setUnverified([]);
    setError(null);
    setPhase("streaming");
    void streamExplain(
      { kind, id, question: ask ? question : undefined },
      {
        onText: (t) => setText((prev) => prev + t),
        onDone: (info) => {
          setUnverified(info.unverified);
          setNote(info.note);
          setPhase("done");
        },
        onError: (e) => {
          setError(e);
          setPhase("error");
        },
      },
      ctl.signal,
    );
  }

  const ready = status.status === "ready" && status.data.state === "ready";
  useEffect(() => {
    if (autoStart && ready && !started.current) {
      started.current = true;
      const t = setTimeout(run, 0);
      return () => clearTimeout(t);
    }
  });

  if (status.status === "loading") return null;
  if (status.status === "ready" && status.data.state === "disabled") return null;
  if (!ready) {
    const state = status.status === "ready" ? status.data.state : "error";
    return (
      <div className="flex items-center gap-3 rounded-tile border border-dashed border-border px-4 py-3 text-small text-fg-muted">
        <Sparkles className="size-4 shrink-0 text-fg-subtle" aria-hidden="true" />
        <span className="flex-1">{SETUP[state] ?? SETUP.error}</span>
        <Button size="sm" variant="ghost" asChild>
          <Link to="/settings?tab=ai">Set up the AI helper</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {ask ? (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.trim()) run();
          }}
        >
          <Input aria-label="Your question" className="flex-1" value={question} maxLength={500} placeholder={placeholder} onChange={(e) => setQuestion(e.target.value)} />
          <Button type="submit" disabled={!question.trim() || phase === "streaming"}>
            <Sparkles aria-hidden="true" />
            {label}
          </Button>
        </form>
      ) : (
        phase === "idle" && (
          <Button variant="soft" className="w-fit" onClick={run}>
            <Sparkles aria-hidden="true" />
            {label}
          </Button>
        )
      )}
      {(phase === "streaming" || phase === "done") && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: duration.base, ease }}
          className="flex flex-col gap-3 rounded-tile bg-accent-soft/40 p-4"
          aria-live="polite"
          aria-busy={phase === "streaming"}
        >
          {text ? <AIText text={text} /> : <p className="m-0 text-small text-fg-muted">Thinking…</p>}
          {phase === "streaming" && (
            <Button size="sm" variant="ghost" className="w-fit" onClick={() => { abort.current?.abort(); setPhase("done"); }}>
              <Square aria-hidden="true" />
              Stop
            </Button>
          )}
          {phase === "done" && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-tiny text-fg-subtle">
              <span>{note || "AI-generated. Check important numbers."}</span>
              {!ask && (
                <Button size="sm" variant="ghost" onClick={run}>
                  <RotateCcw aria-hidden="true" />
                  Ask again
                </Button>
              )}
            </div>
          )}
          {unverified.length > 0 && (
            <p className="m-0 flex items-start gap-1.5 text-small text-warning-soft-fg">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              These numbers don't appear in your results, so treat them with care: {unverified.join(", ")}.
            </p>
          )}
        </motion.div>
      )}
      {phase === "error" && error && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-tile bg-warning-soft px-4 py-3 text-small text-warning-soft-fg">
          <span>
            {error.message} {error.action}
          </span>
          <Button size="sm" variant="ghost" onClick={run}>
            Try again
          </Button>
        </div>
      )}
    </div>
  );
}
