import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowUp, Check, History, Loader2, Plus, Square, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useKairos, type Step, type Turn } from "../../lib/kairosChat";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { Kbd } from "../ui/kbd";
import { Pill } from "../ui/pill";
import { ResultCard } from "./cards";
import { KairosMark } from "./KairosMark";
import { ScrollBox } from "../ui/scroll-box";

const MODE_LABEL: Record<string, { text: string; tone: "accent" | "neutral" | "warning"; hint: string }> = {
  ai: { text: "AI", tone: "accent", hint: "Kairos is thinking with the AI model on your laptop." },
  practice: { text: "Practice", tone: "neutral", hint: "Practice mode: Kairos follows its rules and replies with templates." },
  basic: { text: "Basic", tone: "warning", hint: "The AI helper isn't set up, so Kairos follows its rules. Set it up in Settings → AI helper." },
};

/** **bold**, bullet lines and paragraphs: enough formatting for Kairos's replies. */
function RichText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  const inline = (s: string): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={i} className="font-semibold text-fg">
          {part.slice(2, -2)}
        </strong>
      ) : (
        part
      ),
    );
  return (
    <div className="flex flex-col gap-2">
      {blocks.map((b, i) => {
        const lines = b.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*([-•*]|\d+\.)\s+/.test(l))) {
          return (
            <ul key={i} className="m-0 flex list-disc flex-col gap-1 pl-5">
              {lines.map((l) => (
                <li key={l}>{inline(l.replace(/^\s*([-•*]|\d+\.)\s+/, ""))}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="m-0 whitespace-pre-line">
            {inline(b)}
          </p>
        );
      })}
    </div>
  );
}

function StepRow({ step }: { step: Step }) {
  const icon =
    step.status === "running" ? (
      <Loader2 className="size-3.5 animate-spin text-accent" aria-hidden="true" />
    ) : step.status === "done" ? (
      <Check className="size-3.5 text-profit" aria-hidden="true" />
    ) : (
      <AlertTriangle className="size-3.5 text-warning" aria-hidden="true" />
    );
  return (
    <motion.li initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-1.5">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-2">{icon}</span>
        <div className="min-w-0 flex-1">
          <p className="m-0 text-small text-fg">
            {step.label}
            {step.detail && <span className="text-fg-subtle"> · {step.detail}</span>}
          </p>
          {step.status === "running" && step.pct !== undefined && (
            <div className="mt-1 flex flex-col gap-0.5">
              <div className="h-1 overflow-hidden rounded-full bg-surface-2">
                <motion.div className="h-full bg-accent" animate={{ width: `${Math.max(4, step.pct)}%` }} transition={{ duration: 0.3 }} />
              </div>
              {step.message && <p className="m-0 truncate text-tiny text-fg-subtle">{step.message}</p>}
            </div>
          )}
        </div>
      </div>
      {step.status === "done" && step.card && (
        <div className="pl-7">
          <ResultCard card={step.card} />
        </div>
      )}
    </motion.li>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="m-0 max-w-[85%] rounded-[14px] rounded-br-[4px] bg-accent-soft px-3 py-2 text-[14px] leading-5 whitespace-pre-line text-fg">{turn.text}</p>
      </div>
    );
  }
  const waiting = turn.streaming && !turn.text && !turn.steps.length;
  return (
    <div className="flex gap-2.5">
      <KairosMark className="mt-0.5 size-6 shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-3 text-[14px] leading-[21px] text-fg-muted">
        {waiting && (
          <p className="m-0 flex items-center gap-2 text-small text-fg-subtle" aria-live="polite">
            <span className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <motion.span key={i} className="size-1.5 rounded-full bg-fg-subtle" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }} />
              ))}
            </span>
            {turn.thinking ? "Thinking it through…" : "Reading your request…"}
          </p>
        )}
        {turn.notice && <p className="m-0 text-small text-fg-subtle">{turn.notice}</p>}
        {turn.steps.length > 0 && (
          <ScrollBox size="sm">
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="What Kairos did">
              {turn.steps.map((s) => (
                <StepRow key={s.id} step={s} />
              ))}
            </ol>
          </ScrollBox>
        )}
        {turn.text && <RichText text={turn.text} />}
        {turn.streaming && turn.text && <span className="inline-block h-4 w-1.5 animate-pulse bg-accent" aria-hidden="true" />}
        {turn.error && (
          <div role="alert" className="rounded-tile border border-warning/30 bg-warning-soft p-3 text-small text-warning-soft-fg">
            <p className="m-0 font-semibold">{turn.error.message}</p>
            <p className="m-0">{turn.error.action}</p>
          </div>
        )}
        {turn.unchecked && turn.unchecked.length > 0 && (
          <p className="m-0 text-tiny text-fg-subtle">Couldn't check these numbers against Agora's data: {turn.unchecked.join(", ")}.</p>
        )}
      </div>
    </div>
  );
}

export function KairosDrawer() {
  const k = useKairos();
  const [draft, setDraft] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const open = k?.open ?? false;
  const turns = k?.turns;

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 150);
  }, [open]);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    else el.scrollTop = el.scrollHeight;
  }, [turns]);

  if (!k) return null;
  const mode = MODE_LABEL[k.status?.mode ?? ""] ?? null;
  const submit = () => {
    if (!draft.trim() || k.busy) return;
    k.send(draft);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape") {
      k.setOpen(false);
    }
  };
  const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          key="kairos"
          aria-label="Kairos, your trading agent"
          initial={{ x: 460, opacity: 0.6 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 460, opacity: 0.6 }}
          transition={{ type: "spring", stiffness: 320, damping: 34 }}
          className="fixed top-0 right-0 z-40 flex h-screen w-[440px] flex-col border-l border-border bg-surface shadow-e3"
        >
          <header className="flex h-[60px] shrink-0 items-center gap-2 border-b border-border px-4">
            <KairosMark className="size-6" />
            <div className="min-w-0 flex-1">
              <p className="m-0 flex items-center gap-2 text-[15px] font-semibold">
                Kairos
                {mode && (
                  <Pill tone={mode.tone} className="h-5 px-2 text-tiny" title={mode.hint}>
                    {mode.text}
                  </Pill>
                )}
              </p>
              <p className="m-0 truncate text-tiny text-fg-subtle">Your trading agent · paper money only</p>
            </div>
            <Button size="icon-sm" variant="ghost" aria-label="Past conversations" aria-expanded={showHistory} onClick={() => setShowHistory((s) => !s)}>
              <History />
            </Button>
            <Button size="icon-sm" variant="ghost" aria-label="New conversation" onClick={() => { k.newThread(); setShowHistory(false); }}>
              <Plus />
            </Button>
            <Button size="icon-sm" variant="ghost" aria-label="Close Kairos" onClick={() => k.setOpen(false)}>
              <X />
            </Button>
          </header>

          {showHistory && (
            <div className="max-h-[260px] shrink-0 overflow-y-auto border-b border-border bg-surface-2/60 px-2 py-2">
              {k.threads.length === 0 && <p className="m-0 px-2 py-1 text-small text-fg-subtle">No past conversations yet.</p>}
              {k.threads.map((t) => (
                <div key={t.id} className={cn("group flex items-center gap-2 rounded-control px-2 py-1.5 hover:bg-surface", t.id === k.threadId && "bg-surface")}>
                  <button type="button" className="min-w-0 flex-1 truncate text-left text-small text-fg" onClick={() => { k.openThread(t.id); setShowHistory(false); }}>
                    {t.title}
                  </button>
                  <button type="button" aria-label={`Delete “${t.title}”`} className="rounded p-1 text-fg-subtle opacity-0 group-hover:opacity-100 hover:text-loss" onClick={() => k.deleteThread(t.id)}>
                    <Trash2 className="size-3.5" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div ref={scroller} className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-4">
            {k.turns.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
                <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }}>
                  <KairosMark className="size-12" />
                </motion.div>
                <div>
                  <p className="m-0 text-[17px] font-semibold text-fg">What should we look at?</p>
                  <p className="m-0 mt-1 text-small text-fg-muted">I read charts and news, build and test strategies, and paper trade, all inside Agora.</p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {(k.status?.suggestions ?? []).map((s) => (
                    <button key={s} type="button" onClick={() => k.send(s)} className="rounded-full border border-border bg-surface px-3 py-1.5 text-small text-fg hover:border-accent/50 hover:bg-accent-soft/40">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              k.turns.map((t) => <TurnView key={t.key} turn={t} />)
            )}
          </div>

          <div className="shrink-0 border-t border-border p-3">
            <div className="flex items-end gap-2 rounded-tile border border-border bg-surface px-3 py-2 shadow-e1 focus-within:border-accent/60">
              <textarea
                ref={input}
                value={draft}
                rows={1}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKey}
                placeholder="Ask Kairos anything, or tell it what to do…"
                aria-label="Message Kairos"
                className="max-h-[120px] min-h-[24px] flex-1 resize-none border-0 bg-transparent text-[14px] leading-6 text-fg outline-none placeholder:text-fg-subtle [field-sizing:content]"
              />
              {k.busy ? (
                <Button size="icon-sm" variant="secondary" aria-label="Stop" onClick={k.stop}>
                  <Square />
                </Button>
              ) : (
                <Button size="icon-sm" variant="primary" aria-label="Send" disabled={!draft.trim()} onClick={submit}>
                  <ArrowUp />
                </Button>
              )}
            </div>
            <p className="m-0 mt-1.5 flex items-center justify-between text-tiny text-fg-subtle">
              <span>{k.status?.footer ?? "Kairos is a research tool, not financial advice. Paper money only."}</span>
              <span className="flex items-center gap-1">
                <Kbd>{isMac ? "⌘ J" : "Ctrl J"}</Kbd>
              </span>
            </p>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
